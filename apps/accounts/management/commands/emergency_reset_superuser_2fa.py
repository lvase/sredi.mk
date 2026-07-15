import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import RecoveryCode
from apps.accounts.security import revoke_trusted_devices


class Command(BaseCommand):
    help = "Emergency VPS-console reset for a platform superuser's 2FA."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("--confirm", required=True)

    def handle(self, *args, **options):
        username = options["username"]
        if os.environ.get("ENABLE_EMERGENCY_2FA_RESET") != "true":
            raise CommandError("Set ENABLE_EMERGENCY_2FA_RESET=true only for this VPS console run.")
        if options["confirm"] != f"RESET-{username}":
            raise CommandError("Confirmation must exactly match RESET-<username>.")
        user = get_user_model().objects.filter(username=username, is_superuser=True).first()
        if not user:
            raise CommandError("No active platform superuser matches that username.")
        TOTPDevice.objects.filter(user=user).delete()
        RecoveryCode.objects.filter(user=user).delete()
        revoke_trusted_devices(user)
        self.stdout.write(self.style.WARNING("2FA reset. Enrollment is required on the next login."))
