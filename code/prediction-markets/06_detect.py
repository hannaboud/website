#!/usr/bin/env python3
"""
06_detect.py — Find monotonicity violations in ladder families.

A ladder's rungs are nested thresholds ("above 2.75%", "above 3.00%"). Since
clearing a higher bar cannot be easier than clearing a lower one, prices must
step down as the strike rises. Any step up is a logical violation.

Two tests per adjacent pair:

  SOFT   midpoints out of order. Requires both rungs fully quoted. Means the
         two markets are not watching each other. Not tradeable.

  HARD   you could buy the underpriced lower rung at its ASK, sell the
         overpriced higher rung at its BID, and be guaranteed not to lose.
         Needs only those two sides — not all four quotes.

No magnitude threshold. Every violation carries its size in cents and, for
hard ones, the depth available. Thresholds are applied at analysis time,
where they can be changed; baked into detection they cannot.

Outputs:
  violations.csv   one row per violating pair per cycle
  families.csv     one row per family per cycle (the denominator)

Usage:
    python 06_detect.py
    python 06_detect.py --max-cycles 5000
"""

import argparse
import csv
import glob
import importlib.util
import json
import os
import sys
from collections import defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")
RAW_DIR = os.path.join(_HERE, "raw")

# Ladders where a higher strike means a LOWER probability: "above X".
__version__ = "1.2-zerosize"

DESCENDING = {"greater", "greater_or_equal", "structured"}
# Ladders where a higher strike means a HIGHER probability: "below X".
ASCENDING = {"less", "less_or_equal"}


