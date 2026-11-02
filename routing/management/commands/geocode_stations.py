from django.core.management.base import BaseCommand

from routing.models import FuelStation
from routing.services.gazetteer import load_city_state_centroids


class Command(BaseCommand):
    help = "Geocode FuelStation rows via the free offline GeoNames city/state gazetteer (no API calls)."

    def handle(self, *args, **options):
        centroids = load_city_state_centroids()
        stations = list(FuelStation.objects.filter(latitude__isnull=True))
        total = len(stations)

        matched = []
        for station in stations:
            coords = centroids.get((station.city.lower(), station.state))
            if coords:
                station.latitude, station.longitude = coords
                matched.append(station)
        FuelStation.objects.bulk_update(matched, ["latitude", "longitude"], batch_size=500)

        self.stdout.write(self.style.SUCCESS(f"Geocoded {len(matched)}/{total} stations."))
        if len(matched) < total:
            self.stdout.write(f"{total - len(matched)} stations had no exact city/state match in the gazetteer.")
