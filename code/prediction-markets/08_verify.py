#!/usr/bin/env python3
"""
08_verify.py — Settle whether the zero-size fix is actually running.

The symptom: soft violations changed but hard violations did not, and the
assertion guarding zero-depth hard violations never fired. Those cannot all
be true of one run, so something is stale. This checks which.

  1. File timestamps. If violations.csv is older than 06_detect.py, the
     results were produced by an earlier version of the detector.
  2. Live behaviour. Imports detect_family from the 06_detect.py sitting on
     disk right now and feeds it a zero-size book. If a hard violation comes
     back, the fix is not in that file.
  3. The actual quotes behind a reported violation, pulled from the data, so
     the prices and sizes can be read directly instead of inferred.

Usage:
    python 08_verify.py
"""

import csv
import glob
import gzip
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone

_HERE = os.path.dirname(os.path.abspath(__file__))


def stamp(path):
    if not os.path.exists(path):
        return "MISSING"
    st = os.stat(path)
    t = datetime.fromtimestamp(st.st_mtime, timezone.utc)
    h = hashlib.md5(open(path, "rb").read()).hexdigest()[:8]
    return f"{t:%Y-%m-%d %H:%M:%S}Z  {st.st_size:>9,}b  md5:{h}"


def check_files():
    print("=" * 66)
    print("1. FILE FRESHNESS")
    print("=" * 66)
    files = ["06_detect.py", "violations.csv", "family_cycles.csv"]
    ts = {}
    for f in files:
        p = os.path.join(_HERE, f)
        print(f"  {f:<20} {stamp(p)}")
        ts[f] = os.stat(p).st_mtime if os.path.exists(p) else 0

    if ts["violations.csv"] and ts["violations.csv"] < ts["06_detect.py"]:
        print("\n  !! violations.csv is OLDER than 06_detect.py.")
        print("     These results came from a previous version. Re-run 06.")
        return False
    print("\n  violations.csv is newer than the detector — results are current.")
    return True


def check_behaviour():
    print("\n" + "=" * 66)
    print("2. LIVE DETECTOR BEHAVIOUR")
    print("=" * 66)
    path = os.path.join(_HERE, "06_detect.py")
    spec = importlib.util.spec_from_file_location("d", path)
    d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(d)

    def q(bid, ask, bsz, asz):
        return {"yes_bid_dollars": bid, "yes_ask_dollars": ask,
                "yes_bid_size_fp": bsz, "yes_ask_size_fp": asz,
                "status": "active"}

    fam = {"series": "S", "direction": -1,
           "rungs": ["R1", "R2"], "strikes": [1.0, 2.0]}

    # Crossed prices, but the bid we would sell into has zero size.
    st = {"R1": q("0.43", "0.45", "30", "200"),
          "R2": q("0.50", "0.52", "0", "40")}
    try:
        v, _t, _p = d.detect_family(fam, st)
    except AssertionError as e:
        print(f"  assertion fired: {e}")
        print("  -> side() is NOT filtering. Fix is absent from this file.")
        return False

    hard = [x for x in v if x["kind"] == "hard"]
    print(f"  zero-size bid, crossed prices -> hard violations: {len(hard)}")
    if hard:
        print(f"     {hard}")
        print("  -> FIX IS NOT ACTIVE in this 06_detect.py")
        return False

    # Control: same prices, real size. Should produce one hard violation.
    st2 = {"R1": q("0.43", "0.45", "30", "200"),
           "R2": q("0.50", "0.52", "150", "40")}
    v2, _t, _p = d.detect_family(fam, st2)
    hard2 = [x for x in v2 if x["kind"] == "hard"]
    print(f"  real size,      crossed prices -> hard violations: {len(hard2)}"
          f"  depth={hard2[0]['depth'] if hard2 else '-'}")
    if len(hard2) == 1:
        print("\n  -> FIX IS ACTIVE and working correctly.")
        return True
    print("\n  -> control case failed; the detector is not behaving as expected.")
    return False


def show_raw_examples(n=3):
    print("\n" + "=" * 66)
    print("3. RAW QUOTES BEHIND REPORTED HARD VIOLATIONS")
    print("=" * 66)
    vpath = os.path.join(_HERE, "violations.csv")
    if not os.path.exists(vpath):
        print("  no violations.csv")
        return
    with open(vpath) as f:
        hard = [r for r in csv.DictReader(f) if r["kind"] == "hard"]
    if not hard:
        print("  no hard violations in the file")
        return

    want = {}
    for r in hard[:n]:
        want[r["lower"]] = None
        want[r["upper"]] = None

    latest = {}
    for p in sorted(glob.glob(os.path.join(_HERE, "data", "quotes_*.jsonl.gz"))):
        try:
            with gzip.open(p, "rt") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("ticker") in want:
                        latest[row["ticker"]] = row
        except (OSError, EOFError):
            continue

    for r in hard[:n]:
        print(f"\n  {r['event']}  cycle {r['cycle']}  "
              f"edge {r['magnitude_c']}c  depth {r['depth']}")
        for role, tick in (("lower (buy at ask)", r["lower"]),
                           ("upper (sell at bid)", r["upper"])):
            row = latest.get(tick)
            if not row:
                print(f"    {role:<20} {tick}  (no quote found)")
                continue
            print(f"    {role:<20} {tick}")
            print(f"       bid {row.get('yes_bid_dollars')} "
                  f"x {row.get('yes_bid_size_fp')}   "
                  f"ask {row.get('yes_ask_dollars')} "
                  f"x {row.get('yes_ask_size_fp')}")
    print("\n  Note: these are the LAST quotes seen for those tickers, not")
    print("  necessarily the ones at the violating cycle. Use them to judge")
    print("  whether sizes are plausibly zero, not as exact reproduction.")


def main():
    fresh = check_files()
    ok = check_behaviour()
    show_raw_examples()

    print("\n" + "=" * 66)
    if ok and fresh:
        print("VERDICT: detector is correct and results are current.")
        print("If hard violations still show zero depth, the depth column is")
        print("being written by something other than the path we inspected.")
    elif ok and not fresh:
        print("VERDICT: detector is correct but violations.csv is stale.")
        print("Re-run: python 06_detect.py")
    else:
        print("VERDICT: the 06_detect.py on disk does not have the fix.")
        print("Re-download it and check for a second copy on your PATH.")
    print("=" * 66)


if __name__ == "__main__":
    main()
