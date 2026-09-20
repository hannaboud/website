#!/usr/bin/env python3
"""
07_inspect.py — Interrogate the results before believing them.

Three questions:

  1. Which cycles are keyframes, and which mark did they get? Confirms that
     scheduled keyframes (_kf 1) validate and resume keyframes (_kf 2) are
     correctly excluded.

  2. What do the hard violations actually look like? A "guaranteed profit"
     of 1 cent on 3 contracts is technically executable and economically
     nothing. Magnitude and depth decide whether the finding is real.

  3. How long do violations last? A crude preview of the headline metric,
     measured in consecutive cycles rather than wall-clock seconds. Runs of
     one cycle are noise; long runs are the interesting part.

Usage:
    python 07_inspect.py
"""

import csv
import glob
import gzip
import json
import os
import sys
from collections import Counter, defaultdict

_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")
VIOLATIONS = os.path.join(_HERE, "violations.csv")
INTERVAL_S = 15


def pct(xs, p):
    if not xs:
        return None
    xs = sorted(xs)
    i = min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))
    return xs[i]


def hist(counter, width=40, top=12):
    if not counter:
        return
    mx = max(counter.values())
    for k, v in sorted(counter.items())[:top]:
        bar = "#" * max(1, int(width * v / mx))
        print(f"    {str(k):>8}  {v:>7,}  {bar}")


# ---------------------------------------------------------------- 1. keyframes

def keyframe_census():
    print("=" * 66)
    print("1. KEYFRAME CENSUS")
    print("=" * 66)
    c = Counter()
    for f in sorted(glob.glob(os.path.join(DATA_DIR, "quotes_*.jsonl.gz"))):
        try:
            with gzip.open(f, "rt") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("_kf"):
                        c[(r.get("_cycle"), r["_kf"])] += 1
        except (OSError, EOFError):
            continue

    if not c:
        print("  no keyframes found")
        return
    label = {1: "scheduled (validated)", 2: "resume (not checkable)"}
    for (cycle, kf), n in sorted(c.items()):
        print(f"  cycle {cycle:>6}  _kf={kf}  {n:>6,} rows   {label.get(kf, '?')}")
    print("\n  Mismatches reported by 05 should come only from cycles whose")
    print("  mark is 1 but which were actually resumes — i.e. written before")
    print("  the _kf 2 fix. Those age out as the data rolls forward.")


# ---------------------------------------------------------------- 2. anatomy

def load_violations():
    if not os.path.exists(VIOLATIONS):
        sys.exit(f"Missing {VIOLATIONS}. Run 06_detect.py first.")
    with open(VIOLATIONS) as f:
        return list(csv.DictReader(f))


def anatomy(rows):
    print("\n" + "=" * 66)
    print("2. HARD VIOLATION ANATOMY")
    print("=" * 66)
    hard = [r for r in rows if r["kind"] == "hard"]
    soft = [r for r in rows if r["kind"] == "soft"]
    print(f"  hard: {len(hard):,}    soft: {len(soft):,}")
    if not hard:
        print("  none to inspect")
        return

    mags = [float(r["magnitude_c"]) for r in hard]
    print("\n  magnitude (cents of guaranteed edge):")
    hist(Counter(round(m) for m in mags))
    print(f"    median {pct(mags,50):.1f}   p90 {pct(mags,90):.1f}   "
          f"max {max(mags):.1f}")

    deps = [float(r["depth"]) for r in hard if r["depth"]]
    if deps:
        print("\n  depth (contracts available at the crossing price):")
        print(f"    min {min(deps):g}   p25 {pct(deps,25):g}   "
              f"median {pct(deps,50):g}   p75 {pct(deps,75):g}   "
              f"max {max(deps):g}")
        for thr in (0.01, 0.1, 1, 10, 100, 1000):
            n = sum(1 for d in deps if d >= thr)
            print(f"    >= {thr:>6g} contracts: {n:>7,}  ({n/len(deps):6.1%})")

    print("\n  dollar value of the edge (magnitude x depth, capped at depth):")
    vals = [float(r["magnitude_c"]) / 100 * float(r["depth"])
            for r in hard if r["depth"]]
    if vals:
        print(f"    median ${pct(vals,50):.4f}   p90 ${pct(vals,90):.4f}   "
              f"max ${max(vals):.4f}")

    print("\n  rung gap (0 = adjacent rungs, larger = rungs were dropped):")
    hist(Counter(r["gap"] for r in hard), top=8)

    ev = Counter(r["event"] for r in hard)
    print(f"\n  spread across {len(ev):,} distinct events")
    print(f"    top event holds {ev.most_common(1)[0][1]:,} "
          f"({ev.most_common(1)[0][1]/len(hard):.1%} of all hard violations)")
    for e, n in ev.most_common(5):
        print(f"      {n:>6,}  {e}")

    print("\n  soft magnitudes, for comparison:")
    smags = [float(r["magnitude_c"]) for r in soft]
    if smags:
        print(f"    median {pct(smags,50):.1f}   p90 {pct(smags,90):.1f}   "
              f"max {max(smags):.1f}")


# ---------------------------------------------------------------- 3. runs

def persistence_preview(rows):
    """
    Group by (event, rung pair, kind) and find runs of consecutive cycles.

    This is the headline metric in miniature. It measures cycles, not
    seconds, and it does not exclude collector gaps — so treat it as a
    preview, not a result. The real stitcher has to do both.
    """
    print("\n" + "=" * 66)
    print("3. PERSISTENCE PREVIEW (consecutive cycles, gaps NOT excluded)")
    print("=" * 66)

    by_pair = defaultdict(list)
    for r in rows:
        key = (r["kind"], r["event"], r["lower"], r["upper"])
        try:
            by_pair[key].append(int(r["cycle"]))
        except (TypeError, ValueError):
            continue

    runs = defaultdict(list)
    for (kind, *_), cycles in by_pair.items():
        cycles.sort()
        start = prev = cycles[0]
        for c in cycles[1:] + [None]:
            if c is None or c != prev + 1:
                runs[kind].append(prev - start + 1)
                start = c
            prev = c if c is not None else prev

    for kind in ("soft", "hard"):
        rr = runs.get(kind)
        if not rr:
            continue
        print(f"\n  {kind}: {len(rr):,} episodes")
        print(f"    1 cycle only : {sum(1 for x in rr if x==1):>7,}  "
              f"({sum(1 for x in rr if x==1)/len(rr):.1%})")
        print(f"    median       : {pct(rr,50)} cycles "
              f"(~{pct(rr,50)*INTERVAL_S}s)")
        print(f"    p90          : {pct(rr,90)} cycles "
              f"(~{pct(rr,90)*INTERVAL_S}s)")
        print(f"    max          : {max(rr)} cycles "
              f"(~{max(rr)*INTERVAL_S/60:.1f} min)")
        print("    run-length distribution (last bucket is 20 OR MORE):")
        hist(Counter(min(x, 20) for x in rr), top=20)

    print("\n  A median of 1 cycle means most violations are gone before the")
    print("  next poll — order books updating out of step, not inefficiency.")
    print("  The long tail is where genuine inattention lives.")


def main():
    keyframe_census()
    rows = load_violations()
    anatomy(rows)
    persistence_preview(rows)


if __name__ == "__main__":
    main()