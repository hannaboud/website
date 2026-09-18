"""
Who owns US Treasury debt. (v2 - schema-aware)

    pip install pandas requests
    python ownership.py --inspect        # DO THIS FIRST
    python ownership.py
    python ownership.py --source ofs2

What v1 got wrong, and why
--------------------------
`record_date` in the Treasury Bulletin tables is the BULLETIN ISSUE DATE, not
the date the data refers to. Every quarterly issue republishes the full
back-history, so filtering to max(record_date) returns ten years of periods at
once, and summing them gives a meaningless multi-quadrillion total. The period
lives in a separate column.

v1 also guessed at which column held the investor class and fell through to
`df.columns[1]`, which is the period. Hence a "holder" column full of dates.

v2 inspects the schema instead of guessing, and handles both possible layouts:
  - LONG:  one row per (period, investor class), single value column
  - WIDE:  one row per period, one value column per investor class

Run --inspect first. If auto-detection still picks the wrong columns, the
inspect output tells you exactly what to override with --holder-col /
--value-col / --period-col.
"""

from __future__ import annotations

import argparse
import io
import pathlib

import pandas as pd
import requests

FISCAL_BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"

ENDPOINTS = {
    "ofs2": "/v1/accounting/tb/ofs2_estimated_ownership_treasury_securities",
    "ofs1": "/v1/accounting/tb/ofs1_distribution_federal_securities_class_investors_type_issues",
}

TIC_CANDIDATES = [
    "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/mfhhis01.txt",
    "https://ticdata.treasury.gov/resource-center/data-chart-center/tic/Documents/mfh.txt",
]

OUT = pathlib.Path("out")

# columns that are metadata, never the investor class
META = {
    "record_date", "record_calendar_year", "record_calendar_quarter",
    "record_calendar_month", "record_calendar_day", "record_fiscal_year",
    "record_fiscal_quarter", "src_line_nbr", "table_nbr", "table_name",
}


def _is_label(s: pd.Series) -> bool:
    """True for text columns. Do NOT test `dtype == object`: pandas 3.x gives
    string columns a dedicated str dtype, so that check silently matches
    nothing and every column mapping fails."""
    return not (pd.api.types.is_numeric_dtype(s)
                or pd.api.types.is_datetime64_any_dtype(s)
                or pd.api.types.is_bool_dtype(s))


def fiscal_data(endpoint: str, page_size: int = 10_000, **params) -> pd.DataFrame:
    url = FISCAL_BASE + endpoint
    query = {"format": "json", "page[size]": page_size, "page[number]": 1}
    query.update(params)

    frames, total_pages = [], 1
    while query["page[number]"] <= total_pages:
        r = requests.get(url, params=query, timeout=60)
        r.raise_for_status()
        payload = r.json()
        frames.append(pd.DataFrame(payload["data"]))
        total_pages = payload["meta"]["total-pages"]
        query["page[number]"] += 1
    return pd.concat(frames, ignore_index=True)


# --------------------------------------------------------------------------
def inspect_ofs2() -> pd.DataFrame:
    """Print the real schema so the column mapping stops being guesswork."""
    raw = fiscal_data(ENDPOINTS["ofs2"], page_size=500)
    print(f"  {len(raw):,} rows, {len(raw.columns)} columns\n")

    print("  COLUMNS")
    for c in raw.columns:
        sample = raw[c].dropna().astype(str).head(3).tolist()
        nuniq = raw[c].nunique()
        print(f"    {c:<45} uniq={nuniq:<6} e.g. {sample}")

    value_cols = [c for c in raw.columns if c.endswith(("_bil_amt", "_mil_amt", "_amt"))]
    print(f"\n  value-looking columns ({len(value_cols)}): {value_cols}")
    print("  layout guess:", "WIDE" if len(value_cols) > 1 else "LONG")

    cat = [c for c in raw.columns
           if c not in META and c not in value_cols
           and _is_label(raw[c]) and raw[c].nunique() < 60]
    print(f"  categorical candidates: {cat}")
    print("\n  first 3 rows:")
    print(raw.head(3).to_string())
    return raw


