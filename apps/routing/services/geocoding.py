"""
Resolve user locations to coordinates, cheapest method first:

1. ``{"lat", "lng"}`` objects and ``"lat,lng"`` strings are used as they are.
2. ZIP codes and "City, ST" / "City, State" use the offline gazetteer.
3. Anything else (street addresses) goes to an external geocoder: ORS when a key
   is set, otherwise Nominatim. Results are restricted to the USA and cached.
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import requests
from django.conf import settings
from django.core.cache import cache

from apps.core.borders import foreign_country_at, is_within_usa
from apps.core.exceptions import LocationNotFound, LocationOutsideUSA, UpstreamServiceError
from apps.core.gazetteer import foreign_region, get_gazetteer, normalize_state
from apps.routing.services.http import get_http_session, http_timeout
from apps.routing.services.metrics import record_external_call

logger = logging.getLogger(__name__)

_LATLNG_RE = re.compile(r"^\s*(-?\d{1,2}(?:\.\d+)?)\s*,\s*(-?\d{1,3}(?:\.\d+)?)\s*$")
_ZIP_RE = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")
_TRAILING_ZIP_RE = re.compile(r"[\s,]+(\d{5})(?:-\d{4})?\s*$")
_COUNTRY_SUFFIX_RE = re.compile(r"[\s,]+(USA|US|U\.S\.A\.|U\.S\.|UNITED STATES(?: OF AMERICA)?)\s*$", re.I)


@dataclass(frozen=True, slots=True)
class GeocodedLocation:
    query: str
    label: str
    lat: float
    lng: float
    source: str  # coordinates | zip_code | city_state | ors | nominatim

    @property
    def is_external(self) -> bool:
        return self.source in {"ors", "nominatim"}

    def as_dict(self) -> dict:
        return {
            "query": self.query,
            "label": self.label,
            "latitude": round(self.lat, 6),
            "longitude": round(self.lng, 6),
            "geocoder": self.source,
        }


# External geocoders
class ExternalGeocoder(ABC):
    name = "external"

    @abstractmethod
    def geocode(self, query: str) -> GeocodedLocation | None: ...


class NominatimGeocoder(ExternalGeocoder):
    """OpenStreetMap Nominatim (free, no key; usage policy: max 1 request/second)."""

    name = "nominatim"
    _lock = threading.Lock()
    _last_call = 0.0

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def geocode(self, query: str) -> GeocodedLocation | None:
        with self._lock:  # honour the 1 req/s usage policy
            wait = 1.0 - (time.monotonic() - NominatimGeocoder._last_call)
            if wait > 0:
                time.sleep(wait)
            NominatimGeocoder._last_call = time.monotonic()
        record_external_call("geocoding")
        try:
            resp = get_http_session().get(
                f"{self.base_url}/search",
                params={"q": query, "format": "jsonv2", "limit": 1, "countrycodes": "us"},
                timeout=http_timeout(),
            )
        except requests.RequestException as exc:
            logger.warning("Nominatim geocoding failed for %r: %s", query, type(exc).__name__)
            raise UpstreamServiceError("Geocoding service is unavailable. Try 'City, ST' or 'lat,lng'.") from exc
        if resp.status_code == 403:
            # Nominatim blocks generic / placeholder User-Agents (usage policy).
            logger.error(
                "Nominatim refused the request (403). Set HTTP_USER_AGENT to an app name + real contact email."
            )
            raise UpstreamServiceError(
                "The address geocoder refused the request. Use 'City, ST', a ZIP code or 'lat,lng', "
                "or configure ORS_API_KEY / HTTP_USER_AGENT on the server."
            )
        try:
            resp.raise_for_status()
            results = resp.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Nominatim geocoding failed for %r: HTTP %s", query, resp.status_code)
            raise UpstreamServiceError("Geocoding service is unavailable. Try 'City, ST' or 'lat,lng'.") from exc
        if not results:
            return None
        top = results[0]
        return GeocodedLocation(query, top.get("display_name", query), float(top["lat"]), float(top["lon"]), self.name)


class OrsGeocoder(ExternalGeocoder):
    """OpenRouteService geocoder (requires ORS_API_KEY)."""

    name = "ors"

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def geocode(self, query: str) -> GeocodedLocation | None:
        record_external_call("geocoding")
        try:
            resp = get_http_session().get(
                f"{self.base_url}/geocode/search",
                params={"text": query, "boundary.country": "USA", "size": 1},
                headers={"Authorization": self.api_key},
                timeout=http_timeout(),
            )
            resp.raise_for_status()
            features = resp.json().get("features") or []
        except (requests.RequestException, ValueError) as exc:
            # Log the exception type only: messages can contain full request URLs.
            logger.warning("ORS geocoding failed for %r: %s", query, type(exc).__name__)
            raise UpstreamServiceError("Geocoding service is unavailable. Try 'City, ST' or 'lat,lng'.") from exc
        if not features:
            return None
        lng, lat = features[0]["geometry"]["coordinates"][:2]
        label = features[0].get("properties", {}).get("label", query)
        return GeocodedLocation(query, label, float(lat), float(lng), self.name)


def get_external_geocoder() -> ExternalGeocoder | None:
    cfg = settings.FUEL_ROUTE
    provider = cfg["GEOCODER_PROVIDER"].lower()
    if provider == "none":
        return None
    if provider == "ors" or (provider == "auto" and cfg["ORS_API_KEY"]):
        if not cfg["ORS_API_KEY"]:
            raise ValueError("GEOCODER_PROVIDER=ors requires ORS_API_KEY")
        return OrsGeocoder(cfg["ORS_BASE_URL"], cfg["ORS_API_KEY"])
    return NominatimGeocoder(cfg["NOMINATIM_BASE_URL"])


# Public API
def _resolve_offline(query: str) -> GeocodedLocation | None:
    gazetteer = get_gazetteer()

    if m := _ZIP_RE.match(query):
        place = gazetteer.lookup_zip(m.group(1))
        return GeocodedLocation(query, place.label, place.lat, place.lng, "zip_code") if place else None

    text = _COUNTRY_SUFFIX_RE.sub("", query).strip(" ,")
    zip_match = _TRAILING_ZIP_RE.search(text)
    if zip_match:
        place = gazetteer.lookup_zip(zip_match.group(1))
        if place:
            return GeocodedLocation(query, place.label, place.lat, place.lng, "zip_code")
        text = text[: zip_match.start()].strip(" ,")

    if "," in text:
        city, _, state = text.rpartition(",")
        candidates = [(city, state)]
    else:  # "Dallas TX" or "Salt Lake City Utah"
        parts = text.split()
        candidates = [(" ".join(parts[:-n]), " ".join(parts[-n:])) for n in (1, 2) if len(parts) > n]

    for city, state in candidates:
        if city.strip() and normalize_state(state):
            place = gazetteer.lookup_city(city, state)
            if place:
                return GeocodedLocation(query, place.label, place.lat, place.lng, "city_state")

    # "Toronto, ON", "Monterrey, Nuevo Leon", "Vancouver, Canada": reject without an API call.
    # Skipped when the region could also be a US state ("Santa Fe, New Mexico").
    regions = [state for _, state in candidates] + [text]
    if not any(normalize_state(region) for region in regions):
        for region in regions:
            if country := foreign_region(region):
                raise LocationOutsideUSA(f"'{query}' is in {country}. Start and finish must be inside the USA.")
    return None


def geocode_location(value: str | dict) -> GeocodedLocation:
    """Resolve a location (string or ``{"lat", "lng"}``) to a USA coordinate."""
    if isinstance(value, dict):
        lat, lng = float(value["lat"]), float(value["lng"])
        location = GeocodedLocation(f"{lat},{lng}", f"{lat:.5f}, {lng:.5f}", lat, lng, "coordinates")
    else:
        query = value.strip()
        if m := _LATLNG_RE.match(query):
            lat, lng = float(m.group(1)), float(m.group(2))
            location = GeocodedLocation(query, f"{lat:.5f}, {lng:.5f}", lat, lng, "coordinates")
        else:
            location = _resolve_offline(query) or _geocode_external_cached(query)

    if not is_within_usa(location.lat, location.lng):
        country = foreign_country_at(location.lat, location.lng)
        where = f"in {country}" if country else "outside the USA"
        raise LocationOutsideUSA(
            f"'{location.query}' resolves to a point {where}. Start and finish must be inside the USA."
        )
    return location


def _geocode_external_cached(query: str) -> GeocodedLocation:
    key = "geocode:" + hashlib.sha256(query.lower().encode()).hexdigest()
    cached = cache.get(key)
    if cached is not None:
        if cached == "__not_found__":
            raise LocationNotFound(f"Could not find a US location matching '{query}'.")
        return GeocodedLocation(**{**cached, "query": query})

    geocoder = get_external_geocoder()
    result = geocoder.geocode(query) if geocoder else None
    ttl = settings.FUEL_ROUTE["GEOCODE_CACHE_TTL_SECONDS"]
    if result is None:
        cache.set(key, "__not_found__", timeout=3600)
        raise LocationNotFound(
            f"Could not find a US location matching '{query}'. Try 'City, ST', a ZIP code or 'lat,lng'."
        )
    cache.set(
        key,
        {"query": query, "label": result.label, "lat": result.lat, "lng": result.lng, "source": result.source},
        timeout=ttl,
    )
    return result
