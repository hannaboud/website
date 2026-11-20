"""
MSFT implied vs realized volatility signal -> data/vol_history.csv

Hanna's definitions:
  IV     : average of the call and put IMP_VOLT (LSEG) at the strike closest to that day's close,
           for the weekly expiry 5 to 12 calendar days out
  RV     : 21-day close-to-close log returns, sample std, annualized with sqrt(252)
  spread : IV - RV                          (both in vol points, e.g. 0.34 - 0.27 = 0.07)
  z      : (spread - mean of last 63 spreads) / std of last 63 spreads
  prices : price_history.json (course server) from 2026-09-22 on; LSEG MSFT.O closes before that

The first run backfills the whole history (a few minutes of LSEG calls). Later runs only add new days.

Login: reads LSEG_APP_KEY / LSEG_USERNAME / LSEG_PASSWORD from the environment (GitHub secrets);
if they are missing it asks for them in the terminal.
"""

import concurrent.futures
import json
import math
import os
import warnings
from datetime import date, timedelta
from getpass import getpass

import pandas as pd

warnings.filterwarnings("ignore")

ROOT = os.path.dirname(os.path.abspath(__file__))
PRICE_FILE = os.path.join(ROOT, "price_history.json")
HISTORY_FILE = os.path.join(ROOT, "data", "vol_history.csv")

CONID = "272093"            # MSFT in price_history.json
STOCK_RIC = "MSFT.O"
OPT_ROOT = "MSFT"
RV_DAYS = 21
Z_DAYS = 63
MIN_DTE, MAX_DTE = 5, 12    # calendar days to expiry for the "1-week" option
STRIKE_STEP = 2.5           # candidate grid; a strike that is not listed simply returns no data
STRIKE_TRIES = 6            # how many nearest candidate strikes to try
TIMEOUT = 30

CALL_LETTERS = "ABCDEFGHIJKL"
PUT_LETTERS = "MNOPQRSTUVWX"


# ---------------------------------------------------------------- LSEG

def login():
    import lseg.data as ld
    app_key = os.environ.get("LSEG_APP_KEY") or getpass("LSEG app key (hidden): ").strip()
    username = os.environ.get("LSEG_USERNAME") or input("LSEG username: ").strip()
    password = os.environ.get("LSEG_PASSWORD") or getpass("LSEG password (hidden): ")
    session = ld.session.platform.Definition(
        app_key=app_key,
        grant=ld.session.platform.GrantPassword(username=username, password=password),
        signon_control=True,
    ).get_session()
    session.open()
    ld.session.set_default(session)
    return ld, session


def history(ld, **kw):
    """ld.get_history with a timeout; None if not found, empty, or hung."""
    ex = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(ld.get_history, **kw)
    try:
        df = fut.result(timeout=TIMEOUT)
    except Exception:
        df = None
    ex.shutdown(wait=False)
    return df if df is not None and not df.empty else None


def option_ric(expiry, strike, right, expired):
    """US option RIC, same format as the SPY wheel: MSFTK272650000.U, expired -> ...U^K26."""
    m = (CALL_LETTERS if right == "C" else PUT_LETTERS)[expiry.month - 1]
    yy = f"{expiry.year % 100:02d}"
    body = f"{m}{expiry.day:02d}{yy}{round(strike * 100):05d}"
    suffix = f"^{CALL_LETTERS[expiry.month - 1]}{yy}" if expired else ""
    return f"{OPT_ROOT}{body}.U{suffix}"


_cache = {}


def option_history(ld, expiry, strike, right, start):
    """Daily history of one contract (cached). Tries the expired and live RIC forms."""
    key = (expiry, strike, right)
    if key not in _cache:
        df = None
        for expired in (expiry < date.today(), expiry >= date.today()):
            df = history(ld, universe=option_ric(expiry, strike, right, expired), interval="daily",
                         start=str(start), end=str(expiry + timedelta(days=1)))
            if df is not None:
                break
        if df is not None:
            df.index = pd.to_datetime(df.index).date
        _cache[key] = df
    return _cache[key]


# ---------------------------------------------------------------- prices

def load_closes(ld, need_from):
    """price_history.json closes from its first day on; LSEG MSFT.O closes before that."""
    with open(PRICE_FILE) as f:
        bars = json.load(f)[CONID]["price_history"]
    course = pd.Series({date.fromisoformat(d): v["close"] for d, v in bars.items()}).sort_index()
    first = course.index[0]
    lseg = history(ld, universe=STOCK_RIC, fields=["TRDPRC_1"], interval="daily",
                   start=str(need_from), end=str(first))
    older = pd.Series(dtype=float)
    if lseg is not None:
        older = lseg["TRDPRC_1"].astype(float)
        older.index = pd.to_datetime(older.index).date
        older = older[older.index < first]
    closes = pd.concat([older, course]).sort_index()
    source = pd.Series(["LSEG"] * len(older) + ["price_history.json"] * len(course), index=closes.index)
    return closes, source