def get_ofs2(
    holder_col: str | None = None,
    value_col: str | None = None,
    period_col: str | None = None,
) -> pd.DataFrame:
    """Ownership by investor class, tidied to (period, holder, holdings_bn)."""
    raw = fiscal_data(ENDPOINTS["ofs2"])

    value_cols = [c for c in raw.columns if c.endswith(("_bil_amt", "_mil_amt"))]
    if value_col:
        value_cols = [value_col]
    if not value_cols:
        raise KeyError(f"no value column found. columns: {list(raw.columns)}")

    # --- the period: a date column that is NOT record_date ---------------
    if period_col is None:
        cands = [c for c in raw.columns
                 if c != "record_date" and ("date" in c or "period" in c or "month" in c)]
        period_col = cands[0] if cands else "record_date"
    raw[period_col] = pd.to_datetime(raw[period_col], errors="coerce")

    if period_col == "record_date":
        print("  WARNING: falling back to record_date as the period. That is the "
              "Bulletin ISSUE date; check --inspect output and set --period-col.")

    # --- long vs wide ----------------------------------------------------
    if len(value_cols) > 1:
        # WIDE: each value column IS an investor class
        df = raw.melt(id_vars=[period_col], value_vars=value_cols,
                      var_name="holder", value_name="holdings_bn")
        df["holder"] = (df["holder"]
                        .str.replace(r"_(bil|mil)_amt$", "", regex=True)
                        .str.replace("_", " ").str.strip().str.title())
        scale = 1.0 if value_cols[0].endswith("bil_amt") else 1e-3
        df = df.rename(columns={period_col: "period"})
    else:
        vc = value_cols[0]
        if holder_col is None:
            cands = [c for c in raw.columns
                     if c not in META and c != vc and c != period_col
                     and _is_label(raw[c]) and 1 < raw[c].nunique() < 60]
            if not cands:
                raise KeyError(
                    "could not identify the investor-class column. "
                    "Run --inspect and pass --holder-col explicitly.")
            holder_col = cands[0]
            print(f"  using '{holder_col}' as the investor class column")
        df = raw[[period_col, holder_col, vc]].copy()
        df.columns = ["period", "holder", "holdings_bn"]
        scale = 1.0 if vc.endswith("bil_amt") else 1e-3

    df["holdings_bn"] = pd.to_numeric(df["holdings_bn"], errors="coerce") * scale
    df = df.dropna(subset=["period", "holdings_bn"])

    # each Bulletin issue republishes history: keep one row per period+holder
    df = (df.sort_values("period")
            .drop_duplicates(subset=["period", "holder"], keep="last"))

    # pre-2024-03 machine-readable values are zero
    dead = df.groupby("period")["holdings_bn"].sum().eq(0)
    if dead.any():
        print(f"  dropping {int(dead.sum())} all-zero period(s) (the pre-2024-03 gap)")
        df = df[~df["period"].isin(dead[dead].index)]

    return df.sort_values(["period", "holdings_bn"], ascending=[True, False])


def latest_complete_period(df: pd.DataFrame, tol: float = 0.8) -> pd.Timestamp:
    """Most recent period with a full set of investor classes.

    OFS-2's investor-class detail is derived from the Fed's Z.1 and therefore
    lags the headline debt totals by a quarter. The newest period typically
    carries only the fast-reporting series, with the rest NaN. Taking
    max(period) after dropna() silently leaves you with two or three classes
    and a nonsense 98% share. Pick the newest period that is actually full.
    """
    counts = df.groupby("period")["holder"].nunique()
    full = counts.max()
    ok = counts[counts >= tol * full]
    chosen = ok.index.max()
    newest = counts.index.max()
    if chosen != newest:
        print(f"  note: {newest.date()} carries only {counts.loc[newest]}/{full} "
              f"classes (detail lags a quarter); using {chosen.date()}")
    return chosen


# OFS-2 nests: Total Public Debt = Fed/Govt Accounts + Total Privately Held,
# and Total Privately Held = sum of the detail categories. Mixing levels
# double-counts, so aggregates are held back and used as a check instead.
AGGREGATES = r"total|grand|^all\b"


def summarise(df: pd.DataFrame, period=None) -> pd.DataFrame:
    if period is None:
        period = latest_complete_period(df)
    snap = df[df["period"] == period].copy()

    is_agg = snap["holder"].str.contains(AGGREGATES, case=False, na=False)
    detail, aggs = snap[~is_agg].copy(), snap[is_agg]

    total = detail["holdings_bn"].sum()
    detail["share_pct"] = 100 * detail["holdings_bn"] / total
    detail.attrs["period"] = period
    detail.attrs["aggregates"] = aggs
    detail.attrs["total"] = total
    return detail.sort_values("holdings_bn", ascending=False)


def reconcile(detail: pd.DataFrame) -> None:
    """Check the detail against whatever total rows the table carries.

    If these do not tie out, the category list is wrong: either a subtotal is
    being counted as a category, or a category is missing. Do not report
    shares until this reconciles.
    """
    aggs = detail.attrs.get("aggregates")
    if aggs is None or len(aggs) == 0:
        print("  no total row found to reconcile against")
        return
    built = detail.attrs["total"]
    print("  reconciliation:")
    for _, r in aggs.iterrows():
        diff = built - r["holdings_bn"]
        flag = "OK" if abs(diff) < 0.01 * r["holdings_bn"] else "CHECK"
        print(f"    detail {built:,.0f} vs '{r['holder']}' {r['holdings_bn']:,.0f} "
              f"-> diff {diff:,.0f}  [{flag}]")


