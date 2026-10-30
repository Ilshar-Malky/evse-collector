"""
Static data of every Belgian EV charger (location, operator, power, connector).

Same API and token as collect_changes.py: the /locations response contains a
static part (aegiEnergyInfrastructureTablePublication) next to the status part.
This script keeps the static part, one row per charging point (EVSE), and writes:

    data/static/chargers_YYYY-MM-DD.csv.gz

Runs on GitHub Actions (workflow "Static chargers", once a week + by hand), so no
token is needed on your PC. Join with the status data on evse_id.

Data: Eco-Movement / transportdata.be, CC BY 4.0
"""
import csv
import gzip
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from requests.utils import parse_header_links

BASE_URL = "https://nap-be.eco-movement.com/datex2/v1/locations"
DATA = Path(__file__).resolve().parent.parent / "data"

FIELDS = ["snapshot_date", "site_id", "station_id", "evse_id", "operator",
          "street", "postcode", "city", "latitude", "longitude",
          "current_type", "max_power_kw", "station_max_power_kw",
          "n_connectors", "connector_types", "auth_methods"]


def as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def text(multilingual):
    """DATEX II multilingual string -> first value."""
    for v in as_list((multilingual or {}).get("values")):
        if v.get("value"):
            return v["value"]
    return None


def kw(watts):
    try:
        return round(float(watts) / 1000, 1)
    except (TypeError, ValueError):
        return None


def org_name(obj):
    return text(((obj or {}).get("energyDistributor") or {}).get("afacAnOrganisation", {}).get("name"))


def rows_from_page(payload, snapshot_date):
    table_pub = payload.get("aegiEnergyInfrastructureTablePublication", {})
    for table in as_list(table_pub.get("energyInfrastructureTable")):
        for site in as_list(table.get("energyInfrastructureSite")):
            entrance = next(iter(as_list(site.get("entrance"))), {})
            loc = entrance.get("locAreaLocation", {})
            coords = loc.get("coordinatesForDisplay", {})
            address = (loc.get("locLocationExtensionG", {})
                          .get("FacilityLocation", {}).get("address", {}))
            street = next((text(line.get("text")) for line in as_list(address.get("addressLine"))
                           if (line.get("type") or {}).get("value") == "street"), None)
            site_operator = org_name(site)
            for station in as_list(site.get("energyInfrastructureStation")):
                operator = org_name(station) or site_operator
                auth = ",".join(sorted({a.get("value") for a in
                                        as_list(station.get("authenticationAndIdentificationMethods"))
                                        if a.get("value")}))
                for rp in as_list(station.get("refillPoint")):
                    cp = rp.get("aegiElectricChargingPoint", {})
                    connectors = as_list(cp.get("connector"))
                    powers = [p for p in as_list(cp.get("availableChargingPower")) if p is not None]
                    powers += [c.get("maxPowerAtSocket") for c in connectors if c.get("maxPowerAtSocket")]
                    yield {
                        "snapshot_date": snapshot_date,
                        "site_id": site.get("idG"),
                        "station_id": station.get("idG"),
                        "evse_id": cp.get("idG"),
                        "operator": operator,
                        "street": street,
                        "postcode": address.get("postcode"),
                        "city": text(address.get("city")),
                        "latitude": coords.get("latitude"),
                        "longitude": coords.get("longitude"),
                        "current_type": (cp.get("currentType") or {}).get("value"),
                        "max_power_kw": kw(max(powers)) if powers else None,
                        "station_max_power_kw": kw(station.get("totalMaximumPower")),
                        "n_connectors": cp.get("numberOfConnectors") or len(connectors) or None,
                        "connector_types": ",".join(sorted({(c.get("connectorType") or {}).get("value")
                                                            for c in connectors
                                                            if (c.get("connectorType") or {}).get("value")})),
                        "auth_methods": auth,
                    }


def fetch_pages(token):
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    next_url, n = BASE_URL, 0
    while next_url:
        for attempt in range(3):
            try:
                r = requests.get(next_url, headers=headers, timeout=180)
                r.raise_for_status()
                break
            except requests.RequestException as e:
                if attempt == 2:
                    sys.exit(f"Giving up on {next_url}: {e}")
                time.sleep(15 * (attempt + 1))
        n += 1
        yield r.json()
        links = parse_header_links(r.headers.get("Link", ""))
        nxt = next((l for l in links if l.get("rel") == "next"), None)
        next_url = nxt["url"] if nxt else None
        time.sleep(1)
    print(f"Fetched {n} pages")


def main():
    # Offline test: python collector/fetch_static.py some_page.json
    if len(sys.argv) > 1:
        opener = gzip.open if sys.argv[1].endswith(".gz") else open
        with opener(sys.argv[1], "rt", encoding="utf-8") as f:
            pages = [json.load(f)]
    else:
        token = os.environ.get("ECO_MOVEMENT_TOKEN") or sys.exit("ECO_MOVEMENT_TOKEN is not set.")
        pages = fetch_pages(token)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows, seen = [], set()
    for page in pages:
        for row in rows_from_page(page, today):
            if row["evse_id"] and row["evse_id"] not in seen:
                seen.add(row["evse_id"])
                rows.append(row)
    if not rows:
        sys.exit("No chargers found in the static part.")

    path = DATA / "static" / f"chargers_{today}.csv.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    with_coords = sum(1 for r in rows if r["latitude"] is not None)
    with_pc = sum(1 for r in rows if r["postcode"])
    print(f"{len(rows)} chargers -> {path.name} | coordinates {with_coords/len(rows):.0%}, "
          f"postcode {with_pc/len(rows):.0%}")


if __name__ == "__main__":
    main()
