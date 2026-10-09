# Poor Man's Covered Call backtest on LLY

Page: https://hannaboudara.com/pmcc.html

A Poor Man's Covered Call replaces the 100 shares of a covered call with one deep
in-the-money call that has about a year to expiry, and sells a short call against it
every week. This folder holds the code and data behind the page.

## Files

| File | What it does | Needs |
|---|---|---|
| `04_pull_lly.py` | Pulls LLY stock history and option history from LSEG, one contract at a time, into `data/` | LSEG Workspace login, `lseg-data` |
| `05_backtest.py` | Runs the backtest from the CSV files in `data/`; writes blotter, weekly ledger, daily values and metrics to `results/` | `pandas`, `numpy` |
| `06_build_site_data.py` | Runs the backtest and writes `pmcc-book.js`, the data file the page reads | same |

## Reproduce

```
pip install pandas numpy
python 05_backtest.py
```

The LSEG pull does not need to be repeated: its output is saved in `data/`.
All rules are parameters at the top of `05_backtest.py`, and the full rule list is in
its docstring and on the page.

## Data

- `data/stock.csv`: daily LLY prices, 18 Aug 2025 to 2 Oct 2026.
- `data/weekly_calls.csv`: daily bid, ask, delta and implied volatility for the weekly
  calls considered each week.
- `data/leap_calls.csv`: the same for the long-call candidates.

Source: LSEG Workspace, pulled 8 Oct 2026.
