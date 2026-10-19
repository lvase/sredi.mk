import logging
import smtplib
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import connection
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import AuthenticationAttempt
from apps.issues.models import (
    AttachmentDeletionState,
    ReceiptDelivery,
    ReceiptDeliveryState,
    SubmissionRateLimit,
)
from apps.issues.retention import eligible_attachments, run_retention_batch
from apps.issues.storage import STORAGE_STATE_KEY, filesystem_usage_state
from apps.municipalities.models import Municipality

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=5)
def send_receipt_email(self, delivery_id):
    delivery = ReceiptDelivery.objects.select_related("issue", "issue__municipality").get(
        pk=delivery_id
    )
    if delivery.state == ReceiptDeliveryState.SENT:
        return "already_sent"
    now = timezone.now()
    ReceiptDelivery.objects.filter(pk=delivery_id).update(
        attempt_count=F("attempt_count") + 1,
        last_attempt_at=now,
        state=ReceiptDeliveryState.QUEUED,
    )
    try:
        delivered = send_mail(
            subject=f"Потврда за пријава {delivery.issue.tracking_code}",
            message=(
                f"Вашата пријава до {delivery.issue.municipality.name} е примена.\n\n"
                f"Код за следење: {delivery.issue.tracking_code}\n"
                "Кодот чувајте го приватно и користете го за проверка на статусот."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[delivery.recipient],
            fail_silently=False,
        )
        if not delivered:
            raise smtplib.SMTPException("SMTP backend did not accept the message")
    except (smtplib.SMTPException, TimeoutError, OSError, ConnectionError) as exc:
        if self.request.retries >= self.max_retries:
            ReceiptDelivery.objects.filter(pk=delivery_id).update(
                state=ReceiptDeliveryState.FAILED,
                failed_at=now,
                last_error=exc.__class__.__name__,
            )
            return "failed"
        ReceiptDelivery.objects.filter(pk=delivery_id).update(
            state=ReceiptDeliveryState.QUEUED,
            failed_at=None,
            last_error=exc.__class__.__name__,
        )
        raise self.retry(
            exc=exc, countdown=min(3600, 60 * (2 ** self.request.retries))
        ) from exc
    except Exception as exc:
        ReceiptDelivery.objects.filter(pk=delivery_id).update(
            state=ReceiptDeliveryState.FAILED,
            failed_at=now,
            last_error=exc.__class__.__name__,
        )
        logger.exception(
            "receipt_delivery_unexpected_failure",
            extra={"receipt_delivery_id": delivery_id},
        )
        raise
    ReceiptDelivery.objects.filter(pk=delivery_id).update(
        state=ReceiptDeliveryState.SENT,
        sent_at=now,
        failed_at=None,
        last_error="",
    )
    return "sent"


@shared_task
def run_attachment_retention(municipality_ids=None, batch_size=100, retry_failed=True):
    municipalities = (
        Municipality.objects.filter(pk__in=municipality_ids)
        if municipality_ids
        else Municipality.objects.all()
    )
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", [settings.MEDIA_MAINTENANCE_LOCK_ID])
        acquired = cursor.fetchone()[0]
    if not acquired:
        run_attachment_retention.apply_async(
            kwargs={
                "municipality_ids": municipality_ids,
                "batch_size": batch_size,
                "retry_failed": retry_failed,
            },
            countdown=15 * 60,
        )
        return {
            "processed": 0,
            "failed": 0,
            "deferred": "backup_in_progress",
            "continuation_queued": True,
        }
    try:
        batch_size = min(100, max(1, batch_size))
        result = run_retention_batch(
            municipalities,
            batch_size=batch_size,
            retry_failed=retry_failed,
        )
        has_more = any(
            eligible_attachments(municipality)
            .exclude(deletion_state=AttachmentDeletionState.FAILED)
            .exists()
            for municipality in municipalities
        )
        if has_more:
            try:
                run_attachment_retention.apply_async(
                    kwargs={
                        "municipality_ids": municipality_ids,
                        "batch_size": batch_size,
                        "retry_failed": False,
                    },
                    countdown=5,
                )
            except Exception:
                logger.exception("retention_continuation_queue_failed")
                result["continuation_queued"] = False
            else:
                result["continuation_queued"] = True
        return result
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [settings.MEDIA_MAINTENANCE_LOCK_ID])


@shared_task
def prune_legacy_counters():
    cutoff = timezone.now() - timedelta(hours=48)
    submissions, _ = SubmissionRateLimit.objects.filter(updated_at__lte=cutoff).delete()
    attempts, _ = AuthenticationAttempt.objects.filter(updated_at__lte=cutoff).delete()
    return {"submission_rows": submissions, "authentication_rows": attempts}


@shared_task
def monitor_storage():
    state = filesystem_usage_state()
    try:
        cache.set(STORAGE_STATE_KEY, state, timeout=30 * 60)
        should_alert = state["enforced"] and state["level"] != "ok" and cache.add(
            f"operations:storage-alert:{state['level']}", True, timeout=24 * 60 * 60
        )
    except Exception:
        should_alert = state["enforced"] and state["level"] != "ok"
    if should_alert:
        logger.warning("storage_capacity_alert", extra={"storage_state": state})
        if settings.OPERATIONS_ALERT_EMAILS:
            send_mail(
                subject=f"Sredi storage alert: {state['level']}",
                message=f"Filesystem usage is {state['used_percent']}%.",
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=settings.OPERATIONS_ALERT_EMAILS,
                fail_silently=True,
            )
    return state
