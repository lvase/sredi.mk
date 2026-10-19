from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

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
        "CONN_MAX_AGE": env.int("DB_CONN_MAX_AGE", default=60),
        "OPTIONS": {
            "options": (
                f"-c statement_timeout={env.int('DB_STATEMENT_TIMEOUT_MS', default=15000)} "
                f"-c lock_timeout={env.int('DB_LOCK_TIMEOUT_MS', default=5000)}"
            )
        },
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
DATA_UPLOAD_MAX_MEMORY_SIZE = env.int("DATA_UPLOAD_MAX_MEMORY_SIZE", default=28 * 1024 * 1024)
ISSUE_RATE_LIMIT_HOURLY = env.int("ISSUE_RATE_LIMIT_HOURLY", default=3)
ISSUE_RATE_LIMIT_DAILY = env.int("ISSUE_RATE_LIMIT_DAILY", default=10)
TRUSTED_PROXY_IPS = env.list("TRUSTED_PROXY_IPS", default=[])
MAX_ISSUE_PHOTOS = env.int("MAX_ISSUE_PHOTOS", default=5)
MAX_ISSUE_IMAGE_SIZE_BYTES = env.int("MAX_ISSUE_IMAGE_SIZE_BYTES", default=5 * 1024 * 1024)
ISSUE_IMAGE_MAX_PIXEL_COUNT = env.int("ISSUE_IMAGE_MAX_PIXEL_COUNT", default=24_000_000)
ISSUE_IMAGE_MAX_LONG_EDGE = env.int("ISSUE_IMAGE_MAX_LONG_EDGE", default=2048)
ISSUE_IMAGE_MIN_LONG_EDGE = env.int("ISSUE_IMAGE_MIN_LONG_EDGE", default=1024)
ISSUE_IMAGE_MAX_OUTPUT_SIZE_BYTES = env.int(
    "ISSUE_IMAGE_MAX_OUTPUT_SIZE_BYTES", default=800 * 1024
)
ISSUE_TEXT_BODY_LIMIT_BYTES = env.int("ISSUE_TEXT_BODY_LIMIT_BYTES", default=1024 * 1024)

REDIS_URL = env("REDIS_URL", default="")
RATE_LIMIT_CACHE_ALIAS = "rate_limits"
if REDIS_URL:
    redis_parts = urlsplit(REDIS_URL)

    def redis_database_url(database):
        return urlunsplit(redis_parts._replace(path=f"/{database}"))

    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": redis_database_url(1),
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "TIMEOUT": 300,
        },
        "rate_limits": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": redis_database_url(2),
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "TIMEOUT": 900,
        },
    }
else:
    CACHES = {
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "rate_limits": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "sredi-rate-limits",
        },
    }

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL or "memory://")
CELERY_RESULT_BACKEND = env("CELERY_RESULT_BACKEND", default=REDIS_URL or "cache+memory://")
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True
CELERY_TASK_TIME_LIMIT = env.int("CELERY_TASK_TIME_LIMIT", default=300)
CELERY_WORKER_MAX_TASKS_PER_CHILD = env.int("CELERY_WORKER_MAX_TASKS_PER_CHILD", default=100)
CELERY_RESULT_EXPIRES = env.int("CELERY_RESULT_EXPIRES", default=3600)
STORAGE_WARNING_PERCENT = env.int("STORAGE_WARNING_PERCENT", default=70)
STORAGE_URGENT_PERCENT = env.int("STORAGE_URGENT_PERCENT", default=80)
STORAGE_CRITICAL_PERCENT = env.int("STORAGE_CRITICAL_PERCENT", default=90)
STORAGE_MONITOR_ENABLED = env.bool("STORAGE_MONITOR_ENABLED", default=PRODUCTION)
OPERATIONS_ALERT_EMAILS = env.list("OPERATIONS_ALERT_EMAILS", default=[])
MEDIA_MAINTENANCE_LOCK_ID = env.int("MEDIA_MAINTENANCE_LOCK_ID", default=734733)
CELERY_BEAT_SCHEDULE = {
    "attachment-retention-daily": {
        "task": "apps.issues.tasks.run_attachment_retention",
        "schedule": 24 * 60 * 60,
    },
    "legacy-counter-pruning-daily": {
        "task": "apps.issues.tasks.prune_legacy_counters",
        "schedule": 24 * 60 * 60,
    },
    "storage-monitor-quarter-hour": {
        "task": "apps.issues.tasks.monitor_storage",
        "schedule": 15 * 60,
    },
}

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
    if not REDIS_URL:
        production_errors.append("REDIS_URL is required for shared throttling and task queues")
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
    },
}
