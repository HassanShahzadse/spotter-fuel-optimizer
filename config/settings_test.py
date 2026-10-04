"""Test settings: an in-memory cache so tests never touch the development cache."""

import os

os.environ.setdefault("SECRET_KEY", "test-only-secret-key")

from config.settings import *  # noqa: F403

CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "fuel-route-api-tests",
    }
}
