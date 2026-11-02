from rest_framework import serializers


class RouteRequestSerializer(serializers.Serializer):
    start = serializers.CharField(max_length=200, help_text="Starting location in the USA, e.g. `Chicago, IL`.")
    finish = serializers.CharField(max_length=200, help_text="Destination in the USA, e.g. `Dallas, TX`.")


class FuelStopSerializer(serializers.Serializer):
    name = serializers.CharField(help_text="Truck stop name from the fuel price list.")
    city = serializers.CharField()
    state = serializers.CharField(help_text="Two-letter US state code.")
    price_per_gallon = serializers.DecimalField(
        max_digits=6, decimal_places=3, coerce_to_string=False, help_text="Retail diesel price, USD."
    )
    mile_marker = serializers.FloatField(help_text="Distance from the start along the route, in miles.")
    gallons_purchased = serializers.DecimalField(max_digits=6, decimal_places=2, coerce_to_string=False)
    cost = serializers.DecimalField(
        max_digits=8, decimal_places=2, coerce_to_string=False, help_text="`gallons_purchased` x `price_per_gallon`, USD."
    )
    latitude = serializers.FloatField()
    longitude = serializers.FloatField()


class LineStringSerializer(serializers.Serializer):
    type = serializers.ChoiceField(choices=["LineString"])
    coordinates = serializers.ListField(
        child=serializers.ListField(child=serializers.FloatField(), min_length=2, max_length=2),
        help_text="GeoJSON order: `[longitude, latitude]`.",
    )


class RouteResponseSerializer(serializers.Serializer):
    total_distance_miles = serializers.FloatField(help_text="Driving distance reported by the router.")
    total_fuel_cost = serializers.DecimalField(
        max_digits=10, decimal_places=2, coerce_to_string=False, help_text="Sum of all stop costs, USD."
    )
    route_geometry = LineStringSerializer(help_text="The driving route as a GeoJSON LineString.")
    fuel_stops = FuelStopSerializer(many=True, help_text="Stations where fuel is purchased, in driving order.")


class ErrorSerializer(serializers.Serializer):
    error = serializers.CharField()
