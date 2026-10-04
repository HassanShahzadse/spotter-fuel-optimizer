from django.urls import path

from apps.routing.views import RouteMapView, RoutePlanView

urlpatterns = [
    path("route/", RoutePlanView.as_view(), name="route-plan"),
    path("route/<str:plan_id>/map/", RouteMapView.as_view(), name="route-map"),
]
