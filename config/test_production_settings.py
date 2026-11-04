import os
import runpy
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

SETTINGS_PATH = Path(__file__).with_name("settings.py")
PRODUCTION_ENV = {
    "DJANGO_PRODUCTION": "true",
    "DJANGO_DEBUG": "false",
    "DJANGO_SECRET_KEY": "production-settings-test-only-secret-1234567890",
    "DOMAIN": "sredi.example.mk",
    "DJANGO_ALLOWED_HOSTS": "sredi.example.mk",
    "CSRF_TRUSTED_ORIGINS": "https://sredi.example.mk",
    "EMAIL_BACKEND": "django.core.mail.backends.smtp.EmailBackend",
    "EMAIL_HOST": "smtp.example.mk",
    "DEFAULT_FROM_EMAIL": "noreply@example.mk",
    "REDIS_URL": "redis://redis:6379/0",
}


def load_settings(**overrides):
    # Read settings afresh without inheriting developer credentials or changing Django's settings.
    with (
        patch.dict(os.environ, {**PRODUCTION_ENV, **overrides}, clear=True),
        patch("environ.Env.read_env"),
    ):
        return runpy.run_path(str(SETTINGS_PATH))


def test_matching_production_domain_is_accepted():
    configured = load_settings()
    assert configured["SECURE_SSL_REDIRECT"] is True
    assert configured["ALLOWED_HOSTS"] == ["sredi.example.mk"]


@pytest.mark.parametrize("domain", [
    "", "https://sredi.example.mk", "sredi.example.mk:443", "sredi.example.mk/path",
    "sredi.example.mk?query", "sredi.example.mk#fragment", "*.example.mk", "localhost",
    "127.0.0.1", "sredi.example.mk\n", "bad_name.example.mk",
])
def test_invalid_production_domain_is_rejected(domain):
    with pytest.raises(ImproperlyConfigured, match="DOMAIN must be a DNS hostname"):
        load_settings(DOMAIN=domain)


@pytest.mark.parametrize("hosts", ["other.example.mk", ".example.mk", "*"])
def test_domain_must_be_explicitly_allowed(hosts):
    with pytest.raises(ImproperlyConfigured, match="DOMAIN must appear explicitly"):
        load_settings(DJANGO_ALLOWED_HOSTS=hosts)


@pytest.mark.parametrize("origins", ["https://other.example.mk", "http://sredi.example.mk", "https://sredi.example.mk/"])
def test_domain_requires_matching_https_csrf_origin(origins):
    with pytest.raises(ImproperlyConfigured, match="CSRF_TRUSTED_ORIGINS must include"):
        load_settings(CSRF_TRUSTED_ORIGINS=origins)


def test_development_does_not_require_domain():
    assert load_settings(DJANGO_PRODUCTION="false", DOMAIN="")["PRODUCTION"] is False


@pytest.mark.django_db
def test_production_readiness_requires_public_host(client):
    with override_settings(
        DEBUG=False,
        ALLOWED_HOSTS=["sredi.example.mk"],
        SECURE_SSL_REDIRECT=True,
        SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    ):
        ready = client.get(
            "/health/ready/", HTTP_HOST="sredi.example.mk", HTTP_X_FORWARDED_PROTO="https"
        )
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        rejected = client.get(
            "/health/ready/", HTTP_HOST="localhost:8000", HTTP_X_FORWARDED_PROTO="https"
        )
        assert rejected.status_code == 400
