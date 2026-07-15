from django.conf import settings
from django.db import models

from apps.municipalities.models import Department, Municipality


class StaffRole(models.TextChoices):
    MUNICIPALITY_ADMIN = "municipality_admin", "Municipality admin"
    COORDINATOR = "coordinator", "Coordinator"
    DEPARTMENT_MANAGER = "department_manager", "Department manager"
    FIELD_WORKER = "field_worker", "Field worker"
    VIEWER = "viewer", "Viewer"


class StaffProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    municipality = models.ForeignKey(
        Municipality, null=True, blank=True, related_name="staff_profiles", on_delete=models.PROTECT
    )
    department = models.ForeignKey(
        Department, null=True, blank=True, related_name="staff_profiles", on_delete=models.PROTECT
    )
    role = models.CharField(max_length=40, choices=StaffRole.choices, default=StaffRole.VIEWER)
    must_change_password = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.user.get_username()} — {self.role}"


class RecoveryCode(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="two_factor_recovery_codes", on_delete=models.CASCADE
    )
    code_hash = models.CharField(max_length=64)
    used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "used_at"])]


class TrustedDevice(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="trusted_login_devices", on_delete=models.CASCADE
    )
    token_hash = models.CharField(max_length=64, unique=True)
    password_hash = models.CharField(max_length=128)
    label = models.CharField(max_length=160, blank=True)
    last_ip_hash = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["user", "expires_at", "revoked_at"])]


class AuthenticationAttempt(models.Model):
    username_hash = models.CharField(max_length=64)
    ip_hash = models.CharField(max_length=64)
    window_start = models.DateTimeField()
    failure_count = models.PositiveSmallIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["username_hash", "ip_hash"], name="unique_auth_attempt_identity"
            )
        ]
        indexes = [models.Index(fields=["window_start"])]
