from functools import lru_cache

import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving"
METERS_PER_MILE = 1609.344


class LocationNotFound(Exception):
    """The geocoder returned no match for the given address."""


class RouteNotFound(Exception):
    """OSRM could not build a driving route between the two points."""


class UpstreamUnavailable(Exception):
    """A map/routing provider timed out, errored, or was unreachable."""


@lru_cache(maxsize=256)
def geocode_address(address):
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": address, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": "fuel-route-assessment"},
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
    except requests.RequestException as e:
        raise UpstreamUnavailable(f"Geocoding service unavailable: {e}") from e
    if not results:
        raise LocationNotFound(f"Could not find a US location matching: {address}")
    return float(results[0]["lat"]), float(results[0]["lon"])


def get_route(start_lat, start_lon, end_lat, end_lon):
    url = f"{OSRM_BASE_URL}/{start_lon},{start_lat};{end_lon},{end_lat}"
    try:
        # "simplified" keeps the route's shape at ~1/400th the payload of "full";
        # the distance below is OSRM's own exact figure either way.
        resp = requests.get(url, params={"overview": "simplified", "geometries": "geojson"}, timeout=15)
        if resp.status_code >= 500:
            resp.raise_for_status()
        data = resp.json()  # OSRM reports NoRoute etc. as HTTP 400 with a JSON body
    except requests.RequestException as e:
        raise UpstreamUnavailable(f"Routing service unavailable: {e}") from e
    if data.get("code") != "Ok" or not data.get("routes"):
        raise RouteNotFound(f"No driving route found: {data.get('message', data.get('code'))}")
    route = data["routes"][0]
    return {
        "distance_miles": route["distance"] / METERS_PER_MILE,
        "geometry": route["geometry"]["coordinates"],  # [[lon, lat], ...]
    }
