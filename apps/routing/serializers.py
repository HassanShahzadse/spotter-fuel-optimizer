"""Request validation for the route planning endpoint."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers


@extend_schema_field(OpenApiTypes.STR)
class LocationField(serializers.Field):
    """
    Accepts any of:
      * ``"Chicago, IL"`` / ``"Chicago Illinois"``  (city + state)
      * ``"60601"``                                 (US ZIP code)
      * ``"41.8781,-87.6298"``                      (lat,lng)
      * ``{"lat": 41.8781, "lng": -87.6298}``       (object)
      * any US street address (resolved by the external geocoder)
    """

    default_error_messages = {
        "invalid": "Provide a location string (e.g. 'Chicago, IL') or an object {'lat': .., 'lng': ..}.",
        "blank": "Location may not be blank.",
        "too_long": "Location is too long (max 200 characters).",
        "bad_coordinates": "Latitude must be in [-90, 90] and longitude in [-180, 180].",
    }

    def to_internal_value(self, data):
        if isinstance(data, dict):
            try:
                lat, lng = float(data["lat"]), float(data["lng"])
            except (KeyError, TypeError, ValueError):
                self.fail("invalid")
            if not (-90 <= lat <= 90 and -180 <= lng <= 180):
                self.fail("bad_coordinates")
            return {"lat": lat, "lng": lng}
        if not isinstance(data, str):
            self.fail("invalid")
        value = data.strip()
        if not value:
            self.fail("blank")
        if len(value) > 200:
            self.fail("too_long")
        return value

    def to_representation(self, value):
        return value


class RoutePlanRequestSerializer(serializers.Serializer):
    start = LocationField(help_text="Start location inside the USA, e.g. 'New York, NY'.")
    finish = LocationField(help_text="Finish location inside the USA, e.g. 'Los Angeles, CA'.")
    corridor_miles = serializers.FloatField(
        required=False,
        min_value=1,
        max_value=50,
        help_text="Max distance a station may be from the route (default 10).",
    )
    start_fuel_level = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=1,
        help_text="Tank level at departure: 1 = full (default) .. 0 = empty (fuel up near the start).",
    )
    max_range_miles = serializers.FloatField(
        required=False, min_value=50, max_value=2000, help_text="Vehicle range on a full tank (default 500)."
    )
    mpg = serializers.FloatField(required=False, min_value=1, max_value=100, help_text="Miles per gallon (default 10).")
    stop_penalty_usd = serializers.FloatField(
        required=False,
        min_value=0,
        max_value=100,
        help_text="Cost-equivalent of one extra stop, used to avoid tiny top-ups (default 3). 0 = cheapest fuel only.",
    )
    include_geometry = serializers.BooleanField(
        required=False,
        default=False,
        help_text="Also return the route line as an encoded polyline (for apps that draw their own map).",
    )
