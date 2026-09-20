#!/usr/bin/env python3
"""
04_collect.py — The collector. Run this, leave it running.

Polls top-of-book for every market in a chosen set of series, on a fixed
cadence, and appends to daily gzipped files. This is the instrument; the
dataset does not exist until it has been running.

Design decisions, each with a reason:

  Bulk /markets, not per-market /orderbook.
      yes_bid_dollars, yes_ask_dollars, yes_bid_size_fp and yes_ask_size_fp
      are on 100% of markets and come back from the bulk endpoint. That is
      price AND depth at top of book — everything both tests need. Polling
      20,000 markets one orderbook at a time would take hours per cycle.

  One clock.
      Every row carries _t, this machine's receipt time. Venue timestamps
      update at different moments per market; comparing across them
      manufactures violations that never happened.

  Heartbeat log.
      Every cycle writes a row saying what it saw. Without this, a collector
      outage during a violation becomes a fake long-lived violation — and
      persistence is the headline metric. Episodes spanning a gap get dropped
      at analysis time.

  Never dies.
      Every error is caught and logged. A collector that exits on the first
      unhandled exception is a collector that silently stops on night three.

Outputs:
  data/quotes_YYYYMMDD.jsonl.gz     one row per market per cycle
  data/heartbeat_YYYYMMDD.jsonl     one row per cycle

Usage:
    python 04_collect.py                 # run forever
    python 04_collect.py --once          # single cycle, for testing
    python 04_collect.py --interval 30
"""

import argparse
import glob
import gzip
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

import requests

BASES = [
    "https://external-api.kalshi.com/trade-api/v2",
    "https://api.elections.kalshi.com/trade-api/v2",
]

# Chosen from the 03_universe.py shortlist. Ladders first — nested thresholds
# need no exhaustiveness assumption. Tight-increment series (BTCD steps $100,
# gas steps half a cent) are where adjacent rungs have near-identical true
# probabilities, so a small book asymmetry is enough to invert them.
SERIES_LADDER = [
    "KXBTCD",        # BTC hourly, $100 steps, very tight
    "KXBTCMAXMON",   # BTC monthly max
    "KXFED",         # Fed funds, 25bp steps, slow-moving control
    "KXAAAGASDMI",   # gas prices, half-cent steps, low attention
    "KXNFLTOTAL",    # NFL totals, heavily attended
    "KXMLBTOTAL",    # MLB totals, many concurrent games
    "KXNFL1HTOTAL",
    "KXNCAAFTOTAL",
]
# Partitions, as a contrast on the other constraint type.
SERIES_PARTITION = [
    "KXHIGHNY", "KXHIGHLAX", "KXHIGHCHI", "KXHIGHMIA",
    "KXBTCY", "KXINXY",
]
SERIES = SERIES_LADDER + SERIES_PARTITION

DATA_DIR = "data"
INTERVAL = 15
PAGE_LIMIT = 1000
MAX_PAGES = 20
MAX_429_RETRIES = 5
TIMEOUT = 20

# Requests are fired back to back, so 14 series land as a ~16/sec burst
# against an average of ~1/sec. Burst limits fire on the peak, not the mean.
# Spacing spreads the cycle over ~4s of a 15s budget — cheap insurance.
REQUEST_SPACING = 0.25

# Only these fields are kept. Everything else is static metadata already
# captured by 01_recon and would multiply storage by cycle count for nothing.
KEEP = ["ticker", "event_ticker", "status",
        "yes_bid_dollars", "yes_ask_dollars",
        "yes_bid_size_fp", "yes_ask_size_fp",
        "no_bid_dollars", "no_ask_dollars",
        "last_price_dollars", "volume_24h_fp", "open_interest_fp"]

# A row is written only when one of these changes. Writing all 2,550 markets
# every cycle costs ~9GB over three weeks, and most of those rows say exactly
# what the previous row said. Volume and open interest are deliberately NOT
# here — they tick constantly and would defeat the filter; they ride along on
# whatever rows do get written, plus every keyframe.
QUOTE_KEYS = ["yes_bid_dollars", "yes_ask_dollars",
              "yes_bid_size_fp", "yes_ask_size_fp",
              "no_bid_dollars", "no_ask_dollars", "status"]

