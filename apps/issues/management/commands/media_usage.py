from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError

from apps.issues.models import IssueAttachment
from apps.municipalities.models import Municipality


def _percentage_reduction(original_bytes, stored_bytes):
    if not original_bytes:
        return "n/a"
    return f"{(1 - stored_bytes / original_bytes) * 100:.1f}%"


class Command(BaseCommand):
    help = "Report read-only issue attachment media usage."

    def add_arguments(self, parser):
        parser.add_argument("--municipality", default="", metavar="SLUG")

    def handle(self, *args, **options):
        queryset = IssueAttachment.objects.select_related("issue__municipality").order_by("pk")
        municipality_slug = options["municipality"]
        if municipality_slug:
            if not Municipality.objects.filter(slug=municipality_slug).exists():
                raise CommandError(f"Unknown municipality: {municipality_slug}")
            queryset = queryset.filter(issue__municipality__slug=municipality_slug)

        totals = {"count": 0, "stored": 0, "original": 0, "processed_stored": 0}
        by_municipality = defaultdict(
            lambda: {"count": 0, "stored": 0, "original": 0, "processed_stored": 0}
        )
        missing_count = 0
        for attachment in queryset:
            try:
                stored_size = attachment.image.storage.size(attachment.image.name)
            except (OSError, ValueError):
                missing_count += 1
                continue
            original_size = attachment.original_size_bytes or 0
            municipality = attachment.issue.municipality.slug
            totals["count"] += 1
            totals["stored"] += stored_size
            totals["original"] += original_size
            if original_size:
                totals["processed_stored"] += stored_size
            row = by_municipality[municipality]
            row["count"] += 1
            row["stored"] += stored_size
            row["original"] += original_size
            if original_size:
                row["processed_stored"] += stored_size

        average = totals["stored"] / totals["count"] if totals["count"] else 0
        self.stdout.write(
            f"total_bytes={totals['stored']} attachment_count={totals['count']} "
            f"average_bytes={average:.0f} reduction_ratio="
            f"{_percentage_reduction(totals['original'], totals['processed_stored'])} "
            f"missing_files={missing_count}"
        )
        for slug in sorted(by_municipality):
            row = by_municipality[slug]
            self.stdout.write(
                f"municipality={slug} total_bytes={row['stored']} "
                f"attachment_count={row['count']} reduction_ratio="
                f"{_percentage_reduction(row['original'], row['processed_stored'])}"
            )
