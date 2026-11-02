from collections import defaultdict
from math import radians, sin, cos, sqrt, atan2

from routing.models import FuelStation

EARTH_RADIUS_MILES = 3958.8
STATION_SEARCH_RADIUS_MILES = 15
GRID_CELL_DEGREES = 0.25  # ~17 miles; a 3x3 block of cells comfortably covers the 15-mile search radius


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * atan2(sqrt(a), sqrt(1 - a))


def sample_route(coordinates, step_miles=5):
    """coordinates: [[lon, lat], ...] from OSRM. Returns (samples, total_miles) where
    samples is a list of (lat, lon, cumulative_miles) spaced ~step_miles apart."""
    first_lon, first_lat = coordinates[0]
    samples = [(first_lat, first_lon, 0.0)]
    cumulative = 0.0
    last_lat, last_lon = first_lat, first_lon

    for lon, lat in coordinates[1:]:
        cumulative += haversine_miles(last_lat, last_lon, lat, lon)
        if cumulative - samples[-1][2] >= step_miles:
            samples.append((lat, lon, cumulative))
        last_lat, last_lon = lat, lon

    if samples[-1][2] != cumulative:
        samples.append((last_lat, last_lon, cumulative))
    return samples, cumulative


def _grid_cell(lat, lon):
    return round(lat / GRID_CELL_DEGREES), round(lon / GRID_CELL_DEGREES)


def _build_sample_grid(samples):
    grid = defaultdict(list)
    for lat, lon, mile in samples:
        grid[_grid_cell(lat, lon)].append((lat, lon, mile))
    return grid


def _nearby_samples(grid, lat, lon):
    cell_lat, cell_lon = _grid_cell(lat, lon)
    for dlat in (-1, 0, 1):
        for dlon in (-1, 0, 1):
            yield from grid.get((cell_lat + dlat, cell_lon + dlon), ())


def stations_along_route(samples, max_distance_miles=STATION_SEARCH_RADIUS_MILES):
    """Returns [(station, mile_marker), ...] sorted by mile_marker, one entry per
    station whose nearest sampled route point is within max_distance_miles.

    Brute force would be O(stations x samples) haversine calls — with a few
    hundred candidate stations and a few hundred samples on a long route, that's
    tens of thousands of trig calls and was the dominant cost of the whole
    request. Bucketing samples into a lat/lon grid and only checking a station's
    own cell plus its 8 neighbors cuts the inner loop from "every sample" to
    "the handful of samples actually nearby"."""
    lats = [lat for lat, _, _ in samples]
    lons = [lon for _, lon, _ in samples]
    pad = 1.0  # degrees of padding so the bounding-box prefilter doesn't clip edge stations
    candidates = FuelStation.objects.filter(
        latitude__isnull=False,
        latitude__gte=min(lats) - pad,
        latitude__lte=max(lats) + pad,
        longitude__gte=min(lons) - pad,
        longitude__lte=max(lons) + pad,
    )

    grid = _build_sample_grid(samples)
    results = []
    for station in candidates:
        best_distance, best_mile = None, None
        for lat, lon, mile in _nearby_samples(grid, station.latitude, station.longitude):
            d = haversine_miles(station.latitude, station.longitude, lat, lon)
            if best_distance is None or d < best_distance:
                best_distance, best_mile = d, mile
        if best_distance is not None and best_distance <= max_distance_miles:
            results.append((station, best_mile))

    results.sort(key=lambda pair: pair[1])
    return results
