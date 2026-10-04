"""
Routing provider status for ``/api/v1/health/``.

Each routing call records its outcome. ``?deep=true`` runs a short probe route,
cached for 5 minutes so health checks don't use up the API quota.
"""

from __future__ import annotations

import time

from django.core.cache import cache
from rest_framework.exceptions import APIException

from apps.core.exceptions import RouteNotFound

LAST_CALL_KEY = "health:routing:last-call"
PROBE_KEY = "health:routing:probe"
PROBE_TTL_SECONDS = 300
# Two points a few miles apart in Kansas City, MO: always routable by every provider.
PROBE_START = (39.0997, -94.5786)
PROBE_END = (39.0473, -94.5893)


def _outcome(provider: str, ok: bool, error: str | None = None) -> dict:
    return {"provider": provider, "ok": ok, "error": error, "at": int(time.time())}


def record_routing_outcome(provider: str, exc: Exception | None = None) -> None:
    """Remember the last upstream result. ``RouteNotFound`` means the provider answered fine."""
    ok = exc is None or isinstance(exc, RouteNotFound)
    error = None if ok else str(getattr(exc, "detail", exc))
    cache.set(LAST_CALL_KEY, _outcome(provider, ok, error), timeout=None)


def last_routing_outcome() -> dict | None:
    return cache.get(LAST_CALL_KEY)


def probe_routing() -> dict:
    """One real (cached) routing call to prove the provider works right now."""
    from apps.routing.services.routing_providers import get_routing_provider

    provider = get_routing_provider()
    cached = cache.get(PROBE_KEY)
    if cached is not None and cached["provider"] == provider.name:
        return {**cached, "cached": True}
    try:
        provider.route(PROBE_START, PROBE_END)
        result = _outcome(provider.name, True)
    except APIException as exc:
        result = _outcome(provider.name, False, str(exc.detail))
    record_routing_outcome(provider.name, None if result["ok"] else Exception(result["error"]))
    cache.set(PROBE_KEY, result, timeout=PROBE_TTL_SECONDS)
    return {**result, "cached": False}
