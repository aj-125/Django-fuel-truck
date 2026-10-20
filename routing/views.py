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
            start_lat, start_lon = route_client.geocode_address(req.validated_data["start"])
            end_lat, end_lon = route_client.geocode_address(req.validated_data["finish"])
            route = route_client.get_route(start_lat, start_lon, end_lat, end_lon)
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        samples, total_miles = geometry.sample_route(route["geometry"])
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
