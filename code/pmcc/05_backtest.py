"""
Step 5 - Poor Man's Covered Call backtest on LLY, from the files in ./data.

Rules (every one is a parameter below):
  Long leg   : on START buy 1 call expiring LEAP_EXPIRIES[0], strike whose delta on the
               PREVIOUS trading day is closest to 0.85 (never below 0.80). Fill at the ask.
               Held to expiry, settled at intrinsic value, replaced the next trading day
               by the same rule with the next expiry in LEAP_EXPIRIES.
  Short leg  : first trading day of each week, sell 1 call expiring the last trading day
               of that week. Fill at that day's closing bid.
  Short delta: 0.15 if the stock closed above its 21-day average on the prior trading
               day, else 0.35. Strike = listed strike whose delta at the entry-day close
               is closest to the target (the same close the call is sold at).
  Floor      : optional (USE_FLOOR): short strike >= long strike + price paid. Off.
  Expiry     : out of the money -> expires. In the money -> buy 100 shares at the close
               and deliver them at the strike (loss = close - strike). Never short stock.
  Valuation  : daily, at the price to close (long call at bid, short call at ask).
  Capital    : both strategies start with the same cash, the cost of 100 shares at the
               START close. The PMCC spends part of it on the long call; the rest stays in cash.
  Benchmark  : buy 100 shares at the START close and hold.

No look-ahead: the trend signal and the long-call selection use the prior trading day's
data. The short strike is chosen from deltas at the entry-day close and sold at that same
close's bid (signal and fill on the same closing quote; nothing later is used).

Run:  python 05_backtest.py     Outputs in ./results
"""
import os
import json
import numpy as np
import pandas as pd

# ---------------- parameters ----------------
START = "2025-10-03"
END = "2026-10-02"
LEAP_EXPIRIES = ["2026-09-18", "2027-09-17"]
LEAP_DELTA, LEAP_MIN_DELTA = 0.85, 0.80
MA_DAYS = 21
DELTA_UPTREND, DELTA_DOWNTREND = 0.15, 0.35
USE_FLOOR = False           # breakeven floor: short strike >= long strike + price paid
SHORT_DELTA_DAY = "entry"   # "entry" = delta at the close we trade on; "prior" = previous trading day
CASH_RATE = 0.0363             # annual interest earned on idle cash (0 = none)
RISK_FREE = 0.0363          # annual, for the Sharpe ratio (effective fed funds, Sept 2026)
MULT = 100
DATA, OUT = "data", "results"
# --------------------------------------------