# ---------------------------------------------------------------- IV for one day

def weekly_expiry(day):
    """The Friday 5-12 calendar days after `day` (Thursday if that Friday is an NYSE holiday)."""
    for dte in range(MIN_DTE, MAX_DTE + 1):
        e = day + timedelta(days=dte)
        if e.weekday() == 4:
            try:
                import exchange_calendars as xcals
                holiday = not xcals.get_calendar("XNYS").is_session(pd.Timestamp(e))
            except ImportError:   # fallback: NYSE Friday holidays
                holiday = e.isoformat() in {"2026-04-03", "2026-06-19", "2026-07-03", "2026-12-25",
                                            "2027-03-26", "2027-06-18", "2027-12-24"}
            return e - timedelta(days=1) if holiday else e
    return None


def atm_iv(ld, day, close):
    """(expiry, strike, call IV, put IV) at the listed strike closest to the close, or None."""
    expiry = weekly_expiry(day)
    if expiry is None:
        return None
    base = round(close / STRIKE_STEP) * STRIKE_STEP
    grid = sorted({base + i * STRIKE_STEP for i in range(-STRIKE_TRIES, STRIKE_TRIES + 1)},
                  key=lambda k: (abs(k - close), k))
    start = day - timedelta(days=10)
    for k in grid[:STRIKE_TRIES]:
        ivs = []
        for right in ("C", "P"):
            df = option_history(ld, expiry, k, right, start)
            if df is None or day not in df.index or "IMP_VOLT" not in df.columns:
                break
            v = df.loc[day, "IMP_VOLT"]
            if pd.isna(v):
                break
            ivs.append(float(v) / 100)
        if len(ivs) == 2:
            return expiry, k, ivs[0], ivs[1]
    return None


# ---------------------------------------------------------------- main

def main():
    ld, session = login()
    old = pd.read_csv(HISTORY_FILE, parse_dates=["date"]) if os.path.exists(HISTORY_FILE) else None
    done = set(old["date"].dt.date) if old is not None else set()

    closes, source = load_closes(ld, need_from=date(2026, 5, 1))
    days = list(closes.index)
    # days that can have an RV (21 returns before them) and that we have not stored yet
    targets = [d for i, d in enumerate(days) if i >= RV_DAYS and d not in done]
    print(f"{len(days)} closes ({days[0]} to {days[-1]}); computing IV for {len(targets)} new day(s)")

    rows = []
    for d in targets:
        got = atm_iv(ld, d, closes[d])
        if got is None:
            print(f"  {d}: no IV found")
            continue
        expiry, k, iv_c, iv_p = got
        rows.append(dict(date=d, close=closes[d], price_source=source[d], expiry=expiry, strike=k,
                         iv_call=round(iv_c, 6), iv_put=round(iv_p, 6)))
        print(f"  {d}: close {closes[d]:.2f}  strike {k:g} exp {expiry}  IV call {iv_c:.3f} put {iv_p:.3f}")
    session.close()

    new = pd.DataFrame(rows)
    hist = pd.concat([old[["date", "close", "price_source", "expiry", "strike", "iv_call", "iv_put"]], new]
                     if old is not None else [new], ignore_index=True)
    hist["date"] = pd.to_datetime(hist["date"]).dt.date
    hist = hist.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)

    # RV, spread and z-score are recomputed over the full table every run (cheap, and always consistent)
    logret = pd.Series([math.log(closes[days[i]] / closes[days[i - 1]]) for i in range(1, len(days))],
                       index=days[1:])
    rv = logret.rolling(RV_DAYS).std(ddof=1) * math.sqrt(252)
    hist["iv"] = (hist["iv_call"] + hist["iv_put"]) / 2
    hist["rv"] = hist["date"].map(rv)
    hist["spread"] = hist["iv"] - hist["rv"]
    roll = hist["spread"].rolling(Z_DAYS)
    hist["z"] = (hist["spread"] - roll.mean()) / roll.std(ddof=1)

    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    hist.round(6).to_csv(HISTORY_FILE, index=False)
    last = hist.iloc[-1]
    print(f"\nSaved {len(hist)} days to {os.path.relpath(HISTORY_FILE, ROOT)}")
    print(f"Latest {last['date']}: IV {last['iv']:.3f}  RV {last['rv']:.3f}  spread {last['spread']:+.3f}  "
          f"z {last['z']:+.2f}" if pd.notna(last["z"]) else f"Latest {last['date']}: z not available yet")


if __name__ == "__main__":
    main()
