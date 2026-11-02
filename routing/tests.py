import random
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

import requests
from django.contrib.auth.models import User
from django.test import Client, SimpleTestCase, TestCase

from routing.models import FuelStation
from routing.services import geometry, planner, route_client
from routing.services.planner import VEHICLE_RANGE_MILES, InfeasibleRoute, plan_fuel_stops


def station(price):
    return SimpleNamespace(price_per_gallon=Decimal(str(price)))


def simulate_tank(stops, total_miles):
    """Replays a plan and returns the lowest and highest fuel levels (in miles of range)."""
    fuel, position, low, high = float(VEHICLE_RANGE_MILES), 0.0, float(VEHICLE_RANGE_MILES), 0.0
    for stop in stops:
        fuel -= stop["mile_marker"] - position
        low = min(low, fuel)
        fuel += float(stop["gallons"]) * planner.MILES_PER_GALLON
        high = max(high, fuel)
        position = stop["mile_marker"]
    fuel -= total_miles - position
    return min(low, fuel), high


class PlannerTests(SimpleTestCase):
    def test_trip_within_range_needs_no_stops(self):
        stops, cost = plan_fuel_stops([(station(3.0), 100)], total_miles=450)
        self.assertEqual(stops, [])
        self.assertEqual(cost, Decimal("0"))

    def test_buys_just_enough_to_reach_a_cheaper_station(self):
        # A "fill up at the cheapest reachable station" heuristic pays $130 here:
        # it fills 50 gal at Z even though only 40 are needed to finish.
        x, y, z = station(3.0), station(4.0), station(2.0)
        stops, cost = plan_fuel_stops([(x, 100), (y, 500), (z, 600)], total_miles=1000)

        self.assertEqual(cost, Decimal("110.00"))
        self.assertEqual([(s["station"], s["gallons"]) for s in stops], [(x, Decimal("10")), (z, Decimal("40"))])

    def test_skips_expensive_station_when_a_cheaper_one_is_reachable(self):
        a, b = station(4.0), station(3.0)
        stops, cost = plan_fuel_stops([(a, 100), (b, 400)], total_miles=800)

        self.assertEqual([s["station"] for s in stops], [b])
        self.assertEqual(cost, Decimal("90.00"))

    def test_cost_matches_the_reported_price_and_gallons(self):
        # Stored prices carry 4+ decimals (3.2823); the API reports 3 (3.282).
        stops, _ = plan_fuel_stops([(station(3.2823), 300)], total_miles=704.3)

        stop = stops[0]
        self.assertEqual(stop["price_per_gallon"], Decimal("3.282"))
        self.assertEqual(stop["gallons"], Decimal("20.43"))
        self.assertEqual(stop["cost"], Decimal("67.05"))  # 20.43 x 3.282, not 20.43 x 3.2823 = 67.06

    def test_raises_when_a_gap_exceeds_vehicle_range(self):
        with self.assertRaises(InfeasibleRoute):
            plan_fuel_stops([(station(3.0), 400), (station(3.0), 950)], total_miles=1200)

    def test_random_plans_are_feasible_and_waste_no_fuel(self):
        rng = random.Random(42)
        for _ in range(50):
            total_miles = rng.uniform(600, 3000)
            mile, stations = 0.0, []
            while mile < total_miles:
                mile += rng.uniform(10, 120)
                stations.append((station(round(rng.uniform(2.8, 4.5), 3)), mile))

            stops, cost = plan_fuel_stops(stations, total_miles)

            low, high = simulate_tank(stops, total_miles)
            self.assertGreaterEqual(low, -0.5, "ran out of fuel")
            self.assertLessEqual(high, VEHICLE_RANGE_MILES + 0.5, "overfilled the tank")
            # Starts full, arrives empty: exactly (distance - range) miles of fuel are bought.
            bought = sum(float(s["gallons"]) for s in stops)
            self.assertAlmostEqual(bought, (total_miles - VEHICLE_RANGE_MILES) / 10, delta=0.01 * len(stops) + 0.06)
            self.assertEqual(cost, sum(s["cost"] for s in stops))


class GeometryTests(TestCase):
    def test_haversine_one_degree_of_longitude_at_equator(self):
        self.assertAlmostEqual(geometry.haversine_miles(0, 0, 0, 1), 69.09, places=1)

    def test_sample_route_interpolates_inside_long_segments(self):
        samples, total = geometry.sample_route([[0, 0], [1.447, 0]])  # one ~100 mile segment

        self.assertAlmostEqual(total, 100, delta=0.5)
        gaps = [b[2] - a[2] for a, b in zip(samples, samples[1:])]
        self.assertTrue(all(g <= 5 + 1e-9 for g in gaps))
        self.assertEqual(len(samples), 21)  # mile 0, 5, ..., 95, plus the endpoint at ~99.98

    def test_finds_station_east_of_route_at_northern_latitude(self):
        # 14 miles east of a north-south route at 48.9N is ~0.31 deg of longitude.
        # These coordinates land two cells apart on the old 0.25 deg grid, so it
        # silently dropped this station; the 0.5 deg grid puts them in one cell.
        nearby = FuelStation.objects.create(
            opis_id=1, name="Near", city="X", state="ND", price_per_gallon=3, latitude=48.9, longitude=-99.8725
        )
        samples, _ = geometry.sample_route([[-100.1805, 47.0], [-100.1805, 49.0]])

        self.assertIn(nearby, [s for s, _ in geometry.stations_along_route(samples)])

    def test_grid_lookup_matches_brute_force(self):
        rng = random.Random(7)
        path = [[-122 + i, 48.5 + rng.uniform(-1, 1)] for i in range(25)]
        FuelStation.objects.bulk_create(
            FuelStation(
                opis_id=i, name=f"S{i}", city="X", state="WA", price_per_gallon=3,
                latitude=rng.uniform(46.5, 50.5), longitude=rng.uniform(-122.5, -97.5),
            )
            for i in range(800)
        )
        samples, _ = geometry.sample_route(path)

        def brute_force():
            out = []
            for s in FuelStation.objects.all():
                d, mile = min((geometry.haversine_miles(s.latitude, s.longitude, lat, lon), m) for lat, lon, m in samples)
                if d <= geometry.STATION_SEARCH_RADIUS_MILES:
                    out.append((s.opis_id, mile))
            return sorted(out)

        grid = sorted((s.opis_id, mile) for s, mile in geometry.stations_along_route(samples))
        self.assertGreater(len(grid), 50)
        self.assertEqual(grid, brute_force())


