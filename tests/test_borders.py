"""The offline USA check must accept every US ZIP code and reject neighbouring countries."""

import pytest
import zipcodes

from apps.core.borders import foreign_country_at, is_within_usa
from apps.core.gazetteer import US_STATES


def test_every_us_zip_code_is_inside_the_usa():
    rejected = []
    for row in zipcodes.list_all():
        # Same filter as the gazetteer: military (APO/FPO) ZIPs are overseas mail codes.
        if row.get("country") != "US" or row["state"] not in US_STATES or row.get("zip_code_type") == "MILITARY":
            continue
        try:
            lat, lng = float(row["lat"]), float(row["long"])
        except (TypeError, ValueError):
            continue
        if lat == 0 and lng == 0:  # ~45 PO-box / parcel-return codes have no coordinates
            continue
        if not is_within_usa(lat, lng):
            rejected.append((row["zip_code"], row["city"], row["state"]))
    assert rejected == []


@pytest.mark.parametrize(
    "name,lat,lng,country",
    [
        ("Windsor ON", 42.30, -83.02, "Canada"),
        ("Sarnia", 42.97, -82.40, "Canada"),
        ("Fort Erie", 42.905, -78.93, "Canada"),
        ("Niagara Falls ON", 43.09, -79.08, "Canada"),
        ("Toronto", 43.65, -79.38, "Canada"),
        ("Brockville", 44.59, -75.684, "Canada"),
        ("Montreal", 45.50, -73.57, "Canada"),
        ("Edmundston", 47.373, -68.325, "Canada"),
        ("Sault Ste Marie ON", 46.52, -84.33, "Canada"),
        ("Thunder Bay", 48.38, -89.25, "Canada"),
        ("Winnipeg", 49.90, -97.14, None),  # north of every US box: rejected without a polygon
        ("Vancouver", 49.28, -123.12, "Canada"),
        ("Victoria", 48.43, -123.37, "Canada"),
        ("Whitehorse", 60.72, -135.06, "Canada"),
        ("Prince Rupert", 54.31, -130.32, "Canada"),
        ("Tijuana", 32.52, -117.03, "Mexico"),
        ("Mexicali", 32.63, -115.45, "Mexico"),
        ("Nogales, Sonora", 31.30, -110.94, "Mexico"),
        ("Ciudad Juarez", 31.69, -106.42, "Mexico"),
        ("Nuevo Laredo", 27.48, -99.52, "Mexico"),
        ("Reynosa", 26.08, -98.30, "Mexico"),
        ("Matamoros", 25.87, -97.50, "Mexico"),
        ("Monterrey", 25.67, -100.31, "Mexico"),
        ("Nassau", 25.05, -77.35, "The Bahamas"),
    ],
)
def test_neighbouring_countries_are_rejected(name, lat, lng, country):
    assert not is_within_usa(lat, lng), name
    assert foreign_country_at(lat, lng) == country


@pytest.mark.parametrize(
    "name,lat,lng",
    [
        ("Detroit", 42.331, -83.046),
        ("Buffalo", 42.886, -78.878),
        ("Niagara Falls NY", 43.094, -79.05),
        ("El Paso", 31.76, -106.49),
        ("Laredo", 27.51, -99.507),
        ("Brownsville", 25.90, -97.497),
        ("San Ysidro", 32.555, -117.04),
        ("Calexico", 32.68, -115.50),
        ("Nogales AZ", 31.34, -110.94),
        ("Port Huron", 42.97, -82.43),
        ("Sault Ste Marie MI", 46.495, -84.345),
        ("International Falls", 48.60, -93.41),
        ("Blaine WA", 48.99, -122.75),
        ("Point Roberts", 48.98, -123.06),
        ("Calais ME", 45.184, -67.276),
        ("Madawaska ME", 47.355, -68.33),
        ("Hyder AK", 55.917, -130.025),
        ("Key West", 24.56, -81.78),
        ("Honolulu", 21.31, -157.86),
        ("Anchorage", 61.22, -149.9),
    ],
)
def test_us_border_towns_are_accepted(name, lat, lng):
    assert is_within_usa(lat, lng), name


def test_far_away_points_are_rejected():
    assert not is_within_usa(51.5074, -0.1278)  # London
    assert not is_within_usa(19.43, -99.13)  # Mexico City (south of the US boxes)
