from decimal import Decimal

VEHICLE_RANGE_MILES = 500
MILES_PER_GALLON = 10


def plan_fuel_stops(stations_on_route, total_miles):
    """Greedy gas-station-problem solver: drive as far as the tank allows, and
    whenever a stop is forced, refuel at the cheapest station reachable within
    range. Assumes the tank starts full (no cost for the initial fill)."""
    current_mile = 0.0
    stops = []
    total_cost = Decimal("0")

    while total_miles - current_mile > VEHICLE_RANGE_MILES:
        reachable = [
            (station, mile)
            for station, mile in stations_on_route
            if current_mile < mile <= current_mile + VEHICLE_RANGE_MILES
        ]
        if not reachable:
            raise ValueError(
                f"No fuel station found within {VEHICLE_RANGE_MILES} miles of mile "
                f"{round(current_mile, 1)} — route is infeasible with the available data."
            )

        station, mile = min(reachable, key=lambda pair: pair[0].price_per_gallon)
        distance_traveled = mile - current_mile
        gallons = round(distance_traveled / MILES_PER_GALLON, 2)
        cost = round(Decimal(str(gallons)) * station.price_per_gallon, 2)

        stops.append({
            "station": station,
            "mile_marker": round(mile, 1),
            "gallons": gallons,
            "cost": cost,
        })
        total_cost += cost
        current_mile = mile

    return stops, round(total_cost, 2)
