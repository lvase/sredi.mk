import pytest
from django.conf import settings
from django.core.cache import caches


@pytest.fixture(autouse=True)
def isolate_shared_caches():
    """Keep shared throttle/cache state from leaking between database tests."""
    for alias in settings.CACHES:
        caches[alias].clear()
    yield
    for alias in settings.CACHES:
        caches[alias].clear()
