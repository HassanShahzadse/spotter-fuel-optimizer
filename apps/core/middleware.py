"""Adds an ``X-Response-Time-ms`` header and logs API request times."""

import logging
import time

logger = logging.getLogger("apps.core.requests")


class RequestTimingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        elapsed_ms = (time.perf_counter() - started) * 1000
        response["X-Response-Time-ms"] = f"{elapsed_ms:.1f}"
        if request.path.startswith("/api/"):
            logger.info("%s %s -> %s in %.1fms", request.method, request.path, response.status_code, elapsed_ms)
        return response
