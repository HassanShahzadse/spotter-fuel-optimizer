"""
Builds the public ``/api/v1/route/`` response from the full plan.

The full plan is cached and also used by the map page.
"""

from __future__ import annotations

import numpy as np
from django.conf import settings

from apps.core.geo import encode_polyline


def public_response(plan: dict, *, include_geometry: bool = False) -> dict:
    summary = plan["summary"]
    stops = [
        {
            "stop": s["stop_number"],
            "station": s["station"]["name"],
            "address": f"{s['station']['address']}, {s['station']['city']}, {s['station']['state']}",
            "mile": s["mile_marker"],
            "price_per_gallon": s["price_per_gallon"],
            "gallons": s["gallons_purchased"],
            "cost": s["cost_usd"],
        }
        for s in plan["fuel_stops"]
    ]
    out = {
        "start": plan["start"]["label"],
        "finish": plan["finish"]["label"],
        "distance_miles": summary["total_distance_miles"],
        "fuel_stops": stops,
        "total_gallons": summary["total_gallons_purchased"],
        "total_fuel_cost": summary["total_fuel_cost_usd"],
        "map_url": plan["map"]["html_url"],
    }
    if include_geometry:
        out["route_polyline"] = _route_polyline(plan)
    out["meta"] = {
        "routing_api_calls": plan["meta"]["external_api_calls"]["routing"],
        "cached": plan["meta"]["cache_hit"],
        "response_time_ms": plan["meta"]["compute_time_ms"],
    }
    return out


def _route_polyline(plan: dict) -> str:
    route = next(f for f in plan["map"]["geojson"]["features"] if f["properties"]["kind"] == "route")
    lnglat = route["geometry"]["coordinates"]
    limit = settings.FUEL_ROUTE["RESPONSE_POLYLINE_POINTS"]
    if len(lnglat) > limit:
        idx = np.unique(np.linspace(0, len(lnglat) - 1, limit).round().astype(int))
        lnglat = [lnglat[i] for i in idx]
    return encode_polyline([(lat, lng) for lng, lat in lnglat])
