"""
Second source: Elia Open Data (Belgian electricity grid), no token needed.

Downloads quarter-hourly grid load, solar and wind production for the same period
as the charger collection. Run on your PC (re-run at the end of the project to get
the latest days):

    python collector/download_elia.py 2026-10-12 2026-12-02

Output: data/elia/<name>.csv  (semicolon separated, times in UTC like the collector)

Elia splits each series into a HISTORICAL dataset (complete, but published with a
delay of a few days) and a NEAR-REAL-TIME dataset (only the last days + forecasts).
This script downloads both, keeps only the requested period, and merges them:
for each quarter-hour the row with a measured value wins. At the end it prints the
covered period and the share of rows that have a measured value.
"""
import io
import sys
from pathlib import Path

import pandas as pd
import requests

SERIES = {
    #  name               candidate dataset IDs (historical first, then near-real-time)
    "grid_load":        ["ods003", "ods001"],
    "solar_production": ["ods032", "ods087"],
    "wind_production":  ["ods031", "ods086"],
}
VALUE_COLUMNS = ["eliagridload", "measured", "realtime"]          # measured values, if present
KEY_COLUMNS = ["datetime", "region", "offshoreonshore", "gridconnectiontype"]
BASE = "https://opendata.elia.be/api/explore/v2.1/catalog/datasets/{id}/exports/csv"
OUT = Path(__file__).resolve().parent.parent / "data" / "elia"


def download(dataset_id, start, end):
    params = {"where": f"datetime >= date'{start}' AND datetime < date'{end}'",
              "timezone": "UTC", "delimiter": ";"}
    try:
        r = requests.get(BASE.format(id=dataset_id), params=params, timeout=600)
    except requests.RequestException as e:
        print(f"  {dataset_id}: {e}")
        return None
    if not r.ok or r.content.count(b"\n") < 2:
        print(f"  {dataset_id}: HTTP {r.status_code}, no rows")
        return None
    df = pd.read_csv(io.BytesIO(r.content), sep=";", encoding="utf-8-sig")
    df["source_dataset"] = dataset_id
    return df


def merge(frames, start, end):
    df = pd.concat(frames, ignore_index=True, sort=False)
    ts = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
    df = df[(ts >= pd.Timestamp(start, tz="UTC")) & (ts < pd.Timestamp(end, tz="UTC"))].copy()
    values = [c for c in VALUE_COLUMNS if c in df.columns]
    keys = [c for c in KEY_COLUMNS if c in df.columns]
    df["_has_value"] = df[values].notna().any(axis=1) if values else False
    # rows with a measured value first, then keep one row per quarter-hour (+ region...)
    df = (df.sort_values("_has_value", ascending=False)
            .drop_duplicates(keys)
            .drop(columns="_has_value")
            .sort_values(keys))
    return df, values


def main():
    if len(sys.argv) != 3:
        sys.exit("Usage: python collector/download_elia.py START END   (YYYY-MM-DD)")
    start, end = sys.argv[1], sys.argv[2]
    OUT.mkdir(parents=True, exist_ok=True)
    for name, candidates in SERIES.items():
        print(f"{name}:")
        frames = []
        for dataset_id in candidates:
            df = download(dataset_id, start, end)
            if df is not None:
                t = pd.to_datetime(df["datetime"], utc=True, errors="coerce")
                print(f"  {dataset_id}: {len(df):>6} rows, {t.min():%Y-%m-%d %H:%M} -> {t.max():%Y-%m-%d %H:%M}")
                frames.append(df)
        if not frames:
            print("  FAILED: no dataset returned data. Check the IDs on opendata.elia.be")
            continue
        df, values = merge(frames, start, end)
        t = pd.to_datetime(df["datetime"], utc=True)
        measured = df[values].notna().any(axis=1).mean() if values else 0
        df.to_csv(OUT / f"{name}.csv", sep=";", index=False)
        print(f"  => {name}.csv: {len(df)} rows, {t.min():%Y-%m-%d} -> {t.max():%Y-%m-%d}, "
              f"measured value in {measured:.0%} of rows")


if __name__ == "__main__":
    main()
