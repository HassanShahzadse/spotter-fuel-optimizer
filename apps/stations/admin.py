from django.contrib import admin

from apps.stations.models import FuelStation


@admin.register(FuelStation)
class FuelStationAdmin(admin.ModelAdmin):
    list_display = ("opis_id", "name", "city", "state", "retail_price", "latitude", "longitude", "geocode_source")
    list_filter = ("state", "geocode_source")
    search_fields = ("name", "city", "address", "opis_id")
    ordering = ("retail_price",)
    readonly_fields = ("created_at", "updated_at")
