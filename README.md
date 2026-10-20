# Fuel Route API

Given a start and finish location in the USA, returns the driving route plus the
cheapest fuel stops needed along the way, assuming a vehicle with a 500-mile range
and 10 MPG. Built with Django 6.1 + Django REST Framework.

## How it works

1. **Geocode** the start/finish addresses (Nominatim, free, 2 calls).
2. **Route** between them (OSRM public demo server, free, 1 call).
3. **Match** fuel stations from the provided price list to the route (all local —
   no further external calls).
4. **Plan stops**: greedy algorithm — drive as far as the tank allows, and
   whenever a stop is forced, refuel at the cheapest station reachable within
   range, filling back up to a full tank each time. Assumes the tank starts full
   (no cost for the initial fill).

Total external calls per request: 3 (2 geocode + 1 route), regardless of trip
length.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py import_fuel_prices   # loads routing/data/fuel-prices-for-be-assessment.csv
python manage.py geocode_stations     # adds lat/lon to each station, offline, ~20s

python manage.py runserver
```

## API

`POST /api/route/`

```json
{
  "start": "Chicago, IL",
  "finish": "Dallas, TX"
}
```

Returns total distance, total fuel cost, the route geometry (GeoJSON), and the
list of fuel stops (name, location, price, gallons purchased, cost).

## Map

A Leaflet-based visualization is at `/api/map/` — enter a start/finish and it
draws the route with fuel stop markers (click a marker for price/gallons/cost).

## Data notes

- The fuel price CSV has no coordinates, only city/state and a free-text highway
  description (e.g. `I-44, EXIT 283 & US-69`). Station coordinates are therefore
  city-level, not exit-level — a reasonable trade-off for a route-planning
  exercise, called out here rather than hidden.
- Station geocoding uses the free [GeoNames US ZIP gazetteer](https://download.geonames.org/export/zip/US.zip)
  (`routing/data/us_zip_codes.txt`), averaged per city/state, matched entirely
  offline. This is deliberate: Nominatim's usage policy prohibits bulk/systematic
  geocoding, so running ~6,600 lookups against it risks an IP ban that would also
  break the live per-request geocoding. 6,620 of 6,626 stations (99.9%) match
  exactly; the rest are minor name-formatting mismatches (e.g. `Winston Salem` vs
  `Winston-Salem`).
- Duplicate rows per truck stop (same ID, different prices) are deduped at import
  time, keeping the cheapest price per station. Non-US rows (Canada) are dropped.
