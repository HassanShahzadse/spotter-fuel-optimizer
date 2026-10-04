"""
Route planning: geocode, fetch the route, find stations along it, plan the stops.

Two caches avoid repeat API calls:

* ``route:`` holds the route geometry, shared by all option combinations.
* ``plan:`` holds the full plan, which the map page also reads.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import dataclass

import numpy as np
from django.conf import settings
from django.core.cache import cache
from scipy.spatial import cKDTree

from apps.core.exceptions import FuelPlanInfeasible, SameLocation, StationDataUnavailable
from apps.core.geo import (
    chord_to_miles,
    cumulative_distance_miles,
    densify,
    downsample,
    haversine_miles,
    miles_to_chord,
    to_unit_xyz,
)
from apps.routing.services.fuel_optimizer import Candidate, InfeasibleRouteError, plan_fuel_stops
from apps.routing.services.geocoding import GeocodedLocation, geocode_location
from apps.routing.services.metrics import count_external_calls
from apps.routing.services.provider_health import record_routing_outcome
from apps.routing.services.routing_providers import RouteResult, get_routing_provider
from apps.stations.models import FuelStation
from apps.stations.services.station_index import get_station_index

logger = logging.getLogger(__name__)

PLAN_CACHE_PREFIX = "plan:"
ROUTE_CACHE_PREFIX = "route:"
DENSIFY_STEP_MILES = 0.5
# Start and finish closer than this are treated as the same place (no routing call is made).
SAME_PLACE_MILES = 1.0


@dataclass(frozen=True)
class PlanOptions:
    corridor_miles: float
    start_fuel_level: float  # 0.0 (empty, fuel up at origin) .. 1.0 (full tank)
    max_range_miles: float
    mpg: float
    stop_penalty_usd: float = 0.0
    include_geometry: bool = False

    @classmethod
    def from_request(cls, data: dict) -> PlanOptions:
        cfg = settings.FUEL_ROUTE
        return cls(
            corridor_miles=float(data.get("corridor_miles") or cfg["CORRIDOR_MILES"]),
            start_fuel_level=float(
                data["start_fuel_level"] if data.get("start_fuel_level") is not None else cfg["START_FUEL_LEVEL"]
            ),
            max_range_miles=float(data.get("max_range_miles") or cfg["VEHICLE_MAX_RANGE_MILES"]),
            mpg=float(data.get("mpg") or cfg["VEHICLE_MPG"]),
            stop_penalty_usd=float(
                data["stop_penalty_usd"] if data.get("stop_penalty_usd") is not None else cfg["STOP_PENALTY_USD"]
            ),
            include_geometry=bool(data.get("include_geometry", False)),
        )


# Public entry point
def plan_route(start_input, finish_input, options: PlanOptions, *, base_url: str = "") -> dict:
    started = time.perf_counter()
    with count_external_calls() as calls:
        start = geocode_location(start_input)
        finish = geocode_location(finish_input)
        if haversine_miles(start.lat, start.lng, finish.lat, finish.lng) < SAME_PLACE_MILES:
            raise SameLocation(f"'{start.query}' and '{finish.query}' resolve to the same place.")

        plan_id = _plan_id(start, finish, options)
        cached = cache.get(PLAN_CACHE_PREFIX + plan_id)
        if cached is not None:
            return _with_meta(
                cached, calls, started, cache_hit=True, include_geometry=options.include_geometry, base_url=base_url
            )

        route = _get_route(start, finish)
        payload = _build_plan(plan_id, start, finish, route, options)
        cache.set(PLAN_CACHE_PREFIX + plan_id, payload, timeout=settings.FUEL_ROUTE["ROUTE_CACHE_TTL_SECONDS"])
        return _with_meta(
            payload, calls, started, cache_hit=False, include_geometry=options.include_geometry, base_url=base_url
        )


def get_cached_plan(plan_id: str) -> dict | None:
    return cache.get(PLAN_CACHE_PREFIX + plan_id)


# Steps
def _plan_id(start: GeocodedLocation, finish: GeocodedLocation, o: PlanOptions) -> str:
    key = json.dumps(
        [
            get_routing_provider().name,
            round(start.lat, 5),
            round(start.lng, 5),
            round(finish.lat, 5),
            round(finish.lng, 5),
            o.corridor_miles,
            o.start_fuel_level,
            o.max_range_miles,
            o.mpg,
            o.stop_penalty_usd,
            get_station_index().version,
        ],
    )
    return hashlib.sha256(key.encode()).hexdigest()[:20]


def _get_route(start: GeocodedLocation, finish: GeocodedLocation) -> RouteResult:
    provider = get_routing_provider()
    key = (
        ROUTE_CACHE_PREFIX
        + hashlib.sha256(
            f"{provider.name}:{start.lat:.5f},{start.lng:.5f}:{finish.lat:.5f},{finish.lng:.5f}".encode()
        ).hexdigest()
    )
    cached = cache.get(key)
    if cached is not None:
        return RouteResult(np.asarray(cached["coords"]), cached["distance"], cached["duration"], cached["provider"])

    call_started = time.perf_counter()
    try:
        route = provider.route((start.lat, start.lng), (finish.lat, finish.lng))
    except Exception as exc:
        record_routing_outcome(provider.name, exc)
        raise
    record_routing_outcome(provider.name)
    logger.info(
        "Routing call to %s took %.0f ms (%.0f miles, %d points)",
        provider.name,
        (time.perf_counter() - call_started) * 1000,
        route.distance_miles,
        len(route.coords),
    )
    cache.set(
        key,
        {
            "coords": route.coords.astype(np.float32),
            "distance": route.distance_miles,
            "duration": route.duration_seconds,
            "provider": route.provider,
        },
        timeout=settings.FUEL_ROUTE["ROUTE_CACHE_TTL_SECONDS"],
    )
    return route


def _stations_along_route(coords: np.ndarray, corridor_miles: float):
    """
    Find stations within ``corridor_miles`` of the route.

    Returns ``(station_positions, mile_markers, off_route_miles)`` where
    positions index into the in-memory station index.
    """
    index = get_station_index()
    if index.size == 0:
        raise StationDataUnavailable()

    cumdist = cumulative_distance_miles(coords)
    dense, dense_d = densify(coords, cumdist, DENSIFY_STEP_MILES)

    # Cheap bounding-box prefilter (corridor converted to degrees, generously).
    pad_lat = corridor_miles / 69.0 + 0.05
    pad_lng = corridor_miles / (69.0 * max(np.cos(np.radians(np.abs(dense[:, 0]).max())), 0.2)) + 0.05
    candidates = index.in_bbox(
        dense[:, 0].min() - pad_lat,
        dense[:, 0].max() + pad_lat,
        dense[:, 1].min() - pad_lng,
        dense[:, 1].max() + pad_lng,
    )
    if candidates.size == 0:
        return candidates, np.empty(0), np.empty(0), cumdist

    tree = cKDTree(to_unit_xyz(dense[:, 0], dense[:, 1]))
    chord, nearest = tree.query(index.xyz[candidates], k=1, distance_upper_bound=miles_to_chord(corridor_miles))
    hit = np.isfinite(chord)
    positions = candidates[hit]
    return positions, dense_d[nearest[hit]], chord_to_miles(chord[hit]), cumdist


def _origin_station(start: GeocodedLocation, radius_miles: float) -> tuple[int, float] | None:
    """(index position, distance) of the cheapest station near the start point."""
    index = get_station_index()
    if index.size == 0:
        return None
    dist = haversine_miles(start.lat, start.lng, index.lat, index.lng)
    near = np.flatnonzero(dist <= radius_miles)
    if near.size == 0:
        return None
    order = np.lexsort((dist[near], index.price[near]))  # cheapest, then closest
    pos = int(near[order[0]])
    return pos, float(dist[pos])


def _build_plan(plan_id, start, finish, route: RouteResult, options: PlanOptions) -> dict:
    cfg = settings.FUEL_ROUTE
    index = get_station_index()
    assumptions: list[str] = []

    positions, miles, off_route, cumdist = _stations_along_route(route.coords, options.corridor_miles)
    geometric_length = float(cumdist[-1]) if len(cumdist) else 0.0
    total_miles = route.distance_miles or geometric_length
    # Scale mile markers from geometry length to the provider's road distance.
    scale = total_miles / geometric_length if geometric_length > 0 else 1.0
    miles = miles * scale

    capacity = options.max_range_miles / options.mpg
    initial_fuel = options.start_fuel_level * capacity

    origin = _origin_station(start, cfg["ORIGIN_FUEL_RADIUS_MILES"])
    origin_candidate = None
    if origin is not None:
        pos, dist = origin
        origin_candidate = Candidate(int(index.ids[pos]), 0.0, float(index.price[pos]), dist)
    if options.start_fuel_level == 0:
        if origin_candidate is not None:
            assumptions.append(
                "Vehicle starts with an empty tank at the cheapest station within "
                f"{cfg['ORIGIN_FUEL_RADIUS_MILES']:.0f} miles of the start and fuels up there."
            )
        else:
            initial_fuel = capacity
            assumptions.append(
                f"No fuel station within {cfg['ORIGIN_FUEL_RADIUS_MILES']:.0f} miles of the start; "
                "vehicle is assumed to start with a full tank."
            )
    else:
        assumptions.append(f"Vehicle starts with {options.start_fuel_level:.0%} of a {capacity:.0f} gallon tank.")

    # One candidate per (location, price): stations geocoded to the same city share a position.
    best: dict[tuple[float, float], Candidate] = {}
    for pos, mile, detour in zip(positions.tolist(), miles.tolist(), off_route.tolist(), strict=True):
        ref = int(index.ids[pos])
        if origin_candidate is not None and ref == origin_candidate.ref:
            continue
        cand = Candidate(ref, mile, float(index.price[pos]), detour)
        key = (round(float(index.lat[pos]), 4), round(float(index.lng[pos]), 4))
        if key not in best or cand.price < best[key].price:
            best[key] = cand
    candidates = list(best.values())

    try:
        fuel_plan = plan_fuel_stops(
            candidates,
            total_miles,
            max_range_miles=options.max_range_miles,
            mpg=options.mpg,
            initial_fuel_gallons=initial_fuel,
            origin_station=origin_candidate,
            stop_penalty=options.stop_penalty_usd,
        )
    except InfeasibleRouteError as exc:
        raise FuelPlanInfeasible(
            f"{exc} The vehicle range is {options.max_range_miles:.0f} miles (including the detour to each "
            "station); try a wider corridor_miles value."
        ) from exc

    stations = FuelStation.objects.in_bulk([p.candidate.ref for p in fuel_plan.purchases])
    stops = []
    for n, purchase in enumerate(fuel_plan.purchases, start=1):
        st = stations[purchase.candidate.ref]
        stops.append(
            {
                "stop_number": n,
                "type": "origin" if purchase.is_origin else "en_route",
                "mile_marker": round(purchase.candidate.mile, 1),
                "distance_from_route_miles": round(purchase.candidate.detour_miles, 1),
                "detour_miles": round(purchase.candidate.detour_miles * (1 if purchase.is_origin else 2), 1),
                "station": {
                    "id": st.id,
                    "opis_id": st.opis_id,
                    "name": st.name,
                    "address": st.address,
                    "city": st.city,
                    "state": st.state,
                    "latitude": round(st.latitude, 6),
                    "longitude": round(st.longitude, 6),
                },
                "price_per_gallon": round(purchase.candidate.price, 3),
                "fuel_on_arrival_gallons": round(purchase.fuel_on_arrival, 2),
                "gallons_purchased": round(purchase.gallons, 2),
                "fuel_on_departure_gallons": round(purchase.fuel_on_departure, 2),
                "cost_usd": round(purchase.cost, 2),
            }
        )

    purchased = fuel_plan.total_gallons_purchased
    total_cost = fuel_plan.total_cost
    summary = {
        "total_distance_miles": round(total_miles, 1),
        "detour_miles": round(fuel_plan.detour_miles, 1),
        "total_miles_driven": round(fuel_plan.total_miles_driven, 1),
        "estimated_duration_hours": round(route.duration_seconds / 3600, 2),
        "number_of_fuel_stops": len(stops),
        "total_gallons_consumed": round(fuel_plan.total_gallons_consumed, 2),
        "total_gallons_purchased": round(purchased, 2),
        "starting_fuel_gallons": round(fuel_plan.initial_fuel, 2),
        "ending_fuel_gallons": round(fuel_plan.final_fuel, 2),
        "average_price_per_gallon": round(total_cost / purchased, 3) if purchased else None,
        "total_fuel_cost_usd": round(total_cost, 2),
    }

    thin = downsample(route.coords, cumdist, cfg["MAX_GEOMETRY_POINTS"])
    geometry = {"type": "LineString", "coordinates": np.round(thin[:, [1, 0]], 5).tolist()}

    return {
        "id": plan_id,
        "start": start.as_dict(),
        "finish": finish.as_dict(),
        "vehicle": {
            "max_range_miles": options.max_range_miles,
            "mpg": options.mpg,
            "tank_capacity_gallons": round(capacity, 2),
        },
        "summary": summary,
        "fuel_stops": stops,
        "assumptions": [
            *assumptions,
            f"Stations within {options.corridor_miles:g} miles of the route are considered.",
            "Station coordinates are city-level (the price file has no coordinates).",
            "The detour to each station (straight-line distance, there and back) counts against the "
            "range and is included in the fuel bought.",
        ],
        "map": {
            "html_url": f"/api/v1/route/{plan_id}/map/",
            "geojson": _feature_collection(geometry, start, finish, stops),
        },
        "meta": {
            "routing_provider": route.provider,
            "candidate_stations_on_route": len(candidates),
            "corridor_miles": options.corridor_miles,
            "stop_penalty_usd": options.stop_penalty_usd,
            "optimizer": "exact dynamic programme (min fuel cost + stop penalty, detours included)",
        },
    }


def _feature_collection(geometry, start, finish, stops) -> dict:
    features = [
        {"type": "Feature", "geometry": geometry, "properties": {"kind": "route"}},
        _point(start.lng, start.lat, {"kind": "start", "label": start.label}),
        _point(finish.lng, finish.lat, {"kind": "finish", "label": finish.label}),
    ]
    for stop in stops:
        st = stop["station"]
        features.append(
            _point(
                st["longitude"],
                st["latitude"],
                {
                    "kind": "fuel_stop",
                    "stop_number": stop["stop_number"],
                    "name": st["name"],
                    "address": f"{st['address']}, {st['city']}, {st['state']}",
                    "price_per_gallon": stop["price_per_gallon"],
                    "gallons_purchased": stop["gallons_purchased"],
                    "cost_usd": stop["cost_usd"],
                    "mile_marker": stop["mile_marker"],
                },
            )
        )
    return {"type": "FeatureCollection", "features": features}


def _point(lng, lat, props) -> dict:
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(lng, 6), round(lat, 6)]},
        "properties": props,
    }


def _with_meta(payload: dict, calls, started: float, *, cache_hit: bool, include_geometry: bool, base_url: str) -> dict:
    out = dict(payload)
    out["map"] = {**payload["map"], "html_url": base_url + payload["map"]["html_url"]}
    out["meta"] = {
        **payload["meta"],
        "cache_hit": cache_hit,
        "external_api_calls": {"routing": calls.get("routing", 0), "geocoding": calls.get("geocoding", 0)},
        "compute_time_ms": round((time.perf_counter() - started) * 1000, 1),
    }
    if not include_geometry:
        out["map"] = {"html_url": out["map"]["html_url"]}
    return out