def _load_reconstructor():
    """
    Module names starting with a digit can't be imported normally, so load by
    path. Resolve against this file's own directory rather than the current
    working directory — otherwise running from anywhere else silently fails.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "05_reconstruct.py")
    if not os.path.exists(path):
        sys.exit(f"Missing {path}\n"
                 f"06_detect.py needs 05_reconstruct.py in the same folder.")
    spec = importlib.util.spec_from_file_location("recon", path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------- metadata

def cents(v):
    """'0.5600' -> 56.0. Kalshi sends prices as dollar strings."""
    try:
        return round(float(v) * 100, 4)
    except (TypeError, ValueError):
        return None


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_metadata():
    """
    ticker -> {event, series, strike, strike_type} for every market seen in
    any recon dump. Later dumps win, so re-running 01_recon daily keeps new
    markets (fresh temperature events, new games) in scope.
    """
    paths = sorted(glob.glob(os.path.join(RAW_DIR, "events_*.jsonl")))
    if not paths:
        sys.exit(f"No {RAW_DIR}/events_*.jsonl. Run 01_recon.py first.")

    meta = {}
    for p in paths:
        with open(p) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for m in e.get("markets") or []:
                    t = m.get("ticker")
                    if not t:
                        continue
                    strike = fnum(m.get("floor_strike"))
                    if strike is None:
                        strike = fnum(m.get("cap_strike"))
                    meta[t] = {
                        "event": e.get("event_ticker"),
                        "series": e.get("series_ticker"),
                        "strike": strike,
                        "strike_type": (m.get("strike_type") or "").lower(),
                        "mutually_exclusive": e.get("mutually_exclusive"),
                    }
    return meta, len(paths)


def build_families(meta):
    """
    Group markets into ladder families.

    A family qualifies if: not mutually exclusive (nested rungs overlap, so
    Kalshi marks them False), at least 3 rungs with distinct numeric strikes,
    and one consistent direction. Mixed-direction families are dropped rather
    than guessed at — a family containing both "above X" and "below Y" rungs
    is not a single monotonic sequence.
    """
    by_event = defaultdict(list)
    for t, m in meta.items():
        if m["mutually_exclusive"] is not False:
            continue
        if m["strike"] is None:
            continue
        by_event[m["event"]].append((t, m))

    families, rejected = {}, defaultdict(int)
    for event, members in by_event.items():
        if len(members) < 3:
            rejected["too_few_rungs"] += 1
            continue

        types = {m["strike_type"] for _, m in members}
        desc = types & DESCENDING
        asc = types & ASCENDING
        if desc and asc:
            rejected["mixed_direction"] += 1
            continue
        if desc:
            direction = -1          # price falls as strike rises
        elif asc:
            direction = +1
        else:
            rejected["unknown_direction"] += 1
            continue

        strikes = [m["strike"] for _, m in members]
        if len(set(strikes)) != len(strikes):
            rejected["duplicate_strikes"] += 1
            continue

        members.sort(key=lambda tm: tm[1]["strike"])
        families[event] = {
            "series": members[0][1]["series"],
            "direction": direction,
            "rungs": [t for t, _ in members],
            "strikes": [m["strike"] for _, m in members],
        }
    return families, rejected


# ---------------------------------------------------------------- detection

def side(price_v, size_v):
    """
    A price with no size behind it is not a quote.

    Kalshi reports a price field even when no orders rest on that side —
    typically 0.0000 with yes_bid_size_fp of 0. Treating that as a real bid
    produced 1,661 "guaranteed profit" opportunities offering zero contracts,
    and fed fictional midpoints into the soft test. Returns (price_cents,
    size) or (None, None) if the side is empty.
    """
    p, s = cents(price_v), fnum(size_v)
    if p is None or s is None or s <= 0:
        return None, None
    return p, s


def detect_family(fam, state):
    """
    Test one family at one cycle.

    Rungs absent from state (market closed, never quoted) are dropped and the
    remaining ones tested pairwise in strike order. Monotonicity is
    transitive, so testing non-adjacent survivors is still valid — the gap
    field records how many strikes apart the tested pair was.

    Returns (violations, n_pairs_tested, n_rungs_present).
    """
    present = []
    for t, k in zip(fam["rungs"], fam["strikes"]):
        q = state.get(t)
        if q is not None and q.get("status") == "active":
            present.append((t, k, q))

    if len(present) < 2:
        return [], 0, len(present)

    d = fam["direction"]
    out, tested = [], 0

    for i in range(len(present) - 1):
        (t_lo, k_lo, q_lo) = present[i]
        (t_hi, k_hi, q_hi) = present[i + 1]
        tested += 1
        # How far apart the tested rungs are. Equals the normal rung spacing
        # unless intervening rungs were dropped for being unquoted.
        gap = round(k_hi - k_lo, 6)

        bid_lo, bsz_lo = side(q_lo["yes_bid_dollars"], q_lo.get("yes_bid_size_fp"))
        ask_lo, asz_lo = side(q_lo["yes_ask_dollars"], q_lo.get("yes_ask_size_fp"))
        bid_hi, bsz_hi = side(q_hi["yes_bid_dollars"], q_hi.get("yes_bid_size_fp"))
        ask_hi, asz_hi = side(q_hi["yes_ask_dollars"], q_hi.get("yes_ask_size_fp"))

        # --- SOFT: midpoints, needs all four quotes -----------------------
        if None not in (bid_lo, ask_lo, bid_hi, ask_hi):
            mid_lo = (bid_lo + ask_lo) / 2
            mid_hi = (bid_hi + ask_hi) / 2
            # d = -1: mid must fall, so mid_hi > mid_lo is a violation.
            # d = +1: mid must rise, so mid_lo > mid_hi is a violation.
            diff = (mid_hi - mid_lo) if d < 0 else (mid_lo - mid_hi)
            if diff > 0:
                out.append({
                    "kind": "soft", "magnitude_c": round(diff, 4),
                    "lower": t_lo, "upper": t_hi,
                    "strike_lo": k_lo, "strike_hi": k_hi, "gap": gap,
                    "depth": "",
                })

        # --- HARD: buy the cheap side, sell the dear side -----------------
        # For d = -1 the upper rung is the one that is overpriced, so we sell
        # it at its bid and buy the lower at its ask. Only those two sides
        # are needed; the other two quotes are irrelevant to the trade.
        if d < 0:
            buy_at, sell_at = ask_lo, bid_hi
            buy_size, sell_size = asz_lo, bsz_hi
        else:
            buy_at, sell_at = ask_hi, bid_lo
            buy_size, sell_size = asz_hi, bsz_lo

        # side() already guarantees size > 0 wherever a price survived, so a
        # violation reaching here is executable by construction.
        if buy_at is not None and sell_at is not None:
            edge = sell_at - buy_at
            if edge > 0:
                depth = min(buy_size, sell_size)
                if depth <= 0:
                    raise AssertionError(
                        f"hard violation with depth {depth} on {t_lo}/{t_hi} "
                        f"— side() should have filtered this. Stale file?")
                out.append({
                    "kind": "hard", "magnitude_c": round(edge, 4),
                    "lower": t_lo, "upper": t_hi,
                    "strike_lo": k_lo, "strike_hi": k_hi, "gap": gap,
                    "depth": depth,
                })

    return out, tested, len(present)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-cycles", type=int, default=None)
    args = ap.parse_args()

    print(f"06_detect version {__version__}")
    recon = _load_reconstructor()
    recon.DATA_DIR = DATA_DIR

    meta, n_dumps = load_metadata()
    print(f"metadata: {len(meta):,} markets from {n_dumps} recon dump(s)")

    families, rejected = build_families(meta)
    print(f"ladder families: {len(families):,}")
    for r, n in sorted(rejected.items(), key=lambda kv: -kv[1]):
        print(f"  rejected {n:>6,}  {r}")

    if not families:
        sys.exit("No ladder families. Check that 01_recon captured "
                 "mutually_exclusive=False events with strikes.")

    # Anchor outputs to the script directory, matching where 07_inspect and
    # 08_verify look for them. Writing CWD-relative while readers resolve
    # script-relative means new results land somewhere the readers never see.
    vio_path = os.path.join(_HERE, "violations.csv")
    fam_path = os.path.join(_HERE, "family_cycles.csv")
    vf = open(vio_path, "w", newline="")
    ff = open(fam_path, "w", newline="")
    vw = csv.DictWriter(vf, fieldnames=[
        "cycle", "ts", "event", "series", "kind", "magnitude_c", "depth",
        "lower", "upper", "strike_lo", "strike_hi", "gap"])
    fw = csv.DictWriter(ff, fieldnames=[
        "cycle", "ts", "event", "series", "n_rungs_present", "n_pairs_tested",
        "n_soft", "n_hard", "frac_soft", "frac_hard"])
    vw.writeheader()
    fw.writeheader()

    n_cycles = n_vio = n_fam_rows = 0
    totals = {"soft": 0, "hard": 0}
    by_series = defaultdict(lambda: {"tested": 0, "soft": 0, "hard": 0})
    last_ts = ""

    for cycle, state, _m in recon.replay(recon.read_rows()):
        n_cycles += 1
        if args.max_cycles and n_cycles > args.max_cycles:
            break

        for event, fam in families.items():
            vios, tested, present = detect_family(fam, state)
            if tested == 0:
                continue

            n_soft = sum(1 for v in vios if v["kind"] == "soft")
            n_hard = sum(1 for v in vios if v["kind"] == "hard")
            s = by_series[fam["series"]]
            s["tested"] += tested
            s["soft"] += n_soft
            s["hard"] += n_hard
            totals["soft"] += n_soft
            totals["hard"] += n_hard

            fw.writerow({
                "cycle": cycle, "ts": last_ts, "event": event,
                "series": fam["series"], "n_rungs_present": present,
                "n_pairs_tested": tested, "n_soft": n_soft, "n_hard": n_hard,
                "frac_soft": round(n_soft / tested, 4),
                "frac_hard": round(n_hard / tested, 4),
            })
            n_fam_rows += 1

            for v in vios:
                vw.writerow({"cycle": cycle, "ts": last_ts, "event": event,
                             "series": fam["series"], **v})
                n_vio += 1

    vf.close()
    ff.close()

    print(f"\ncycles processed : {n_cycles:,}")
    print(f"family-cycles    : {n_fam_rows:,}")
    print(f"violations       : {n_vio:,}  "
          f"(soft {totals['soft']:,}, hard {totals['hard']:,})")

    print("\nby series (violation rate per pair tested):")
    print(f"  {'series':<22} {'pairs':>12} {'soft':>9} {'hard':>9}")
    for s, d in sorted(by_series.items(), key=lambda kv: -kv[1]["tested"]):
        if not d["tested"]:
            continue
        print(f"  {s:<22} {d['tested']:>12,} "
              f"{d['soft']/d['tested']:>8.3%} {d['hard']/d['tested']:>8.3%}")

    print(f"\nwrote {vio_path} and {fam_path}")


if __name__ == "__main__":
    main()