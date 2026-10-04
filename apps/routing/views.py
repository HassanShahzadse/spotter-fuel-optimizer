"""HTTP layer for route planning. Business logic lives in ``services/``."""

from django.http import Http404
from django.shortcuts import render
from django.views import View
from drf_spectacular.utils import OpenApiExample, OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.routing.serializers import RoutePlanRequestSerializer
from apps.routing.services.presenter import public_response
from apps.routing.services.route_planner import PlanOptions, get_cached_plan, plan_route

_EXAMPLE = OpenApiExample(
    "New York to Los Angeles",
    value={"start": "New York, NY", "finish": "Los Angeles, CA"},
    request_only=True,
)
_ERRORS = {
    400: OpenApiResponse(description="Invalid input"),
    422: OpenApiResponse(description="Location not found / outside USA / no route / infeasible"),
    502: OpenApiResponse(description="Upstream routing service failed"),
}


class RoutePlanView(APIView):
    """Plan a route with cost-optimal fuel stops."""

    def _plan(self, request, data):
        serializer = RoutePlanRequestSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        validated = serializer.validated_data
        options = PlanOptions.from_request(validated)
        plan = plan_route(
            validated["start"],
            validated["finish"],
            options,
            base_url=request.build_absolute_uri("/").rstrip("/"),
        )
        return Response(public_response(plan, include_geometry=options.include_geometry))

    @extend_schema(
        summary="Plan a route with optimal fuel stops",
        description=(
            "Returns the cheapest fuel stops for a vehicle with a 500 mile range at 10 MPG that leaves "
            "with a full tank, the total fuel cost and a link to an interactive map. Set "
            "`include_geometry` to also get the route as an encoded polyline."
        ),
        request=RoutePlanRequestSerializer,
        examples=[_EXAMPLE],
        responses={200: OpenApiResponse(description="Route plan"), **_ERRORS},
        tags=["Route"],
    )
    def post(self, request):
        return self._plan(request, request.data)

    @extend_schema(
        summary="Plan a route (query-string variant)",
        parameters=[
            OpenApiParameter("start", str, required=True, description="e.g. New York, NY"),
            OpenApiParameter("finish", str, required=True, description="e.g. Los Angeles, CA"),
            OpenApiParameter("corridor_miles", float),
            OpenApiParameter("start_fuel_level", float),
            OpenApiParameter("max_range_miles", float),
            OpenApiParameter("mpg", float),
            OpenApiParameter("stop_penalty_usd", float),
            OpenApiParameter("include_geometry", bool),
        ],
        responses={200: OpenApiResponse(description="Route plan"), **_ERRORS},
        tags=["Route"],
    )
    def get(self, request):
        return self._plan(request, request.query_params.dict())


class RouteMapView(View):
    """Leaflet map for a previously computed plan, served from the cache."""

    def get(self, request, plan_id: str):
        plan = get_cached_plan(plan_id)
        if plan is None:
            raise Http404("This map has expired. Request the route again to regenerate it.")
        return render(request, "routing/map.html", {"plan": plan})
