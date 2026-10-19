import time

from django.conf import settings
from django.core.cache import caches


class SharedThrottleUnavailable(RuntimeError):
    """Raised when a shared safety counter cannot be enforced."""


def _cache():
    return caches[settings.RATE_LIMIT_CACHE_ALIAS]


def fixed_window_key(prefix, identity, window_seconds, now=None):
    epoch = int(time.time() if now is None else now)
    bucket = epoch // window_seconds
    return f"throttle:{prefix}:{identity}:{bucket}", epoch


def increment_fixed_window(prefix, identity, window_seconds):
    key, epoch = fixed_window_key(prefix, identity, window_seconds)
    ttl = window_seconds - (epoch % window_seconds) + 2
    cache = _cache()
    try:
        if cache.add(key, 1, timeout=ttl):
            value = 1
        else:
            value = cache.incr(key)
    except Exception as exc:
        raise SharedThrottleUnavailable("shared throttle unavailable") from exc
    return int(value), ttl


def current_fixed_window(prefix, identity, window_seconds):
    key, epoch = fixed_window_key(prefix, identity, window_seconds)
    try:
        value = _cache().get(key, 0)
    except Exception as exc:
        raise SharedThrottleUnavailable("shared throttle unavailable") from exc
    return int(value or 0), window_seconds - (epoch % window_seconds) + 2


def clear_fixed_window(prefix, identity, window_seconds):
    key, _ = fixed_window_key(prefix, identity, window_seconds)
    try:
        _cache().delete(key)
    except Exception as exc:
        raise SharedThrottleUnavailable("shared throttle unavailable") from exc
