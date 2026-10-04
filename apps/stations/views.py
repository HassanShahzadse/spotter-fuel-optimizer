from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics
from rest_framework.pagination import LimitOffsetPagination

from apps.stations.models import FuelStation
from apps.stations.serializers import FuelStationSerializer


class StationPagination(LimitOffsetPagination):
    default_limit = 50
    max_limit = 500


@extend_schema(
    summary="List fuel stations",
    tags=["Stations"],
    parameters=[
        OpenApiParameter("state", str, description="Two-letter state code, e.g. TX"),
        OpenApiParameter("city", str, description="City name (case-insensitive)"),
        OpenApiParameter("ordering", str, enum=["retail_price", "-retail_price", "name"]),
    ],
)
class FuelStationListView(generics.ListAPIView):
    serializer_class = FuelStationSerializer
    pagination_class = StationPagination

    def get_queryset(self):
        qs = FuelStation.objects.all()
        params = self.request.query_params
        if state := params.get("state"):
            qs = qs.filter(state=state.upper())
        if city := params.get("city"):
            qs = qs.filter(city__iexact=city)
        ordering = params.get("ordering")
        if ordering in {"retail_price", "-retail_price", "name"}:
            qs = qs.order_by(ordering, "id")
        return qs
