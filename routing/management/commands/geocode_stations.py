import csv
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand

from routing.models import FuelStation

GAZETTEER_PATH = Path(__file__).resolve().parents[3] / "routing" / "data" / "us_zip_codes.txt"


def load_city_state_centroids():
    """GeoNames US postal-code gazetteer: one row per ZIP code, columns are
    tab-separated (country, postal_code, place_name, admin_name1, admin_code1
    [state abbr], ..., latitude, longitude, accuracy). Average all ZIP centroids
    sharing a (city, state) into a single point — plenty precise for routing."""
    sums = defaultdict(lambda: [0.0, 0.0, 0])
    with open(GAZETTEER_PATH, newline="", encoding="utf-8") as f:
        for row in csv.reader(f, delimiter="\t"):
            city, state_abbr, lat, lon = row[2].strip().lower(), row[4].strip(), row[9], row[10]
            key = (city, state_abbr)
            entry = sums[key]
            entry[0] += float(lat)
            entry[1] += float(lon)
            entry[2] += 1
    return {key: (lat_sum / n, lon_sum / n) for key, (lat_sum, lon_sum, n) in sums.items()}


class Command(BaseCommand):
    help = "Geocode FuelStation rows via the free offline GeoNames city/state gazetteer (no API calls)."

    def handle(self, *args, **options):
        centroids = load_city_state_centroids()
        stations = FuelStation.objects.filter(latitude__isnull=True)
        total = stations.count()

        matched = 0
        for station in stations.iterator():
            coords = centroids.get((station.city.strip().lower(), station.state.strip()))
            if coords:
                station.latitude, station.longitude = coords
                station.save(update_fields=["latitude", "longitude"])
                matched += 1

        self.stdout.write(self.style.SUCCESS(f"Geocoded {matched}/{total} stations."))
        if matched < total:
            self.stdout.write(f"{total - matched} stations had no exact city/state match in the gazetteer.")
