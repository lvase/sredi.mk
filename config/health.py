import shutil

from django.conf import settings
from django.core.cache import caches
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


@require_GET
@never_cache
def live(request):
    return JsonResponse({"status": "ok"})


@require_GET
@never_cache
def ready(request):
    diagnostics = {
        "database": "unavailable",
        "migrations": "unknown",
        "redis": "unavailable",
        "storage": "unknown",
    }
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        diagnostics["database"] = "ok"
        executor = MigrationExecutor(connection)
        missing = executor.migration_plan(executor.loader.graph.leaf_nodes())
        diagnostics["migrations"] = "missing" if missing else "ok"
    except Exception:
        return JsonResponse({"status": "unavailable", "dependencies": diagnostics}, status=503)

    try:
        caches[settings.RATE_LIMIT_CACHE_ALIAS].get("healthcheck")
        diagnostics["redis"] = "ok"
    except Exception:
        pass

    try:
        media_path = settings.MEDIA_ROOT if settings.MEDIA_ROOT.exists() else settings.MEDIA_ROOT.parent
        usage = shutil.disk_usage(media_path)
        used_percent = round((usage.used / usage.total) * 100, 1) if usage.total else 100.0
        diagnostics["storage"] = {
            "status": (
                "critical"
                if used_percent >= settings.STORAGE_CRITICAL_PERCENT
                else "urgent"
                if used_percent >= settings.STORAGE_URGENT_PERCENT
                else "warning"
                if used_percent >= settings.STORAGE_WARNING_PERCENT
                else "ok"
            ),
            "used_percent": used_percent,
            "attachment_writes_enabled": (
                not settings.STORAGE_MONITOR_ENABLED
                or used_percent < settings.STORAGE_CRITICAL_PERCENT
            ),
        }
    except OSError:
        diagnostics["storage"] = "unavailable"

    if diagnostics["migrations"] != "ok" or diagnostics["redis"] != "ok":
        return JsonResponse({"status": "unavailable", "dependencies": diagnostics}, status=503)
    return JsonResponse({"status": "ready", "dependencies": diagnostics})
