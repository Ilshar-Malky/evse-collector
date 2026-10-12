"""
Collect Belgian EV charger status changes from the Eco-Movement DATEX II API.

Runs every 15 min on GitHub Actions. Each run:
  - downloads all pages of /datex2/v1/locations (status part only is kept)
  - writes only the chargers whose status changed since the previous run
      -> data/events/YYYY/MM/DD/HHMM.csv.gz        (small)
  - once per UTC day, also writes a full snapshot of every charger
      -> data/baselines/YYYY-MM-DD.csv.gz           (~1 MB)
  - remembers the run time in data/last_run.txt

How changes are detected: DATEX II `lastUpdated` is the time a charger's
status last CHANGED, so any row with lastUpdated after the previous run
(minus a 5-minute safety overlap) is a change. Duplicates from the overlap
are removed in analysis with: drop_duplicates(["evse_id", "last_updated"]).

Data: Eco-Movement / transportdata.be, CC BY 4.0
"""
import csv
import gzip
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from requests.utils import parse_header_links

BASE_URL = "https://nap-be.eco-movement.com/datex2/v1/locations"
DATA = Path(__file__).resolve().parent.parent / "data"
LAST_RUN = DATA / "last_run.txt"
OVERLAP = timedelta(minutes=5)

BASELINE_FIELDS = ["observed_at", "site_id", "station_id", "evse_id", "status",
                   "last_updated", "kwh_price_excl_vat", "minute_price_excl_vat"]
EVENT_FIELDS = ["observed_at", "evse_id", "status", "last_updated",
                "kwh_price_excl_vat", "minute_price_excl_vat"]


def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def get(url, headers):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=headers, timeout=120)
            if r.status_code == 401:
                sys.exit("401 Unauthorized - token rejected or expired.")
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if attempt == 2:
                sys.exit(f"Giving up on {url}: {e}")
            time.sleep(15 * (attempt + 1))


def fetch_rows(token, observed_at):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    next_url, n_pages = BASE_URL, 0
    while next_url:
        r = get(next_url, headers)
        n_pages += 1
        pub = r.json().get("aegiEnergyInfrastructureStatusPublication", {})
        for site in as_list(pub.get("energyInfrastructureSiteStatus")):
            site_id = site.get("reference", {}).get("idG")
            for station in as_list(site.get("energyInfrastructureStationStatus")):
                station_id = station.get("reference", {}).get("idG")
                for rp in as_list(station.get("refillPointStatus")):
                    cp = rp.get("aegiElectricChargingPointStatus", {})
                    kwh = minute = None
                    for upd in as_list(cp.get("energyRateUpdate")):
                        for p in as_list(upd.get("energyPrice")):
                            ptype = (p.get("priceType") or {}).get("value")
                            if ptype == "pricePerKWh" and kwh is None:
                                kwh = p.get("value")
                            elif ptype == "pricePerMinute" and minute is None:
                                minute = p.get("value")
                    yield {
                        "observed_at": observed_at,
                        "site_id": site_id,
                        "station_id": station_id,
                        "evse_id": cp.get("reference", {}).get("idG"),
                        "status": (cp.get("status") or {}).get("value"),
                        "last_updated": cp.get("lastUpdated"),
                        "kwh_price_excl_vat": kwh,
                        "minute_price_excl_vat": minute,
                    }
        links = parse_header_links(r.headers.get("Link", ""))
        nxt = next((l for l in links if l.get("rel") == "next"), None)
        next_url = nxt["url"] if nxt else None
        time.sleep(1)  # be polite to the API
    print(f"Fetched {n_pages} pages")


def write_gz(path, fields, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main():
    token = os.environ.get("ECO_MOVEMENT_TOKEN")
    if not token:
        sys.exit("ECO_MOVEMENT_TOKEN is not set.")

    now = datetime.now(timezone.utc).replace(microsecond=0)
    observed_at = now.isoformat().replace("+00:00", "Z")
    last_run = parse_ts(LAST_RUN.read_text().strip()) if LAST_RUN.exists() else None

    rows = list(fetch_rows(token, observed_at))
    if not rows:
        sys.exit("No status rows returned - not updating last_run.")

    # Full snapshot on the first run, and on the first run of each UTC day
    baseline_path = DATA / "baselines" / f"{now:%Y-%m-%d}.csv.gz"
    if last_run is None or not baseline_path.exists():
        write_gz(baseline_path, BASELINE_FIELDS, rows)
        print(f"Baseline: {len(rows)} chargers -> {baseline_path.name}")

    if last_run is not None:
        since = last_run - OVERLAP
        changes = [r for r in rows
                   if (t := parse_ts(r["last_updated"])) and t >= since]
        if changes:
            event_path = DATA / "events" / f"{now:%Y/%m/%d}" / f"{now:%H%M}.csv.gz"
            write_gz(event_path, EVENT_FIELDS, changes)
        print(f"Changes since {since:%Y-%m-%d %H:%M}Z: {len(changes)} of {len(rows)}")

    LAST_RUN.parent.mkdir(parents=True, exist_ok=True)
    LAST_RUN.write_text(observed_at + "\n")


if __name__ == "__main__":
    main()
