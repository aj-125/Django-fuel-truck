from decimal import ROUND_HALF_UP, Decimal

VEHICLE_RANGE_MILES = 500
MILES_PER_GALLON = 10
_EPSILON_MILES = 1e-6


class InfeasibleRoute(Exception):
    """Some stretch of the route has no fuel station within the vehicle's range."""


def plan_fuel_stops(stations_on_route, total_miles):
    """Minimum-cost refuelling plan (the classic greedy for the gas station problem).

    stations_on_route: [(station, mile_marker), ...] sorted by mile_marker.
    The vehicle leaves the origin with a full tank (nothing can be bought there).
    At each station:
      * if a cheaper station is within range, buy only enough to reach the
        nearest one;
      * otherwise, if the destination is within range, buy only enough to finish;
      * otherwise fill the tank and continue to the cheapest station in range.
    This never buys fuel that goes unused, and every gallon is bought at the
    cheapest price available for the stretch it powers.

    Returns (stops, total_cost) where stops only include stations where fuel was
    actually purchased.
    """
    stations = [(mile, station) for station, mile in stations_on_route if mile < total_miles]
    position, fuel = 0.0, float(VEHICLE_RANGE_MILES)  # fuel is measured in miles of range
    here = None  # index into `stations`; None means the origin
    stops, total_cost = [], Decimal("0")

    while True:
        here_price = stations[here][1].price_per_gallon if here is not None else None
        reach = position + VEHICLE_RANGE_MILES
        first = 0 if here is None else here + 1
        in_range = []
        for j in range(first, len(stations)):
            if stations[j][0] > reach:
                break
            in_range.append(j)

        cheaper = next(
            (j for j in in_range if here_price is None or stations[j][1].price_per_gallon < here_price),
            None,
        )
        if cheaper is not None:
            next_stop, target = cheaper, stations[cheaper][0]
        elif total_miles <= reach:
            next_stop, target = None, total_miles
        elif in_range:
            # On a price tie, the farther station is equally cheap and saves a stop.
            next_stop = min(in_range, key=lambda j: (stations[j][1].price_per_gallon, -stations[j][0]))
            target = reach
        else:
            raise InfeasibleRoute(
                f"No fuel station within {VEHICLE_RANGE_MILES} miles of mile {position:.1f}; "
                "the route can't be completed with the available station data."
            )

        to_buy = (target - position) - fuel
        if to_buy > _EPSILON_MILES:  # never true at the origin: target <= reach and the tank is full
            station = stations[here][1]
            # Price at the quoted 3-decimal pump price, so cost == gallons x price exactly as reported.
            price = station.price_per_gallon.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
            gallons = Decimal(str(round(to_buy / MILES_PER_GALLON, 2)))
            cost = (gallons * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            stops.append({
                "station": station, "price_per_gallon": price,
                "mile_marker": round(position, 1), "gallons": gallons, "cost": cost,
            })
            total_cost += cost
            fuel += to_buy

        if next_stop is None:
            return stops, total_cost
        fuel -= stations[next_stop][0] - position
        position, here = stations[next_stop][0], next_stop
