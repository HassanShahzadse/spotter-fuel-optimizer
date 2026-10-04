from django.urls import path

from apps.stations.views import FuelStationListView

urlpatterns = [
    path("stations/", FuelStationListView.as_view(), name="station-list"),
]