# Every Nth cycle writes every market regardless of change. Two reasons:
# reconstruction can start from a keyframe instead of the top of the file,
# and state carried forward to just before a keyframe can be checked against
# it — a built-in correctness test for the reconstruction code.
KEYFRAME_EVERY = 240          # hourly at 15s

_last = {}                    # ticker -> tuple of QUOTE_KEYS values

_stop = False


def _handle_signal(signum, frame):
    global _stop
    _stop = True
    print(f"\n  signal {signum} received, finishing cycle then exiting", flush=True)


def last_cycle_seen():
    """
    Highest cycle number in any heartbeat file.

    Cycle numbers are the ordering key for replay, so they must keep
    increasing across restarts. Resetting to 1 would make a restarted run
    look like time running backwards, and any episode spanning the restart
    would get a meaningless duration.
    """
    hi = 0
    for p in sorted(glob.glob(os.path.join(DATA_DIR, "heartbeat_*.jsonl"))):
        try:
            with open(p) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        c = json.loads(line).get("cycle")
                    except json.JSONDecodeError:
                        continue
                    if isinstance(c, int) and c > hi:
                        hi = c
        except OSError:
            continue
    return hi


def now():
    return datetime.now(timezone.utc)


def day_key(t):
    return t.strftime("%Y%m%d")


# ---------------------------------------------------------------- fetching

def resolve_base(session):
    for base in BASES:
        try:
            r = session.get(f"{base}/exchange/status", timeout=10)
            if r.status_code == 200:
                return base
        except requests.RequestException:
            continue
    return None


