import requests

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_BASE_URL = "http://router.project-osrm.org/route/v1/driving"


def geocode_address(address):
    resp = requests.get(
        NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1, "countrycodes": "us"},
        headers={"User-Agent": "fuel-route-assessment"},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    if not results:
        raise ValueError(f"Could not find location: {address}")
    return float(results[0]["lat"]), float(results[0]["lon"])


def get_route(start_lat, start_lon, end_lat, end_lon):
    url = f"{OSRM_BASE_URL}/{start_lon},{start_lat};{end_lon},{end_lat}"
    resp = requests.get(url, params={"overview": "full", "geometries": "geojson"}, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != "Ok":
        raise ValueError(f"Routing failed: {data.get('message', data.get('code'))}")
    route = data["routes"][0]
    return {
        "distance_miles": route["distance"] / 1609.34,
        "geometry": route["geometry"]["coordinates"],  # list of [lon, lat]
    }
