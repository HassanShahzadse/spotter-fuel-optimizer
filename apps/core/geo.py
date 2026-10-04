"""Geodesy helpers, vectorised with NumPy."""

from __future__ import annotations

import numpy as np

EARTH_RADIUS_MILES = 3958.7613
METERS_PER_MILE = 1609.344


def haversine_miles(lat1, lng1, lat2, lng2):
    """Great-circle distance in miles. Works on scalars or NumPy arrays."""
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))


def to_unit_xyz(lat, lng) -> np.ndarray:
    """Convert lat/lng (degrees) to 3D unit vectors, for KD-tree nearest-neighbour search."""
    lat = np.radians(np.asarray(lat, dtype=float))
    lng = np.radians(np.asarray(lng, dtype=float))
    cos_lat = np.cos(lat)
    return np.column_stack((cos_lat * np.cos(lng), cos_lat * np.sin(lng), np.sin(lat)))


def miles_to_chord(miles: float) -> float:
    """Great-circle distance (miles) -> straight chord length on the unit sphere."""
    return 2.0 * np.sin(miles / (2.0 * EARTH_RADIUS_MILES))


def chord_to_miles(chord):
    return 2.0 * EARTH_RADIUS_MILES * np.arcsin(np.clip(np.asarray(chord) / 2.0, 0.0, 1.0))


def cumulative_distance_miles(coords: np.ndarray) -> np.ndarray:
    """Cumulative distance along a polyline of ``[lat, lng]`` rows (first value 0)."""
    if len(coords) < 2:
        return np.zeros(len(coords))
    seg = haversine_miles(coords[:-1, 0], coords[:-1, 1], coords[1:, 0], coords[1:, 1])
    return np.concatenate(([0.0], np.cumsum(seg)))


def densify(coords: np.ndarray, cumdist: np.ndarray, max_step_miles: float) -> tuple[np.ndarray, np.ndarray]:
    """
    Insert interpolated points so that consecutive points are at most
    ``max_step_miles`` apart. Nearest-vertex search on the result then
    approximates point-to-segment distance within ``max_step_miles / 2``.
    """
    if len(coords) < 2:
        return coords, cumdist
    seg_len = np.diff(cumdist)
    pieces = np.maximum(1, np.ceil(seg_len / max_step_miles).astype(int))
    if np.all(pieces == 1):
        return coords, cumdist

    total = int(pieces.sum()) + 1
    out = np.empty((total, 2))
    out_d = np.empty(total)
    seg_index = np.repeat(np.arange(len(pieces)), pieces)
    offsets = np.arange(total - 1) - np.repeat(np.cumsum(pieces) - pieces, pieces)
    frac = offsets / np.repeat(pieces, pieces)
    start, end = coords[seg_index], coords[seg_index + 1]
    out[:-1] = start + (end - start) * frac[:, None]
    out_d[:-1] = cumdist[seg_index] + seg_len[seg_index] * frac
    out[-1], out_d[-1] = coords[-1], cumdist[-1]
    return out, out_d


def downsample(coords: np.ndarray, cumdist: np.ndarray, max_points: int) -> np.ndarray:
    """
    Thin a polyline to about ``max_points`` points, spaced evenly by distance
    rather than by index. The first and last points are kept.
    """
    if len(coords) <= max_points:
        return coords
    targets = np.linspace(0.0, cumdist[-1], max_points)
    idx = np.unique(np.clip(np.searchsorted(cumdist, targets), 0, len(coords) - 1))
    return coords[idx]


def encode_polyline(latlng, precision: int = 5) -> str:
    """Encode ``[[lat, lng], ...]`` as a Google encoded polyline string."""
    factor = 10**precision
    result: list[str] = []
    prev_lat = prev_lng = 0
    for lat, lng in latlng:
        ilat, ilng = round(lat * factor), round(lng * factor)
        for delta in (ilat - prev_lat, ilng - prev_lng):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                result.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            result.append(chr(value + 63))
        prev_lat, prev_lng = ilat, ilng
    return "".join(result)


def decode_polyline(encoded: str, precision: int = 5) -> list[tuple[float, float]]:
    """Inverse of :func:`encode_polyline` (used by the tests)."""
    factor = 10**precision
    coords, index, lat, lng = [], 0, 0, 0
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            shift = result = 0
            while True:
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        lat += deltas[0]
        lng += deltas[1]
        coords.append((lat / factor, lng / factor))
    return coords
