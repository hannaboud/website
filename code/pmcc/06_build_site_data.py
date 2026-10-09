"""
Step 6 - Bake the backtest results into one JavaScript file for the web page.

Runs 05_backtest.py (final rules), re-runs it with the first-draft rules for the
"what changed" comparison, and writes pmcc-book.js. Every number on the page is read
from this file, so the page cannot disagree with the backtest.

Run:  python 06_build_site_data.py [output_folder]
"""
import sys
import json
import importlib.util
import pandas as pd

spec = importlib.util.spec_from_file_location("bt", "05_backtest.py")
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

final = bt.main(out="results", quiet=True)

# first-draft rules: breakeven floor on, strike picked from the prior day's delta
bt.USE_FLOOR, bt.SHORT_DELTA_DAY = True, "prior"
draft = bt.main(out="results/first_draft", quiet=True)
bt.USE_FLOOR, bt.SHORT_DELTA_DAY = False, "entry"


def records(path):
    df = pd.read_csv(path)
    return json.loads(df.to_json(orient="records"))


data = dict(
    meta=dict(ticker="LLY", start=bt.START, end=bt.END, cash_rate=bt.CASH_RATE, risk_free=bt.RISK_FREE,
              ma_days=bt.MA_DAYS, delta_up=bt.DELTA_UPTREND, delta_down=bt.DELTA_DOWNTREND,
              leap_delta=bt.LEAP_DELTA, leap_min_delta=bt.LEAP_MIN_DELTA),
    metrics=final,
    first_draft={k: draft[k] for k in ("strategy", "premium_collected", "weeks_assigned",
                                       "assignment_cost", "short_leg_net", "weeks_floor_binding")},
    blotter=records("results/blotter.csv"),
    ledger=records("results/weekly_ledger.csv"),
    daily=records("results/daily_nav.csv"),
)
out = (sys.argv[1].rstrip("/") + "/" if len(sys.argv) > 1 else "results/") + "pmcc-book.js"
with open(out, "w") as f:
    f.write("window.PMCC_DATA = " + json.dumps(data, default=str) + ";\n")
print("wrote", out)
print("final :", final["strategy"])
print("draft :", draft["strategy"])
