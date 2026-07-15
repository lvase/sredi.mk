from pathlib import Path

from django.core.management.base import BaseCommand

from apps.municipalities.configuration import apply_configuration, load_configuration


class Command(BaseCommand):
    help = "Seed unverified starter data for the Radoviš pilot."

    def handle(self, *args, **options):
        path = Path(__file__).resolve().parents[2] / "config" / "radovis.json"
        apply_configuration(load_configuration(path), "Bundled unverified starter data")
        self.stdout.write(self.style.SUCCESS("Seeded unverified Radoviš starter data."))
