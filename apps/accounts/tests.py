from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from django_otp.oath import totp
from django_otp.plugins.otp_totp.models import TOTPDevice

from apps.accounts.models import RecoveryCode, StaffProfile, TrustedDevice
from apps.accounts.security import TRUSTED_DEVICE_COOKIE, generate_recovery_codes


def current_token(device):
    return str(
        totp(
            device.bin_key,
            step=device.step,
            t0=device.t0,
            digits=device.digits,
            drift=device.drift,
        )
    ).zfill(device.digits)


@pytest.mark.django_db
def test_non_enrolled_staff_uses_password_only(client):
    user = get_user_model().objects.create_user(username="staff", password="good-test-pass")
    StaffProfile.objects.create(user=user)

    response = client.post("/api/auth/login/", {"username": "staff", "password": "good-test-pass"})

    assert response.status_code == 200
    assert response.json()["data"]["next_step"] == "authenticated"
    assert client.session.get("_auth_user_id") == str(user.pk)


@pytest.mark.django_db
def test_superuser_enrolls_once_and_receives_hashed_recovery_and_trusted_tokens(client):
    user = get_user_model().objects.create_superuser(
        username="owner", email="owner@example.mk", password="good-test-pass"
    )
    login_response = client.post(
        "/api/auth/login/", {"username": "owner", "password": "good-test-pass"}
    )
    assert login_response.json()["data"]["next_step"] == "enroll_superuser_2fa"

    setup = client.post("/api/auth/security/totp/setup/", {}).json()["data"]
    device = TOTPDevice.objects.get(user=user, confirmed=False)
    confirm = client.post(
        "/api/auth/security/totp/confirm/",
        {"token": current_token(device), "remember_device": True},
    )

    assert confirm.status_code == 200
    payload = confirm.json()["data"]
    assert payload["authenticated"] is True
    assert len(payload["recovery_codes"]) == 10
    assert RecoveryCode.objects.filter(user=user, used_at__isnull=True).count() == 10
    assert not RecoveryCode.objects.filter(code_hash=payload["recovery_codes"][0]).exists()
    assert setup["secret"] not in RecoveryCode.objects.values_list("code_hash", flat=True)
    cookie = confirm.cookies[TRUSTED_DEVICE_COOKIE].value
    trusted = TrustedDevice.objects.get(user=user)
    assert cookie.split(".", 1)[1] != trusted.token_hash
    assert timedelta(days=29, hours=23) < trusted.expires_at - trusted.created_at <= timedelta(days=30)
    assert client.get("/admin/").status_code == 200

    client.post("/api/auth/logout/", {})
    second_login = client.post(
        "/api/auth/login/", {"username": "owner", "password": "good-test-pass"}
    )
    assert second_login.json()["data"]["next_step"] == "authenticated"


@pytest.mark.django_db
def test_expired_trusted_device_requires_otp(client):
    user = get_user_model().objects.create_user(username="staff", password="good-test-pass")
    StaffProfile.objects.create(user=user)
    TOTPDevice.objects.create(user=user, name="Sredi", confirmed=True)
    client.post("/api/auth/login/", {"username": "staff", "password": "good-test-pass"})
    pending = client.session
    pending["pending_auth_user_id"] = user.pk
    pending.save()
    device = TOTPDevice.objects.get(user=user)
    verified = client.post(
        "/api/auth/2fa/verify/", {"token": current_token(device), "remember_device": True}
    )
    assert verified.status_code == 200
    TrustedDevice.objects.filter(user=user).update(expires_at=timezone.now() - timedelta(seconds=1))
    client.post("/api/auth/logout/", {})

    response = client.post(
        "/api/auth/login/", {"username": "staff", "password": "good-test-pass"}
    )
    assert response.json()["data"]["next_step"] == "verify_2fa"


@pytest.mark.django_db
def test_recovery_code_is_single_use(client):
    user = get_user_model().objects.create_user(username="staff", password="good-test-pass")
    StaffProfile.objects.create(user=user)
    TOTPDevice.objects.create(user=user, name="Sredi", confirmed=True)
    code = generate_recovery_codes(user)[0]

    client.post("/api/auth/login/", {"username": "staff", "password": "good-test-pass"})
    first = client.post("/api/auth/2fa/verify/", {"token": code, "remember_device": False})
    assert first.status_code == 200
    client.post("/api/auth/logout/", {})
    client.cookies.pop(TRUSTED_DEVICE_COOKIE, None)
    client.post("/api/auth/login/", {"username": "staff", "password": "good-test-pass"})
    second = client.post("/api/auth/2fa/verify/", {"token": code, "remember_device": False})
    assert second.status_code == 400


@pytest.mark.django_db
def test_five_password_failures_are_throttled_by_username_and_ip(client):
    user = get_user_model().objects.create_user(username="staff", password="good-test-pass")
    StaffProfile.objects.create(user=user)
    for _ in range(4):
        assert client.post(
            "/api/auth/login/", {"username": "staff", "password": "wrong"}
        ).status_code == 400
    fifth = client.post("/api/auth/login/", {"username": "staff", "password": "wrong"})
    assert fifth.status_code == 429
    assert int(fifth["Retry-After"]) > 0
    assert client.post(
        "/api/auth/login/", {"username": "staff", "password": "good-test-pass"}
    ).status_code == 429


@pytest.mark.django_db
def test_temporary_password_must_change_before_workspace_access(client):
    user = get_user_model().objects.create_user(username="new-staff", password="temporary-pass-123")
    StaffProfile.objects.create(user=user, must_change_password=True)
    login_response = client.post(
        "/api/auth/login/", {"username": "new-staff", "password": "temporary-pass-123"}
    )
    assert login_response.json()["data"]["next_step"] == "change_password"
    assert "_auth_user_id" not in client.session

    changed = client.post(
        "/api/auth/security/password/",
        {"current_password": "temporary-pass-123", "new_password": "new-long-pass-456"},
    )
    assert changed.status_code == 200
    assert changed.json()["data"]["next_step"] == "authenticated"
    user.refresh_from_db()
    assert user.staffprofile.must_change_password is False
    assert user.check_password("new-long-pass-456")
