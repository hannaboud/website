"""
Figures from the bank-level Treasury holdings CSV.

    pip install pandas matplotlib
    python plot_banks.py banks_20260331.csv
    python plot_banks.py banks_20260331.csv --show
    python plot_banks.py banks_20260331.csv --top 15 --format png

Writes to ./figures/:
    fig_bank_top_holders.(pdf|png|svg)    ranked bar chart
    fig_bank_concentration.(pdf|png|svg)  cumulative share curve with HHI

Defaults to PDF because vector text stays sharp in LaTeX and journals
generally require it. --format png if you want something for slides.

--show also opens the figures in a window. That needs a GUI backend; if
matplotlib is on headless 'Agg' the script says so rather than doing
nothing silently.

Units: FDIC reports in THOUSANDS of dollars. Everything converts to
billions on read, so the axis labels are honest.
"""

from __future__ import annotations

import argparse
import pathlib

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.figure import Figure

# OFS-2 'Depository institutions', 2026-03-31. Used only for the annotation.
OFS2_DEPOSITORY_BN = 2169.5

# Dealer-affiliated banks. Call Report Schedule RC-B excludes trading-account
# securities, so these are the institutions whose holdings are understated.
DEALER_BANKS = {
    "JPMORGAN CHASE BANK NA", "BANK OF AMERICA NA", "CITIBANK NATIONAL ASSN",
    "GOLDMAN SACHS BANK USA", "MORGAN STANLEY BANK NA", "WELLS FARGO BANK NA",
}

BLUE, ORANGE = "#3b6ea5", "#c76b32"

plt.rcParams.update({
    "font.size": 9,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.alpha": 0.25,
    "grid.linewidth": 0.5,
    "figure.dpi": 150,
    "savefig.bbox": "tight",
})

TIDY = {
    "JPMORGAN CHASE BANK NA": "JPMorgan Chase",
    "BANK OF AMERICA NA": "Bank of America",
    "CITIBANK NATIONAL ASSN": "Citibank",
    "GOLDMAN SACHS BANK USA": "Goldman Sachs",
    "WELLS FARGO BANK NA": "Wells Fargo",
    "MORGAN STANLEY BANK NA": "Morgan Stanley",
    "TD BANK NATIONAL ASSN": "TD Bank",
    "PNC BANK NATIONAL ASSN": "PNC",
    "BANK OF NEW YORK MELLON": "BNY Mellon",
    "U S BANK NATIONAL ASSN": "US Bank",
    "STATE STREET BANK&TRUST CO": "State Street",
    "BANCO POPULAR DE PUERTO RICO": "Banco Popular PR",
    "BMO BANK NATIONAL ASSN": "BMO",
    "HSBC BANK USA NATIONAL ASSN": "HSBC USA",
    "MORGAN STANLEY PRIVATE BK NA": "Morgan Stanley Priv.",
    "CITY NATIONAL BANK": "City National",
    "TRUIST BANK": "Truist",
    "FIRST-CITIZENS BANK&TRUST CO": "First Citizens",
    "CAPITAL ONE NATIONAL ASSN": "Capital One",
    "HUNTINGTON NATIONAL BANK": "Huntington",
    "USAA FEDERAL SAVINGS BANK": "USAA",
    "CIBC BANK USA": "CIBC USA",
    "NORTHERN TRUST CO": "Northern Trust",
    "KEYBANK NATIONAL ASSN": "KeyBank",
    "BEAL BANK USA": "Beal Bank",
}


def load(path: str, col: str = "SCUST") -> pd.DataFrame:
    df = pd.read_csv(path)
    if col not in df.columns:
        raise KeyError(f"{col} not in {path}. Columns: {list(df.columns)}")

    n_all = len(df)
    df = df.dropna(subset=[col])
    df = df[df[col] > 0].copy()

    df["holdings_bn"] = df[col] / 1e6          # thousands -> billions
    df = df.sort_values("holdings_bn", ascending=False).reset_index(drop=True)

    total = df["holdings_bn"].sum()
    df["share_pct"] = 100 * df["holdings_bn"] / total
    df["cum_share_pct"] = df["share_pct"].cumsum()
    df["label"] = df["NAME"].map(TIDY).fillna(df["NAME"].str.title())
    df["is_dealer"] = df["NAME"].isin(DEALER_BANKS)

    df.attrs["total_bn"] = total
    df.attrs["hhi"] = (df["share_pct"] ** 2).sum()
    df.attrs["n_eff"] = 10_000 / df.attrs["hhi"]   # effective number of firms
    df.attrs["n_all"] = n_all
    df.attrs["n_zero"] = n_all - len(df)
    return df


