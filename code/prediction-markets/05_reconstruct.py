#!/usr/bin/env python3
"""
05_reconstruct.py — Replay change-only quote files into full market state.

04_collect writes a row only when a quote moves, so the file is not a
sequence of snapshots — it is a sequence of edits. This module replays those
edits to answer: what did every market look like at cycle N?

Everything downstream depends on this being right, so it validates itself.
Keyframes (every 240th cycle, marked _kf) contain every market regardless of
change. Carry state forward to just before a keyframe, compare to the
keyframe, and any mismatch is a bug in the replay. That check is the whole
reason keyframes exist.

Safe to run while the collector is still writing: a partially-written final
line is expected and skipped, not crashed on.

Usage:
    python 05_reconstruct.py                 # validate + report
    python 05_reconstruct.py --cycle 500     # dump state at one cycle
"""

import argparse
import glob
import gzip
import json
import os
from datetime import datetime
import sys
from collections import defaultdict

DATA_DIR = "data"
QUOTE_FIELDS = ["yes_bid_dollars", "yes_ask_dollars",
                "yes_bid_size_fp", "yes_ask_size_fp",
                "no_bid_dollars", "no_ask_dollars", "status"]


# ---------------------------------------------------------------- reading

def read_rows(paths=None):
    """
    Yield every quote row in cycle order.

    Tolerates a truncated final line — the collector may be mid-write. A
    partial line is a normal condition here, not an error, so it is counted
    and skipped rather than raised.
    """
    if paths is None:
        paths = sorted(glob.glob(os.path.join(DATA_DIR, "quotes_*.jsonl.gz")))
    if not paths:
        sys.exit(f"No quote files in {DATA_DIR}/. Has the collector run?")

    bad = 0
    for p in paths:
        try:
            with gzip.open(p, "rt") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        bad += 1
        except (EOFError, OSError):
            # gzip can raise on a member that is still being written.
            bad += 1
    if bad:
        print(f"  (skipped {bad} incomplete record(s) — expected if the "
              f"collector is running)", file=sys.stderr)


def read_heartbeats():
    """Cycle -> heartbeat record. This is how gaps become visible."""
    hb = {}
    for p in sorted(glob.glob(os.path.join(DATA_DIR, "heartbeat_*.jsonl"))):
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if "cycle" in r:
                    hb[r["cycle"]] = r
    return hb


# ---------------------------------------------------------------- replay

def quote_of(row):
    return {k: row.get(k) for k in QUOTE_FIELDS}


def replay(rows):
    """
    Walk rows in order, maintaining current state per ticker.

    Yields (cycle, state, meta) once per cycle, where state maps
    ticker -> quote dict. The state object is reused between yields for
    speed — consumers that need to keep a cycle must copy it.
    """
    state = {}
    meta = {}          # ticker -> event_ticker, series
    cur = None
    pending_kf = set()

    for row in rows:
        c = row.get("_cycle")
        if c is None:
            continue
        if cur is None:
            cur = c
        if c != cur:
            yield cur, state, {"keyframe_tickers": pending_kf}
            pending_kf = set()
            cur = c

        t = row.get("ticker")
        if t is None:
            continue
        state[t] = quote_of(row)
        if t not in meta:
            meta[t] = {"event_ticker": row.get("event_ticker"),
                       "series": row.get("series")}
        if row.get("_kf"):
            pending_kf.add(t)

    if cur is not None:
        yield cur, state, {"keyframe_tickers": pending_kf}


def validate(paths=None, verbose=True):
    """
    Check replayed state against every keyframe.

    A keyframe holds the true value for every market. Carry state forward from
    deltas; if it disagrees, a change happened that never got written.

    Intra-cycle duplicates are counted separately. Kalshi's cursor is not
    stable across a paginated fetch, so a market can appear on two pages of
    the same cycle with its size field changed in between. That is a
    collector-side data quality issue, not a replay failure, and conflating
    the two hides both.
    """
    checked = mismatches = dupes = dupes_differing = skipped_resume = 0
    details = []
    set_at = {}          # ticker -> cycle at which state[t] was written
    state = {}

    for row in read_rows(paths):
        t, c = row.get("ticker"), row.get("_cycle")
        if t is None or c is None:
            continue
        q = quote_of(row)

        if t in state and set_at[t] == c:
            # Same ticker, same cycle: a duplicate from pagination overlap.
            dupes += 1
            if state[t] != q:
                dupes_differing += 1
        elif row.get("_kf") == 1 and t in state:
            checked += 1
            if state[t] != q:
                mismatches += 1
                if len(details) < 5:
                    details.append({"ticker": t, "cycle": c,
                                    "carried": state[t], "keyframe": q,
                                    "set_at": set_at.get(t)})
        elif row.get("_kf") == 2 and t in state:
            # Resume keyframe: an unobserved gap precedes it, so carried
            # state is legitimately stale. Not a replay failure.
            skipped_resume += 1
        state[t] = q
        set_at[t] = c

    if verbose:
        print(f"\n  keyframe checks : {checked:,}")
        print(f"  mismatches      : {mismatches:,}")
        print(f"  intra-cycle dups: {dupes:,}  "
              f"({dupes_differing:,} with differing values)")
        if skipped_resume:
            print(f"  skipped (resume) : {skipped_resume:,}  "
                  f"— keyframes after a restart gap, not checkable")
        if dupes:
            print("     Pagination overlap — a market returned on two pages of")
            print("     one cycle. Harmless for replay (last value wins) but")
            print("     inflates row counts. Fixed collector-side by deduping.")
        if mismatches:
            print("\n  !! Replay disagrees with keyframes. Do NOT trust any")
            print("     downstream result until this is understood.\n")
            for d in details:
                print(f"     {d['ticker']} @ cycle {d['cycle']} "
                      f"(state set at cycle {d['set_at']})")
                print(f"       carried : {d['carried']}")
                print(f"       keyframe: {d['keyframe']}")
        elif checked:
            print("  replay verified against keyframes")
        else:
            print("  (no keyframe after the first yet — needs 1 hour of data)")
    return mismatches


