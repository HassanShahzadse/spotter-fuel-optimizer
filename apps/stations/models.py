from django.db import models


class FuelStation(models.Model):
    """A truck stop from the OPIS fuel price file, geocoded at import time."""

    class GeocodeSource(models.TextChoices):
        CITY_CENTROID = "city_centroid", "City centroid (offline USPS gazetteer)"
        EXTERNAL = "external", "External geocoder"
        MANUAL = "manual", "Manual"

    opis_id = models.PositiveIntegerField(unique=True, help_text="OPIS Truckstop ID")
    name = models.CharField(max_length=255)
    address = models.CharField(max_length=255)
    city = models.CharField(max_length=128)
    state = models.CharField(max_length=2, db_index=True)
    rack_id = models.PositiveIntegerField(null=True, blank=True)
    retail_price = models.DecimalField(max_digits=8, decimal_places=5, db_index=True)

    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    geocode_source = models.CharField(max_length=32, choices=GeocodeSource.choices, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["state", "city", "name"]
        indexes = [models.Index(fields=["latitude", "longitude"], name="station_lat_lng_idx")]

    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.state}) ${self.retail_price}"

    @property
    def is_geocoded(self) -> bool:
        return self.latitude is not None and self.longitude is not None
