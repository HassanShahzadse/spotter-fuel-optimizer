import pytest

from apps.stations.models import FuelStation
from apps.stations.services.importer import import_fuel_stations

CSV = """OPIS Truckstop ID,Truckstop Name,Address,City,State,Rack ID,Retail Price
1,PILOT A,"I-40, EXIT 1",Amarillo,TX,10,3.50
1,PILOT A ALT,"I-40, EXIT 1",Amarillo,TX,10,3.20
2,CANADA STOP,HWY 1,Calgary,AB,20,4.00
3,NOWHERE,HWY 2,Notarealcityxyz,TX,30,3.00
4,BAD PRICE,HWY 3,Dallas,TX,40,abc
"""


@pytest.mark.django_db
def test_import_dedupes_skips_and_geocodes(tmp_path):
    FuelStation.objects.all().delete()
    path = tmp_path / "prices.csv"
    path.write_text(CSV)
    report = import_fuel_stations(path)
    assert report.rows_read == 5
    assert report.rows_non_us == 1
    assert report.rows_invalid == 1
    assert report.duplicates_merged == 1
    assert report.stations_upserted == 2
    assert report.geocoded_offline == 1
    assert len(report.not_geocoded) == 1

    station = FuelStation.objects.get(opis_id=1)
    assert float(station.retail_price) == pytest.approx(3.20)  # lowest price kept
    assert station.is_geocoded
    assert not FuelStation.objects.get(opis_id=3).is_geocoded

    # Idempotent re-run
    again = import_fuel_stations(path, purge=True)
    assert again.stations_upserted == 2
    assert FuelStation.objects.count() == 2


@pytest.mark.django_db
def test_real_csv_is_fully_geocoded():
    assert FuelStation.objects.filter(latitude__isnull=True).count() == 0
    assert FuelStation.objects.count() > 6000
