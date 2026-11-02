import logging
from concurrent.futures import ThreadPoolExecutor

from django.shortcuts import render
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.parsers import JSONParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import ErrorSerializer, RouteRequestSerializer, RouteResponseSerializer
from .services import geometry, planner, route_client

logger = logging.getLogger(__name__)

EXAMPLE_RESPONSE = {
    "total_distance_miles": 966.9,
    "total_fuel_cost": 134.80,
    "route_geometry": {
        "type": "LineString",
        "coordinates": [[-87.675896, 41.854215], [-87.624684, 41.720145], [-87.866842, 41.220226]],
    },
    "fuel_stops": [
        {"name": "HUCKS FOOD & FUEL #379", "city": "Marion", "state": "IL", "price_per_gallon": 2.929,
         "mile_marker": 314.5, "gallons_purchased": 29.4, "cost": 86.11, "latitude": 37.7257, "longitude": -88.9294},
        {"name": "Quiktrip #7900", "city": "Texarkana", "state": "TX", "price_per_gallon": 2.857,
         "mile_marker": 794.0, "gallons_purchased": 1.03, "cost": 2.94, "latitude": 33.435983, "longitude": -94.078233},
        {"name": "EXTRA MILE TRUCK STOP", "city": "Hooks", "state": "TX", "price_per_gallon": 2.817,
         "mile_marker": 804.3, "gallons_purchased": 12.37, "cost": 34.85, "latitude": 33.5253, "longitude": -94.2657},
        {"name": "CADOO MILLS", "city": "Caddo Mills", "state": "TX", "price_per_gallon": 2.801,
         "mile_marker": 928.0, "gallons_purchased": 3.89, "cost": 10.90, "latitude": 33.0683, "longitude": -96.2391},
    ],
}


def map_view(request):
    return render(request, "routing/map.html")


class RoutePlanView(APIView):
    # Public, stateless endpoint: no session auth means no CSRF requirement,
    # even for a browser that happens to be logged into /admin.
    authentication_classes = []
    permission_classes = [AllowAny]
    parser_classes = [JSONParser]

    @extend_schema(
        operation_id="plan_route",
        summary="Plan a route with the cheapest fuel stops",
        description=(
            "Geocodes `start` and `finish`, fetches the driving route, and returns the "
            "minimum-cost set of fuel stops for a vehicle with a 500-mile range at 10 MPG. "
            "The vehicle is assumed to depart with a full tank, so trips under 500 miles "
            "need no stops. `City, ST`, `City, State` and ZIP inputs are geocoded offline, so a typical "
            "request makes exactly 1 external call (routing). Free-text addresses fall back to an online "
            "geocoder (up to 3 calls)."
        ),
        request=RouteRequestSerializer,
        responses={
            200: OpenApiResponse(
                RouteResponseSerializer,
                description="Route and fuel plan. `total_fuel_cost` is exactly the sum of the stops' `cost`.",
                examples=[
                    OpenApiExample(
                        "Chicago to Dallas",
                        value=EXAMPLE_RESPONSE,
                        description="Real response; `route_geometry.coordinates` truncated to the first 3 points.",
                    )
                ],
            ),
            400: OpenApiResponse(
                description="Field validation failed, or a location could not be found in the USA.",
                examples=[
                    OpenApiExample("Missing fields", value={"start": ["This field is required."]}),
                    OpenApiExample("Unknown location", value={"error": "Could not find a US location matching: Atlantis"}),
                ],
            ),
            422: OpenApiResponse(ErrorSerializer, description="No drivable route, or a stretch with no fuel station in range."),
            502: OpenApiResponse(ErrorSerializer, description="The geocoding or routing provider is unavailable."),
        },
        examples=[
            OpenApiExample("Chicago to Dallas", value={"start": "Chicago, IL", "finish": "Dallas, TX"}, request_only=True),
        ],
    )
    def post(self, request):
        req = RouteRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)

        try:
            # The two lookups are independent and I/O-bound, so run them concurrently.
            with ThreadPoolExecutor(max_workers=2) as executor:
                start = executor.submit(route_client.geocode_address, req.validated_data["start"])
                finish = executor.submit(route_client.geocode_address, req.validated_data["finish"])
                (start_lat, start_lon), (end_lat, end_lon) = start.result(), finish.result()
            route = route_client.get_route(start_lat, start_lon, end_lat, end_lon)

            samples, geometry_miles = geometry.sample_route(route["geometry"])
            # OSRM's distance is exact; the simplified polyline undercounts slightly,
            # so rescale sample mile markers to agree with the authoritative total.
            total_miles = route["distance_miles"]
            scale = total_miles / geometry_miles if geometry_miles else 1
            samples = [(lat, lon, mile * scale) for lat, lon, mile in samples]

            stops, total_cost = planner.plan_fuel_stops(geometry.stations_along_route(samples), total_miles)
        except route_client.LocationNotFound as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except (route_client.RouteNotFound, planner.InfeasibleRoute) as e:
            return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
        except route_client.UpstreamUnavailable as e:
            logger.warning("Upstream provider failure: %s", e)
            return Response({"error": str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        payload = {
            "total_distance_miles": round(total_miles, 1),
            "total_fuel_cost": total_cost,
            "route_geometry": {"type": "LineString", "coordinates": route["geometry"]},
            "fuel_stops": [
                {
                    "name": s["station"].name,
                    "city": s["station"].city,
                    "state": s["station"].state,
                    "price_per_gallon": s["price_per_gallon"],
                    "mile_marker": s["mile_marker"],
                    "gallons_purchased": s["gallons"],
                    "cost": s["cost"],
                    "latitude": round(s["station"].latitude, 6),
                    "longitude": round(s["station"].longitude, 6),
                }
                for s in stops
            ],
        }
        return Response(RouteResponseSerializer(payload).data)