# --------------------------------------------------------------------------
def get_tic(local: str | None = None) -> pd.DataFrame:
    """Major Foreign Holders. The published file is whitespace-delimited text
    with header junk, not CSV, which is why sep=None choked in v1."""
    if local:
        p = pathlib.Path(local)
        df = (pd.read_excel(p) if p.suffix in (".xls", ".xlsx")
              else pd.read_csv(p, skip_blank_lines=True))
        df = df.rename(columns={df.columns[0]: "country"})
        df["country"] = df["country"].astype(str).str.strip()
        return df[~df["country"].str.contains(
            "Total|Grand|Footnote|Source|^nan$", case=False, regex=True, na=True)]

    last = None
    for url in TIC_CANDIDATES:
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            df = pd.read_fwf(io.StringIO(r.text))
            if df.shape[1] < 2:
                raise ValueError("parsed to a single column")
            df.columns = [str(c).strip() for c in df.columns]
            df = df.rename(columns={df.columns[0]: "country"})
            df["country"] = df["country"].astype(str).str.strip()
            df = df[~df["country"].str.contains(
                "Total|Grand|Footnote|Source|Department|^nan$",
                case=False, regex=True, na=True)]
            return df
        except Exception as e:  # noqa: BLE001
            last = e
            continue
    raise RuntimeError(
        f"all TIC URLs failed (last: {last}). Download the Major Foreign "
        "Holders table by hand from home.treasury.gov/data/"
        "treasury-international-capital-tic-system and point pandas at it."
    )


def z1_instructions() -> None:
    """Z.1 has no stable direct-download URL; v1's was fabricated."""
    print("""  Z.1 must be downloaded manually - there is no stable permalink.
    1. go to federalreserve.gov/datadownload
    2. choose 'Z.1 Financial Accounts of the United States'
    3. select table L.210 (Treasury Securities)
    4. package format CSV, label include, layout series column
    5. save as out/z1_l210.csv
  Two minutes, once a quarter. This is also the ONLY way to get ownership
  history before 2024-03, since the machine-readable OFS-2 is empty there.""")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--source", choices=["ofs2", "ofs1", "tic", "z1", "all"], default="all")
    ap.add_argument("--holder-col")
    ap.add_argument("--value-col")
    ap.add_argument("--period-col")
    ap.add_argument("--tic-file", help="manually downloaded Major Foreign Holders csv/xls")
    args = ap.parse_args()

    OUT.mkdir(exist_ok=True)

    if args.inspect:
        print("OFS-2 schema")
        try:
            inspect_ofs2()
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
        return

    want = {"ofs2", "ofs1", "tic", "z1"} if args.source == "all" else {args.source}

    if "ofs2" in want:
        print("OFS-2: ownership by investor class")
        try:
            df = get_ofs2(args.holder_col, args.value_col, args.period_col)
            df.to_csv(OUT / "ofs2_ownership.csv", index=False)
            latest = summarise(df)
            print(f"  period {latest.attrs['period'].date()}, "
                  f"${latest.attrs['total']:,.0f}bn across "
                  f"{len(latest)} investor classes")
            print(latest[["holder", "holdings_bn", "share_pct"]]
                  .to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
            print()
            reconcile(latest)
            print(f"\n  full history: {df['period'].min().date()} to "
                  f"{df['period'].max().date()}, out/ofs2_ownership.csv")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            print("  run --inspect and pass --holder-col / --value-col / --period-col")
        print()

    if "ofs1" in want:
        print("OFS-1: govt accounts / Fed / private")
        try:
            fiscal_data(ENDPOINTS["ofs1"]).to_csv(OUT / "ofs1_distribution.csv", index=False)
            print("  written to out/ofs1_distribution.csv")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
        print()

    if "tic" in want:
        print("TIC: foreign holders by country")
        try:
            tic = get_tic(args.tic_file)
            tic.to_csv(OUT / "tic_foreign_holders.csv", index=False)
            print(f"  {len(tic)} rows. Reminder: custody basis, not beneficial "
                  "ownership - Belgium, Cayman, Luxembourg are overstated.")
        except Exception as e:
            print(f"  FAILED: {e}")
        print()

    if "z1" in want:
        print("Z.1: Treasury securities by sector")
        z1_instructions()
        print()


if __name__ == "__main__":
    main()