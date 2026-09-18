"""
AOD — Asia-Open Drift.  XAUUSD, 5-minute bars.   *** RETIRED — DO NOT TRADE ***

Failed its 7.6-year holdout (2015-2022): -3.03 bp/session, t = -5.53, -47.9% cumulative.
Kept only so the result can be reproduced. See FINDINGS.md and AOD_RETIRED.md.

Looked like the only cost-clearing edge in 4 years of 5m gold data (2022-09 .. 2026-09).
Extending the sample to 11.7 years destroyed it.  It harvests the overnight/close-to-open risk premium that
accrues in the thin hours after the COMEX daily settlement break.

Design notes (each one is a research finding, not a preference):
  * LONG ONLY.  Of 396 intraday windows scanned, only 2 had gross drift negative
    enough to clear the spread on the short side, and neither survived OOS.
  * NO STOP LOSS.  Every ATR stop tested (1.0x .. 3.0x) turned the edge negative.
    The edge is a smooth drift; a stop converts noise into realised losses.
  * NO VOL FILTER, NO TREND FILTER.  Both failed out-of-sample.
  * Anchored to the session REOPEN, not the clock, so it is DST-proof and never
    trades the wide-spread reopen bar itself.
"""
import numpy as np
import pandas as pd

# ---- locked parameters -------------------------------------------------------
# Two variants of the same edge. FULL holds ~3.5h and captures the whole drift;
# SHORT holds exactly 2h and captures its densest slice, for traders who will not
# carry a position longer. The drift accrues roughly uniformly, so a shorter hold
# takes proportionally less of it while paying the identical round-trip cost --
# SHORT is therefore structurally about half as profitable, not a free lunch.
VARIANTS = {
    "full":  dict(k_in=(2, 3, 4),    k_out=(36, 42, 48)),   # ~3.0-4.0 h
    "short": dict(k_in=(14, 16, 18), k_out=(38, 40, 42)),   # exactly 2.0 h
}
K_IN_SET   = VARIANTS["full"]["k_in"]
K_OUT_SET  = VARIANTS["full"]["k_out"]
SKIP_DOW   = (6,)             # skip the Sunday-night reopen session
MIN_SESSION_BARS = 200        # ignore half-days / broken sessions
SLIP       = 0.10             # $ per side, on top of half the quoted spread
GAP_MIN    = 10               # a >10 min hole in the tape = session break


def mark_sessions(df, gap_min=GAP_MIN, min_bars=MIN_SESSION_BARS):
    """Label each trading session by the daily reopen; add bar-index `k`."""
    d = df.copy()
    gap = d.index.to_series().diff().dt.total_seconds() / 60
    d["reopen"] = gap > gap_min
    d.iloc[0, d.columns.get_loc("reopen")] = True
    d["sess"] = d["reopen"].cumsum()
    d["k"] = d.groupby("sess").cumcount()
    d["sess_len"] = d["sess"].map(d.groupby("sess").size())
    return d[d["sess_len"] >= min_bars]


def signals(df, variant="full"):
    """One row per tradeable session: entry/exit bar timestamps and prices.

    variant "full"  -> 9 legs, k_in 2/3/4 x k_out 36/42/48   (~3.5 h hold)
    variant "short" -> 3 legs, k_in 14/16/18 -> k_in+24      (exactly 2 h hold)
    """
    cfg = VARIANTS[variant]
    d = mark_sessions(df)
    o = d.pivot_table(index="sess", columns="k", values="open", aggfunc="first")
    sp = d.pivot_table(index="sess", columns="k", values="spread", aggfunc="first")
    t0 = d.groupby("sess").apply(lambda g: g.index[0])
    pairs = ([(ki, ki + 24) for ki in cfg["k_in"]] if variant == "short"
             else [(ki, ko) for ki in cfg["k_in"] for ko in cfg["k_out"]])
    out = []
    for ki, ko in pairs:
            if ki not in o.columns or ko not in o.columns:
                continue
            entry = o[ki] + sp[ki] / 2 + SLIP          # buy: cross half the spread
            exitp = o[ko] - sp[ko] / 2 - SLIP          # sell: cross half the spread
            leg = pd.DataFrame({
                "t0": t0, "k_in": ki, "k_out": ko,
                "entry": entry, "exit": exitp,
                "pnl": exitp - entry,
            })
            leg["bp"] = leg["pnl"] / leg["entry"] * 1e4
            out.append(leg)
    r = pd.concat(out)
    r["dow"] = r["t0"].dt.dayofweek
    r = r[~r["dow"].isin(SKIP_DOW)]
    return r.dropna(subset=["bp"])


def portfolio(df, variant="full"):
    """Equal-weight the plateau legs -> one return series per session."""
    r = signals(df, variant)
    g = r.groupby("t0")
    p = pd.DataFrame({"bp": g["bp"].mean(), "pnl": g["pnl"].mean(),
                      "entry": g["entry"].mean(), "legs": g.size()})
    p["dow"] = p.index.dayofweek
    p["year"] = p.index.year
    return p


def stats(p, label="AOD"):
    x = p["bp"].dropna()
    eq = x.cumsum(); dd = eq - eq.cummax()
    return {
        "label": label, "sessions": len(x),
        "mean_bp": round(x.mean(), 2),
        "t_stat": round(x.mean() / x.std() * np.sqrt(len(x)), 2),
        "sharpe": round(x.mean() / x.std() * np.sqrt(252), 2),
        "total_pct": round(x.sum() / 100, 1),
        "maxdd_pct": round(dd.min() / 100, 1),
        "win_pct": round((x > 0).mean() * 100, 1),
        "best_bp": round(x.max(), 1), "worst_bp": round(x.min(), 1),
    }
