import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from routing.models import FuelStation

CSV_PATH = Path(__file__).resolve().parents[3] / "routing" / "data" / "fuel-prices-for-be-assessment.csv"

US_STATES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA", "HI", "ID", "IL", "IN", "IA",
    "KS", "KY", "LA", "ME", "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VT",
    "VA", "WA", "WV", "WI", "WY", "DC",
}


class Command(BaseCommand):
    help = "Import fuel prices CSV, keeping the cheapest price per truckstop ID and dropping non-US rows."

    def handle(self, *args, **options):
        cheapest = {}
        with open(CSV_PATH, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                state = row["State"].strip()
                if state not in US_STATES:
                    continue
                opis_id = int(row["OPIS Truckstop ID"])
                price = float(row["Retail Price"])
                existing = cheapest.get(opis_id)
                if existing is None or price < existing["price"]:
                    cheapest[opis_id] = {
                        "name": row["Truckstop Name"].strip(),
                        "city": row["City"].strip(),
                        "state": state,
                        "price": price,
                    }

        FuelStation.objects.all().delete()
        FuelStation.objects.bulk_create(
            FuelStation(
                opis_id=opis_id,
                name=data["name"],
                city=data["city"],
                state=data["state"],
                price_per_gallon=data["price"],
            )
            for opis_id, data in cheapest.items()
        )
        self.stdout.write(self.style.SUCCESS(f"Imported {len(cheapest)} US fuel stations."))
