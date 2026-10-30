"""
Step 1 of the static data: discover the structure of the Eco-Movement Belgium feed.

The status collector (collect_changes.py) only keeps status + price. Location,
operator and power live in the STATIC part of the DATEX II feed. Before writing
the extractor we need to see the exact JSON keys, so this script prints a map of
every field with an example value.

Run in the evse-collector folder (cmd):
    set ECO_MOVEMENT_TOKEN=your-token
    python collector/explore_static.py

If you already have a raw dump (e.g. belgium_datex_raw.json):
    python collector/explore_static.py belgium_datex_raw.json

Output:
    static_raw_page1.json   first page of the feed, as received
    static_structure.txt    every field path + an example value  -> send this file to Claude
"""
import json
import os
import sys
from collections import OrderedDict

import requests

URL = "https://nap-be.eco-movement.com/datex2/v1/locations"


def load():
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding="utf-8") as f:
            return json.load(f)
    token = os.environ.get("ECO_MOVEMENT_TOKEN")
    if not token:
        sys.exit("Set ECO_MOVEMENT_TOKEN first (same token as the GitHub secret).")
    r = requests.get(URL, headers={"Authorization": f"Bearer {token}",
                                   "Accept": "application/json"}, timeout=300)
    r.raise_for_status()
    with open("static_raw_page1.json", "w", encoding="utf-8") as f:
        f.write(r.text)
    print("HTTP", r.status_code, "| Link header:", r.headers.get("Link"))
    return r.json()


def leaf_paths(obj, prefix="", out=None):
    """Every leaf path once, with one example value. Lists are shown as [] (first 3 items scanned)."""
    if out is None:
        out = OrderedDict()
    if isinstance(obj, dict):
        for k, v in obj.items():
            leaf_paths(v, f"{prefix}.{k}" if prefix else k, out)
    elif isinstance(obj, list):
        for item in obj[:3]:
            leaf_paths(item, prefix + "[]", out)
    else:
        out.setdefault(prefix, repr(obj)[:90])
    return out


def main():
    data = load()
    lines = []
    if isinstance(data, dict):
        lines.append("TOP-LEVEL KEYS: " + ", ".join(data.keys()))
        for key, value in data.items():
            lines.append(f"\n=== {key} ===")
            for path, example in leaf_paths(value).items():
                lines.append(f"{key}.{path} = {example}")
    else:
        lines.append(f"Top level is a {type(data).__name__}")
        for path, example in leaf_paths(data).items():
            lines.append(f"{path} = {example}")
    report = "\n".join(lines)
    with open("static_structure.txt", "w", encoding="utf-8") as f:
        f.write(report)
    print(report[:4000])
    print(f"\n... full report: static_structure.txt ({len(lines)} lines). Send it to Claude.")


if __name__ == "__main__":
    main()
