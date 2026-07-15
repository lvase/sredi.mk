from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.municipalities.configuration import apply_configuration, load_configuration


class Command(BaseCommand):
    help = "Validate or apply a municipality configuration JSON file."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--source", default="")
        parser.add_argument("--verify-as", default="")

    def handle(self, *args, **options):
        data = load_configuration(options["path"])
        if not options["apply"]:
            from apps.municipalities.configuration import validate_configuration_payload

            errors = validate_configuration_payload(data)
            if errors:
                raise CommandError(" ".join(errors))
            self.stdout.write(self.style.SUCCESS("Configuration is valid. Use --apply to import."))
            return
        actor = None
        if options["verify_as"]:
            actor = get_user_model().objects.filter(
                username=options["verify_as"],
                is_superuser=True,
            ).first()
            if not actor:
                raise CommandError("--verify-as must identify an existing superuser.")
        try:
            municipality = apply_configuration(
                data,
                options["source"],
                actor=actor,
                verify=bool(actor),
            )
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(self.style.SUCCESS(f"Imported {municipality.name}."))
