"""Helpers that build realistic fake upstream responses."""

import numpy as np

from apps.core.gazetteer import get_gazetteer
from apps.core.geo import METERS_PER_MILE, cumulative_distance_miles, densify


def polyline_through(*cities: str, step_miles: float = 1.0) -> tuple[list[list[float]], float]:
    """Return ([lng, lat] coordinates, distance_miles) for a path through 'City, ST' waypoints."""
    g = get_gazetteer()
    pts = []
    for c in cities:
        city, state = c.rsplit(",", 1)
        place = g.lookup_city(city, state)
        assert place, c
        pts.append([place.lat, place.lng])
    pts = np.asarray(pts)
    dist = cumulative_distance_miles(pts)
    dense, _ = densify(pts, dist, step_miles)
    return dense[:, [1, 0]].tolist(), float(dist[-1])


def osrm_response(coords_lnglat, distance_miles, speed_mph=60.0) -> dict:
    return {
        "code": "Ok",
        "routes": [
            {
                "geometry": {"type": "LineString", "coordinates": coords_lnglat},
                "distance": distance_miles * METERS_PER_MILE,
                "duration": distance_miles / speed_mph * 3600,
            }
        ],
        "waypoints": [],
    }


def ors_response(coords_lnglat, distance_miles, speed_mph=60.0) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords_lnglat},
                "properties": {"summary": {"distance": distance_miles, "duration": distance_miles / speed_mph * 3600}},
            }
        ],
    }
