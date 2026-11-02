from concurrent.futures import ThreadPoolExecutor

from django.shortcuts import render
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import RouteRequestSerializer, RouteResponseSerializer
from .services import geometry, planner, route_client


def map_view(request):
    return render(request, "routing/map.html")


class RoutePlanView(APIView):
    def post(self, request):
        req = RouteRequestSerializer(data=request.data)
        req.is_valid(raise_exception=True)

        try:
            # Geocoding start/finish are independent, I/O-bound calls — run them
            # concurrently instead of waiting on one then the other.
            with ThreadPoolExecutor(max_workers=2) as executor:
                start_future = executor.submit(route_client.geocode_address, req.validated_data["start"])
                end_future = executor.submit(route_client.geocode_address, req.validated_data["finish"])
                start_lat, start_lon = start_future.result()
                end_lat, end_lon = end_future.result()
            route = route_client.get_route(start_lat, start_lon, end_lat, end_lon)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        samples, geometry_miles = geometry.sample_route(route["geometry"])
        # OSRM's own distance is always exact; the geometry (now simplified, for
        # speed) is only used for shape/matching, so rescale its cumulative mile
        # markers to agree with the authoritative total.
        total_miles = route["distance_miles"]
        scale = total_miles / geometry_miles if geometry_miles else 1
        samples = [(lat, lon, mile * scale) for lat, lon, mile in samples]
        stations_on_route = geometry.stations_along_route(samples)

        try:
            stops, total_cost = planner.plan_fuel_stops(stations_on_route, total_miles)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        payload = {
            "total_distance_miles": round(total_miles, 1),
            "total_fuel_cost": float(total_cost),
            "route_geometry": {"type": "LineString", "coordinates": route["geometry"]},
            "fuel_stops": [
                {
                    "name": s["station"].name,
                    "city": s["station"].city,
                    "state": s["station"].state,
                    "price_per_gallon": s["station"].price_per_gallon,
                    "mile_marker": s["mile_marker"],
                    "gallons_purchased": s["gallons"],
                    "cost": s["cost"],
                    "latitude": s["station"].latitude,
                    "longitude": s["station"].longitude,
                }
                for s in stops
            ],
        }
        return Response(RouteResponseSerializer(payload).data)
