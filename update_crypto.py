"""Download market data for break-the-chain.html and save it as crypto-data.json.

Run by hand:      python3 update_crypto.py
Runs by itself:   every 3 hours through GitHub Actions (see .github/workflows/update-crypto-data.yml)

Data comes from CoinGecko's free API. It works without a key, but the free keyless
pool is shared and sometimes says "too many requests". If that keeps happening, get a
free Demo key at coingecko.com/en/api and save it in the repo as an Actions secret
named COINGECKO_DEMO_KEY. The script picks it up automatically.

If a download fails, the script keeps the last good data for that part, so the page
never loses its numbers. If nothing at all downloads, it leaves the file untouched.
"""
import calendar
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests

OUT = "crypto-data.json"
API = "https://api.coingecko.com/api/v3"
KEY = os.environ.get("COINGECKO_DEMO_KEY", "").strip()

# Page id -> CoinGecko id
COINS = {
    "btc": "bitcoin",
    "eth": "ethereum",
    "usdt": "tether",
    "bnb": "binancecoin",
    "xrp": "ripple",
    "usdc": "usd-coin",
    "sol": "solana",
    "doge": "dogecoin",
}
HISTORY = ["btc", "eth", "bnb", "xrp", "sol"]  # coins drawn on the 12-month chart
MONTHS_BACK = 12
PAUSE = 2 if KEY else 13  # seconds between calls; keyless allows about 5 calls a minute


def fetch_json(path, params):
    """GET one CoinGecko endpoint, retrying politely when rate limited."""
    headers = {"accept": "application/json"}
    if KEY:
        headers["x-cg-demo-api-key"] = KEY
    for attempt in range(4):
        try:
            resp = requests.get(API + path, params=params, headers=headers, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                wait = 20 * (2 ** attempt)
                print(f"  {path}: HTTP {resp.status_code}, waiting {wait}s")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as err:
            wait = 10 * (2 ** attempt)
            print(f"  {path}: {err}, waiting {wait}s")
            time.sleep(wait)
    return None


def month_ends(today, n=MONTHS_BACK):
    """The last day of each of the n complete months before `today`, oldest first."""
    out = []
    y, m = today.year, today.month
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(date(y, m, calendar.monthrange(y, m)[1]))
    return list(reversed(out))


def month_end_closes(prices, ends):
    """Pick each month's closing price from CoinGecko's daily points.

    Daily points are stamped 00:00 UTC, so the close of day D is the point stamped D + 1.
    Falls back to the latest point on or before that moment.
    """
    points = sorted((datetime.fromtimestamp(ms / 1000, tz=timezone.utc), p) for ms, p in prices if p)
    closes = []
    for end in ends:
        cutoff = datetime(end.year, end.month, end.day, tzinfo=timezone.utc) + timedelta(days=1, hours=12)
        best = None
        for ts, p in points:
            if ts <= cutoff:
                best = p
            else:
                break
        if best is None:
            return None
        closes.append(best)
    return closes


def sig(x, digits=8):
    return float(f"{x:.{digits}g}") if x is not None else None


def load_existing():
    try:
        with open(OUT, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main():
    now = datetime.now(timezone.utc)
    old = load_existing()
    data = {
        "updated": old.get("updated"),
        "source": "CoinGecko",
        "global": old.get("global"),
        "coins": old.get("coins", {}),
        "history": old.get("history"),
    }
    got_any = False

    print("Downloading prices and market values")
    markets = fetch_json("/coins/markets", {
        "vs_currency": "usd",
        "ids": ",".join(COINS.values()),
        "price_change_percentage": "24h",
    })
    if isinstance(markets, list) and markets:
        by_id = {row.get("id"): row for row in markets}
        coins = {}
        for key, cg in COINS.items():
            row = by_id.get(cg)
            if not row or not row.get("current_price"):
                if key in data["coins"]:
                    coins[key] = data["coins"][key]
                continue
            coins[key] = {
                "price": sig(row["current_price"]),
                "market_cap": round(row.get("market_cap") or 0),
                "rank": row.get("market_cap_rank"),
                "change_24h": sig(row.get("price_change_percentage_24h") or 0, 6),
                "volume_24h": round(row.get("total_volume") or 0),
                "circulating_supply": sig(row.get("circulating_supply") or 0, 10),
            }
        if coins:
            data["coins"] = coins
            data["updated"] = now.isoformat(timespec="seconds").replace("+00:00", "Z")
            got_any = True

    time.sleep(PAUSE)
    print("Downloading market totals")
    glob = fetch_json("/global", {})
    if isinstance(glob, dict) and isinstance(glob.get("data"), dict):
        g = glob["data"]
        try:
            data["global"] = {
                "total_market_cap": round(g["total_market_cap"]["usd"]),
                "total_volume": round(g["total_volume"]["usd"]),
                "btc_dominance": round(g["market_cap_percentage"]["btc"], 2),
                "eth_dominance": round(g["market_cap_percentage"]["eth"], 2),
            }
            got_any = True
        except (KeyError, TypeError):
            print("  market totals came back in an unexpected shape, keeping the old ones")

    ends = month_ends(now.date())
    old_hist = data["history"] if isinstance(data["history"], dict) else {}
    same_months = old_hist.get("months") == [d.isoformat() for d in ends]
    series = dict(old_hist.get("series", {})) if same_months else {}
    for key in HISTORY:
        time.sleep(PAUSE)
        print(f"Downloading 12-month history for {COINS[key]}")
        chart = fetch_json(f"/coins/{COINS[key]}/market_chart", {"vs_currency": "usd", "days": "365"})
        closes = month_end_closes(chart.get("prices", []), ends) if isinstance(chart, dict) else None
        if closes:
            series[key] = [sig(c) for c in closes]
            got_any = True
        else:
            print(f"  no history for {key}, keeping what we had")
    if all(k in series for k in HISTORY):
        data["history"] = {"months": [d.isoformat() for d in ends], "series": series}
    elif same_months:
        data["history"] = old_hist

    if not got_any:
        print("Nothing downloaded. Leaving crypto-data.json unchanged.")
        return 0
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"))
        f.write("\n")
    print(f"Saved {OUT}: {len(data['coins'])} coins, history {'ok' if data.get('history') else 'missing'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
