import pytest
import responses

from apps.core.exceptions import LocationNotFound, LocationOutsideUSA, UpstreamServiceError
from apps.core.gazetteer import get_gazetteer, normalize_city
from apps.routing.services.geocoding import OrsGeocoder, geocode_location
from apps.routing.services.metrics import count_external_calls


def test_normalize_city_variants():
    assert normalize_city("St. Louis") == normalize_city("Saint Louis") == "ST LOUIS"
    assert normalize_city("  Fort   Smith ") == "FT SMITH"


@pytest.mark.parametrize(
    "city,state",
    [("Big Cabin", "OK"), ("Saint Louis", "MO"), ("St. Louis", "Missouri"), ("De Forest", "WI"), ("Gila Bend", "AZ")],
)
def test_gazetteer_city_lookup(city, state):
    assert get_gazetteer().lookup_city(city, state) is not None


@pytest.mark.parametrize(
    "query,source",
    [
        ("New York, NY", "city_state"),
        ("Dallas TX", "city_state"),
        ("Salt Lake City, Utah", "city_state"),
        ("Chicago, IL, USA", "city_state"),
        ("10001", "zip_code"),
        ("Austin, TX 78701", "zip_code"),
        ("34.0522,-118.2437", "coordinates"),
    ],
)
def test_offline_geocoding(query, source):
    with count_external_calls() as calls:
        loc = geocode_location(query)
    assert loc.source == source
    assert sum(calls.values()) == 0


def test_object_coordinates():
    loc = geocode_location({"lat": 39.7392, "lng": -104.9903})
    assert loc.source == "coordinates"


def test_outside_usa_rejected():
    with pytest.raises(LocationOutsideUSA):
        geocode_location("51.5074,-0.1278")  # London


@responses.activate
def test_external_fallback_is_called_once_and_cached(osrm_settings):
    responses.get(
        "https://nominatim.openstreetmap.org/search",
        json=[{"lat": "38.8977", "lon": "-77.0365", "display_name": "White House, Washington DC"}],
    )
    with count_external_calls() as calls:
        first = geocode_location("1600 Pennsylvania Avenue NW Washington")
        second = geocode_location("1600 Pennsylvania Avenue NW Washington")
    assert first.lat == second.lat
    assert calls["geocoding"] == 1
    assert len(responses.calls) == 1


@responses.activate
def test_external_not_found(osrm_settings):
    responses.get("https://nominatim.openstreetmap.org/search", json=[])
    with pytest.raises(LocationNotFound):
        geocode_location("zzzz definitely not a place")


@pytest.mark.parametrize(
    "query",
    [
        "Toronto, ON",
        "Montreal, Quebec",
        "Vancouver, Canada",
        "Tijuana, Baja California",
        "Mexico City, Mexico",
        "Toronto, Ontario, Canada",
        "Monterrey Nuevo Leon",
    ],
)
def test_foreign_regions_rejected_offline(query):
    with count_external_calls() as calls, pytest.raises(LocationOutsideUSA):
        geocode_location(query)
    assert sum(calls.values()) == 0


@pytest.mark.parametrize("query", ["Santa Fe, New Mexico", "Mexico, MO", "Ontario, CA", "Hidalgo, TX", "Durango, CO"])
def test_us_places_with_foreign_looking_names(query):
    assert geocode_location(query).source == "city_state"


@responses.activate
def test_ors_geocoder_sends_key_in_header_not_url():
    responses.get(
        "https://ors.test/geocode/search",
        json={"features": [{"geometry": {"coordinates": [-77.03, 38.89]}, "properties": {"label": "DC"}}]},
    )
    OrsGeocoder("https://ors.test", "secret-key").geocode("1600 Pennsylvania Ave NW, Washington, DC")
    request = responses.calls[0].request
    assert request.headers["Authorization"] == "secret-key"
    assert "secret-key" not in request.url


@responses.activate
def test_nominatim_refusal_has_a_helpful_message(osrm_settings):
    responses.get("https://nominatim.openstreetmap.org/search", status=403, body="Access blocked")
    with pytest.raises(UpstreamServiceError, match="refused"):
        geocode_location("1 Main Street Springfield")
