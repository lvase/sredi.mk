from django.conf import settings
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Send a provider-neutral SMTP delivery test."

    def add_arguments(self, parser):
        parser.add_argument("--to", required=True, help="Recipient address for the test")

    def handle(self, *args, **options):
        try:
            delivered = send_mail(
                "Sredi SMTP test",
                "This message confirms that the Sredi production SMTP configuration works.",
                settings.DEFAULT_FROM_EMAIL,
                [options["to"]],
                fail_silently=False,
            )
        except Exception as exc:
            raise CommandError(f"SMTP test failed: {exc.__class__.__name__}: {exc}") from exc
        if delivered != 1:
            raise CommandError("SMTP backend did not confirm delivery.")
        self.stdout.write(self.style.SUCCESS("SMTP test message accepted for delivery."))