# ---------------------------------------------------------------- gaps

def report_gaps(hb, interval=15):
    """
    Where the collector stopped looking.

    Two distinct kinds, and the second is easy to miss. A *missing cycle* is a
    hole in the numbering. A *time gap* is a hole in the clock with no hole in
    the numbering — which is exactly what a clean restart produces, since
    numbering resumes where it left off. Both must be excluded from episode
    durations: a violation spanning either was unobserved, not persistent.
    """
    if not hb:
        print("  no heartbeats found")
        return [], []

    cycles = sorted(hb)
    lo, hi = cycles[0], cycles[-1]
    missing = sorted(set(range(lo, hi + 1)) - set(cycles))

    time_gaps = []
    prev_c = prev_t = None
    for c in cycles:
        ts = hb[c].get("_t")
        t = None
        if ts:
            try:
                t = datetime.fromisoformat(ts)
            except ValueError:
                t = None
        if prev_t is not None and t is not None:
            delta = (t - prev_t).total_seconds()
            if delta > interval * 2.5:
                time_gaps.append((prev_c, c, round(delta, 1)))
        if t is not None:
            prev_c, prev_t = c, t

    degraded = [c for c in cycles if hb[c].get("n_series_failed")]
    throttled = [c for c in cycles if hb[c].get("retries_429")]
    dup = sum(hb[c].get("dupes", 0) or 0 for c in cycles)
    fatal = [c for c in cycles if hb[c].get("fatal")]

    print(f"\n  cycles {lo}-{hi} ({len(cycles):,} recorded)")
    print(f"  missing cycles   : {len(missing):,}")
    print(f"  time gaps        : {len(time_gaps):,}  "
          f"(clock jumped with no missing cycle — e.g. a restart)")
    print(f"  degraded cycles  : {len(degraded):,}  (a series failed)")
    print(f"  throttled cycles : {len(throttled):,}  (429 retries)")
    print(f"  duplicate rows   : {dup:,}")
    print(f"  fatal cycles     : {len(fatal):,}")

    for a, b, d in time_gaps[:5]:
        print(f"    cycle {a} -> {b}: {d:,.0f}s unobserved")
    if len(time_gaps) > 5:
        print(f"    ... and {len(time_gaps)-5} more")

    if missing:
        runs, start = [], missing[0]
        for a, b in zip(missing, missing[1:] + [None]):
            if b != (a + 1 if a is not None else None):
                runs.append((start, a))
                start = b
        print(f"  gap runs: {runs[:6]}{' ...' if len(runs) > 6 else ''}")
    return missing, time_gaps


# ---------------------------------------------------------------- main

def state_at(cycle, paths=None):
    """Full market state as of a given cycle."""
    state = {}
    for row in read_rows(paths):
        c = row.get("_cycle")
        if c is None or c > cycle:
            break
        t = row.get("ticker")
        if t:
            state[t] = quote_of(row)
    return state


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cycle", type=int, help="dump state at this cycle")
    args = ap.parse_args()

    if args.cycle:
        st = state_at(args.cycle)
        print(f"{len(st):,} markets known at cycle {args.cycle}")
        for t, q in list(st.items())[:10]:
            print(f"  {t:<38} {q['yes_bid_dollars']} / {q['yes_ask_dollars']}")
        return

    print("Replaying quote files...")
    n_rows = n_cycles = 0
    tickers = set()
    per_series = defaultdict(int)
    for row in read_rows():
        n_rows += 1
        if row.get("ticker"):
            tickers.add(row["ticker"])
        if row.get("series"):
            per_series[row["series"]] += 1
    print(f"  rows      : {n_rows:,}")
    print(f"  tickers   : {len(tickers):,}")

    hb = read_heartbeats()
    n_cycles = len(hb)
    print(f"  cycles    : {n_cycles:,}")
    if n_cycles:
        seen = sum(h.get("n_markets", 0) for h in hb.values())
        wrote = sum(h.get("n_written", 0) for h in hb.values())
        if seen:
            print(f"  write rate: {wrote/seen:.1%} of observations stored")

    print("\nValidating replay against keyframes...")
    bad = validate()

    print("\nCollector health:")
    report_gaps(hb)

    print("\n  rows by series:")
    for s, n in sorted(per_series.items(), key=lambda kv: -kv[1])[:15]:
        print(f"    {n:>9,}  {s}")

    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()