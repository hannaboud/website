"""
Institution-level Treasury holdings: banks, funds, money funds, dealers.

The aggregate tables (OFS-2, Z.1) stop at "depository institutions" and
"mutual funds". This goes underneath them, to individual banks and individual
fund series, using the regulatory filings those institutions already make.

    pip install pandas requests
    python institutions.py --discover           # find the right field names first
    python institutions.py --banks --date 20260630
    python institutions.py --funds --quarter 2026q1
    python institutions.py --mmf --month 2026-06
    python institutions.py --dealers

What each source actually gives you
-----------------------------------
BANKS - FDIC BankFind Suite API. One row per insured institution per quarter,
    with US Treasury securities held, split HTM/AFS. ~4,500 banks. Free, no
    key required. This is the fastest path to bank-level detail.
    Deeper: FFIEC Call Report Schedule RC-B has the remaining-maturity and
    repricing distribution (Memorandum item 2), which the FDIC summary fields
    do not carry. That needs the FFIEC CDR bulk download (free account).
    Bank holding companies file FR Y-9C, available via the Chicago Fed.

FUNDS - SEC Form N-PORT structured data sets. Position-level holdings for
    every registered fund: mutual funds, ETFs, closed-end funds. CUSIP, par
    value, market value, AND maturity date. This is the only free source that
    gives you a genuine holder-by-maturity grid rather than an assumption.
    Filed monthly, published quarterly, roughly a 60-day lag.

MMF - Form N-MFP. Money market funds are EXCLUDED from N-PORT and file this
    instead. Monthly, security-level, with maturity. Since money funds hold
    roughly $2.5tn of bills, omitting them would gut any short-maturity
    analysis.

DEALERS - NY Fed FR 2004 primary dealer positions. Weekly, by maturity
    bucket. Aggregate across the ~24 primary dealers, not per-dealer, but it
    is the only window into the intermediaries who warehouse the debt.

What will NOT work
------------------
Form 13F. It covers Section 13(f) securities: exchange-traded equities,
options, convertible debt, closed-end fund shares. Treasuries are not
reportable on 13F. Every few months someone builds a pipeline on 13F before
discovering this. Don't.

Insurers. NAIC Schedule D has security-level detail but is not free. The
public substitutes are statutory filings via state DOIs, or the aggregate
insurance sector line in Z.1.
"""

from __future__ import annotations

import argparse
import io
import zipfile

import pandas as pd
import requests

# The SEC requires a descriptive User-Agent with contact details on every
# automated request. Requests without one get 403'd. Put YOUR email here.
SEC_UA = {"User-Agent": "Research project - your.name@university.edu"}

FDIC_API = "https://banks.data.fdic.gov/api"
NPORT_BASE = "https://www.sec.gov/files/dera/data/form-n-port-data-sets"
NMFP_BASE = "https://www.sec.gov/files/dera/data/form-n-mfp-data-sets"
FR2004_URL = "https://www.newyorkfed.org/medialibrary/media/markets/gsds/search.csv"


# --------------------------------------------------------------------------
# banks
# --------------------------------------------------------------------------
FDIC_SCHEMA_URLS = [
    "https://api.fdic.gov/banks/risview_properties.yaml",
    "https://api.fdic.gov/banks/financial_properties.yaml",
    "https://banks.data.fdic.gov/docs/risview_properties.yaml",
]
FDIC_REPORTS_XLSX = "https://api.fdic.gov/banks/All Financial Reports.xlsx"

# Candidate SDI codes for US Treasury securities. None of these are verified -
# probe_fdic_fields() tests which actually return data rather than trusting a
# guess. The FFIEC Call Report source items are Schedule RC-B item 1:
#   RCON0211 HTM amortised cost, RCON0213 HTM fair value,
#   RCON1286 AFS amortised cost, RCON1287 AFS fair value.
CANDIDATE_FIELDS = [
    "SCUST", "SCUSTS", "SCUS", "SCUSA", "SCUSTSA", "SCUSTSH",
    "SCHTM", "SCAF", "SCSFM", "SCEQ", "SCMUNI", "SCMTGBS", "SC", "ASSET",
]


