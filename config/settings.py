from pathlib import Path

import environ
from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DJANGO_DEBUG=(bool, False),
    E2E_TEST_MODE=(bool, False),
    DJANGO_PRODUCTION=(bool, False),
)

env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="dev-only-change-me")
DEBUG = env("DJANGO_DEBUG", default=False)
E2E_TEST_MODE = env("E2E_TEST_MODE", default=False)
PRODUCTION = env("DJANGO_PRODUCTION", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=["localhost", "127.0.0.1"])
FRONTEND_DEV_ORIGINS = env.list(
    "FRONTEND_DEV_ORIGINS",
    default=["http://localhost:5173", "http://127.0.0.1:5173"],
)

INSTALLED_APPS = [
    "corsheaders",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "apps.accounts",
    "apps.municipalities",
    "apps.issues",
    "apps.dashboard",
    "apps.api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "config.middleware.RequestIDMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    }
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", default="opstinski_inbox"),
        "USER": env("POSTGRES_USER", default="opstinski_inbox"),
        "PASSWORD": env("POSTGRES_PASSWORD", default="opstinski_inbox_dev"),
        "HOST": env("POSTGRES_HOST", default="localhost"),
        "PORT": env("POSTGRES_PORT", default="5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "mk"
TIME_ZONE = "Europe/Skopje"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "staff_dashboard"
LOGOUT_REDIRECT_URL = "home"

EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="noreply@sredi.local")
EMAIL_HOST = env("EMAIL_HOST", default="localhost")
EMAIL_PORT = env.int("EMAIL_PORT", default=25)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=False)
EMAIL_TIMEOUT = env.int("EMAIL_TIMEOUT", default=10)
PLATFORM_OPERATOR_NAME = env("PLATFORM_OPERATOR_NAME", default="Sredi / Opštinski Inbox")
PRIVACY_CONTACT_EMAIL = env("PRIVACY_CONTACT_EMAIL", default="privacy@sredi.mk")

FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
ISSUE_RATE_LIMIT_HOURLY = env.int("ISSUE_RATE_LIMIT_HOURLY", default=3)
ISSUE_RATE_LIMIT_DAILY = env.int("ISSUE_RATE_LIMIT_DAILY", default=10)
TRUSTED_PROXY_IPS = env.list("TRUSTED_PROXY_IPS", default=[])
MAX_ISSUE_PHOTOS = env.int("MAX_ISSUE_PHOTOS", default=5)
MAX_ISSUE_IMAGE_SIZE_BYTES = env.int("MAX_ISSUE_IMAGE_SIZE_BYTES", default=5 * 1024 * 1024)

SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_HTTPONLY = True
CORS_ALLOWED_ORIGINS = FRONTEND_DEV_ORIGINS if DEBUG else []
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=FRONTEND_DEV_ORIGINS)
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = PRODUCTION
CSRF_COOKIE_SECURE = PRODUCTION
SECURE_SSL_REDIRECT = PRODUCTION
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if PRODUCTION else None
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

if PRODUCTION:
    production_errors = []
    if DEBUG:
        production_errors.append("DJANGO_DEBUG must be false")
    if SECRET_KEY == "dev-only-change-me" or len(SECRET_KEY) < 40:
        production_errors.append("DJANGO_SECRET_KEY must be a strong non-development value")
    if not ALLOWED_HOSTS or any(host in {"localhost", "127.0.0.1", "*"} for host in ALLOWED_HOSTS):
        production_errors.append("DJANGO_ALLOWED_HOSTS must contain only explicit production hosts")
    if EMAIL_BACKEND.endswith("console.EmailBackend"):
        production_errors.append("EMAIL_BACKEND cannot use the console backend")
    if not EMAIL_HOST or not DEFAULT_FROM_EMAIL:
        production_errors.append("SMTP host and sender must be configured")
    if not CSRF_TRUSTED_ORIGINS or any(not origin.startswith("https://") for origin in CSRF_TRUSTED_ORIGINS):
        production_errors.append("CSRF_TRUSTED_ORIGINS must contain HTTPS origins")
    if production_errors:
        raise ImproperlyConfigured("Invalid production configuration: " + "; ".join(production_errors))

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "json",
        },
    },
    "formatters": {
        "json": {"()": "config.logging.JSONFormatter"},
    },
    "loggers": {
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
        "apps.issues": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "sredi.request": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}
