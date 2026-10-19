import secrets
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F
from django.utils import timezone

from apps.issues.models import FINAL_ISSUE_STATUSES, Issue, IssueCategory, IssueStatus
from apps.municipalities.models import Municipality, Settlement


class Command(BaseCommand):
    help = "Seed a disposable 5,200- or 78,000-report scalability dataset."

    def add_arguments(self, parser):
        parser.add_argument("--municipality", required=True, metavar="SLUG")
        parser.add_argument("--reports", type=int, choices=[5200, 78000], required=True)
        parser.add_argument("--confirm", default="")
        parser.add_argument("--batch-size", type=int, default=1000)

    def handle(self, *args, **options):
        slug = options["municipality"]
        total = options["reports"]
        if options["confirm"] != f"SEED-{slug}-{total}":
            raise CommandError(f"Set --confirm SEED-{slug}-{total} for this disposable dataset.")
        batch_size = min(5000, max(100, options["batch_size"]))
        try:
            municipality = Municipality.objects.get(slug=slug)
        except Municipality.DoesNotExist as exc:
            raise CommandError(f"Unknown municipality: {slug}") from exc
        settlements = list(
            Settlement.objects.filter(municipality=municipality, is_active=True).values_list(
                "pk", flat=True
            )
        )
        categories = list(
            IssueCategory.objects.filter(municipality=municipality, is_active=True).values_list(
                "pk", flat=True
            )
        )
        if not settlements or not categories:
            raise CommandError("The municipality needs at least one active settlement and category.")

        statuses = [
            IssueStatus.PENDING_TRIAGE,
            IssueStatus.ACCEPTED,
            IssueStatus.ASSIGNED,
            IssueStatus.IN_PROGRESS,
            IssueStatus.RESOLVED,
            IssueStatus.CLOSED,
            IssueStatus.WAITING_EXTERNAL,
        ]
        run_token = secrets.token_hex(3).upper()
        now = timezone.now()
        created = 0
        while created < total:
            count = min(batch_size, total - created)
            rows = []
            for index in range(created, created + count):
                status = statuses[index % len(statuses)]
                age = timedelta(days=(index % 365), minutes=index % 1440)
                submitted_at = now - age
                rows.append(
                    Issue(
                        municipality=municipality,
                        settlement_id=settlements[index % len(settlements)],
                        category_id=categories[index % len(categories)],
                        tracking_code=f"L{run_token}{index:09d}",
                        title=f"Load profile report {index + 1}",
                        public_title=f"Јавна тест пријава {index + 1}",
                        public_title_approved_at=now,
                        description="Synthetic scalability profile report.",
                        location_text=f"Load location {index % 500}",
                        status=status,
                        is_spam=status == IssueStatus.REJECTED_SPAM,
                        triaged_at=submitted_at + timedelta(hours=2)
                        if status != IssueStatus.PENDING_TRIAGE
                        else None,
                        resolved_at=submitted_at + timedelta(days=2)
                        if status == IssueStatus.RESOLVED
                        else None,
                        closed_at=submitted_at + timedelta(days=3)
                        if status == IssueStatus.CLOSED
                        else None,
                        attachment_retention_started_at=submitted_at + timedelta(days=2)
                        if status in FINAL_ISSUE_STATUSES
                        else None,
                    )
                )
            inserted = Issue.objects.bulk_create(rows, batch_size=batch_size)
            Issue.objects.filter(pk__in=[row.pk for row in inserted]).update(
                submitted_at=now - timedelta(days=int((created / total) * 365))
            )
            created += count
            self.stdout.write(f"seeded={created}/{total}")

        Municipality.objects.filter(pk=municipality.pk).update(
            statistics_version=F("statistics_version") + 1
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {total} reports for {slug}; tracking prefix=L{run_token}."
            )
        )
