"""
Build the gazetteer and station index when the server starts, not on the first request.

Called from ``config/wsgi.py`` and ``config/asgi.py``.
"""

from __future__ import annotations

import logging
import time

from django.db import DatabaseError, connections

logger = logging.getLogger(__name__)


def warm_up() -> None:
    from apps.core.gazetteer import get_gazetteer
    from apps.stations.services.station_index import get_station_index

    started = time.perf_counter()
    try:
        get_gazetteer()
        stations = get_station_index().size
    except DatabaseError as exc:  # e.g. migrations not applied yet
        logger.warning("Warm-up skipped the station index: %s", exc)
        stations = 0
    finally:
        # Never hand a DB connection opened here to forked gunicorn workers.
        connections.close_all()
    logger.info("Warm-up done in %.1fs (%d stations in memory)", time.perf_counter() - started, stations)
