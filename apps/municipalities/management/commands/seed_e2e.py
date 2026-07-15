import base64
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import StaffProfile, StaffRole
from apps.issues.models import Issue, IssueAttachment, IssueCategory
from apps.municipalities.configuration import apply_configuration, load_configuration
from apps.municipalities.models import Municipality, Settlement

ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class Command(BaseCommand):
    help = "Seed deterministic data for the isolated Playwright environment."

    def handle(self, *args, **options):
        if not settings.E2E_TEST_MODE:
            raise CommandError("seed_e2e is available only when E2E_TEST_MODE=1.")
        config_root = Path(__file__).resolve().parents[2] / "config"
        apply_configuration(load_configuration(config_root / "konce.json"), "E2E fixture")
        apply_configuration(load_configuration(config_root / "radovis.json"), "E2E fixture")

        user_model = get_user_model()
        for username, slug in [("konce-staff", "konce"), ("radovis-staff", "radovis")]:
            user, _ = user_model.objects.get_or_create(username=username)
            user.set_password("testpass")
            user.save()
            StaffProfile.objects.update_or_create(
                user=user,
                defaults={
                    "municipality": Municipality.objects.get(slug=slug),
                    "role": StaffRole.COORDINATOR,
                },
            )
        owner, _ = user_model.objects.get_or_create(
            username="e2e-owner", defaults={"email": "owner@example.com"}
        )
        owner.is_superuser = True
        owner.is_staff = True
        owner.set_password("testpass")
        owner.save()

        for slug, title, code in [
            ("konce", "E2E Конче пријава", "E2EKONCE01"),
            ("radovis", "E2E Радовиш пријава", "E2ERADOV01"),
        ]:
            municipality = Municipality.objects.get(slug=slug)
            issue, created = Issue.objects.get_or_create(
                tracking_code=code,
                defaults={
                    "municipality": municipality,
                    "settlement": Settlement.objects.filter(
                        municipality=municipality, is_active=True
                    ).first(),
                    "category": IssueCategory.objects.filter(
                        municipality=municipality, is_active=True
                    ).first(),
                    "title": title,
                    "description": "E2E опис",
                    "location_text": "E2E локација",
                },
            )
            if created and slug == "konce":
                attachment = IssueAttachment(issue=issue)
                attachment.image.save("e2e.png", ContentFile(ONE_PIXEL_PNG), save=True)

        visual_municipality = Municipality.objects.get(slug="konce")
        visual_issue, _ = Issue.objects.get_or_create(
            tracking_code="E2EVISUAL01",
            defaults={
                "municipality": visual_municipality,
                "settlement": Settlement.objects.filter(
                    municipality=visual_municipality,
                    is_active=True,
                ).first(),
                "category": IssueCategory.objects.filter(
                    municipality=visual_municipality,
                    is_active=True,
                ).first(),
                "title": "E2E визуелна пријава",
                "description": "Детерминистички опис за визуелна регресија",
                "location_text": "Детерминистичка локација",
            },
        )
        visual_issue.public_title = "Јавен: визуелна пријава"
        visual_issue.public_title_approved_at = timezone.now()
        visual_issue.public_title_approved_by = user_model.objects.get(username="konce-staff")
        visual_issue.save(
            update_fields=[
                "public_title",
                "public_title_approved_at",
                "public_title_approved_by",
                "updated_at",
            ]
        )
        self.stdout.write(self.style.SUCCESS("Seeded E2E fixtures."))
