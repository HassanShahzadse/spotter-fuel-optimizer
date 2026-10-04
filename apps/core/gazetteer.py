"""
Offline US gazetteer: "City, ST" or ZIP code to coordinates.

Built in memory from the ``zipcodes`` package (the USPS ZIP database with centroids).
Used to geocode the fuel stations at import time and to resolve city and ZIP inputs
without an API call. Built once per process.
"""

from __future__ import annotations

import re
import statistics
import threading
from collections import defaultdict
from dataclasses import dataclass

US_STATES: dict[str, str] = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia",
    "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}  # fmt: skip
STATE_NAME_TO_CODE = {name.upper(): code for code, name in US_STATES.items()}

# Canadian and Mexican regions, so "Toronto, ON" is rejected before it reaches the
# US-only geocoder, which would return Toronto, Ohio.
CANADIAN_PROVINCES: dict[str, str] = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "NT": "Northwest Territories",
    "NU": "Nunavut", "ON": "Ontario", "PE": "Prince Edward Island", "QC": "Quebec",
    "SK": "Saskatchewan", "YT": "Yukon",
}  # fmt: skip
MEXICAN_STATES = (
    "Aguascalientes", "Baja California", "Baja California Sur", "Campeche", "Chiapas", "Chihuahua",
    "Ciudad de Mexico", "Coahuila", "Colima", "Durango", "Guanajuato", "Guerrero", "Hidalgo", "Jalisco",
    "Estado de Mexico", "Michoacan", "Morelos", "Nayarit", "Nuevo Leon", "Oaxaca", "Puebla", "Queretaro",
    "Quintana Roo", "San Luis Potosi", "Sinaloa", "Sonora", "Tabasco", "Tamaulipas", "Tlaxcala",
    "Veracruz", "Yucatan", "Zacatecas", "CDMX",
)  # fmt: skip
_FOREIGN_REGIONS: dict[str, str] = {
    **{code: "Canada" for code in CANADIAN_PROVINCES},
    **{name.upper(): "Canada" for name in CANADIAN_PROVINCES.values()},
    **{name.upper(): "Mexico" for name in MEXICAN_STATES},
    "CANADA": "Canada",
    "MEXICO": "Mexico",
    "MX": "Mexico",
}

_ABBREVIATIONS = (
    (r"\bSAINT\b", "ST"),
    (r"\bSAINTE\b", "STE"),
    (r"\bFORT\b", "FT"),
    (r"\bMOUNT\b", "MT"),
    (r"\bMOUNTAIN\b", "MTN"),
    (r"\bPOINT\b", "PT"),
)


def normalize_city(value: str) -> str:
    """Normalize a city name so that 'St. Louis', 'Saint Louis' and 'ST LOUIS' match."""
    text = value.strip().upper()
    text = re.sub(r"[.'`\u2019]", "", text)
    text = re.sub(r"[-/,]", " ", text)
    for pattern, replacement in _ABBREVIATIONS:
        text = re.sub(pattern, replacement, text)
    return re.sub(r"\s+", " ", text).strip()


def normalize_state(value: str) -> str | None:
    text = value.strip().upper().replace(".", "")
    if text in US_STATES:
        return text
    return STATE_NAME_TO_CODE.get(text)


def foreign_region(value: str) -> str | None:
    """Country name if ``value`` is a Canadian province, a Mexican state or the country itself."""
    text = re.sub(r"\s+", " ", value.strip().upper().replace(".", ""))
    text = text.translate(str.maketrans("ÁÉÍÓÚ", "AEIOU"))
    return _FOREIGN_REGIONS.get(text)


@dataclass(frozen=True, slots=True)
class Place:
    city: str
    state: str
    lat: float
    lng: float
    zip_code: str | None = None

    @property
    def label(self) -> str:
        base = f"{self.city.title()}, {self.state}"
        return f"{base} {self.zip_code}" if self.zip_code else base


class Gazetteer:
    """In-memory city/ZIP lookup."""

    def __init__(self) -> None:
        self._cities: dict[tuple[str, str], Place] = {}
        self._cities_compact: dict[tuple[str, str], Place] = {}
        self._zips: dict[str, Place] = {}
        self._build()

    def _build(self) -> None:
        import zipcodes

        primary: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        secondary: dict[tuple[str, str], list[tuple[float, float]]] = defaultdict(list)
        display: dict[tuple[str, str], str] = {}

        for row in zipcodes.list_all():
            if row.get("country") != "US" or row.get("zip_code_type") == "MILITARY":
                continue
            try:
                lat, lng = float(row["lat"]), float(row["long"])
            except (TypeError, ValueError):
                continue
            state = row["state"]
            key = (normalize_city(row["city"]), state)
            primary[key].append((lat, lng))
            display.setdefault(key, row["city"])
            self._zips[row["zip_code"]] = Place(row["city"], state, lat, lng, row["zip_code"])
            for alt in row.get("acceptable_cities") or []:
                alt_key = (normalize_city(alt), state)
                secondary[alt_key].append((lat, lng))
                display.setdefault(alt_key, alt)

        # Primary city names win; "acceptable" alternate names are a fallback.
        for source in (secondary, primary):
            for key, points in source.items():
                lat = statistics.median(p[0] for p in points)
                lng = statistics.median(p[1] for p in points)
                place = Place(display[key], key[1], lat, lng)
                self._cities[key] = place
                self._cities_compact[(key[0].replace(" ", ""), key[1])] = place

    def lookup_city(self, city: str, state: str) -> Place | None:
        state_code = normalize_state(state)
        if not state_code:
            return None
        norm = normalize_city(city)
        return self._cities.get((norm, state_code)) or self._cities_compact.get((norm.replace(" ", ""), state_code))

    def lookup_zip(self, zip_code: str) -> Place | None:
        return self._zips.get(zip_code.strip()[:5])

    @property
    def size(self) -> int:
        return len(self._cities)


_instance: Gazetteer | None = None
_lock = threading.Lock()


def get_gazetteer() -> Gazetteer:
    """Process-wide singleton (thread-safe lazy initialisation)."""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = Gazetteer()
    return _instance
