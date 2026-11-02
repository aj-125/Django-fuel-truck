# Fuel Route API

Give it a start and finish anywhere in the USA. It returns the driving route plus
the **minimum-cost** set of fuel stops for a truck with a 500-mile range at 10 MPG,
and the total fuel cost. Built with Django 6.1 and Django REST Framework.

- **Interactive map:** `http://127.0.0.1:8000/`
- **Swagger UI:** `http://127.0.0.1:8000/api/docs/`
- **OpenAPI spec:** [`docs/openapi.yaml`](docs/openapi.yaml) (also served live at `/api/schema/`)
- **Postman collection:** [`docs/postman/fuel-route-api.postman_collection.json`](docs/postman/fuel-route-api.postman_collection.json): 10 requests, 35 assertions

## Quick start

Requires Python 3.12+.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py import_fuel_prices   # load the price CSV (8,151 rows -> 6,626 US stations)
python manage.py geocode_stations     # add coordinates, offline, ~3 seconds

python manage.py runserver
```

```bash
python manage.py test routing         # 20 unit tests, ~0.5s, no network access needed
```

To test the running server end to end, import the Postman collection (Import → File) and hit **Run**, or use the CLI:

```bash
postman collection run docs/postman/fuel-route-api.postman_collection.json   # or: npx newman run <same file>
```

The collection covers the happy paths, every error status (400, 415, 422), and the business rules: costs add up,
each stop costs exactly gallons × price, no fuel is bought beyond what the trip needs, and stops come in driving order.

## API

### `POST /api/route/`

```bash
curl -X POST http://127.0.0.1:8000/api/route/ \
  -H "Content-Type: application/json" \
  -d '{"start": "Chicago, IL", "finish": "Dallas, TX"}'
