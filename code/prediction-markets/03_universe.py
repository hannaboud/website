#!/usr/bin/env python3
"""
03_universe.py — Corrected structural classification.

Fixes three errors in 02_classify.py, all visible in its own output:

  1. BUCKET/LADDER inversion. Temperature families print rungs like
     "74 or below | 75 to 76 | 77 to 78" — disjoint ranges, i.e. a partition.
     02 labelled them LADDER because a single open-ended top rung
     (strike_type 'greater') flipped the whole family. Classification now
     works on the proportion of two-sided rungs, not the presence of any
     one-sided one.

  2. Rules check always failed (172/172). rules_primary embeds each rung's own
     threshold, so the texts are *supposed* to differ. Compare instead:
     event-level settlement_sources, and rules text with numbers stripped.

  3. Ladders were excluded by construction. Nested thresholds ("1+", "2+",
     "3+") overlap, so multiple rungs can resolve YES, so Kalshi marks them
     mutually_exclusive: False. Filtering on True deleted them. Now scans both.

Outputs:
    partitions.csv   sum-to-100c families
    ladders.csv      monotonicity families

Usage:
    python 03_universe.py [raw/events_X.jsonl]
"""

import csv
import glob
import json
import re
import sys
from collections import Counter, defaultdict

MIN_MARKETS = 3
OPEN_LOW = re.compile(r"\b(or below|or less|or fewer|below|under|<)\b", re.I)
OPEN_HIGH = re.compile(r"\b(or above|or more|or greater|\+|above|over|>)\b", re.I)
RANGE_PAT = re.compile(r"\bto\b|-|–", re.I)
NUMS = re.compile(r"[-+]?\d[\d,]*\.?\d*")


def load(path=None):
    if path is None:
        files = sorted(glob.glob("raw/events_*.jsonl"))
        if not files:
            sys.exit("No raw/events_*.jsonl found. Run 01_recon.py first.")
        path = files[-1]
    print(f"Reading {path}\n")
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def sub(m):
    return (m.get("yes_sub_title") or m.get("subtitle") or "").strip()


# ------------------------------------------------------------ structure

def rung_kind(m):
    """
    TWO_SIDED : bounded range      ('75 to 76', floor+cap)
    ONE_SIDED : open threshold     ('74 or below', '30+')
    OPAQUE    : neither            (a named candidate)
    """
    floor, cap = m.get("floor_strike"), m.get("cap_strike")
    s = sub(m)

    if floor is not None and cap is not None:
        return "TWO_SIDED"
    if RANGE_PAT.search(s) and len(NUMS.findall(s)) >= 2:
        return "TWO_SIDED"
    if floor is not None or cap is not None:
        return "ONE_SIDED"
    if OPEN_LOW.search(s) or OPEN_HIGH.search(s):
        return "ONE_SIDED"
    return "OPAQUE"


def survey_strike_types(events):
    """
    Count what strike_type actually contains, with a real example of each.
    Rescued from 02_classify.py — the one function in that file that was
    right, because it counts instead of judging.

    This runs BEFORE classification on purpose. The bug in 02 came from
    writing branches against a structure I'd assumed; seeing the distribution
    first is what prevents a repeat. It also catches drift: a strike_type
    appearing here that the classifier doesn't handle is a signal to look.
    """
    types = Counter()
    example = {}

    for e in events:
        for m in e.get("markets") or []:
            st = m.get("strike_type") or "(absent)"
            types[st] += 1
            if st not in example:
                example[st] = m

    print("=" * 70)
    print("STRIKE TYPES OBSERVED")
    print("=" * 70)
    total = sum(types.values()) or 1
    for st, c in types.most_common():
        m = example[st]
        print(f"\n  {st:<18} {c:>7,}  ({c/total:5.1%})")
        print(f"      e.g. {m.get('ticker')}")
        print(f"      sub_title : {m.get('yes_sub_title')}")
        print(f"      floor={m.get('floor_strike')}  cap={m.get('cap_strike')}")

    handled = {"greater", "greater_or_equal", "less", "less_or_equal",
               "between", "structured", "custom", "(absent)"}
    unknown = set(types) - handled
    if unknown:
        print(f"\n  !! UNSEEN strike_type values: {sorted(unknown)}")
        print("     Check how the classifier treats these before trusting results.")
    return types


def classify(event):
    """
    PARTITION : mostly bounded ranges, disjoint, covering the outcome space.
                Test: prices sum to 100c.
    LADDER    : all rungs are one-sided thresholds on the same scale, nested.
                Test: monotonicity in the strike.
    """
    markets = event.get("markets") or []
    if len(markets) < MIN_MARKETS:
        return "TOO_SMALL", {}

    kinds = Counter(rung_kind(m) for m in markets)
    n = len(markets)
    two, one, opaque = kinds["TWO_SIDED"], kinds["ONE_SIDED"], kinds["OPAQUE"]

    subs = [sub(m) for m in markets]
    has_open_low = any(OPEN_LOW.search(s) for s in subs)
    has_open_high = any(OPEN_HIGH.search(s) for s in subs)

    # Strikes, for ordering and for the nesting test.
    strikes = []
    for m in markets:
        k = fnum(m.get("floor_strike"))
        if k is None:
            k = fnum(m.get("cap_strike"))
        if k is not None:
            strikes.append(k)

    meta = {
        "n_two_sided": two,
        "n_one_sided": one,
        "n_opaque": opaque,
        "open_low": has_open_low,
        "open_high": has_open_high,
        "n_strikes": len(strikes),
        "strikes_distinct": len(set(strikes)) == len(strikes) if strikes else False,
    }

    if opaque > 0.5 * n:
        return "NAMED_FIELD", meta          # candidate lists — weakest constraint

    # A partition is dominated by bounded ranges; the one-sided rungs are just
    # the two open ends. Do NOT let those ends decide the label.
    if two >= 0.5 * n and one <= 2:
        # Exhaustive only if both ends are open.
        meta["exhaustive"] = has_open_low and has_open_high
        return "PARTITION", meta

    # A ladder is one-sided all the way down, on distinct ordered strikes.
    if one >= 0.9 * n and len(strikes) >= MIN_MARKETS and meta["strikes_distinct"]:
        return "LADDER", meta

    return "MIXED", meta


