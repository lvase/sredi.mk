from apps.issues.models import ReceiptDelivery


def queue_receipt_delivery(issue):
    """Persist an outbox record in the submission transaction; never contact Redis here."""
    delivery, _ = ReceiptDelivery.objects.get_or_create(issue=issue, defaults={"recipient": issue.citizen_email})
    return delivery
