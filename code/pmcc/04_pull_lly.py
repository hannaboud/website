"""
Step 4 - Pull every price the LLY Poor Man's Covered Call backtest needs.

Method (same as the NVDA assignment): option RICs are built by hand and queried
one at a time with daily history. No search, because search does not return
expired contracts.

Run with Workspace open:   python 04_pull_lly.py
Takes roughly 30-60 minutes (about 3,500 single requests). It caches each week,
so if it stops you can re-run it and it resumes where it left off.

Outputs (./data):
    stock.csv         daily OHLC for LLY.N
    weekly_calls.csv  one row per (date, weekly call): bid, ask, mid, last, delta, iv
    leap_calls.csv    same columns for the long-call candidates
"""
import os
import datetime as dt
import concurrent.futures
import warnings
import pandas as pd
import lseg.data as ld

warnings.filterwarnings("ignore", category=FutureWarning)

# ---------------- parameters ----------------
STOCK = "LLY.N"
ROOT = "LLY"
START = dt.date(2025, 10, 3)        # long call bought at this close
END = dt.date(2026, 10, 2)
WARMUP = dt.date(2025, 8, 15)       # extra stock history for the 21-day MA
WEEKLY_UP = 1.15                    # weekly strikes pulled from spot up to spot * this
WEEKLY_MIN_TOP = 900.0              # ...and at least up to here (room for the breakeven floor)
WEEKLY_STEP = 2.5
LEAP1_EXPIRY = dt.date(2026, 9, 18)
LEAP2_EXPIRIES = [dt.date(2027, 6, 18), dt.date(2027, 9, 17), dt.date(2028, 1, 21)]
LEAP_LO, LEAP_HI, LEAP_STEP = 0.55, 0.95, 10.0   # strikes as a fraction of spot
TIMEOUT = 30
OUT = "data"
KEEP = ["BID", "ASK", "MID_PRICE", "TRDPRC_1", "DELTA", "IMP_VOLT"]
# --------------------------------------------

TODAY = dt.date.today()
CALL_LETTERS = "ABCDEFGHIJKL"


def build_ric(expiry, strike, expired):
    """US OPRA call RIC. Strikes >= 1000 use a lowercase month letter and strike*10
    (confirmed in 03_lly_data_test.py: LLYi252611400.U^I26)."""
    m = CALL_LETTERS[expiry.month - 1]
    dd, yy = f"{expiry.day:02d}", f"{expiry.year % 100:02d}"
    if strike < 1000:
        body = f"{m}{dd}{yy}{round(strike * 100):05d}"
    else:
        body = f"{m.lower()}{dd}{yy}{round(strike * 10):05d}"
    return f"{ROOT}{body}.U" + (f"^{m}{yy}" if expired else "")


def get_history(**kw):
    """ld.get_history with a timeout; returns None if not found / empty / hung."""
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(ld.get_history, **kw)
    try:
        df = fut.result(timeout=TIMEOUT)
    except Exception:
        df = None
    ex.shutdown(wait=False)
    return df if df is not None and not df.empty else None


def fetch_contract(expiry, strike, start, end):
    """Daily history of one call as tidy rows, or an empty list if it does not exist."""
    expired = expiry < TODAY
    for flag in (expired, not expired):          # a just-expired contract may still be under the live code
        ric = build_ric(expiry, strike, flag)
        df = get_history(universe=ric, interval="daily", start=str(start), end=str(end))
        if df is not None:
            break
    else:
        return []
    rows = []
    for date, r in df.iterrows():
        row = {"date": pd.Timestamp(date).date(), "expiry": expiry, "strike": strike, "ric": ric}
        for c in KEEP:
            row[c.lower()] = r[c] if c in df.columns and pd.notna(r[c]) else None
        if row["bid"] is not None or row["ask"] is not None:
            rows.append(row)
    return rows


