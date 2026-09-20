#!/usr/bin/env python3
"""
01_recon.py — Kalshi fetch + schema report.

Step 1b of the coherence project. Does two things and nothing else:
fetches every open event with its markets, and reports what the data
actually looks like. Classification lives in 03_universe.py.

This script does NOT assume it knows the schema. Kalshi changed field
formats around Aug 2026 (dollars / fixed-point), so the first job is to
find out what is really there before writing any parser against it.

Outputs:
  raw/events_<timestamp>.jsonl   every event as received, plus _fetched_at

Usage:
    pip install requests
    python 01_recon.py
"""

import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import requests

# Kalshi production hosts, in the order the docs recommend.
# `external-api` is the dedicated external Trade API host; `api.elections` is
# the older shared one, kept for compatibility. Despite its name it serves ALL
# markets, not just elections. Probe rather than trust — hostnames move.
BASES = [
    "https://external-api.kalshi.com/trade-api/v2",
    "https://api.elections.kalshi.com/trade-api/v2",
]
RAW_DIR = "raw"
PAGE_LIMIT = 200
SLEEP_BETWEEN_PAGES = 0.25
MAX_PAGES = 200              # safety stop; warns loudly if actually reached
MAX_429_RETRIES = 6          # bounded, or a rate limit becomes an infinite loop
TIMEOUT = 30


# ---------------------------------------------------------------- fetching

def resolve_base(session):
    """
    Find a host that answers. Uses the unauthenticated exchange/status
    endpoint as the cheapest possible liveness check.
    """
    for base in BASES:
        try:
            r = session.get(f"{base}/exchange/status", timeout=10)
            if r.status_code == 200:
                print(f"  host OK: {base}")
                return base
            print(f"  host responded {r.status_code}: {base}", file=sys.stderr)
        except requests.exceptions.ConnectionError:
            print(f"  host unreachable (DNS/connection): {base}", file=sys.stderr)
        except requests.RequestException as e:
            print(f"  host error: {base} - {e}", file=sys.stderr)
    return None


def fetch_events():
    """Page through open events with markets nested. Returns (events, truncated)."""
    session = requests.Session()
    session.headers.update({"User-Agent": "coherence-research/0.1"})

    base = resolve_base(session)
    if base is None:
        print("\nNo Kalshi host reachable. Either every hostname changed, or your",
              file=sys.stderr)
        print("machine has no DNS/internet. Test with:", file=sys.stderr)
        print("  curl -sS https://external-api.kalshi.com/trade-api/v2/exchange/status",
              file=sys.stderr)
        return [], False

    events, cursor, page = [], None, 0
    retries_429 = 0

    while page < MAX_PAGES:
        params = {"status": "open", "with_nested_markets": "true", "limit": PAGE_LIMIT}
        if cursor:
            params["cursor"] = cursor

        try:
            r = session.get(f"{base}/events", params=params, timeout=TIMEOUT)
        except requests.RequestException as e:
            print(f"  ! network error on page {page}: {e}", file=sys.stderr)
            break

        if r.status_code == 429:
            # Bounded retry. An unbounded `continue` here loops forever if the
            # rate limit is persistent — and this loop gets reused by the
            # collector, which runs unattended for weeks.
            retries_429 += 1
            if retries_429 > MAX_429_RETRIES:
                print(f"  ! rate limited {MAX_429_RETRIES}x, giving up", file=sys.stderr)
                break
            wait = min(60, 2 ** retries_429)
            print(f"  ! rate limited, retry {retries_429}/{MAX_429_RETRIES} in {wait}s",
                  file=sys.stderr)
            time.sleep(wait)
            continue

        if r.status_code != 200:
            print(f"  ! HTTP {r.status_code}: {r.text[:300]}", file=sys.stderr)
            break

        retries_429 = 0
        payload = r.json()
        batch = payload.get("events", [])

        # One clock: stamp receipt time on every record, from this machine.
        stamp = datetime.now(timezone.utc).isoformat()
        for e in batch:
            e["_fetched_at"] = stamp

        events.extend(batch)
        page += 1
        print(f"  page {page}: +{len(batch)} events (total {len(events)})")

        cursor = payload.get("cursor")
        if not cursor or not batch:
            return events, False
        time.sleep(SLEEP_BETWEEN_PAGES)

    truncated = page >= MAX_PAGES
    return events, truncated


def save_raw(events):
    os.makedirs(RAW_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(RAW_DIR, f"events_{stamp}.jsonl")
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    print(f"\nRaw data saved: {path}")
    return path


# ---------------------------------------------------------------- schema

# Fields the project actually depends on, confirmed present in the 2026-09 run.
NEEDED_EVENT = ["event_ticker", "series_ticker", "mutually_exclusive",
                "settlement_sources", "category", "strike_period"]
NEEDED_MARKET = ["ticker", "yes_bid_dollars", "yes_ask_dollars",
                 "yes_bid_size_fp", "yes_ask_size_fp",     # depth: hard violations
                 "volume_24h_fp", "liquidity_dollars", "open_interest_fp",
                 "strike_type", "floor_strike", "cap_strike",
                 "yes_sub_title", "rules_primary", "close_time", "status"]


def report_schema(events):
    """Print which keys appear and how often. Trust this over any documentation."""
    ev_keys, mk_keys = Counter(), Counter()
    n_markets = 0

    for e in events:
        ev_keys.update(e.keys())
        for m in e.get("markets") or []:
            mk_keys.update(m.keys())
            n_markets += 1

    print("\n" + "=" * 64)
    print("OBSERVED SCHEMA")
    print("=" * 64)

    print(f"\nEVENT keys ({len(events):,} events):")
    for k, c in ev_keys.most_common():
        print(f"  {c/len(events):5.0%}  {k}")

    if n_markets:
        print(f"\nMARKET keys ({n_markets:,} markets):")
        for k, c in mk_keys.most_common():
            print(f"  {c/n_markets:5.0%}  {k}")
    else:
        print("\n  !! No nested markets. Check the with_nested_markets param name.")
        return

    print("\nFields this project depends on:")
    missing = []
    for k in NEEDED_EVENT:
        ok = k in ev_keys
        missing += [] if ok else [f"event.{k}"]
        print(f"  {'OK' if ok else 'MISSING'}  event.{k}")
    for k in NEEDED_MARKET:
        pct = mk_keys.get(k, 0) / n_markets
        # Sparse is fine for strike fields — they vary by market shape.
        ok = k in mk_keys
        missing += [] if ok else [f"market.{k}"]
        print(f"  {'OK' if ok else 'MISSING'}  market.{k:<20} {pct:5.0%}")

    if missing:
        print("\n  !! MISSING FIELDS — the API changed. Do not run downstream")
        print("     scripts until these are resolved:")
        for k in missing:
            print(f"       {k}")


def main():
    print("Fetching open Kalshi events (public endpoint, no auth)...")
    events, truncated = fetch_events()
    if not events:
        print("\nNothing returned. Check host and param names against current docs.")
        sys.exit(1)

    if truncated:
        print(f"\n  !! HIT MAX_PAGES ({MAX_PAGES}) — this dataset is INCOMPLETE.")
        print("     Raise MAX_PAGES and re-run before analysing.")

    save_raw(events)
    report_schema(events)

    print("\n" + "=" * 64)
    print("NEXT: python 03_universe.py   (classifies structure, no network)")
    print("=" * 64)


if __name__ == "__main__":
    main()
