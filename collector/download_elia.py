"""
Second source: Elia Open Data (Belgian electricity grid), no token needed.

Downloads quarter-hourly grid load, solar and wind production for the same period
as the charger collection. Run on your PC (re-run at the end of the project to get
the latest days):

    pip install requests
    python collector/download_elia.py 2026-10-12 2026-12-02

Output: data/elia/<name>.csv  (semicolon separated, times in UTC like the collector)

Elia sometimes renames/archives datasets, so each series has a list of candidate
dataset IDs; the first one that returns rows for the period is used, and the
script prints which one worked and its columns.
"""
import sys
from pathlib import Path

import requests

SERIES = {
    "grid_load":        ["ods003", "ods001"],   # load on the Elia grid (MW)
    "solar_production": ["ods087", "ods032"],   # photovoltaic production (MW)
    "wind_production":  ["ods086", "ods031"],   # wind production (MW)
}
BASE = "https://opendata.elia.be/api/explore/v2.1/catalog/datasets/{id}/exports/csv"
OUT = Path(__file__).resolve().parent.parent / "data" / "elia"


def try_dataset(dataset_id, start, end):
    params = {"where": f"datetime >= date'{start}' AND datetime < date'{end}'",
              "timezone": "UTC", "delimiter": ";"}
    try:
        r = requests.get(BASE.format(id=dataset_id), params=params, timeout=600)
    except requests.RequestException as e:
        print(f"  {dataset_id}: {e}")
        return None
    rows = r.content.count(b"\n") - 1
    if r.ok and rows > 0:
        return r.content
    print(f"  {dataset_id}: HTTP {r.status_code}, {max(rows, 0)} rows")
    return None


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: python collector/download_elia.py START END   (YYYY-MM-DD)")
    start, end = sys.argv[1], sys.argv[2]
    OUT.mkdir(parents=True, exist_ok=True)
    for name, candidates in SERIES.items():
        print(f"{name}:")
        for dataset_id in candidates:
            content = try_dataset(dataset_id, start, end)
            if content:
                path = OUT / f"{name}.csv"
                path.write_bytes(content)
                n_rows = content.count(b"\n") - 1
                header = content.split(b"\n", 1)[0].decode("utf-8", "replace")
                print(f"  OK {dataset_id} -> {path.name}: {n_rows} rows")
                print(f"     columns: {header}")
                break
        else:
            print(f"  FAILED: none of {candidates} returned data. Check opendata.elia.be")


if __name__ == "__main__":
    main()