# ------------------------------------------------------------ rules

def rules_comparable(event):
    """
    Family members must settle off the same source at the same time.
    rules_primary legitimately differs per rung (it names that rung's
    threshold), so strip numbers before comparing, and check the event-level
    settlement_sources too.
    """
    markets = event.get("markets") or []

    skeletons = set()
    for m in markets:
        txt = (m.get("rules_primary") or "")
        skeletons.add(NUMS.sub("#", txt).strip().lower())

    srcs = event.get("settlement_sources") or []
    src_names = tuple(sorted((s or {}).get("name", "") for s in srcs))

    closes = {m.get("close_time") for m in markets}

    return {
        "rules_skeleton_uniform": len(skeletons) <= 1,
        "n_rule_skeletons": len(skeletons),
        "settlement_sources": "|".join(n for n in src_names if n),
        "close_times_uniform": len(closes) <= 1,
    }


# ------------------------------------------------------------ main

def main():
    events = load(sys.argv[1] if len(sys.argv) > 1 else None)
    print(f"{len(events):,} events, "
          f"{sum(len(e.get('markets') or []) for e in events):,} markets\n")

    survey_strike_types(events)

    shapes_by_flag = defaultdict(Counter)
    partitions, ladders = [], []

    for e in events:
        flag = e.get("mutually_exclusive")
        shape, meta = classify(e)
        shapes_by_flag[flag][shape] += 1

        if shape not in ("PARTITION", "LADDER"):
            continue

        markets = e.get("markets") or []
        vol24 = sum(fnum(m.get("volume_24h_fp")) or 0 for m in markets)
        liq = sum(fnum(m.get("liquidity_dollars")) or 0 for m in markets)
        rc = rules_comparable(e)

        row = {
            "event_ticker": e.get("event_ticker", ""),
            "series_ticker": e.get("series_ticker", ""),
            "title": (e.get("title") or "")[:80],
            "category": e.get("category", ""),
            "mutually_exclusive": flag,
            "shape": shape,
            "n_markets": len(markets),
            "volume_24h": round(vol24, 2),
            "liquidity": round(liq, 2),
            "exhaustive": meta.get("exhaustive", ""),
            "rules_uniform": rc["rules_skeleton_uniform"],
            "n_rule_skeletons": rc["n_rule_skeletons"],
            "close_times_uniform": rc["close_times_uniform"],
            "settlement_sources": rc["settlement_sources"][:60],
            "close_time": markets[0].get("close_time", "") if markets else "",
            "rungs": " | ".join(sub(m) for m in markets[:5]),
        }
        (partitions if shape == "PARTITION" else ladders).append(row)

    print("=" * 70)
    print("SHAPE BY mutually_exclusive FLAG")
    print("=" * 70)
    for flag in (True, False, None):
        c = shapes_by_flag.get(flag)
        if not c:
            continue
        print(f"\n  mutually_exclusive = {flag}   ({sum(c.values()):,} events)")
        for s, n in c.most_common():
            print(f"      {s:<14} {n:>6,}")

    for name, rows in (("PARTITIONS  (test: sum to 100c)", partitions),
                       ("LADDERS     (test: monotonicity)", ladders)):
        rows.sort(key=lambda r: -r["volume_24h"])
        active = [r for r in rows if r["volume_24h"] > 0]
        clean = [r for r in active if r["rules_uniform"] and r["close_times_uniform"]]

        print("\n" + "=" * 70)
        print(name)
        print("=" * 70)
        print(f"  total ............... {len(rows):,}")
        print(f"  traded in 24h ....... {len(active):,}")
        print(f"  ... rules+close OK .. {len(clean):,}")
        if rows and "exhaustive" in rows[0]:
            exh = [r for r in active if r["exhaustive"] is True]
            print(f"  ... exhaustive ...... {len(exh):,}")

        for r in active[:12]:
            flags = []
            if not r["rules_uniform"]:
                flags.append(f"rules x{r['n_rule_skeletons']}")
            if not r["close_times_uniform"]:
                flags.append("close times differ")
            if r["exhaustive"] is False:
                flags.append("NOT exhaustive")
            tag = ("  [" + ", ".join(flags) + "]") if flags else ""
            print(f"\n  {r['event_ticker']:<28} 24h {r['volume_24h']:>10,.0f}"
                  f"  ME={r['mutually_exclusive']}{tag}")
            print(f"      {r['title']}")
            print(f"      {r['rungs'][:105]}")

        series = defaultdict(float)
        for r in active:
            series[r["series_ticker"]] += r["volume_24h"]
        print(f"\n  top series:")
        for s, v in sorted(series.items(), key=lambda kv: -kv[1])[:12]:
            print(f"      {s:<24} {v:>12,.0f}")

    for fn, rows in (("partitions.csv", partitions), ("ladders.csv", ladders)):
        if rows:
            with open(fn, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            print(f"\nWrote {fn} ({len(rows):,} rows)")

    print("\n" + "=" * 70)
    print("CHECK BY EYE: partition rungs should be disjoint ranges with open")
    print("ends; ladder rungs should be nested thresholds on one scale.")
    print("If a family looks wrong here, it will look wrong in the results.")
    print("=" * 70)


if __name__ == "__main__":
    main()
