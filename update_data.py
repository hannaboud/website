"""Download the market data for bonds.html and save it as bonds-data.json.

Run by hand:      python3 update_data.py
Runs by itself:   every weekday through GitHub Actions (see .github/workflows/update-bonds-data.yml)
"""
import io
import json
import sys
from datetime import date

import numpy as np
import pandas as pd
import requests

YIELDS = ["DGS3MO", "DGS6MO", "DGS1", "DGS2", "DGS5", "DGS7", "DGS10", "DGS20", "DGS30"]
EXTRAS = ["T10YIE", "T5YIE", "T5YIFR", "DFII10", "BAMLC0A0CM", "BAMLH0A0HYM2"]
CPI = "CPIAUCSL"
START = "2000-01-01"
OUT = "bonds-data.json"


def fetch(series_id):
    try:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={START}"
        resp = requests.get(url, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = ["date", series_id]
        s = pd.to_numeric(df[series_id], errors="coerce")
        s.index = pd.to_datetime(df["date"])
        s = s.dropna()
        return s if len(s) else None
    except Exception as err:
        print(f"  could not load {series_id}: {err}")
        return None


def sample():
    """Made-up data for testing the page without internet. Never publish this."""
    rng = np.random.default_rng(1)
    days = pd.bdate_range(start=START, end=pd.Timestamp(date.today()))

    def ar1(mean, sd):
        x = np.empty(len(days)); x[0] = mean
        e = rng.normal(0, sd, len(days))
        for i in range(1, len(days)):
            x[i] = x[i - 1] + 0.002 * (mean - x[i - 1]) + e[i]
        return x

    common = ar1(0, 0.05)
    level = dict(zip(YIELDS, [2.5, 2.6, 2.7, 2.9, 3.3, 3.6, 3.8, 4.2, 4.3]))
    out = {k: pd.Series(np.clip(v + common + ar1(0, 0.01), 0.05, None), index=days) for k, v in level.items()}
    for k, v in zip(EXTRAS, [2.2, 2.1, 2.3, 1.5, 1.4, 4.8]):
        out[k] = pd.Series(np.clip(ar1(v, 0.012), 0.1, None), index=days)
    months = pd.date_range(start=START, end=days[-1], freq="MS")
    out[CPI] = pd.Series(170 * np.cumprod(1 + rng.normal(0.0021, 0.0015, len(months))), index=months)
    return out


def main():
    use_sample = "--sample" in sys.argv
    if use_sample:
        got = sample()
    else:
        got = {}
        for sid in YIELDS + EXTRAS + [CPI]:
            print("loading", sid)
            got[sid] = fetch(sid)
    missing = [k for k in ("DGS2", "DGS10", "DGS30") if got.get(k) is None]
    if missing:
        sys.exit(f"Stopping without touching {OUT}: could not load {missing}.")

    daily = pd.DataFrame({k: got[k] for k in YIELDS + EXTRAS if got.get(k) is not None}).sort_index()
    daily = daily.dropna(how="all").round(2)
    cpi = got.get(CPI)
    payload = {
        "updated": daily[YIELDS[6]].dropna().index.max().strftime("%Y-%m-%d"),
        "sample": use_sample,
        "dates": [d.strftime("%Y-%m-%d") for d in daily.index],
        "series": {k: [None if pd.isna(v) else float(v) for v in daily[k]] for k in daily.columns},
        "cpi": {"dates": [d.strftime("%Y-%m-%d") for d in cpi.index], "values": [round(float(v), 3) for v in cpi]}
               if cpi is not None else {"dates": [], "values": []},
    }
    with open(OUT, "w") as f:
        json.dump(payload, f, separators=(",", ":"))
    print(f"Saved {OUT}: {len(payload['dates'])} days through {payload['updated']}, {len(payload['series'])} series.")


if __name__ == "__main__":
    main()