def main(out=OUT, quiet=False):
    os.makedirs(out, exist_ok=True)
    stock = pd.read_csv(f"{DATA}/stock.csv", parse_dates=["date"]).set_index("date")
    close = stock["TRDPRC_1"].astype(float)
    wk = pd.read_csv(f"{DATA}/weekly_calls.csv", parse_dates=["date", "expiry"])
    lp = pd.read_csv(f"{DATA}/leap_calls.csv", parse_dates=["date", "expiry"])
    start, end = pd.Timestamp(START), pd.Timestamp(END)
    days = list(close.index)
    prev_day = {d: days[i - 1] for i, d in enumerate(days) if i > 0}
    ma = close.rolling(MA_DAYS).mean()

    blotter, weekly = [], []
    cash = 0.0
    leap = None      # dict(strike, expiry, ric, paid)
    short = None     # dict(strike, expiry, ric, premium)
    pending_leap = [pd.Timestamp(e) for e in LEAP_EXPIRIES]
    capital = None
    interest = 0.0
    capital0 = MULT * close[start]       # starting cash for BOTH strategies = cost of 100 shares on START
    leap_cost = None

    def book(time, instrument, side, qty, limit, fill, cash_delta, note):
        nonlocal cash
        cash += cash_delta
        blotter.append(dict(time=time.date(), instrument=instrument, side=side, qty=qty,
                            limit=limit, fill=fill, cash_delta=round(cash_delta, 2), note=note))

    def buy_leap(day):
        nonlocal leap
        expiry = pending_leap.pop(0)
        c = lp[lp["expiry"] == expiry]
        sel = c[(c["date"] == prev_day[day]) & c["delta"].notna()][["strike", "delta"]]
        px = c[(c["date"] == day) & (c["ask"] > 0)][["strike", "ask", "ric"]]
        m = sel.merge(px, on="strike")
        m = m[m["delta"] >= LEAP_MIN_DELTA]
        if m.empty:
            raise RuntimeError(f"no long call with delta >= {LEAP_MIN_DELTA} on {day.date()}")
        m = m.assign(gap=(m["delta"] - LEAP_DELTA).abs()).sort_values(["gap", "strike"])
        r = m.iloc[0]
        leap = dict(strike=r["strike"], expiry=expiry, ric=r["ric"], paid=r["ask"])
        book(day, r["ric"], "BUY", 1, r["ask"], r["ask"], -MULT * r["ask"],
             f"Long call {r['strike']:g} exp {expiry.date()}, prior-day delta {r['delta']:.3f}, filled at ask")

    # ---- week table from the tape ----
    weeks = {}
    for d in days:
        if start < d <= end:
            weeks.setdefault(tuple(d.isocalendar()[:2]), []).append(d)
    entry_of = {v[0]: v[-1] for v in weeks.values()}     # entry day -> expiry day

    nav_rows = []
    quotes_l = lp.set_index(["ric", "date"])[["bid", "ask"]].sort_index()
    quotes_w = wk.set_index(["ric", "date"])[["bid", "ask"]].sort_index()
    last_mark = {}

    def mark(table, ric, day, col):
        """Latest quote on or before `day` (carried forward if a day has no quote)."""
        try:
            v = table.loc[(ric, day), col]
            if pd.notna(v):
                last_mark[(ric, col)] = float(v)
        except KeyError:
            pass
        return last_mark.get((ric, col), np.nan)

    for day in [d for d in days if start <= d <= end]:
        S = close[day]

        if CASH_RATE and day > start:                 # interest on a positive cash balance
            earned = max(cash, 0.0) * CASH_RATE * (day - prev_day[day]).days / 365
            cash += earned
            interest += earned

        # 1) long call: buy on START, or the trading day after the old one expired
        if leap is None and pending_leap:
            buy_leap(day)
            if capital is None:
                leap_cost = MULT * leap["paid"]
                cash += capital0                      # account funded with the cost of 100 shares
                capital = capital0

        # 2) sell this week's short call
        if day in entry_of and short is None and leap is not None:
            expiry, dec = entry_of[day], prev_day[day]
            uptrend = close[dec] > ma[dec]
            target = DELTA_UPTREND if uptrend else DELTA_DOWNTREND
            floor = leap["strike"] + leap["paid"] if USE_FLOOR else 0.0
            c = wk[wk["expiry"] == expiry]
            sel = c[(c["date"] == (dec if SHORT_DELTA_DAY == "prior" else day)) & c["delta"].notna()][["strike", "delta"]]
            px = c[(c["date"] == day) & (c["bid"] > 0)][["strike", "bid", "ric"]]
            m = sel.merge(px, on="strike")
            free = m.assign(gap=(m["delta"] - target).abs()).sort_values(["gap", "strike"])
            m = free[free["strike"] >= floor]
            row = dict(week_of=day.date(), expiry=expiry.date(), trend="up" if uptrend else "down",
                       target_delta=target, floor=round(floor, 2), spot_entry=S)
            if m.empty:
                book(day, "OPTION", "SKIP", 0, None, None, 0.0,
                     f"No call with a bid at or above the breakeven floor {floor:.2f} -> none sold")
                row.update(strike=None, delta=None, premium=0.0, floor_binding=True)
            else:
                r = m.iloc[0]
                binding = bool(len(free) and free.iloc[0]["strike"] < floor)
                short = dict(strike=r["strike"], expiry=expiry, ric=r["ric"], premium=MULT * r["bid"])
                book(day, r["ric"], "SELL", 1, r["bid"], r["bid"], MULT * r["bid"],
                     f"Sold {r['strike']:g} call, trend {'up' if uptrend else 'down'}, target delta {target:.2f}, "
                     f"delta {r['delta']:.3f}" + (", strike raised by breakeven floor" if binding else ""))
                row.update(strike=r["strike"], delta=round(r["delta"], 4), premium=MULT * r["bid"],
                           floor_binding=binding)
            weekly.append(row)

        # 3) short call expiry
        if short is not None and day == short["expiry"]:
            K = short["strike"]
            if S > K:
                book(day, short["ric"], "ASSIGN", 1, None, K, 0.0,
                     f"Call in the money at expiry (close {S:.2f} > strike {K:g})")
                book(day, "LLY.N", "BUY", MULT, S, S, -MULT * S, "Buy shares at the close to deliver")
                book(day, "LLY.N", "SELL", MULT, K, K, MULT * K, f"Deliver shares at strike {K:g}")
                weekly[-1].update(outcome="ASSIGNED", assignment_cost=round(MULT * (S - K), 2))
            else:
                book(day, short["ric"], "EXPIRE", 1, None, 0.0, 0.0,
                     f"Call out of the money at expiry (close {S:.2f} <= strike {K:g})")
                weekly[-1].update(outcome="EXPIRED", assignment_cost=0.0)
            weekly[-1].update(spot_expiry=S)
            short = None
        elif weekly and day in entry_of.values() and "outcome" not in weekly[-1]:
            weekly[-1].update(outcome="SKIPPED", assignment_cost=0.0, spot_expiry=S)

        # 4) long call expiry: settle at intrinsic value
        if leap is not None and day == leap["expiry"]:
            intrinsic = max(S - leap["strike"], 0.0)
            book(day, leap["ric"], "SETTLE", 1, None, intrinsic, MULT * intrinsic,
                 f"Long call expired, settled at intrinsic value (close {S:.2f} - strike {leap['strike']:g})")
            leap = None

        # 5) end-of-day valuation at the price to close
        leap_val = MULT * mark(quotes_l, leap["ric"], day, "bid") if leap else 0.0
        short_val = -MULT * mark(quotes_w, short["ric"], day, "ask") if short else 0.0
        nav = cash + leap_val + short_val
        nav_rows.append(dict(date=day.date(), close=S, cash=round(cash, 2), long_call=round(leap_val, 2),
                             short_call=round(short_val, 2), nav=round(nav, 2)))
        if weekly and day in entry_of.values():
            weekly[-1].update(cash=round(cash, 2), long_call=round(leap_val, 2), nav=round(nav, 2))

    nav = pd.DataFrame(nav_rows).set_index("date")
    nav["buy_hold"] = MULT * nav["close"]
    bh_capital = nav["buy_hold"].iloc[0]
    nav["strategy_return"] = nav["nav"] / capital - 1
    nav["buy_hold_return"] = nav["buy_hold"] / bh_capital - 1
    wkdf = pd.DataFrame(weekly)
    bl = pd.DataFrame(blotter)

    def stats(series, cap):
        eq = pd.concat([pd.Series([cap]), series.reset_index(drop=True)], ignore_index=True)
        ret = eq.pct_change().dropna()
        dd = (eq / eq.cummax() - 1).min()
        vol = ret.std() * np.sqrt(252)
        ann = (eq.iloc[-1] / cap) ** (252 / len(ret)) - 1
        return dict(capital=round(cap, 2), final_value=round(eq.iloc[-1], 2),
                    pnl=round(eq.iloc[-1] - cap, 2), total_return=round(eq.iloc[-1] / cap - 1, 4),
                    annualized_return=round(ann, 4), volatility=round(vol, 4),
                    sharpe=round((ann - RISK_FREE) / vol, 2), max_drawdown=round(dd, 4))

    sold = wkdf[wkdf["strike"].notna()]
    metrics = dict(
        period=f"{START} to {END}", trading_days=len(nav),
        strategy=stats(nav["nav"], capital), buy_hold=stats(nav["buy_hold"], bh_capital),
        long_call_cost=round(leap_cost, 2), idle_cash_at_start=round(capital - leap_cost, 2),
        min_cash=round(nav["cash"].min(), 2), interest_earned=round(interest, 2),
        final_cash=round(cash, 2), final_long_call_value=round(nav["long_call"].iloc[-1], 2),
        # what-if: the same trades in an account funded with only the long call's cost
        minimum_funding=dict(stats(nav["nav"] - capital + leap_cost, leap_cost),
                             min_cash=round(nav["cash"].min() - (capital - leap_cost), 2)),
        weeks=len(wkdf), calls_sold=len(sold), weeks_skipped=int((wkdf["outcome"] == "SKIPPED").sum()),
        premium_collected=round(sold["premium"].sum(), 2),
        weeks_assigned=int((wkdf["outcome"] == "ASSIGNED").sum()),
        assignment_cost=round(wkdf["assignment_cost"].sum(), 2),
        short_leg_net=round(sold["premium"].sum() - wkdf["assignment_cost"].sum(), 2),
        weeks_uptrend=int((wkdf["trend"] == "up").sum()), weeks_downtrend=int((wkdf["trend"] == "down").sum()),
        weeks_floor_binding=int(wkdf["floor_binding"].sum()),
        long_calls=[b for b in blotter if b["side"] in ("BUY", "SETTLE") and b["instrument"] != "LLY.N"],
    )

    # consistency: starting cash + every blotter cash movement + interest = ending cash,
    # and ending cash + open positions = final value. One set of books, one set of numbers.
    assert abs(capital + bl["cash_delta"].sum() + interest - cash) < 0.01
    assert abs(cash + nav["long_call"].iloc[-1] + nav["short_call"].iloc[-1] - nav["nav"].iloc[-1]) < 0.02
    assert abs(metrics["strategy"]["final_value"] - nav["nav"].iloc[-1]) < 0.01

    bl.to_csv(f"{out}/blotter.csv", index=False)
    wkdf.to_csv(f"{out}/weekly_ledger.csv", index=False)
    nav.to_csv(f"{out}/daily_nav.csv")
    with open(f"{out}/metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    if not quiet:
        print(json.dumps(metrics, indent=2, default=str))
    return metrics


if __name__ == "__main__":
    main()