def strike_grid(lo, hi, step):
    k = (lo // step) * step
    out = []
    while k <= hi:
        if k >= lo:
            out.append(round(k, 2))
        k += step
    return out


def main():
    os.makedirs(f"{OUT}/cache", exist_ok=True)
    ld.open_session()

    # ---- stock ----
    stock = ld.get_history(universe=STOCK, fields=["OPEN_PRC", "HIGH_1", "LOW_1", "TRDPRC_1"],
                           interval="daily", start=str(WARMUP), end=str(END + dt.timedelta(days=1)))
    stock.index = pd.to_datetime(stock.index).date
    stock.index.name = "date"
    stock = stock[stock["TRDPRC_1"].notna()]
    stock.to_csv(f"{OUT}/stock.csv")
    close = stock["TRDPRC_1"].astype(float)
    days = list(close.index)
    print(f"stock: {len(days)} days, {days[0]} to {days[-1]}")

    # ---- weeks: (decision day = prior trading day, entry = first day of week, expiry = last day of week) ----
    by_week = {}
    for d in days:
        by_week.setdefault(d.isocalendar()[:2], []).append(d)
    weeks = []
    for key in sorted(by_week):
        entry, expiry = by_week[key][0], by_week[key][-1]
        if entry <= START or expiry > END:
            continue
        decision = days[days.index(entry) - 1]
        weeks.append((decision, entry, expiry))
    print(f"weeks: {len(weeks)}, first {weeks[0]}, last {weeks[-1]}")

    # ---- weekly short-call candidates ----
    frames = []
    for i, (decision, entry, expiry) in enumerate(weeks, 1):
        cache = f"{OUT}/cache/week_{entry}.csv"
        if os.path.exists(cache):
            frames.append(pd.read_csv(cache))
            continue
        spot = close[decision]
        strikes = strike_grid(spot * 0.99, max(spot * WEEKLY_UP, WEEKLY_MIN_TOP), WEEKLY_STEP)
        rows = []
        for k in strikes:
            rows += fetch_contract(expiry, k, decision, expiry + dt.timedelta(days=1))
        df = pd.DataFrame(rows)
        n = df["strike"].nunique() if len(df) else 0
        print(f"  [{i}/{len(weeks)}] week {entry} -> {expiry}  spot {spot:.2f}  "
              f"{n} of {len(strikes)} strikes found")
        if n:
            df.to_csv(cache, index=False)
            frames.append(df)
    pd.concat(frames, ignore_index=True).to_csv(f"{OUT}/weekly_calls.csv", index=False)

    # ---- long-call candidates ----
    def leap_block(expiries, spot, start, end, tag):
        cache = f"{OUT}/cache/leap_{tag}.csv"
        if os.path.exists(cache):
            return pd.read_csv(cache)
        rows = []
        for expiry in expiries:
            before = len(rows)
            for k in strike_grid(spot * LEAP_LO, spot * LEAP_HI, LEAP_STEP):
                rows += fetch_contract(expiry, k, start, end)
            print(f"  long call {expiry}: {len({r['strike'] for r in rows[before:]})} strikes found")
        df = pd.DataFrame(rows)
        if len(df):
            df.to_csv(cache, index=False)
        return df

    prev_start = days[days.index(START) - 1]            # day before purchase, for its delta
    leap1 = leap_block([LEAP1_EXPIRY], close[START], prev_start, LEAP1_EXPIRY + dt.timedelta(days=1), "first")
    roll_day = max(d for d in days if d <= LEAP1_EXPIRY)
    prev_roll = days[days.index(roll_day) - 1]
    leap2 = leap_block(LEAP2_EXPIRIES, close[roll_day], prev_roll, END + dt.timedelta(days=1), "second")
    pd.concat([leap1, leap2], ignore_index=True).to_csv(f"{OUT}/leap_calls.csv", index=False)

    ld.close_session()
    print("\nDone. Files in ./data: stock.csv, weekly_calls.csv, leap_calls.csv")


if __name__ == "__main__":
    main()
