import re

import pytest
import responses

from apps.core.exceptions import RouteNotFound, UpstreamServiceError
from apps.routing.services.routing_providers import OpenRouteServiceProvider, OsrmProvider
from tests.factories import ors_response, osrm_response, polyline_through


@responses.activate
def test_osrm_parses_route():
    coords, miles = polyline_through("Dallas, TX", "Houston, TX")
    responses.get(url=re.compile(r"https://osrm\.test/route/v1/driving/.*"), json=osrm_response(coords, miles))
    route = OsrmProvider("https://osrm.test").route((32.78, -96.80), (29.76, -95.37))
    assert route.distance_miles == pytest.approx(miles)
    assert route.coords.shape[1] == 2
    assert route.coords[0][0] == pytest.approx(coords[0][1])  # converted to [lat, lng]


@responses.activate
def test_osrm_no_route():
    responses.get(
        url=re.compile(r"https://osrm\.test/.*"),
        status=400,
        json={"code": "NoRoute", "message": "Impossible route"},
    )
    with pytest.raises(RouteNotFound):
        OsrmProvider("https://osrm.test").route((21.3, -157.8), (40.7, -74.0))


@responses.activate
def test_ors_parses_route_and_sends_key():
    coords, miles = polyline_through("Denver, CO", "Cheyenne, WY")
    responses.post("https://ors.test/v2/directions/driving-car/geojson", json=ors_response(coords, miles))
    route = OpenRouteServiceProvider("https://ors.test", "secret").route((39.7, -104.9), (41.1, -104.8))
    assert route.distance_miles == pytest.approx(miles)
    assert responses.calls[0].request.headers["Authorization"] == "secret"
    # ORS answers 406 to the session default "Accept: application/json" on /geojson.
    assert responses.calls[0].request.headers["Accept"] == "application/geo+json"


@responses.activate
def test_ors_bad_key():
    responses.post("https://ors.test/v2/directions/driving-car/geojson", status=403, json={})
    with pytest.raises(UpstreamServiceError):
        OpenRouteServiceProvider("https://ors.test", "bad").route((39.7, -104.9), (41.1, -104.8))