def discover_fdic_fields(pattern: str = "treas") -> pd.DataFrame:
    """Find the real financials schema.

    The /financials endpoint returns only a SUMMARY field set by default -
    about 160 fields, mostly institution descriptors plus headline balance
    sheet lines. The full SDI has far more. Searching that default set for
    'treas' finds nothing and tells you nothing, which is exactly the trap
    this hit. The authoritative list is the YAML definition file.
    """
    for url in FDIC_SCHEMA_URLS:
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            text = r.text
        except Exception:
            continue

        # crude YAML walk: collect "KEY:" lines and their description/title
        entries, current = [], None
        for line in text.splitlines():
            stripped = line.strip()
            if line[:4].strip() and stripped.endswith(":") and stripped[:-1].isupper():
                current = stripped[:-1]
            elif current and ("title:" in stripped or "description:" in stripped):
                entries.append((current, stripped.split(":", 1)[1].strip()))
                current = None

        df = pd.DataFrame(entries, columns=["field", "description"]).drop_duplicates("field")
        hits = df[df["description"].str.contains(pattern, case=False, na=False)
                  | df["field"].str.contains(pattern, case=False, na=False)]
        print(f"  schema from {url}")
        print(f"  {len(df)} fields defined; {len(hits)} match '{pattern}'")
        if len(hits):
            print(hits.to_string(index=False, max_colwidth=70))
        return df

    print("  could not fetch any schema file. Two fallbacks:")
    print(f"    1. python institutions.py --probe     (tests candidate codes live)")
    print(f"    2. download {FDIC_REPORTS_XLSX}")
    print("       It lists the exact API query and field names behind every")
    print("       standard FDIC financial report, including the securities one.")
    return pd.DataFrame()


def probe_fdic_fields(
    candidates: list[str] | None = None,
    report_date: str = "20260331",
) -> pd.DataFrame:
    """Ask the API for each candidate field and see which return real data.

    A field code that does not exist comes back absent or all-null, so this
    distinguishes 'wrong name' from 'right name, genuinely zero' - the two
    failure modes that look identical if you just eyeball a total.
    """
    candidates = candidates or CANDIDATE_FIELDS
    rows = []
    for f in candidates:
        try:
            r = requests.get(
                f"{FDIC_API}/financials",
                params={"filters": f"REPDTE:{report_date}", "fields": f"CERT,{f}",
                        "limit": 200, "format": "json"},
                timeout=60,
            )
            ok = r.status_code == 200
            data = r.json().get("data", []) if ok else []
            vals = [d.get("data", d).get(f) for d in data]
            nonnull = [v for v in vals if v not in (None, "", "null")]
            rows.append({
                "field": f,
                "status": r.status_code,
                "rows": len(vals),
                "non_null": len(nonnull),
                "sample": nonnull[:3],
            })
        except Exception as e:  # noqa: BLE001
            rows.append({"field": f, "status": "ERR", "rows": 0,
                         "non_null": 0, "sample": str(e)[:40]})

    out = pd.DataFrame(rows).sort_values("non_null", ascending=False)
    print(out.to_string(index=False))
    live = out[out["non_null"] > 0]["field"].tolist()
    print(f"\n  fields returning data: {live}")
    print("  cross-check the winner against the FDIC aggregate before use:")
    print("  bank-sector Treasuries should land near the OFS-2 'Depository")
    print("  institutions' line (~$2,170bn at 2026-03-31).")
    return out


