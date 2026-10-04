"""
In-memory index of geocoded stations, held as NumPy arrays so the station search
for a route doesn't query the database.

A version key in the shared cache tells every worker process to reload after an import.
"""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass

import numpy as np
from django.core.cache import cache

from apps.core.geo import to_unit_xyz

_VERSION_KEY = "stations:index-version"


@dataclass(frozen=True)
class StationIndex:
    version: str
    ids: np.ndarray  # database primary keys
    lat: np.ndarray
    lng: np.ndarray
    price: np.ndarray
    xyz: np.ndarray  # unit vectors for KD-tree queries

    @property
    def size(self) -> int:
        return len(self.ids)

    def in_bbox(self, south: float, north: float, west: float, east: float) -> np.ndarray:
        """Indices of stations inside a lat/lng bounding box."""
        mask = (self.lat >= south) & (self.lat <= north) & (self.lng >= west) & (self.lng <= east)
        return np.flatnonzero(mask)


_index: StationIndex | None = None
_lock = threading.Lock()


def _current_version() -> str:
    version = cache.get(_VERSION_KEY)
    if version is None:
        version = uuid.uuid4().hex
        cache.add(_VERSION_KEY, version, timeout=None)
        version = cache.get(_VERSION_KEY, version)
    return version


def _build(version: str) -> StationIndex:
    from apps.stations.models import FuelStation

    rows = list(
        FuelStation.objects.filter(latitude__isnull=False, longitude__isnull=False)
        .order_by("id")
        .values_list("id", "latitude", "longitude", "retail_price")
    )
    if rows:
        ids, lat, lng, price = (np.asarray(col) for col in zip(*rows, strict=True))
        lat, lng, price = lat.astype(float), lng.astype(float), price.astype(float)
        xyz = to_unit_xyz(lat, lng)
    else:
        ids = np.empty(0, dtype=int)
        lat = lng = price = np.empty(0)
        xyz = np.empty((0, 3))
    return StationIndex(version, ids.astype(int), lat, lng, price, xyz)


def get_station_index() -> StationIndex:
    """Return the (lazily built, version-checked) process-wide station index."""
    global _index
    version = _current_version()
    if _index is None or _index.version != version:
        with _lock:
            if _index is None or _index.version != version:
                _index = _build(version)
    return _index


def invalidate_station_index() -> None:
    """Force every process to rebuild its index on next use (called after imports)."""
    global _index
    cache.set(_VERSION_KEY, uuid.uuid4().hex, timeout=None)
    _index = None
