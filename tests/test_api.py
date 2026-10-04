import itertools
import re

import pytest
import responses
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.geo import decode_polyline, encode_polyline
from tests.factories import osrm_response, polyline_through

OSRM_URL = re.compile(r"https://router\.project-osrm\.org/route/v1/driving/.*")


@pytest.fixture
def client():
    return APIClient()


def mock_osrm(*cities):
    coords, miles = polyline_through(*cities)
    responses.get(OSRM_URL, json=osrm_response(coords, miles * 1.1))
    return miles * 1.1


@pytest.mark.django_db
@responses.activate
def test_long_route_returns_multiple_optimal_stops(client, osrm_settings):
    miles = mock_osrm(
        "Chicago, IL",
        "Des Moines, IA",
        "Omaha, NE",
        "North Platte, NE",
        "Cheyenne, WY",
        "Rock Springs, WY",
        "Salt Lake City, UT",
    )
    resp = client.post(reverse("route-plan"), {"start": "Chicago, IL", "finish": "Salt Lake City, UT"}, format="json")
    assert resp.status_code == 200, resp.content
    data = resp.json()

    assert set(data) == {
        "start",
        "finish",
        "distance_miles",
        "fuel_stops",
        "total_gallons",
        "total_fuel_cost",
        "map_url",
        "meta",
    }
    stops = data["fuel_stops"]
    assert data["distance_miles"] == pytest.approx(miles, rel=1e-3)
    assert len(stops) >= 2
    assert set(stops[0]) == {
        "stop",
        "station",
        "address",
        "mile",
        "price_per_gallon",
        "gallons",
        "cost",
    }
    assert data["total_fuel_cost"] == pytest.approx(sum(s["cost"] for s in stops), abs=0.05)
    assert data["total_gallons"] == pytest.approx(sum(s["gallons"] for s in stops), abs=0.05)
    for s in stops:
        assert s["cost"] == pytest.approx(s["gallons"] * s["price_per_gallon"], abs=0.06)  # display rounding

    # Leaves with a full tank (500 mi), and never drives more than 500 miles between fill-ups.
    marks = [0.0] + [s["mile"] for s in stops] + [data["distance_miles"]]
    assert stops[0]["mile"] > 0
    assert all(b - a <= 500 + 0.5 for a, b in itertools.pairwise(marks))
    # With a full tank at the start, the fuel bought covers the rest of the trip.
    assert data["total_gallons"] == pytest.approx(data["distance_miles"] / 10 - 50, abs=3)

    # Exactly one upstream call, and the map page renders.
    assert data["meta"]["routing_api_calls"] == 1
    assert data["meta"]["cached"] is False
    assert len(responses.calls) == 1
    page = client.get(data["map_url"].replace("http://testserver", ""))
    assert page.status_code == 200
    assert b"leaflet" in page.content
    # OSM tiles (which need a Referer header), with Esri as the fallback.
    assert b"tile.openstreetmap.org" in page.content and b"server.arcgisonline.com" in page.content
    assert b"strict-origin-when-cross-origin" in page.content


@pytest.mark.django_db
@responses.activate
def test_short_trip_needs_no_fuel_stop(client, osrm_settings):
    mock_osrm("Dallas, TX", "Houston, TX")
    data = client.post(reverse("route-plan"), {"start": "Dallas, TX", "finish": "Houston, TX"}, format="json").json()
    assert data["fuel_stops"] == []
    assert data["total_fuel_cost"] == 0


@pytest.mark.django_db
@responses.activate
def test_repeat_request_is_served_from_cache(client, osrm_settings):
    mock_osrm("Dallas, TX", "Houston, TX")
    body = {"start": "Dallas, TX", "finish": "Houston, TX"}
    first = client.post(reverse("route-plan"), body, format="json").json()
    second = client.post(reverse("route-plan"), body, format="json").json()
    assert first["meta"]["cached"] is False
    assert second["meta"]["cached"] is True
    assert second["meta"]["routing_api_calls"] == 0
    assert len(responses.calls) == 1

    # Changing options re-plans but re-uses the cached route geometry (still one upstream call).
    third = client.post(reverse("route-plan"), {**body, "start_fuel_level": 0}, format="json").json()
    assert third["meta"]["routing_api_calls"] == 0
    assert len(third["fuel_stops"]) == 1 and third["fuel_stops"][0]["mile"] == 0
    assert len(responses.calls) == 1