def get_bank_treasuries(
    report_date: str = "20260630",
    fields: str = "CERT,NAME,CITY,STALP,ASSET,SC,SCUST,SCUSA,SCUS,SCAF",
    limit: int = 10_000,
) -> pd.DataFrame:
    """Treasury securities held, bank by bank, for one quarter.

    report_date is YYYYMMDD and must be a quarter end (0331, 0630, 0930, 1231).

    Field codes, verified live with --probe:
        SCUST  US Treasury securities            <- the one you want
        SCUSA  US government agency obligations
        SCUS   ALL US government obligations (Treasury + agency + agency MBS)
        SCAF   available-for-sale securities, total
        SC     total securities
        ASSET  total assets
    All values are in THOUSANDS of dollars.

    SCUS runs many times larger than SCUST. Picking it by mistake overstates
    bank Treasury holdings enormously, and nothing in the output would look
    obviously wrong. Always reconcile against the aggregate.

    One structural gap: Call Report Schedule RC-B, which feeds these fields,
    EXCLUDES securities held in trading accounts (those sit in RC-D). The
    bank subsidiaries of the large dealers carry meaningful Treasury
    inventory in trading books, so expect the bank-sector sum to fall short
    of the OFS-2 depository line, and treat that gap as a measurement issue
    rather than a parsing bug.

    The HTM/AFS split matters for your question: HTM securities are carried at
    amortised cost, so unrealised losses from rate rises are invisible on the
    balance sheet. SVB in 2023 is the worked example. A bank's *reported*
    Treasury position and its *marked* position can differ substantially.
    """
    out, offset = [], 0
    while True:
        r = requests.get(
            f"{FDIC_API}/financials",
            params={
                "filters": f"REPDTE:{report_date}",
                "fields": fields,
                "limit": min(limit, 10_000),
                "offset": offset,
                "format": "json",
            },
            timeout=120,
        )
        r.raise_for_status()
        rows = r.json().get("data", [])
        if not rows:
            break
        out.extend(row.get("data", row) for row in rows)
        offset += len(rows)
        if len(rows) < min(limit, 10_000) or offset >= limit:
            break

    df = pd.DataFrame(out)
    for c in df.columns:
        if c not in ("NAME", "CITY", "STALP", "CERT"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def concentration(df: pd.DataFrame, col: str = "SCUST") -> pd.DataFrame:
    """How concentrated are bank Treasury holdings?

    Worth computing early. If the top 10 banks hold most of the sector's
    Treasuries, then "depository institutions" as a holder class is really a
    handful of named institutions, and the collective-action story changes
    shape: a few large holders internalise much more of any systemic cost
    than an atomistic sector would.
    """
    if col not in df.columns:
        raise KeyError(f"{col} not in data; run --discover to find the right field")
    d = df.dropna(subset=[col]).sort_values(col, ascending=False)
    total = d[col].sum()
    d = d.assign(
        share_pct=100 * d[col] / total,
        cum_share_pct=100 * d[col].cumsum() / total,
    )
    hhi = ((100 * d[col] / total) ** 2).sum()
    d.attrs["hhi"] = hhi
    d.attrs["total"] = total
    return d


# --------------------------------------------------------------------------
# funds
# --------------------------------------------------------------------------
def get_nport_quarter(quarter: str = "2026q1") -> dict[str, pd.DataFrame]:
    """Download and unpack one quarterly N-PORT structured data set.

    Returns a dict of DataFrames keyed by table name. The two that matter:
        SUBMISSION              one row per fund series per report
        FUND_REPORTED_HOLDING   one row per position, with CUSIP and maturity

    These zips are large (hundreds of MB). Cache them; don't refetch.
    The URL pattern changes occasionally - if this 404s, browse
    sec.gov/dera/data/form-n-port-data-sets and copy the current link.
    """
    url = f"{NPORT_BASE}/{quarter}_nport.zip"
    r = requests.get(url, headers=SEC_UA, timeout=600)
    r.raise_for_status()

    tables = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            if not name.lower().endswith((".tsv", ".csv")):
                continue
            sep = "\t" if name.lower().endswith(".tsv") else ","
            with z.open(name) as fh:
                key = name.rsplit("/", 1)[-1].rsplit(".", 1)[0].upper()
                tables[key] = pd.read_csv(fh, sep=sep, low_memory=False)
    return tables


def filter_treasuries(holdings: pd.DataFrame) -> pd.DataFrame:
    """Keep only US Treasury positions from an N-PORT holdings table.

    Identification is deliberately belt-and-braces. Treasury CUSIPs begin
    with 912 (912796 bills, 91282C recent notes, 912810 bonds, 912828 older
    notes), but funds also hold agency and STRIPS paper in the 912 space, so
    the issuer-name check is not redundant.

    Verify your catch rate against the OFS-2 mutual fund total before using
    this. If fund-level Treasuries sum to far less than the aggregate, the
    filter is dropping something.
    """
    df = holdings.copy()
    df.columns = [c.upper() for c in df.columns]

    cusip_col = next((c for c in ("CUSIP", "IDENTIFIER_CUSIP") if c in df), None)
    name_col = next((c for c in ("ISSUER_NAME", "NAME_OF_ISSUER", "TITLE") if c in df), None)

    mask = pd.Series(False, index=df.index)
    if cusip_col:
        mask |= df[cusip_col].astype(str).str.strip().str.startswith("912")
    if name_col:
        mask |= df[name_col].astype(str).str.contains(
            r"treasur|^UNITED STATES", case=False, regex=True, na=False)

    # exclude agency paper that also sits in the 912 range
    if name_col:
        mask &= ~df[name_col].astype(str).str.contains(
            r"FEDERAL HOME|FANNIE|FREDDIE|GINNIE|FARM CREDIT",
            case=False, regex=True, na=False)

    out = df[mask]
    print(f"  {len(out):,} Treasury positions out of {len(df):,} holdings")
    return out


def holdings_by_maturity(treas: pd.DataFrame) -> pd.DataFrame:
    """Bucket fund Treasury positions by remaining maturity.

    This is the grid the aggregate sources cannot give you: who holds the
    short end versus the long end, fund by fund, from filed data rather than
    from an allocation assumption.
    """
    df = treas.copy()
    mat_col = next((c for c in ("MATURITY_DATE", "MATURITYDATE") if c in df), None)
    val_col = next((c for c in ("CURRENT_VALUE_USD", "VALUE_USD", "CURVAL") if c in df), None)
    if not mat_col or not val_col:
        raise KeyError(f"need maturity and value columns; saw {list(df.columns)[:25]}")

    df[mat_col] = pd.to_datetime(df[mat_col], errors="coerce")
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
    df = df.dropna(subset=[mat_col, val_col])

    years = (df[mat_col] - pd.Timestamp.today()).dt.days / 365.25
    df["bucket"] = pd.cut(
        years,
        bins=[-0.01, 1, 3, 5, 10, 20, 100],
        labels=["<1y", "1-3y", "3-5y", "5-10y", "10-20y", "20y+"],
    )
    return df.groupby("bucket", observed=True)[val_col].agg(["sum", "count"])


def get_nmfp_month(month: str = "2026-06") -> dict[str, pd.DataFrame]:
    """Money market fund holdings (Form N-MFP) for one month.

    Money funds are excluded from N-PORT. They hold roughly $2.5tn of bills,
    almost all under a year, so leaving them out would badly distort the
    maturity picture.
    """
    url = f"{NMFP_BASE}/{month}_nmfp.zip"
    r = requests.get(url, headers=SEC_UA, timeout=600)
    r.raise_for_status()
    tables = {}
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        for name in z.namelist():
            if name.lower().endswith((".tsv", ".csv")):
                sep = "\t" if name.lower().endswith(".tsv") else ","
                with z.open(name) as fh:
                    key = name.rsplit("/", 1)[-1].rsplit(".", 1)[0].upper()
                    tables[key] = pd.read_csv(fh, sep=sep, low_memory=False)
    return tables


# --------------------------------------------------------------------------
# dealers
# --------------------------------------------------------------------------
def get_dealer_positions() -> pd.DataFrame:
    """NY Fed FR 2004 primary dealer positions, by maturity bucket.

    Aggregate across dealers, not per-dealer: the Fed suppresses individual
    dealer positions. Still useful, since dealers are the marginal holders
    who absorb supply, and their positioning moves faster than anything in
    the quarterly data.
    """
    r = requests.get(FR2004_URL, timeout=120)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))


