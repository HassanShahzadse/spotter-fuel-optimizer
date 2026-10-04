"""Domain exceptions and a consistent JSON error envelope for the API."""

from __future__ import annotations

import logging

from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler

logger = logging.getLogger(__name__)


class ServiceError(APIException):
    """Base class for errors raised by the service layer."""

    status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_detail = "An unexpected error occurred."
    default_code = "service_error"


class SameLocation(ServiceError):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Start and finish resolve to the same place. Provide two different locations."
    default_code = "same_location"


class LocationNotFound(ServiceError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "The location could not be found."
    default_code = "location_not_found"


class LocationOutsideUSA(ServiceError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "The location must be inside the USA."
    default_code = "location_outside_usa"


class RouteNotFound(ServiceError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "No drivable route was found between the given locations."
    default_code = "route_not_found"


class FuelPlanInfeasible(ServiceError):
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY
    default_detail = "The trip cannot be completed with the vehicle range and the available fuel stations."
    default_code = "fuel_plan_infeasible"


class UpstreamServiceError(ServiceError):
    status_code = status.HTTP_502_BAD_GATEWAY
    default_detail = "An upstream map/routing service failed. Please retry shortly."
    default_code = "upstream_error"


class StationDataUnavailable(ServiceError):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Fuel station data has not been loaded. Run `python manage.py import_fuel_stations`."
    default_code = "station_data_unavailable"


def api_exception_handler(exc, context):
    """Wrap every DRF error as ``{"error": {"code", "message", "details"}}``."""
    response = exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API error", exc_info=exc)
        return Response(
            {"error": {"code": "internal_error", "message": "Internal server error.", "details": None}},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    data = response.data
    if isinstance(exc, APIException):
        codes = exc.get_codes()
        code = codes if isinstance(codes, str) else "validation_error"
    else:
        code = "error"

    if isinstance(data, dict) and set(data.keys()) == {"detail"}:
        message, details = str(data["detail"]), None
    else:
        message, details = "Invalid request.", data
    response.data = {"error": {"code": code, "message": message, "details": details}}
    return response
