from collections import defaultdict
from math import radians, sin, cos, sqrt, atan2

from routing.models import FuelStation

EARTH_RADIUS_MILES = 3958.8
STATION_SEARCH_RADIUS_MILES = 15
# A station's 3x3 block of cells is guaranteed to contain every sample within
# one cell-width of it, so a cell must be >= the search radius on both axes.
# Longitude degrees shrink with latitude: 0.5 deg is >= 15 mi up to ~64 N.
GRID_CELL_DEGREES = 0.5


def haversine_miles(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * atan2(sqrt(a), sqrt(1 - a))


def sample_route(coordinates, step_miles=5):
    """coordinates: [[lon, lat], ...] from OSRM. Returns (samples, total_miles) where
    samples is a list of (lat, lon, cumulative_miles) exactly step_miles apart.

    Points are interpolated *inside* segments: simplified geometry can have
    vertices 50+ miles apart, and sampling only at vertices would miss stations
    that sit right next to the road between them."""
    prev_lon, prev_lat = coordinates[0]
    samples = [(prev_lat, prev_lon, 0.0)]
    cumulative = 0.0
    next_sample_at = step_miles

    for lon, lat in coordinates[1:]:
        segment = haversine_miles(prev_lat, prev_lon, lat, lon)
        while segment > 0 and next_sample_at <= cumulative + segment:
            t = (next_sample_at - cumulative) / segment
            samples.append((prev_lat + t * (lat - prev_lat), prev_lon + t * (lon - prev_lon), next_sample_at))
            next_sample_at += step_miles
        cumulative += segment
        prev_lon, prev_lat = lon, lat

    if samples[-1][2] < cumulative:
        samples.append((prev_lat, prev_lon, cumulative))
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

    Brute force is O(stations x samples) haversine calls (~280K on a
    coast-to-coast route, 1.5s). Bucketing samples into a lat/lon grid and
    checking only a station's own cell plus its 8 neighbors gives the same
    result while touching just the samples that are actually nearby."""
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
