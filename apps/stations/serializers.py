from rest_framework import serializers

from apps.stations.models import FuelStation


class FuelStationSerializer(serializers.ModelSerializer):
    retail_price = serializers.DecimalField(max_digits=8, decimal_places=3, coerce_to_string=False)

    class Meta:
        model = FuelStation
        fields = ("id", "opis_id", "name", "address", "city", "state", "retail_price", "latitude", "longitude")
