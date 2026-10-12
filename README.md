# Belgian EV charger availability

An automated pipeline that records how public EV chargers in Belgium switch between
`available`, `charging`, `outOfOrder` and other states, every 15 minutes, to study
and later predict charger availability.

## How it works

A GitHub Actions workflow (`.github/workflows/collect.yml`) runs
`collector/collect_changes.py` every 15 minutes. Each run downloads the full Belgian
DATEX II feed and keeps only what changed:

| Path | What | Size |
| --- | --- | --- |
| `data/events/YYYY/MM/DD/HHMM.csv.gz` | Chargers whose status changed since the previous run | small, per run |
| `data/baselines/YYYY-MM-DD.csv.gz` | Full snapshot of every charger, once per UTC day | ~1 MB per day |
| `data/last_run.txt` | Time of the last successful run | tiny |

A charger's status at any moment = its status in the day's baseline, updated by the
events that follow. Remove the small overlap between runs with
`drop_duplicates(["evse_id", "last_updated"])`.

## Data source and licence

Data from the [Eco-Movement Belgium DATEX II API](https://developers.eco-movement.com/v5/docs/belgium-datex-ii),
published for Belgium's national access point [transportdata.be](https://transportdata.be),
under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
Coverage is limited to charge point operators that authorised Eco-Movement, not every
charger in Belgium.
