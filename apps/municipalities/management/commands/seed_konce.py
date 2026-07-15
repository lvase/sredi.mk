from pathlib import Path

from django.core.management.base import BaseCommand

from apps.municipalities.configuration import apply_configuration, load_configuration


class Command(BaseCommand):
    help = "Seed unverified starter data for the Konče pilot."

    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / "config" / "konce.json"
        apply_configuration(load_configuration(path), "Bundled unverified starter data")
        self.stdout.write(self.style.SUCCESS("Seeded unverified Konče starter data."))
