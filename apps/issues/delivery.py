import logging

from django.db import transaction
from django.utils import timezone

from apps.issues.models import ReceiptDelivery, ReceiptDeliveryState

logger = logging.getLogger(__name__)


def _publish_receipt(delivery_id):
    from apps.issues.tasks import send_receipt_email

    try:
        send_receipt_email.delay(delivery_id)
    except Exception as exc:
        ReceiptDelivery.objects.filter(pk=delivery_id, state=ReceiptDeliveryState.QUEUED).update(
            state=ReceiptDeliveryState.FAILED,
            failed_at=timezone.now(),
            last_error=exc.__class__.__name__,
        )
        logger.exception("receipt_queue_publish_failed", extra={"receipt_delivery_id": delivery_id})


def queue_receipt_delivery(issue):
    with transaction.atomic():
        delivery = ReceiptDelivery.objects.create(issue=issue, recipient=issue.citizen_email)
        transaction.on_commit(lambda: _publish_receipt(delivery.pk))
    return delivery
