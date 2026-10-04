"""
Import and geocode the OPIS fuel price CSV.

Pipeline
--------
1. Parse and clean rows (trim padded strings, validate numbers).
2. Drop non-US rows (the file also contains Canadian provinces).
3. De-duplicate by ``OPIS Truckstop ID`` keeping the lowest retail price
   (the same truck stop is listed several times under slightly different names).
4. Geocode every station offline from the USPS gazetteer (city + state ->
   city centroid). Optionally fall back to an external geocoder for misses.
5. Upsert into the database in a single transaction (idempotent; safe to re-run).
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.db import transaction

from apps.core.gazetteer import US_STATES, get_gazetteer
from apps.stations.models import FuelStation
from apps.stations.services.station_index import invalidate_station_index

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    "OPIS Truckstop ID",
    "Truckstop Name",
    "Address",
    "City",
    "State",
    "Rack ID",
    "Retail Price",
}


@dataclass
class ImportReport:
    rows_read: int = 0
    rows_invalid: int = 0
    rows_non_us: int = 0
    duplicates_merged: int = 0
    stations_upserted: int = 0
    stations_deleted: int = 0
    geocoded_offline: int = 0
    geocoded_external: int = 0
    not_geocoded: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "rows_read": self.rows_read,
            "rows_invalid": self.rows_invalid,
            "rows_non_us_skipped": self.rows_non_us,
            "duplicates_merged": self.duplicates_merged,
            "stations_upserted": self.stations_upserted,
            "stations_deleted": self.stations_deleted,
            "geocoded_offline": self.geocoded_offline,
            "geocoded_external": self.geocoded_external,
            "not_geocoded": len(self.not_geocoded),
        }


def _parse_rows(path: Path, report: ImportReport) -> dict[int, dict]:
    stations: dict[int, dict] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV is missing required columns: {sorted(missing)}")

        for row in reader:
            report.rows_read += 1
            try:
                opis_id = int(row["OPIS Truckstop ID"])
                price = Decimal(row["Retail Price"].strip())
                rack = row["Rack ID"].strip()
                record = {
                    "opis_id": opis_id,
                    "name": row["Truckstop Name"].strip(),
                    "address": row["Address"].strip(),
                    "city": row["City"].strip(),
                    "state": row["State"].strip().upper(),
                    "rack_id": int(rack) if rack else None,
                    "retail_price": price,
                }
            except (KeyError, ValueError, InvalidOperation, AttributeError):
                report.rows_invalid += 1
                continue
            if price <= 0 or not record["city"]:
                report.rows_invalid += 1
                continue
            if record["state"] not in US_STATES:
                report.rows_non_us += 1
                continue

            existing = stations.get(opis_id)
            if existing is not None:
                report.duplicates_merged += 1
                if price >= existing["retail_price"]:
                    continue
            stations[opis_id] = record
    return stations


def import_fuel_stations(
    csv_path: str | Path,
    *,
    purge: bool = False,
    external_geocoder: Callable[[str], tuple[float, float] | None] | None = None,
) -> ImportReport:
    """Import the CSV at ``csv_path``. Returns an :class:`ImportReport`."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(path)

    report = ImportReport()
    records = _parse_rows(path, report)
    gazetteer = get_gazetteer()

    for record in records.values():
        place = gazetteer.lookup_city(record["city"], record["state"])
        if place is not None:
            record.update(
                latitude=place.lat, longitude=place.lng, geocode_source=FuelStation.GeocodeSource.CITY_CENTROID
            )
            report.geocoded_offline += 1
            continue

        coords = None
        if external_geocoder is not None:
            coords = external_geocoder(f"{record['city']}, {record['state']}, USA")
        if coords:
            record.update(latitude=coords[0], longitude=coords[1], geocode_source=FuelStation.GeocodeSource.EXTERNAL)
            report.geocoded_external += 1
        else:
            record.update(latitude=None, longitude=None, geocode_source="")
            report.not_geocoded.append(f"{record['city']}, {record['state']}")

    objects = [FuelStation(**r) for r in records.values()]
    update_fields = [
        "name",
        "address",
        "city",
        "state",
        "rack_id",
        "retail_price",
        "latitude",
        "longitude",
        "geocode_source",
        "updated_at",
    ]
    with transaction.atomic():
        FuelStation.objects.bulk_create(
            objects,
            batch_size=1000,
            update_conflicts=True,
            unique_fields=["opis_id"],
            update_fields=update_fields,
        )
        report.stations_upserted = len(objects)
        if purge:
            report.stations_deleted, _ = FuelStation.objects.exclude(opis_id__in=records.keys()).delete()
        transaction.on_commit(invalidate_station_index)

    logger.info("Fuel station import finished: %s", report.as_dict())
    return report
