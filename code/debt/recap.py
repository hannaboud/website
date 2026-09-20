"""
Consolidated ownership recap.

Assembles everything produced so far into one picture and one CSV.

    python recap.py
    python recap.py --ofs2 out/ofs2_ownership.csv --banks banks_20260331.csv
    python recap.py --period 2026-03-31 --top 10

Reads what you already have; fetches nothing. If a file is missing, that
section is skipped and flagged rather than silently omitted.
"""

from __future__ import annotations

import argparse
import pathlib

import pandas as pd

# OFS-2 nests: Total Public Debt = Fed/Govt accounts + Total Privately Held,
# and Total Privately Held = sum of the detail rows. Aggregates are held back
# so shares are computed on one level only.
AGGREGATES = r"total|grand|^all\b"

# The classes this project is actually about: US financial institutions.
INSTITUTIONS = [
    "Depository Institutions",
    "Mutual Funds",
    "Pension Funds - Private",
    "Pension Funds - State And Local Governments",
    "Insurance Companies",
]

NON_PRIVATE = "Federal Reserve And Government Accounts"


def load_ofs2(path: str, period: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["period"])

    if period:
        chosen = pd.Timestamp(period)
    else:
        # newest period carrying a full set of classes: the detail lags the
        # headline totals by a quarter, so max(period) is usually incomplete
        counts = df.groupby("period")["holder"].nunique()
        chosen = counts[counts >= 0.8 * counts.max()].index.max()

    snap = df[df["period"] == chosen].copy()
    is_agg = snap["holder"].str.contains(AGGREGATES, case=False, na=False)
    detail = snap[~is_agg].copy()

    total = detail["holdings_bn"].sum()
    detail["share_pct"] = 100 * detail["holdings_bn"] / total
    detail.attrs["period"] = chosen
    detail.attrs["total"] = total
    detail.attrs["private"] = total - detail.loc[
        detail["holder"] == NON_PRIVATE, "holdings_bn"].sum()
    return detail.sort_values("holdings_bn", ascending=False)


def load_banks(path: str, col: str = "SCUST") -> pd.DataFrame:
    df = pd.read_csv(path)
    df = df[df[col].notna() & (df[col] > 0)].copy()
    df["holdings_bn"] = df[col] / 1e6           # FDIC reports in thousands
    df = df.sort_values("holdings_bn", ascending=False).reset_index(drop=True)

    total = df["holdings_bn"].sum()
    df["share_pct"] = 100 * df["holdings_bn"] / total
    df["cum_share_pct"] = df["share_pct"].cumsum()
    df.attrs["total"] = total
    df.attrs["hhi"] = (df["share_pct"] ** 2).sum()
    df.attrs["n_eff"] = 10_000 / df.attrs["hhi"]
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ofs2", default="out/ofs2_ownership.csv")
    ap.add_argument("--banks", default="banks_20260331.csv")
    ap.add_argument("--period", default=None)
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--out", default="out/recap.csv")
    args = ap.parse_args()

    line = "-" * 64

    # ---------------------------------------------------------- ownership
    if not pathlib.Path(args.ofs2).exists():
        print(f"missing {args.ofs2} - run ownership.py first")
        return

    own = load_ofs2(args.ofs2, args.period)
    per = own.attrs["period"].date()
    tot, priv = own.attrs["total"], own.attrs["private"]

    print(f"\nUS TREASURY DEBT OWNERSHIP, {per}")
    print(line)
    print(f"total public debt      ${tot:>10,.0f}bn")
    print(f"privately held         ${priv:>10,.0f}bn\n")

    show = own[["holder", "holdings_bn", "share_pct"]].copy()
    show.columns = ["holder", "$bn", "% of total"]
    print(show.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))

    # ------------------------------------------------ the institution bloc
    inst = own[own["holder"].isin(INSTITUTIONS)]
    inst_total = inst["holdings_bn"].sum()
    foreign = own.loc[own["holder"].str.contains("Foreign", case=False, na=False),
                      "holdings_bn"].sum()

    print(f"\n{line}")
    print("US FINANCIAL INSTITUTIONS")
    print(line)
    missing = set(INSTITUTIONS) - set(own["holder"])
    if missing:
        print(f"  WARNING: label mismatch, not counted: {sorted(missing)}")
    print(f"  banks + funds + pensions + insurers  ${inst_total:,.0f}bn "
          f"({100 * inst_total / priv:.1f}% of privately held)")
    print(f"  foreign and international            ${foreign:,.0f}bn "
          f"({100 * foreign / priv:.1f}% of privately held)")

    # ------------------------------------------------------ named banks
    if pathlib.Path(args.banks).exists():
        banks = load_banks(args.banks)
        dep = own.loc[own["holder"].str.contains("Depositor", case=False, na=False),
                      "holdings_bn"].sum()

        print(f"\n{line}")
        print("NAMED INSTITUTIONS (banks only)")
        print(line)
        print(f"  {len(banks):,} banks hold Treasuries; "
              f"${banks.attrs['total']:,.0f}bn "
              f"({100 * banks.attrs['total'] / dep:.0f}% of the depository line)")
        print(f"  HHI {banks.attrs['hhi']:,.0f} -> effective N = "
              f"{banks.attrs['n_eff']:.1f} firms")
        print(f"  top {args.top} hold "
              f"{banks['cum_share_pct'].iloc[args.top - 1]:.1f}%\n")
        top = banks.head(args.top)[["NAME", "holdings_bn", "cum_share_pct"]].copy()
        top.columns = ["institution", "$bn", "cumulative %"]
        print(top.to_string(index=False, float_format=lambda x: f"{x:,.1f}"))

        big4 = banks.head(4)["holdings_bn"].sum()
        print(f"\n  top 4 banks combined: ${big4:,.0f}bn - larger than any "
              f"single foreign holder bar Japan and the UK")
    else:
        print(f"\n  ({args.banks} not found - skipping named institutions)")

    # ------------------------------------------------------- what's missing
    other = own.loc[own["holder"].str.contains("Other", case=False, na=False),
                    "holdings_bn"].sum()
    funds = own.loc[own["holder"] == "Mutual Funds", "holdings_bn"].sum()

    print(f"\n{line}")
    print("UNRESOLVED")
    print(line)
    print(f"  'Other investors'  ${other:>8,.0f}bn  residual: individuals, GSEs,")
    print("                                brokers, trusts, CORPORATES. -> Z.1")
    print(f"  'Mutual funds'     ${funds:>8,.0f}bn  blends money funds (<1y) with")
    print("                                bond funds. -> N-PORT + N-MFP")
    if pathlib.Path(args.banks).exists():
        gap = dep - banks.attrs["total"]
        print(f"  bank trading books ${gap:>8,.0f}bn  RC-B excludes trading accounts,")
        print("                                so dealers are understated.")

    # -------------------------------------------------------------- output
    outp = pathlib.Path(args.out)
    outp.parent.mkdir(exist_ok=True, parents=True)
    own.assign(period=per).to_csv(outp, index=False)
    print(f"\nwritten to {outp}")


if __name__ == "__main__":
    main()
