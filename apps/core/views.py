"""Health check and landing endpoints."""

from django.conf import settings
from django.db import DatabaseError, connection
from django.http import JsonResponse
from django.views import View
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.stations.models import FuelStation


class IndexView(View):
    def get(self, request):
        return JsonResponse(
            {
                "service": "Fuel Route Optimizer API",
                "version": settings.SPECTACULAR_SETTINGS["VERSION"],
                "docs": request.build_absolute_uri("/api/docs/"),
                "health": request.build_absolute_uri("/api/v1/health/"),
                "route_endpoint": request.build_absolute_uri("/api/v1/route/"),
            }
        )


class HealthCheckView(APIView):
    throttle_classes: list = []

    @extend_schema(
        summary="Service health check",
        description=(
            "Database, station data and routing provider status. The routing status comes from the last real "
            "routing call; `deep=true` also runs one tiny probe route (cached for 5 minutes)."
        ),
        parameters=[OpenApiParameter("deep", bool, description="Probe the routing provider with a real call.")],
        tags=["Health"],
        responses={200: OpenApiTypes.OBJECT, 503: OpenApiTypes.OBJECT},
    )
    def get(self, request):
        from apps.routing.services.provider_health import last_routing_outcome, probe_routing
        from apps.routing.services.routing_providers import get_routing_provider

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            db_ok = True
            stations = FuelStation.objects.count()
        except DatabaseError:  # pragma: no cover - only hit when the DB is down
            db_ok, stations = False, 0

        provider = get_routing_provider().name
        deep = request.query_params.get("deep", "").lower() in {"1", "true", "yes"}
        routing = probe_routing() if deep else last_routing_outcome()
        if routing is not None and routing.get("provider") != provider:
            routing = None  # recorded for a provider that is no longer configured
        routing_ok = routing is None or routing["ok"]

        healthy = db_ok and stations > 0 and routing_ok
        return Response(
            {
                "status": "ok" if healthy else "degraded",
                "database": "ok" if db_ok else "unavailable",
                "fuel_stations_loaded": stations,
                "routing_provider": provider,
                # None until the first routing call; ?deep=true checks now
                "routing_last_check": routing,
                "vehicle": {
                    "max_range_miles": settings.FUEL_ROUTE["VEHICLE_MAX_RANGE_MILES"],
                    "mpg": settings.FUEL_ROUTE["VEHICLE_MPG"],
                },
            },
            status=200 if healthy else 503,
        )
