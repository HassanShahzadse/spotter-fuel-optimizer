"""Shared HTTP session for upstream APIs, with connection pooling, retries and timeouts."""

from __future__ import annotations

import threading

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

_session: requests.Session | None = None
_lock = threading.Lock()


def get_http_session() -> requests.Session:
    global _session
    if _session is None:
        with _lock:
            if _session is None:
                cfg = settings.FUEL_ROUTE
                retry = Retry(
                    total=cfg["HTTP_MAX_RETRIES"],
                    connect=cfg["HTTP_MAX_RETRIES"],
                    read=cfg["HTTP_MAX_RETRIES"],
                    backoff_factor=0.5,
                    status_forcelist=(429, 500, 502, 503, 504),
                    allowed_methods=frozenset({"GET", "POST"}),
                    respect_retry_after_header=True,
                    raise_on_status=False,
                )
                session = requests.Session()
                adapter = HTTPAdapter(max_retries=retry, pool_connections=10, pool_maxsize=20)
                session.mount("https://", adapter)
                session.mount("http://", adapter)
                session.headers.update({"User-Agent": cfg["HTTP_USER_AGENT"], "Accept": "application/json"})
                _session = session
    return _session


def http_timeout() -> float:
    return settings.FUEL_ROUTE["HTTP_TIMEOUT_SECONDS"]
