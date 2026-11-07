import logging
import smtplib
from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import connection, transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import AuthenticationAttempt
from apps.issues.models import (
    AttachmentDeletionState,
    ReceiptDelivery,
    ReceiptDeliveryState,
    SubmissionRateLimit,
)
from apps.issues.operations import receipt_queue_state
from apps.issues.retention import eligible_attachments, run_retention_batch
from apps.issues.storage import STORAGE_STATE_KEY, filesystem_usage_state
from apps.municipalities.models import Municipality

logger = logging.getLogger(__name__)


@shared_task
def dispatch_receipt_deliveries(batch_size=100):
    """Publish durable outbox rows; lost publications are redispatched after five minutes."""
    now = timezone.now()
    with transaction.atomic():
        deliveries = list(
            ReceiptDelivery.objects.select_for_update(skip_locked=True)
            .filter(state=ReceiptDeliveryState.QUEUED, next_attempt_at__lte=now)
            .filter(Q(lease_until__isnull=True) | Q(lease_until__lte=now))
            .filter(Q(dispatched_at__isnull=True) | Q(dispatched_at__lte=now - timedelta(minutes=5)))
            .order_by("queued_at")[:min(100, max(1, batch_size))]
        )
        identifiers = [delivery.pk for delivery in deliveries]
        ReceiptDelivery.objects.filter(pk__in=identifiers).update(dispatched_at=now)
    published = 0
    for identifier in identifiers:
        try:
            send_receipt_email.apply_async(args=[identifier], retry=False)
            published += 1
        except Exception as exc:
            ReceiptDelivery.objects.filter(pk=identifier, dispatched_at=now).update(
                dispatched_at=None, next_attempt_at=now + timedelta(minutes=1),
                last_error=exc.__class__.__name__,
            )
            logger.exception("receipt_queue_publish_failed", extra={"receipt_delivery_id": identifier})
    return {"published": published, "deferred": len(identifiers) - published}


@shared_task
def send_receipt_email(delivery_id):
    now = timezone.now()
    lease = now + timedelta(seconds=settings.CELERY_TASK_TIME_LIMIT + 60)
    with transaction.atomic():
        delivery = ReceiptDelivery.objects.select_for_update().select_related("issue", "issue__municipality").get(pk=delivery_id)
        if delivery.state != ReceiptDeliveryState.QUEUED:
            return "already_sent" if delivery.state == ReceiptDeliveryState.SENT else "failed"
        if delivery.next_attempt_at > now or (delivery.lease_until and delivery.lease_until > now):
            return "deferred"
        delivery.attempt_count += 1
        delivery.last_attempt_at = now
        delivery.lease_until = lease
        delivery.save(update_fields=["attempt_count", "last_attempt_at", "lease_until"])
    try:
        if not delivery.recipient:
            raise ValueError("receipt recipient has been removed")
        delivered = send_mail(
            subject=f"Потврда за пријава {delivery.issue.tracking_code}",
            message=(
                f"Вашата пријава до {delivery.issue.municipality.name} е примена.\n\n"
                f"Код за следење: {delivery.issue.tracking_code}\n"
                "Кодот чувајте го приватно и користете го за проверка на статусот."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[delivery.recipient], fail_silently=False,
        )
        if not delivered:
            raise smtplib.SMTPException("SMTP backend did not accept the message")
    except Exception as exc:
        permanent = isinstance(exc, ValueError) or delivery.attempt_count >= 6
        ReceiptDelivery.objects.filter(pk=delivery_id, lease_until=lease).update(
            state=ReceiptDeliveryState.FAILED if permanent else ReceiptDeliveryState.QUEUED,
            failed_at=timezone.now() if permanent else None,
            next_attempt_at=timezone.now() + timedelta(seconds=min(3600, 60 * 2 ** min(delivery.attempt_count - 1, 6))),
            dispatched_at=None, lease_until=None, last_error=exc.__class__.__name__,
        )
        logger.warning("receipt_delivery_failed" if permanent else "receipt_delivery_retry_pending",
                       extra={"receipt_delivery_id": delivery_id})
        return "failed" if permanent else "retry_pending"
    ReceiptDelivery.objects.filter(pk=delivery_id, lease_until=lease).update(
        state=ReceiptDeliveryState.SENT, sent_at=timezone.now(), failed_at=None,
        lease_until=None, last_error="",
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


@shared_task
def monitor_delivery_queue():
    state = receipt_queue_state()
    if settings.REDIS_URL:
        try:
            from django_redis import get_redis_connection

            memory = get_redis_connection("default").info("memory")
            maximum = memory.get("maxmemory", 0)
            state["redis_used_percent"] = round(100 * memory["used_memory"] / maximum, 1) if maximum else None
            state["redis_rss_bytes"] = memory.get("used_memory_rss")
            if maximum and state["redis_used_percent"] >= 70:
                state["status"] = "warning"
        except Exception:
            state["redis"] = "unavailable"
            state["status"] = "warning"
    if state["status"] == "warning":
        logger.warning("receipt_queue_delayed", extra={"queue_state": state})
        try:
            alert = cache.add("operations:receipt-alert", True, timeout=3600)
        except Exception:
            alert = True
        if alert and settings.OPERATIONS_ALERT_EMAILS:
            send_mail("Sredi receipt queue warning", str(state), settings.DEFAULT_FROM_EMAIL,
                      settings.OPERATIONS_ALERT_EMAILS, fail_silently=True)
    return state
