import shutil

from django.conf import settings
from django.core.cache import cache

STORAGE_STATE_KEY = "operations:storage-state"


def filesystem_usage_state():
    media_path = settings.MEDIA_ROOT if settings.MEDIA_ROOT.exists() else settings.MEDIA_ROOT.parent
    usage = shutil.disk_usage(media_path)
    used_percent = (usage.used / usage.total) * 100 if usage.total else 100.0
    if used_percent >= settings.STORAGE_CRITICAL_PERCENT:
        level = "critical"
    elif used_percent >= settings.STORAGE_URGENT_PERCENT:
        level = "urgent"
    elif used_percent >= settings.STORAGE_WARNING_PERCENT:
        level = "warning"
    else:
        level = "ok"
    return {
        "level": level,
        "used_percent": round(used_percent, 1),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "enforced": settings.STORAGE_MONITOR_ENABLED,
        "attachment_writes_enabled": (
            not settings.STORAGE_MONITOR_ENABLED
            or used_percent < settings.STORAGE_CRITICAL_PERCENT
        ),
    }


def current_storage_state():
    try:
        cached = cache.get(STORAGE_STATE_KEY)
    except Exception:
        cached = None
    return cached or filesystem_usage_state()


def attachment_writes_enabled():
    return bool(current_storage_state()["attachment_writes_enabled"])