def fig_top_holders(df: pd.DataFrame, top: int, out: pathlib.Path,
                    fmt: str, highlight: bool) -> Figure:
    d = df.head(top).iloc[::-1]           # largest at the top of a barh
    fig, ax = plt.subplots(figsize=(6.5, 0.28 * top + 1.4))

    colors = [ORANGE if x else BLUE for x in d["is_dealer"]] if highlight else BLUE
    ax.barh(d["label"], d["holdings_bn"], color=colors, height=0.72)

    pad = df["holdings_bn"].max() * 0.012
    for y, v in zip(d["label"], d["holdings_bn"]):
        ax.text(v + pad, y, f"{v:,.0f}", va="center", fontsize=7.5, color="#444")

    ax.set_xlabel("US Treasury securities held, $bn")
    ax.set_title(f"Top {top} US banks by Treasury holdings, 31 March 2026",
                 loc="left", fontsize=10, fontweight="bold")
    ax.margins(x=0.10)
    ax.grid(axis="y", visible=False)

    if highlight:
        from matplotlib.patches import Patch
        ax.legend(handles=[Patch(facecolor=ORANGE, label="Dealer-affiliated")],
                  loc="lower right", frameon=False, fontsize=7.5)

    fig.text(0.0, -0.02,
             "Source: FDIC BankFind Suite, field SCUST. Call Report Schedule "
             "RC-B excludes trading-account\nsecurities, so dealer-affiliated "
             "banks are understated.",
             fontsize=6.5, color="#666", va="top")

    fig.savefig(out / f"fig_bank_top_holders.{fmt}")
    return fig


def fig_concentration(df: pd.DataFrame, top: int, out: pathlib.Path,
                      fmt: str) -> Figure:
    d = df.head(top)
    fig, ax = plt.subplots(figsize=(6.0, 3.6))

    ax.plot(range(1, len(d) + 1), d["cum_share_pct"],
            marker="o", markersize=3.5, color=BLUE, linewidth=1.6)
    ax.axhline(90, color="#999", linestyle=":", linewidth=0.9)

    n90 = int((df["cum_share_pct"] < 90).sum() + 1)
    if n90 <= top:
        # flip the label left when the 90% point sits near the right edge,
        # otherwise the arrow and text run outside the axes
        near_edge = n90 > 0.6 * top
        ax.annotate(f"{n90} banks reach 90%",
                    xy=(n90, 90),
                    xytext=(n90 - 0.30 * top if near_edge else n90 + 1.5, 66),
                    fontsize=7.5, color="#444", ha="left",
                    arrowprops=dict(arrowstyle="->", color="#888", lw=0.8))

    ax.set_xlabel("Banks, ranked by holdings")
    ax.set_ylabel("Cumulative share of bank Treasury holdings, %")
    ax.set_ylim(0, 100)
    ax.set_xlim(0.5, len(d) + 0.5)
    ax.set_title("Concentration of bank Treasury holdings",
                 loc="left", fontsize=10, fontweight="bold")

    ax.text(0.97, 0.06,
            f"{len(df):,} banks hold ${df.attrs['total_bn']:,.0f}bn\n"
            f"HHI {df.attrs['hhi']:,.0f}  "
            f"(effective N = {df.attrs['n_eff']:.1f})",
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5,
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#ccc", lw=0.6))

    fig.savefig(out / f"fig_bank_concentration.{fmt}")
    return fig


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--col", default="SCUST")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--format", default="pdf", choices=["pdf", "png", "svg"])
    ap.add_argument("--outdir", default="figures")
    ap.add_argument("--show", action="store_true",
                    help="open the figures in a window as well as saving them")
    ap.add_argument("--no-highlight", action="store_true",
                    help="draw all bars one colour instead of flagging dealers")
    args = ap.parse_args()

    out = pathlib.Path(args.outdir)
    out.mkdir(exist_ok=True)

    df = load(args.csv, args.col)
    top = min(args.top, len(df))

    fig_top_holders(df, top, out, args.format, highlight=not args.no_highlight)
    fig_concentration(df, top, out, args.format)

    captured = 100 * df.attrs["total_bn"] / OFS2_DEPOSITORY_BN
    print(f"{len(df):,} banks hold Treasuries "
          f"({df.attrs['n_zero']:,} of {df.attrs['n_all']:,} hold none)")
    print(f"${df.attrs['total_bn']:,.0f}bn total, {captured:.0f}% of the "
          f"OFS-2 depository line")
    print(f"HHI {df.attrs['hhi']:,.0f}  ->  effective N = "
          f"{df.attrs['n_eff']:.1f} firms")
    print(f"top {top} hold {df['cum_share_pct'].iloc[top - 1]:.1f}%")
    print(f"\nwritten to {out}/")

    if args.show:
        if plt.get_backend().lower() == "agg":
            print("\n  matplotlib is on the headless 'Agg' backend, so no window")
            print("  can open. Install a GUI toolkit and rerun:")
            print("      brew install python-tk")
            print("  Or just: open figures/")
        else:
            plt.show()

    plt.close("all")


if __name__ == "__main__":
    main()