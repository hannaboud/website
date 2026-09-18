"""
Ownership breakdown chart: US Treasury debt by holder.

    pip install pandas matplotlib
    python plot_ownership.py
    python plot_ownership.py --show
    python plot_ownership.py --format png --outdir figures

Reads out/ofs2_ownership.csv (written by ownership.py). Picks the newest
period that carries a full set of investor classes, since the detail lags
the headline totals by a quarter.
"""

from __future__ import annotations

import argparse
import pathlib

import matplotlib.pyplot as plt
import pandas as pd

DEEP, TEAL, INK, MUTED = "#1f5673", "#2b7a99", "#1a1a1a", "#6b7280"

# Total Public Debt / Total Privately Held are subtotals, not categories.
AGGREGATES = r"total|grand|^all\b"

SHORT = {
    "Federal Reserve And Government Accounts": "Fed + Govt accounts",
    "Foreign And International": "Foreign",
    "Other Investors": "Other investors",
    "Mutual Funds": "Mutual funds",
    "Depository Institutions": "Banks",
    "State And Local Governments": "State & local",
    "Pension Funds - Private": "Pensions (priv)",
    "Pension Funds - State And Local Governments": "Pensions (S&L)",
    "Insurance Companies": "Insurance",
    "U.S. Savings Bonds": "Savings bonds",
}

# Highlighted because these are the project's focus: US financial institutions
INSTITUTIONS = {"Mutual funds", "Banks", "Pensions (priv)",
                "Pensions (S&L)", "Insurance"}

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


def load(path: str, period: str | None = None) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["period"])

    if period:
        chosen = pd.Timestamp(period)
    else:
        counts = df.groupby("period")["holder"].nunique()
        chosen = counts[counts >= 0.8 * counts.max()].index.max()

    snap = df[df["period"] == chosen].copy()
    snap = snap[~snap["holder"].str.contains(AGGREGATES, case=False, na=False)]

    snap["label"] = snap["holder"].map(SHORT).fillna(snap["holder"])
    snap = snap.sort_values("holdings_bn", ascending=False).reset_index(drop=True)
    snap["share_pct"] = 100 * snap["holdings_bn"] / snap["holdings_bn"].sum()

    snap.attrs["period"] = chosen
    snap.attrs["total"] = snap["holdings_bn"].sum()
    return snap


def plot(df: pd.DataFrame, out: pathlib.Path, fmt: str, highlight: bool):
    d = df.iloc[::-1]                      # largest at top of a barh
    fig, ax = plt.subplots(figsize=(7.0, 0.42 * len(d) + 1.3))

    colors = ([TEAL if lbl in INSTITUTIONS else DEEP for lbl in d["label"]]
              if highlight else DEEP)
    ax.barh(d["label"], d["holdings_bn"], color=colors, height=0.68)

    pad = df["holdings_bn"].max() * 0.012
    for y, v, s in zip(d["label"], d["holdings_bn"], d["share_pct"]):
        ax.text(v + pad, y, f"{v:,.0f}   ({s:.1f}%)",
                va="center", fontsize=8, color=MUTED)

    ax.set_xlabel("US Treasury securities held, $bn")
    # subtitle sits in the title slot; the real title goes above it with pad,
    # otherwise the two overlap
    ax.set_title(f"US Treasury debt by holder, "
                 f"{df.attrs['period'].strftime('%d %B %Y')}",
                 loc="left", fontsize=9, color=MUTED, pad=8)
    ax.text(0, 1.065, f"Who owns the ${df.attrs['total'] / 1000:.0f}tn",
            transform=ax.transAxes, fontsize=13, fontweight="bold", color=INK)

    ax.margins(x=0.16)
    ax.grid(axis="y", visible=False)

    if highlight:
        from matplotlib.patches import Patch
        ax.legend(handles=[Patch(facecolor=TEAL, label="US financial institutions")],
                  loc="lower right", frameon=False, fontsize=8)

    inst = df[df["label"].isin(INSTITUTIONS)]["holdings_bn"].sum()
    fig.text(0.0, -0.02,
             f"Source: Treasury Bulletin OFS-2. US financial institutions hold "
             f"${inst:,.0f}bn combined.\nExcludes subtotal rows; reconciled "
             f"against the published total.",
             fontsize=6.5, color=MUTED, va="top")

    fig.savefig(out / f"fig_ownership_by_holder.{fmt}")
    return fig


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="out/ofs2_ownership.csv")
    ap.add_argument("--period", default=None)
    ap.add_argument("--format", default="pdf", choices=["pdf", "png", "svg"])
    ap.add_argument("--outdir", default="figures")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--no-highlight", action="store_true")
    args = ap.parse_args()

    out = pathlib.Path(args.outdir)
    out.mkdir(exist_ok=True)

    df = load(args.csv, args.period)
    plot(df, out, args.format, highlight=not args.no_highlight)

    print(f"period {df.attrs['period'].date()}, "
          f"${df.attrs['total']:,.0f}bn across {len(df)} classes")
    print(f"written to {out}/fig_ownership_by_holder.{args.format}")

    if args.show:
        if plt.get_backend().lower() == "agg":
            print("\n  headless 'Agg' backend - no window. Try: brew install python-tk")
        else:
            plt.show()
    plt.close("all")


if __name__ == "__main__":
    main()