@pytest.mark.django_db
@responses.activate
def test_get_variant_and_optional_polyline(client, osrm_settings):
    mock_osrm("Atlanta, GA", "Nashville, TN")
    params = {"start": "Atlanta, GA", "finish": "Nashville, TN"}
    resp = client.get(reverse("route-plan"), params)
    assert resp.status_code == 200
    assert "route_polyline" not in resp.json()  # not part of the default response

    with_line = client.get(reverse("route-plan"), {**params, "include_geometry": "true"}).json()
    route = decode_polyline(with_line["route_polyline"])
    assert 2 <= len(route) <= 500
    assert route[0] == pytest.approx((33.75, -84.39), abs=0.3)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "body,status,code",
    [
        ({"finish": "Denver, CO"}, 400, "validation_error"),
        ({"start": "Denver, CO", "finish": "Boulder, CO", "corridor_miles": 500}, 400, "validation_error"),
        ({"start": "Denver, CO", "finish": "Denver, CO"}, 400, "same_location"),
        ({"start": "New York, NY", "finish": "new york ny"}, 400, "same_location"),
        ({"start": "10001", "finish": "40.7506,-73.9972"}, 400, "same_location"),
        ({"start": "51.5,-0.12", "finish": "Denver, CO"}, 422, "location_outside_usa"),
        ({"start": "Toronto, ON", "finish": "Chicago, IL"}, 422, "location_outside_usa"),
        ({"start": "Chicago, IL", "finish": "Vancouver, Canada"}, 422, "location_outside_usa"),
        ({"start": "Monterrey, Nuevo Leon", "finish": "Laredo, TX"}, 422, "location_outside_usa"),
        ({"start": "43.65,-79.38", "finish": "Chicago, IL"}, 422, "location_outside_usa"),  # Toronto
        ({"start": "32.52,-117.03", "finish": "Phoenix, AZ"}, 422, "location_outside_usa"),  # Tijuana
    ],
)
@responses.activate
def test_validation_errors(client, osrm_settings, body, status, code):
    resp = client.post(reverse("route-plan"), body, format="json")
    assert resp.status_code == status
    assert resp.json()["error"]["code"] == code
    assert len(responses.calls) == 0  # rejected before any routing or geocoding call


@pytest.mark.django_db
@responses.activate
def test_upstream_failure_is_502(client, osrm_settings):
    responses.get(OSRM_URL, status=503, json={"code": "Error"})
    resp = client.post(reverse("route-plan"), {"start": "Dallas, TX", "finish": "Austin, TX"}, format="json")
    assert resp.status_code == 502
    assert resp.json()["error"]["code"] == "upstream_error"


@pytest.mark.django_db
@responses.activate
def test_health_reports_routing_failures(client, osrm_settings):
    assert client.get(reverse("health")).json()["routing_last_check"] is None

    responses.get(OSRM_URL, status=503, json={"code": "Error"})
    client.post(reverse("route-plan"), {"start": "Dallas, TX", "finish": "Austin, TX"}, format="json")
    health = client.get(reverse("health"))
    assert health.status_code == 503
    assert health.json()["status"] == "degraded"
    assert health.json()["routing_last_check"]["ok"] is False

    probe_route = osrm_response(*polyline_through("Kansas City, MO", "Olathe, KS"))
    responses.replace(responses.GET, OSRM_URL, json=probe_route)
    deep = client.get(reverse("health"), {"deep": "true"})
    assert deep.status_code == 200
    assert deep.json()["routing_last_check"]["ok"] is True
    # The probe is cached: a second deep check makes no new upstream call.
    calls = len(responses.calls)
    assert client.get(reverse("health"), {"deep": "true"}).json()["routing_last_check"]["cached"] is True
    assert len(responses.calls) == calls


@pytest.mark.django_db
def test_map_expired_is_404(client):
    assert client.get("/api/v1/route/doesnotexist/map/").status_code == 404


@pytest.mark.django_db
def test_health_and_stations(client):
    health = client.get(reverse("health")).json()
    assert health["status"] == "ok" and health["fuel_stations_loaded"] > 6000
    stations = client.get(reverse("station-list"), {"state": "TX", "ordering": "retail_price", "limit": 5}).json()
    prices = [s["retail_price"] for s in stations["results"]]
    assert prices == sorted(prices) and len(prices) == 5


@pytest.mark.django_db
def test_openapi_schema(client):
    assert client.get("/api/schema/").status_code == 200


def test_polyline_round_trip():
    pts = [(38.5, -120.2), (40.7, -120.95), (43.252, -126.453)]
    assert encode_polyline(pts) == "_p~iF~ps|U_ulLnnqC_mqNvxq`@"  # Google's documented example
    assert decode_polyline(encode_polyline(pts)) == pytest.approx(pts)
