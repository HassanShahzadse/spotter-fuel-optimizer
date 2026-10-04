import pytest
from django.conf import settings
from django.core.cache import cache

from apps.stations.services.importer import import_fuel_stations


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    """Load the real fuel price CSV once for the whole test session."""
    with django_db_blocker.unblock():
        import_fuel_stations(settings.FUEL_PRICES_CSV)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def osrm_settings(settings):
    settings.FUEL_ROUTE = {
        **settings.FUEL_ROUTE,
        "ROUTING_PROVIDER": "osrm",
        "ORS_API_KEY": "",
        "GEOCODER_PROVIDER": "nominatim",
        "HTTP_MAX_RETRIES": 0,
    }
    return settings
