"""
MSFT volatility straddle -> open_orders.json (repo root and mkt/)

Reads the latest z-score from data/vol_history.csv (written by vol_signal.py) and the book from
mkt/positions.json, then writes the orders for the next NYSE session:

  - Next session is a Friday and z > +2  -> sell 100 ATM straddles (SHT call + SHT put), weekly, mid
  - Next session is a Friday and z < -2  -> buy  100 ATM straddles (BUY call + BUY put),  weekly, mid
  - Every session: delta-hedge with MSFT shares so that shares = -(options delta).
    With no options left (after expiry), that target is 0, so leftover shares are closed.
"""

import json
import math
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
CONID = 272093
CONTRACTS = 100
Z_CUT = 2.0

# NYSE full-day holidays (fallback if exchange_calendars is not installed)
NYSE_HOLIDAYS = {"2026-11-26", "2026-12-25", "2027-01-01", "2027-01-18", "2027-02-15", "2027-03-26",
                 "2027-05-31", "2027-06-18", "2027-07-05", "2027-09-06", "2027-11-25", "2027-12-24"}


def next_session(after):
    try:
        import exchange_calendars as xcals
        return xcals.get_calendar("XNYS").date_to_session(after + timedelta(days=1), direction="next").date()
    except ImportError:
        d = after + timedelta(days=1)
        while d.weekday() >= 5 or d.isoformat() in NYSE_HOLIDAYS:
            d += timedelta(days=1)
        return d


def read_positions():
    """(shares, options) from mkt/positions.json. Format not published yet: read loosely,
    signed qty (negative = short), options need strike and expiry. Missing file = flat."""
    path = os.path.join(ROOT, "mkt", "positions.json")
    if not os.path.exists(path):
        return 0, []
    with open(path) as f:
        raw = json.load(f)
    shares, options = 0, []
    for p in (raw if isinstance(raw, list) else raw.get("positions", [])):
        if str(p.get("underlying", CONID)) != str(CONID):
            continue
        kind = str(p.get("contract", "")).lower()
        if kind == "underlying":
            shares += int(p.get("qty", 0))
        elif kind in ("call", "put"):
            options.append(dict(kind=kind, qty=int(p["qty"]), strike=float(p["strike"]),
                                expiry=date.fromisoformat(str(p["expiry"])[:10])))
    return shares, options


def bs_delta(kind, spot, strike, years, vol):
    """Black-Scholes delta (no rates or dividends: one week out they barely matter)."""
    if years <= 0:
        return (1.0 if spot > strike else 0.0) if kind == "call" else (-1.0 if spot < strike else 0.0)
    d1 = (math.log(spot / strike) + 0.5 * vol ** 2 * years) / (vol * math.sqrt(years))
    n = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    return n if kind == "call" else n - 1


def share_orders(current, target, day):
    """Orders that move the share position from current to target. Crossing zero takes two orders."""
    orders, steps = [], []
    if current > 0 and target < current:
        steps.append(("SEL", min(current, current - target)))
    if current < 0 and target > current:
        steps.append(("BTC", min(-current, target - current)))
    if target > max(current, 0):
        steps.append(("BUY", target - max(current, 0)))
    if target < min(current, 0):
        steps.append(("SHT", min(current, 0) - target))
    for action, qty in steps:
        if qty > 0:
            orders.append({"id": f"msft-hedge-{action.lower()}-{day}", "for": day, "order_type": "mkt",
                           "action": action, "qty": qty, "underlying": CONID,
                           "contract": "underlying", "ref": "open"})
    return orders


def main():
    hist = pd.read_csv(os.path.join(ROOT, "data", "vol_history.csv"))
    last = hist.iloc[-1]
    today = datetime.now(ZoneInfo("America/New_York")).date()
    session = next_session(today)
    day = session.isoformat()
    orders = []

    # 1) Straddle, Fridays only
    z = last["z"]
    if session.weekday() == 4 and pd.notna(z) and abs(z) > Z_CUT:
        action = "SHT" if z > Z_CUT else "BUY"
        for kind in ("call", "put"):
            orders.append({"id": f"msft-straddle-{kind}-{day}", "for": day, "order_type": "lmt",
                           "action": action, "qty": CONTRACTS, "underlying": CONID, "contract": kind,
                           "expiry": "5DTE+", "strike": "atm", "ref": "open", "lmt_prc": "mid"})

    # 2) Delta hedge of the options held now (deltas from the last close and IV)
    shares, options = read_positions()
    spot, vol = float(last["close"]), float(last["iv"])
    opt_delta = sum(o["qty"] * 100 * bs_delta(o["kind"], spot, o["strike"],
                                             (o["expiry"] - session).days / 365, vol)
                    for o in options if o["expiry"] >= session)
    target = -round(opt_delta)
    orders += share_orders(shares, target, day)

    for path in ("open_orders.json", os.path.join("mkt", "open_orders.json")):
        os.makedirs(os.path.dirname(os.path.join(ROOT, path)), exist_ok=True)
        with open(os.path.join(ROOT, path), "w") as f:
            json.dump(orders, f, indent=2)
            f.write("\n")

    print(f"Signal {last['date']}: IV {last['iv']:.3f} RV {last['rv']:.3f} z {z:+.2f}")
    print(f"Planning {day}: shares {shares}, options delta {opt_delta:+.0f}, hedge target {target}")
    print(json.dumps(orders, indent=2))


if __name__ == "__main__":
    main()
