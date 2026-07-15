from django.contrib import admin

from apps.accounts.models import AuthenticationAttempt, RecoveryCode, StaffProfile, TrustedDevice


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "municipality", "department", "role", "must_change_password"]
    list_filter = ["municipality", "department", "role", "must_change_password"]
    search_fields = ["user__username", "user__email"]


@admin.register(RecoveryCode)
class RecoveryCodeAdmin(admin.ModelAdmin):
    list_display = ["user", "created_at", "used_at"]
    readonly_fields = ["code_hash", "created_at", "used_at"]


@admin.register(TrustedDevice)
class TrustedDeviceAdmin(admin.ModelAdmin):
    list_display = ["user", "label", "created_at", "last_used_at", "expires_at", "revoked_at"]
    readonly_fields = ["token_hash", "password_hash", "last_ip_hash", "created_at", "last_used_at"]


@admin.register(AuthenticationAttempt)
class AuthenticationAttemptAdmin(admin.ModelAdmin):
    list_display = ["window_start", "failure_count", "updated_at"]
    readonly_fields = ["username_hash", "ip_hash", "window_start", "failure_count", "updated_at"]