```

**Request** (`application/json` only)

| Field    | Type   | Description                                  |
|----------|--------|----------------------------------------------|
| `start`  | string | Starting location in the USA, max 200 chars  |
| `finish` | string | Destination in the USA, max 200 chars        |

**Response `200`** (real output; route coordinates truncated)

```json
{
  "total_distance_miles": 966.9,
  "total_fuel_cost": 134.77,
  "route_geometry": {
    "type": "LineString",
    "coordinates": [[-87.624351, 41.875563], [-87.624983, 41.719186], [-87.866987, 41.219737]]
  },
  "fuel_stops": [
    {"name": "HUCKS FOOD & FUEL #379", "city": "Marion", "state": "IL", "price_per_gallon": 2.929,
     "mile_marker": 313.8, "gallons_purchased": 29.23, "cost": 85.61, "latitude": 37.7257, "longitude": -88.9294},
    {"name": "Quiktrip #7900", "city": "Texarkana", "state": "TX", "price_per_gallon": 2.857,
     "mile_marker": 792.3, "gallons_purchased": 1.03, "cost": 2.94, "latitude": 33.435983, "longitude": -94.078233},
    {"name": "EXTRA MILE TRUCK STOP", "city": "Hooks", "state": "TX", "price_per_gallon": 2.817,
     "mile_marker": 802.6, "gallons_purchased": 12.35, "cost": 34.79, "latitude": 33.5253, "longitude": -94.2657},
    {"name": "CADOO MILLS", "city": "Caddo Mills", "state": "TX", "price_per_gallon": 2.801,
     "mile_marker": 926.1, "gallons_purchased": 4.08, "cost": 11.43, "latitude": 33.0683, "longitude": -96.2391}
  ]
}
```

| Field                  | Description                                                              |
|------------------------|--------------------------------------------------------------------------|
| `total_distance_miles` | Driving distance as reported by the router                               |
| `total_fuel_cost`      | USD; always exactly the sum of the stops' `cost`                         |
| `route_geometry`       | GeoJSON `LineString`, coordinates in `[longitude, latitude]` order       |
| `fuel_stops[]`         | Stations where fuel is bought, in driving order. Empty for trips ≤ 500 mi |
| `mile_marker`          | Distance from the start along the route                                  |

All monetary and quantity fields are JSON numbers: prices to 3 decimal places, gallons and costs to 2.

**Errors**

| Status | When                                                         | Body                                |
|--------|--------------------------------------------------------------|-------------------------------------|
| `400`  | A field is missing, blank, or too long                       | `{"start": ["This field is required."]}` |
| `400`  | A location can't be found in the USA                         | `{"error": "..."}`                  |
| `415`  | The body isn't JSON                                          | `{"detail": "..."}`                 |
| `422`  | No drivable route, or a stretch with no station within range | `{"error": "..."}`                  |
| `502`  | The geocoding or routing provider is down or timed out       | `{"error": "..."}`                  |

## How it works

1. **Geocode** `start` and `finish` with Nominatim (2 calls, made concurrently, results cached).
2. **Route** with OSRM (1 call).
3. **Match stations** to the route locally: sample the route every 5 miles and keep stations within 15 miles of it.
4. **Plan stops** with the greedy algorithm below, using the prices already in the database.

That's **3 external calls per request, regardless of trip length**. Everything after the route call is local.

## Design decisions

### The fuel plan is provably minimum-cost
This is the classic "gas station problem". The truck leaves with a full tank. At each station:
- if a **cheaper** station is within range, buy *only enough to reach the nearest one*;
- otherwise, if the destination is within range, buy only enough to finish;
- otherwise, **fill up** and continue to the cheapest station in range.

Every gallon is bought at the cheapest price available for the stretch of road it powers, and no fuel is ever
bought that goes unused. You can verify that from the output: gallons purchased always equals
`(distance − 500) / 10`. The tests check this invariant, plus "never runs dry" and "never overfills",
across 50 randomized routes.

*Trade-off:* pure cost-minimization sometimes makes a small top-up stop, e.g. 1 gallon to reach a station
8¢ cheaper. The brief prioritizes cost, so I kept the objective pure. In a real product I'd add a fixed
per-stop cost (time is money for a trucker) to the objective.

### Station data
- The CSV repeats the same truck stop with different prices, so I keep the **cheapest price per OPIS ID** and drop non-US rows.
- The CSV has no coordinates, only city/state and free text like `I-44, EXIT 283 & US-69`, so station locations are
  **city-level, not exit-level**. That's a deliberate trade-off, and the 15-mile matching radius absorbs it.
- Stations are geocoded **offline** against the free [GeoNames US gazetteer](https://download.geonames.org/export/zip/US.zip)
  (`routing/data/us_zip_codes.txt`). I avoided Nominatim here on purpose: its usage policy forbids bulk geocoding,
  and ~6,600 lookups risk an IP ban that would also break live requests. 6,618 of 6,626 stations match. The other 8
  are spelling mismatches across just three towns (`Winston Salem` vs `Winston-Salem`, `De Forest`, `Mc Leansville`).

### Performance
Profiled per stage on a Los Angeles → New York request (2,794 miles):

| Stage                 | Before | After  | Change                                                                 |
|-----------------------|--------|--------|------------------------------------------------------------------------|
| Station matching      | 1.56s  | ~0.1s  | Brute-force O(stations × samples) → lat/lon grid; check only 3×3 neighboring cells |
| Routing call          | 1.44s  | ~0.2s  | OSRM `overview=simplified`: 53 points instead of 33,852, payload 787 KB → 2 KB |
| Geocoding (×2)        | 1.21s  | ~0.25–0.6s | Two lookups run concurrently instead of back to back, plus an LRU cache   |
| **End to end**        | **4.4s** | **~0.8–1.1s cold, ~0.3–0.4s warm** |                                          |

Correctness is protected around both optimizations:
- **Simplified geometry:** route samples are *interpolated* between the now-sparse vertices, so stations between
  vertices aren't missed. The reported distance is OSRM's exact figure, not a re-sum of the simplified line.
- **Grid lookup:** a test checks it returns the same stations as brute force on 800 random stations.

## Limitations and next steps
- **Free public services.** The OSRM demo server and Nominatim have no SLA, and Nominatim asks for ≤ 1 request/s.
  That's fine for a demo. For production I'd self-host OSRM and use a commercial geocoder.
- **City-level stations.** Exit-level accuracy would need a geocoder that understands highway exits, or a better source dataset.
- **Scale.** At 6.6k stations, a bounding-box query plus Python haversine is fast. At 100× that, I'd move matching
  into PostGIS (`ST_DWithin` on the route line).
- **Public endpoint.** There's no auth or rate limiting. The next step would be DRF throttling, to protect the upstream quotas.

## Project layout

```
config/                     Django settings and root URLs
routing/
  views.py                  POST /api/route/ and the map page
  serializers.py            Request/response contract (drives the OpenAPI spec)
  services/
    route_client.py         Nominatim + OSRM clients; maps failures to typed exceptions
    geometry.py             Route sampling and grid-indexed station matching
    planner.py              Minimum-cost fuel stop algorithm
  management/commands/      import_fuel_prices, geocode_stations
  templates/routing/map.html  Leaflet map
  tests.py                  Planner, geometry, API and client tests
docs/openapi.yaml           Generated OpenAPI 3 spec
docs/postman/               Postman collection with contract and business-rule assertions
```
