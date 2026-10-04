"""
Routing providers: OpenRouteService when ``ORS_API_KEY`` is set, otherwise the
public OSRM server. One API call per route returns the geometry, distance and duration.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import requests
from django.conf import settings

from apps.core.exceptions import RouteNotFound, UpstreamServiceError
from apps.core.geo import METERS_PER_MILE
from apps.routing.services.http import get_http_session, http_timeout
from apps.routing.services.metrics import record_external_call

logger = logging.getLogger(__name__)


@dataclass
class RouteResult:
    coords: np.ndarray  # shape (N, 2) as [lat, lng]
    distance_miles: float
    duration_seconds: float
    provider: str


class RoutingProvider(ABC):
    name = "base"

    @abstractmethod
    def route(self, start: tuple[float, float], end: tuple[float, float]) -> RouteResult: ...

    @staticmethod
    def _to_latlng(lnglat: list) -> np.ndarray:
        coords = np.asarray(lnglat, dtype=float)
        if coords.ndim != 2 or len(coords) < 2:
            raise RouteNotFound("The routing service returned an empty route.")
        return coords[:, [1, 0]]


class OpenRouteServiceProvider(RoutingProvider):
    name = "openrouteservice"

    def __init__(self, base_url: str, api_key: str, profile: str = "driving-car"):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.profile = profile

    def route(self, start, end) -> RouteResult:
        url = f"{self.base_url}/v2/directions/{self.profile}/geojson"
        body = {
            "coordinates": [[start[1], start[0]], [end[1], end[0]]],
            "instructions": False,
            "preference": "recommended",
            "units": "mi",
        }
        # The /geojson endpoint answers 406 ("This response format is not supported") to
        # the session's default "Accept: application/json", so ask for GeoJSON explicitly.
        headers = {"Authorization": self.api_key, "Accept": "application/geo+json"}
        record_external_call("routing")
        try:
            resp = get_http_session().post(url, json=body, headers=headers, timeout=http_timeout())
        except requests.RequestException as exc:
            logger.error("OpenRouteService request failed: %s", type(exc).__name__)
            raise UpstreamServiceError() from exc

        if resp.status_code in (400, 404):
            message = _ors_error_message(resp)
            raise RouteNotFound(f"No drivable route found: {message}")
        if resp.status_code in (401, 403):
            raise UpstreamServiceError("OpenRouteService rejected the API key (check ORS_API_KEY).")
        if resp.status_code >= 400:
            logger.error("OpenRouteService error %s: %s", resp.status_code, resp.text[:300])
            raise UpstreamServiceError()

        try:
            feature = resp.json()["features"][0]
            summary = feature["properties"].get("summary", {})
            coords = self._to_latlng(feature["geometry"]["coordinates"])
        except (KeyError, IndexError, ValueError) as exc:
            raise UpstreamServiceError("Unexpected response from OpenRouteService.") from exc
        return RouteResult(
            coords=coords,
            distance_miles=float(summary.get("distance", 0.0)),  # already in miles (units=mi)
            duration_seconds=float(summary.get("duration", 0.0)),
            provider=self.name,
        )


def _ors_error_message(resp: requests.Response) -> str:
    try:
        return resp.json().get("error", {}).get("message", "route not found")
    except ValueError:
        return "route not found"


class OsrmProvider(RoutingProvider):
    name = "osrm"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def route(self, start, end) -> RouteResult:
        url = f"{self.base_url}/route/v1/driving/{start[1]:.6f},{start[0]:.6f};{end[1]:.6f},{end[0]:.6f}"
        params = {"overview": "full", "geometries": "geojson", "steps": "false", "alternatives": "false"}
        record_external_call("routing")
        try:
            resp = get_http_session().get(url, params=params, timeout=http_timeout())
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("OSRM request failed: %s", exc)
            raise UpstreamServiceError() from exc

        code = payload.get("code")
        if code in {"NoRoute", "NoSegment", "InvalidValue"} or (resp.status_code == 400 and code != "Ok"):
            raise RouteNotFound(f"No drivable route found ({payload.get('message') or code}).")
        if resp.status_code >= 400 or code != "Ok" or not payload.get("routes"):
            logger.error("OSRM error %s: %s", resp.status_code, str(payload)[:300])
            raise UpstreamServiceError()

        route = payload["routes"][0]
        return RouteResult(
            coords=self._to_latlng(route["geometry"]["coordinates"]),
            distance_miles=float(route["distance"]) / METERS_PER_MILE,
            duration_seconds=float(route["duration"]),
            provider=self.name,
        )


def get_routing_provider() -> RoutingProvider:
    cfg = settings.FUEL_ROUTE
    choice = cfg["ROUTING_PROVIDER"].lower()
    if choice == "ors" or (choice == "auto" and cfg["ORS_API_KEY"]):
        if not cfg["ORS_API_KEY"]:
            raise ValueError("ROUTING_PROVIDER=ors requires ORS_API_KEY")
        return OpenRouteServiceProvider(cfg["ORS_BASE_URL"], cfg["ORS_API_KEY"], cfg["ORS_PROFILE"])
    return OsrmProvider(cfg["OSRM_BASE_URL"])