def fetch_series(session, base, series):
    """
    All open markets for one series. Returns (rows, error_or_None, n_retries).
    Never raises — a failing series must not take down the cycle.

    n_retries is returned rather than swallowed: a retry that eventually
    succeeds leaves no trace in the data, so silent throttling looks like
    healthy collection until it gets bad enough to lose rows.
    """
    rows, cursor, page, retries, total_retries = [], None, 0, 0, 0

    while page < MAX_PAGES:
        params = {"series_ticker": series, "status": "open", "limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor
        try:
            r = session.get(f"{base}/markets", params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            return rows, f"{type(e).__name__}", total_retries

        if r.status_code == 429:
            retries += 1
            total_retries += 1
            if retries > MAX_429_RETRIES:
                return rows, "rate_limited", total_retries
            time.sleep(min(30, 2 ** retries))
            continue
        if r.status_code != 200:
            return rows, f"http_{r.status_code}", total_retries

        retries = 0
        try:
            payload = r.json()
        except ValueError:
            return rows, "bad_json", total_retries

        batch = payload.get("markets", [])
        for m in batch:
            row = {k: m.get(k) for k in KEEP}
            row["series"] = series
            rows.append(row)

        page += 1
        cursor = payload.get("cursor")
        if not cursor or not batch:
            break
        time.sleep(REQUEST_SPACING)

    return rows, None, total_retries


# ---------------------------------------------------------------- writing

def write_cycle(rows, stamp, cycle_id):
    """Append to today's gzipped file. Append-only; never rewrite history."""
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"quotes_{day_key(now())}.jsonl.gz")
    with gzip.open(path, "at") as f:
        for row in rows:
            row["_t"] = stamp
            row["_cycle"] = cycle_id
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    return path


def write_heartbeat(record):
    """
    One row per cycle, always, including failed ones. This file is what lets
    the analysis distinguish 'no violation' from 'collector was down'.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    path = os.path.join(DATA_DIR, f"heartbeat_{day_key(now())}.jsonl")
    with open(path, "a") as f:
        f.write(json.dumps(record, separators=(",", ":")) + "\n")


# ---------------------------------------------------------------- cycle

def run_cycle(session, base, cycle_id):
    t0 = time.monotonic()
    stamp = now().isoformat()

    all_rows, errors, retries = [], {}, 0
    for s in SERIES:
        rows, err, n_retry = fetch_series(session, base, s)
        all_rows.extend(rows)
        retries += n_retry
        if err:
            errors[s] = err
        time.sleep(REQUEST_SPACING)

    # Kalshi's cursor is not stable across a paginated fetch: a market can be
    # returned on two pages of the same cycle, with its size field changed in
    # between. Keep the last observation — it is the more recent one — so a
    # cycle holds exactly one row per ticker.
    deduped, n_dupes = {}, 0
    for row in all_rows:
        t = row.get("ticker")
        if t is None:
            continue
        if t in deduped:
            n_dupes += 1
        deduped[t] = row
    all_rows = list(deduped.values())

    # Keyframe on the first cycle too: _last is empty after any restart, so
    # everything is "changed" anyway — marking it makes that explicit in the
    # data rather than implicit.
    # _kf 1 = scheduled keyframe, safe to validate carried state against.
    # _kf 2 = resume keyframe: _last is empty because the process just
    # started, so an unobserved gap precedes it and carried state is stale
    # through no fault of the replay.
    resumed = not _last
    keyframe = resumed or (cycle_id % KEYFRAME_EVERY == 0)
    kf_mark = 2 if resumed else 1

    to_write = []
    for row in all_rows:
        tick = row.get("ticker")
        sig = tuple(row.get(k) for k in QUOTE_KEYS)
        if keyframe or _last.get(tick) != sig:
            if keyframe:
                row["_kf"] = kf_mark
            to_write.append(row)
        _last[tick] = sig

    try:
        write_cycle(to_write, stamp, cycle_id)
        write_err = None
    except OSError as e:
        write_err = str(e)[:120]

    hb = {
        "_t": stamp,
        "cycle": cycle_id,
        "duration_s": round(time.monotonic() - t0, 2),
        "n_series_ok": len(SERIES) - len(errors),
        "n_series_failed": len(errors),
        "n_markets": len(all_rows),      # observed
        "n_written": len(to_write),      # changed
        "retries_429": retries,
        "dupes": n_dupes,
        "keyframe": kf_mark if keyframe else 0,
        "errors": errors or None,
        "write_error": write_err,
    }
    write_heartbeat(hb)
    return hb


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="one cycle then exit")
    ap.add_argument("--interval", type=int, default=INTERVAL)
    args = ap.parse_args()

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    session = requests.Session()
    session.headers.update({"User-Agent": "coherence-research/0.1"})

    base = resolve_base(session)
    if base is None:
        print("No Kalshi host reachable.", file=sys.stderr)
        sys.exit(1)
    print(f"host: {base}")
    print(f"series: {len(SERIES)}   interval: {args.interval}s")
    print(f"writing to {DATA_DIR}/\n")

    cycle_id = last_cycle_seen()
    if cycle_id:
        print(f"resuming after cycle {cycle_id:,}")
    _run_start = cycle_id + 1
    next_at = time.monotonic()

    while not _stop:
        cycle_id += 1
        try:
            hb = run_cycle(session, base, cycle_id)
        except Exception as e:
            # Catch-all on purpose. An unhandled exception here means the
            # collector stops and nobody notices until the data is missing.
            hb = {"cycle": cycle_id, "fatal": f"{type(e).__name__}: {e}"[:200]}
            try:
                write_heartbeat({"_t": now().isoformat(), **hb})
            except OSError:
                pass

        flag = ""
        if hb.get("errors"):
            flag = f"  ! {hb['errors']}"
        if hb.get("fatal"):
            flag = f"  !! {hb['fatal']}"
        print(f"  cycle {cycle_id:>6}  {hb.get('n_markets', 0):>5} seen  "
              f"{hb.get('n_written', 0):>5} written  "
              f"{hb.get('duration_s', 0):>5}s"
              f"{'  KF' if hb.get('keyframe') else ''}"
              f"{'  429x' + str(hb['retries_429']) if hb.get('retries_429') else ''}{flag}",
              flush=True)

        if args.once:
            break

        # Fixed cadence, not sleep(interval). Sleeping a constant after a
        # variable-length cycle makes the effective interval drift, which
        # would bias every duration measured from cycle counts.
        next_at += args.interval
        delay = next_at - time.monotonic()
        if delay < 0:
            # Cycle overran its slot. Skip ahead rather than fall behind.
            next_at = time.monotonic()
            delay = 0
        end = time.monotonic() + delay
        while time.monotonic() < end and not _stop:
            time.sleep(min(0.5, end - time.monotonic()))

    print("\nstopped cleanly")


if __name__ == "__main__":
    main()