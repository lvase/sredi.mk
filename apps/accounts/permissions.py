from functools import wraps

from django.conf import settings
from django.shortcuts import redirect
from rest_framework.permissions import BasePermission

from apps.accounts.security import confirmed_totp_device


def authentication_complete(user):
    if not user.is_authenticated or not user.is_active:
        return False
    profile = getattr(user, "staffprofile", None)
    if profile and profile.must_change_password:
        return False
    if user.is_superuser or confirmed_totp_device(user):
        return bool(callable(getattr(user, "is_verified", None)) and user.is_verified())
    return True


class CompleteAuthentication(BasePermission):
    message = "Завршете ја најавата и потврдата на идентитетот."

    def has_permission(self, request, view):
        return authentication_complete(request.user)


def frontend_login(request, **kwargs):
    origin = settings.FRONTEND_DEV_ORIGINS[0] if settings.DEBUG else ""
    return redirect(f"{origin}/login")


def staff_login_required(view):
    @wraps(view)
    def guarded(request, *args, **kwargs):
        if not authentication_complete(request.user):
            return frontend_login(request)
        return view(request, *args, **kwargs)
    return guarded
