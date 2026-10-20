from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField()
    finish = serializers.CharField()


class FuelStopSerializer(serializers.Serializer):
    name = serializers.CharField()
    city = serializers.CharField()
    state = serializers.CharField()
    price_per_gallon = serializers.DecimalField(max_digits=6, decimal_places=4)
    mile_marker = serializers.FloatField()
    gallons_purchased = serializers.FloatField()
    cost = serializers.FloatField()
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class RouteResponseSerializer(serializers.Serializer):
    total_distance_miles = serializers.FloatField()
    total_fuel_cost = serializers.FloatField()
    route_geometry = serializers.JSONField()
    fuel_stops = FuelStopSerializer(many=True)
