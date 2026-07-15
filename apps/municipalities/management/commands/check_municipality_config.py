from django.core.management.base import BaseCommand, CommandError

from apps.municipalities.configuration import validate_municipality_configuration
from apps.municipalities.models import Municipality


class Command(BaseCommand):
    help = "Validate stored municipality workflow configuration."

    def add_arguments(self, parser):
        parser.add_argument("--slug", default="")

    def handle(self, *args, **options):
        municipalities = Municipality.objects.filter(is_active=True)
        if options["slug"]:
            municipalities = municipalities.filter(slug=options["slug"])
        all_errors = []
        for municipality in municipalities:
            errors = validate_municipality_configuration(municipality)
            if municipality.configuration_status != "verified":
                errors.append("Конфигурацијата не е официјално верификувана.")
            if errors:
                all_errors.extend(f"{municipality.slug}: {error}" for error in errors)
            else:
                self.stdout.write(self.style.SUCCESS(f"{municipality.slug}: valid and verified"))
        if all_errors:
            raise CommandError("\n".join(all_errors))
