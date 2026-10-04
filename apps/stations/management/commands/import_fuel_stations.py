"""
Load the OPIS fuel price CSV into the database and geocode every station.

Usage::

    python manage.py import_fuel_stations                       # uses settings.FUEL_PRICES_CSV
    python manage.py import_fuel_stations --csv path/to/file.csv
    python manage.py import_fuel_stations --purge               # delete stations missing from the file
    python manage.py import_fuel_stations --external-geocoding  # online fallback for unmatched cities
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.stations.services.importer import import_fuel_stations


class Command(BaseCommand):
    help = "Import and geocode fuel stations from the OPIS fuel price CSV."

    def add_arguments(self, parser):
        parser.add_argument("--csv", default=settings.FUEL_PRICES_CSV, help="Path to the fuel price CSV.")
        parser.add_argument("--purge", action="store_true", help="Delete stations that are not in the CSV.")
        parser.add_argument(
            "--external-geocoding",
            action="store_true",
            help="Use the configured online geocoder for cities missing from the offline gazetteer.",
        )

    def handle(self, *args, **options):
        external = None
        if options["external_geocoding"]:
            from apps.routing.services.geocoding import get_external_geocoder

            geocoder = get_external_geocoder()
            if geocoder is None:
                raise CommandError("No external geocoder is configured (GEOCODER_PROVIDER=none).")

            def external(query: str):
                result = geocoder.geocode(query)
                return (result.lat, result.lng) if result else None

        self.stdout.write(f"Importing fuel stations from {options['csv']} ...")
        try:
            report = import_fuel_stations(options["csv"], purge=options["purge"], external_geocoder=external)
        except (FileNotFoundError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        for key, value in report.as_dict().items():
            self.stdout.write(f"  {key.replace('_', ' '):<24} {value}")
        if report.not_geocoded:
            sample = ", ".join(sorted(set(report.not_geocoded))[:10])
            self.stdout.write(self.style.WARNING(f"  Not geocoded (excluded from routing): {sample}"))
        self.stdout.write(self.style.SUCCESS("Fuel station import complete."))