@patch("routing.services.route_client.get_route")
@patch("routing.services.route_client.geocode_address", return_value=(40.0, -100.0))
class RouteApiTests(TestCase):
    url = "/api/route/"
    body = {"start": "Start, NE", "finish": "Finish, OH"}

    @staticmethod
    def straight_route(miles):
        # Due east along 40N; 1 degree of longitude there is ~53 miles.
        degrees = miles / 52.99
        return {"distance_miles": miles, "geometry": [[-100.0, 40.0], [-100.0 + degrees, 40.0]]}

    def add_stations(self, every_degrees=1.0, count=20):
        for i in range(count):
            FuelStation.objects.create(
                opis_id=i, name=f"Stop {i}", city="Town", state="KS", price_per_gallon=Decimal("3.0") + Decimal(i % 4) / 10,
                latitude=40.0, longitude=-100.0 + (i + 1) * every_degrees,
            )

    def test_plans_a_long_route(self, _geocode, get_route):
        get_route.return_value = self.straight_route(1000)
        self.add_stations()

        resp = self.client.post(self.url, self.body, content_type="application/json")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["total_distance_miles"], 1000)
        self.assertEqual(data["route_geometry"]["type"], "LineString")
        self.assertTrue(data["fuel_stops"])
        stop = data["fuel_stops"][0]
        for money_field in ("price_per_gallon", "cost", "gallons_purchased"):
            self.assertIsInstance(stop[money_field], float, f"{money_field} should be a JSON number")
        self.assertAlmostEqual(data["total_fuel_cost"], sum(s["cost"] for s in data["fuel_stops"]), places=2)

    def test_short_route_has_no_stops(self, _geocode, get_route):
        get_route.return_value = self.straight_route(200)

        resp = self.client.post(self.url, self.body, content_type="application/json")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["fuel_stops"], [])
        self.assertEqual(resp.json()["total_fuel_cost"], 0)

    def test_missing_fields_returns_400_with_field_errors(self, _geocode, _get_route):
        resp = self.client.post(self.url, {}, content_type="application/json")

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(set(resp.json()), {"start", "finish"})

    def test_unknown_location_returns_400(self, geocode, _get_route):
        geocode.side_effect = route_client.LocationNotFound("Could not find a US location matching: Atlantis")

        resp = self.client.post(self.url, self.body, content_type="application/json")

        self.assertEqual(resp.status_code, 400)
        self.assertIn("Atlantis", resp.json()["error"])

    def test_no_station_in_range_returns_422(self, _geocode, get_route):
        get_route.return_value = self.straight_route(1000)  # no stations in the DB

        resp = self.client.post(self.url, self.body, content_type="application/json")

        self.assertEqual(resp.status_code, 422)
        self.assertIn("error", resp.json())

    def test_upstream_outage_returns_502_not_500(self, _geocode, get_route):
        get_route.side_effect = route_client.UpstreamUnavailable("Routing service unavailable: timed out")

        with self.assertLogs("routing.views", level="WARNING"):
            resp = self.client.post(self.url, self.body, content_type="application/json")

        self.assertEqual(resp.status_code, 502)
        self.assertEqual(resp["Content-Type"], "application/json")

    def test_logged_in_browser_is_not_blocked_by_csrf(self, _geocode, get_route):
        get_route.return_value = self.straight_route(200)
        browser = Client(enforce_csrf_checks=True)
        browser.force_login(User.objects.create_user("reviewer"))

        resp = browser.post(self.url, self.body, content_type="application/json")

        self.assertEqual(resp.status_code, 200)


class RouteClientTests(SimpleTestCase):
    @patch("routing.services.route_client.requests.get", side_effect=requests.ConnectionError("down"))
    def test_network_failure_becomes_upstream_unavailable(self, _get):
        with self.assertRaises(route_client.UpstreamUnavailable):
            route_client.get_route(40, -100, 41, -90)

    @patch("routing.services.route_client.requests.get")
    def test_osrm_no_route_is_not_treated_as_an_outage(self, get):
        get.return_value.status_code = 400  # OSRM reports NoRoute as HTTP 400 with a JSON body
        get.return_value.json.return_value = {"code": "NoRoute", "message": "Impossible route between points"}

        with self.assertRaises(route_client.RouteNotFound):
            route_client.get_route(21.3, -157.8, 41.8, -87.6)


class PageTests(TestCase):
    def test_map_page_docs_and_schema_are_served(self):
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/api/docs/").status_code, 200)
        schema = self.client.get("/api/schema/")
        self.assertEqual(schema.status_code, 200)
        self.assertIn(b"/api/route/", schema.content)