# --------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--discover", action="store_true")
    ap.add_argument("--probe", action="store_true",
                    help="test candidate field codes against the live API")
    ap.add_argument("--banks", action="store_true")
    ap.add_argument("--funds", action="store_true")
    ap.add_argument("--mmf", action="store_true")
    ap.add_argument("--dealers", action="store_true")
    ap.add_argument("--date", default="20260630", help="bank quarter end YYYYMMDD")
    ap.add_argument("--quarter", default="2026q1", help="N-PORT quarter")
    ap.add_argument("--month", default="2026-06", help="N-MFP month")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    if args.discover:
        print("FDIC field discovery")
        try:
            discover_fdic_fields("treasury")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
        print()

    if args.probe:
        print(f"Probing candidate FDIC field codes at {args.date}")
        try:
            probe_fdic_fields(report_date=args.date)
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
        print()

    if args.banks:
        print(f"Bank Treasury holdings, {args.date}")
        try:
            df = get_bank_treasuries(args.date)
            df.to_csv(f"banks_{args.date}.csv", index=False)
            top = concentration(df).head(args.top)
            total_bn = top.attrs["total"] / 1e6   # $thousands -> $bn
            print(f"  {len(df):,} institutions, ${total_bn:,.0f}bn in Treasuries")
            bench = 2169.5   # OFS-2 'Depository institutions', 2026-03-31
            print(f"  vs OFS-2 depository line ${bench:,.0f}bn -> "
                  f"{100 * total_bn / bench:.0f}% captured "
                  f"(shortfall expected: RC-B excludes trading accounts)")
            print(f"  HHI {top.attrs['hhi']:,.0f}; "
                  f"top {args.top} hold {top['cum_share_pct'].iloc[-1]:.1f}%")
            print(top[["NAME", "SCUST", "share_pct", "cum_share_pct"]]
                  .to_string(index=False, float_format=lambda x: f"{x:,.1f}"))
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
            print("  run --discover first to confirm field names")
        print()

    if args.funds:
        print(f"Fund Treasury holdings, {args.quarter}")
        try:
            tables = get_nport_quarter(args.quarter)
            print("  tables:", ", ".join(sorted(tables)))
            hold = next((v for k, v in tables.items() if "HOLDING" in k), None)
            if hold is None:
                raise KeyError("no holdings table in the zip")
            treas = filter_treasuries(hold)
            treas.to_csv(f"fund_treasuries_{args.quarter}.csv", index=False)
            print(holdings_by_maturity(treas).to_string())
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
        print()

    if args.mmf:
        print(f"Money market fund holdings, {args.month}")
        try:
            tables = get_nmfp_month(args.month)
            print("  tables:", ", ".join(sorted(tables)))
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
        print()

    if args.dealers:
        print("Primary dealer positions")
        try:
            d = get_dealer_positions()
            d.to_csv("dealer_positions.csv", index=False)
            print(f"  {len(d):,} rows written")
        except Exception as e:
            print(f"  FAILED: {type(e).__name__}: {e}")
        print()


if __name__ == "__main__":
    main()