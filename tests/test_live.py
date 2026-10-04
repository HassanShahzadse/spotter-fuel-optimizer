"""
Smoke tests against the real routing and geocoding APIs. Skipped by default; run with:

    python -m pytest -m live

The rest of the suite mocks upstream HTTP, so these catch provider API changes.
"""

import pytest
from django.conf import settings

from apps.core.exceptions import LocationNotFound
from apps.routing.services.geocoding import get_external_geocoder
from apps.routing.services.routing_providers import get_routing_provider

pytestmark = pytest.mark.live


@pytest.fixture
def real_settings(settings):
    # Use the real provider configuration from .env, with normal retries.
    settings.FUEL_ROUTE = {**settings.FUEL_ROUTE}
    return settings


def test_configured_routing_provider_returns_a_route(real_settings):
    route = get_routing_provider().route((32.7767, -96.7970), (30.2672, -97.7431))  # Dallas -> Austin
    assert 150 < route.distance_miles < 250
    assert len(route.coords) > 10


def test_configured_geocoder_resolves_a_street_address(real_settings):
    geocoder = get_external_geocoder()
    if geocoder is None:
        pytest.skip("GEOCODER_PROVIDER=none")
    if geocoder.name == "nominatim" and "@" not in settings.FUEL_ROUTE["HTTP_USER_AGENT"]:
        pytest.skip("Nominatim needs HTTP_USER_AGENT with a real contact email")
    try:
        result = geocoder.geocode("1600 Pennsylvania Ave NW, Washington, DC")
    except LocationNotFound:  # pragma: no cover
        pytest.fail("The White House was not found")
    assert result is not None
    assert result.lat == pytest.approx(38.8977, abs=0.05)
    assert result.lng == pytest.approx(-77.0365, abs=0.05)
