"""Offline US place lookup backed by the GeoNames ZIP gazetteer (routing/data/us_zip_codes.txt).

Rows are tab-separated: country, postal_code, place_name, state_name, state_abbr, ...,
latitude (col 9), longitude (col 10). Used both to geocode fuel stations in bulk and to
resolve request inputs like "Chicago, IL" without calling an external API.
"""
import csv
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

GAZETTEER_PATH = Path(__file__).resolve().parents[1] / "data" / "us_zip_codes.txt"
_COUNTRY_SUFFIX = re.compile(r",\s*(usa|us|united states)\s*$", re.IGNORECASE)
_ZIP = re.compile(r"^(\d{5})(-\d{4})?$")


@lru_cache(maxsize=1)
def _load():
    sums = defaultdict(lambda: [0.0, 0.0, 0])
    zips, state_names = {}, {}
    with open(GAZETTEER_PATH, newline="", encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t"):
            postal_code, city, state_name, state_abbr = row[1], row[2].strip().lower(), row[3].strip(), row[4].strip()
            lat, lon = float(row[9]), float(row[10])
            zips[postal_code] = (lat, lon)
            if state_name and state_abbr:
                state_names[state_name.lower()] = state_abbr
            entry = sums[(city, state_abbr)]
            entry[0] += lat
            entry[1] += lon
            entry[2] += 1
    # A city spans several ZIPs; average their centroids into one point.
    centroids = {key: (lat_sum / n, lon_sum / n) for key, (lat_sum, lon_sum, n) in sums.items()}
    return centroids, zips, state_names


def load_city_state_centroids():
    """{(city_lowercase, STATE_ABBR): (lat, lon)}"""
    return _load()[0]


def lookup(text):
    """Resolve "City, ST", "City, State Name" or a ZIP code to (lat, lon), or None if
    the text isn't in one of those forms or isn't in the gazetteer."""
    centroids, zips, state_names = _load()
    text = _COUNTRY_SUFFIX.sub("", text.strip())

    zip_match = _ZIP.match(text)
    if zip_match:
        return zips.get(zip_match.group(1))

    city, sep, state = text.rpartition(",")
    if not sep:
        return None
    state = state.strip()
    abbr = state.upper() if len(state) == 2 else state_names.get(state.lower())
    return centroids.get((city.strip().lower(), abbr))
