import base64
import hashlib
import hmac
import io
import secrets
from dataclasses import dataclass
from datetime import timedelta

import qrcode
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import AuthenticationAttempt, RecoveryCode, StaffProfile, TrustedDevice

ATTEMPT_WINDOW = timedelta(minutes=15)
MAX_AUTH_FAILURES = 5
TRUSTED_DEVICE_AGE = timedelta(days=30)
PENDING_USER_SESSION_KEY = "pending_auth_user_id"
TRUSTED_DEVICE_COOKIE = "sredi_trusted_device"


@dataclass(frozen=True)
class AttemptState:
    allowed: bool
    retry_after_seconds: int = 0


def _keyed_hash(purpose, value):
    key = f"{settings.SECRET_KEY}:{purpose}".encode()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


def normalized_username(value):
    return (value or "").strip().casefold()[:150]


def attempt_identity(username, ip_address):
    return (
        _keyed_hash("auth-username", normalized_username(username)),
        _keyed_hash("auth-ip", ip_address or "unknown"),
    )


@transaction.atomic
def auth_attempt_state(username, ip_address):
    now = timezone.now()
    username_hash, ip_hash = attempt_identity(username, ip_address)
    attempt, _ = AuthenticationAttempt.objects.select_for_update().get_or_create(
        username_hash=username_hash,
        ip_hash=ip_hash,
        defaults={"window_start": now},
    )
    if now - attempt.window_start >= ATTEMPT_WINDOW:
        attempt.window_start = now
        attempt.failure_count = 0
        attempt.save(update_fields=["window_start", "failure_count", "updated_at"])
    if attempt.failure_count < MAX_AUTH_FAILURES:
        return AttemptState(True)
    retry_at = attempt.window_start + ATTEMPT_WINDOW
    return AttemptState(False, max(1, int((retry_at - now).total_seconds())))


@transaction.atomic
def record_auth_failure(username, ip_address):
    now = timezone.now()
    username_hash, ip_hash = attempt_identity(username, ip_address)
    attempt, _ = AuthenticationAttempt.objects.select_for_update().get_or_create(
        username_hash=username_hash,
        ip_hash=ip_hash,
        defaults={"window_start": now},
    )
    if now - attempt.window_start >= ATTEMPT_WINDOW:
        attempt.window_start = now
        attempt.failure_count = 0
    attempt.failure_count += 1
    attempt.save(update_fields=["window_start", "failure_count", "updated_at"])
    if attempt.failure_count >= MAX_AUTH_FAILURES:
        user = get_user_model().objects.filter(username__iexact=normalized_username(username)).first()
        if user:
            revoke_trusted_devices(user)
    retry_at = attempt.window_start + ATTEMPT_WINDOW
    return AttemptState(
        attempt.failure_count < MAX_AUTH_FAILURES,
        max(1, int((retry_at - now).total_seconds())),
    )


def clear_auth_failures(username, ip_address):
    username_hash, ip_hash = attempt_identity(username, ip_address)
    AuthenticationAttempt.objects.filter(username_hash=username_hash, ip_hash=ip_hash).delete()


def ensure_staff_profile(user):
    profile, _ = StaffProfile.objects.get_or_create(user=user)
    return profile


def confirmed_totp_device(user):
    return TOTPDevice.objects.filter(user=user, confirmed=True).order_by("id").first()


def begin_totp_enrollment(user):
    TOTPDevice.objects.filter(user=user, confirmed=False).delete()
    device = TOTPDevice.objects.create(user=user, name="Sredi", confirmed=False)
    return device


def enrollment_payload(device):
    buffer = io.BytesIO()
    image = qrcode.make(device.config_url)
    image.save(buffer, format="PNG")
    return {
        "secret": device.key.upper(),
        "configuration_url": device.config_url,
        "qr_code": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode(),
    }


def _recovery_hash(user, code):
    normalized = "".join(character for character in (code or "").upper() if character.isalnum())
    return _keyed_hash(f"recovery:{user.pk}", normalized)


def generate_recovery_codes(user):
    RecoveryCode.objects.filter(user=user).delete()
    plain_codes = []
    records = []
    for _ in range(10):
        raw = secrets.token_hex(4).upper()
        display = f"{raw[:4]}-{raw[4:]}"
        plain_codes.append(display)
        records.append(RecoveryCode(user=user, code_hash=_recovery_hash(user, display)))
    RecoveryCode.objects.bulk_create(records)
    return plain_codes


@transaction.atomic
def consume_recovery_code(user, value):
    candidate = _recovery_hash(user, value)
    for recovery in RecoveryCode.objects.select_for_update().filter(user=user, used_at__isnull=True):
        if constant_time_compare(recovery.code_hash, candidate):
            recovery.used_at = timezone.now()
            recovery.save(update_fields=["used_at"])
            return True
    return False


def verify_second_factor(user, token):
    device = confirmed_totp_device(user)
    if device:
        try:
            if device.verify_token(str(token).replace(" ", "")):
                return "totp"
        except (TypeError, ValueError):
            pass
    return "recovery" if consume_recovery_code(user, token) else None


def _trusted_hash(user, raw_token):
    return _keyed_hash(f"trusted-device:{user.pk}", raw_token)


def issue_trusted_device(user, request):
    raw = secrets.token_urlsafe(32)
    expires_at = timezone.now() + TRUSTED_DEVICE_AGE
    trusted = TrustedDevice.objects.create(
        user=user,
        token_hash=_trusted_hash(user, raw),
        password_hash=user.password,
        label=request.META.get("HTTP_USER_AGENT", "")[:160],
        last_ip_hash=_keyed_hash("trusted-device-ip", request.META.get("REMOTE_ADDR", "")),
        expires_at=expires_at,
    )
    return f"{trusted.pk}.{raw}", expires_at


def validate_trusted_device(user, cookie_value):
    try:
        identifier, raw = (cookie_value or "").split(".", 1)
        trusted = TrustedDevice.objects.get(pk=int(identifier), user=user)
    except (TypeError, ValueError, TrustedDevice.DoesNotExist):
        return False
    now = timezone.now()
    valid = (
        trusted.revoked_at is None
        and trusted.expires_at > now
        and constant_time_compare(trusted.password_hash, user.password)
        and constant_time_compare(trusted.token_hash, _trusted_hash(user, raw))
    )
    if not valid:
        return False
    trusted.last_used_at = now
    trusted.save(update_fields=["last_used_at"])
    return True


def revoke_trusted_devices(user):
    TrustedDevice.objects.filter(user=user, revoked_at__isnull=True).update(revoked_at=timezone.now())


def clear_pending_auth(request):
    request.session.pop(PENDING_USER_SESSION_KEY, None)


def set_pending_auth(request, user):
    request.session.cycle_key()
    request.session[PENDING_USER_SESSION_KEY] = user.pk


def pending_user(request):
    user_id = request.session.get(PENDING_USER_SESSION_KEY)
    if not user_id:
        return None
    return get_user_model().objects.filter(pk=user_id, is_active=True).first()
