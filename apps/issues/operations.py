from django.db.models import Count, Min, Q
from django.utils import timezone

from apps.issues.models import ReceiptDelivery


def receipt_queue_state():
    rows = ReceiptDelivery.objects.aggregate(
        pending=Count("pk", filter=Q(state="queued")),
        failed=Count("pk", filter=Q(state="failed")),
        oldest=Min("queued_at", filter=Q(state="queued")),
    )
    oldest = rows.pop("oldest")
    age = max(0, int((timezone.now() - oldest).total_seconds())) if oldest else 0
    return {**rows, "oldest_pending_seconds": age, "status": "warning" if age > 600 or rows["failed"] else "ok"}
