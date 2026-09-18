"""Bracket-trade backtest engine. Vectorised-ish, conservative fills.

Conventions
  - A signal on bar i is executed at the OPEN of bar i+1 (no lookahead).
  - Entry cost: half spread of the entry bar + slippage.  Same on exit.
  - Stop and target are checked against bar high/low. If a bar spans both,
    the STOP is assumed first (conservative floor).
  - R = initial risk in $ (entry -> stop distance). All results reported in R
    and in $ per unit (1 oz).
"""
import numpy as np, pandas as pd

def run(df, sig, sl_atr=1.5, tp_atr=None, atr_col="atr14", max_bars=72,
        slip=0.10, be_at=None, trail_atr=None, exit_k=None, max_per_day=None,
        risk_cap_atr=None):
    """sig: Series aligned to df.index with +1 long / -1 short / 0 none (signal bar).
    exit_k: optional Series of forced-exit bar positions (int index into df)."""
    idx = df.index
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float);  c = df["close"].to_numpy(float)
    sp = df["spread"].to_numpy(float); atr = df[atr_col].to_numpy(float)
    day = df["session_day"].to_numpy() if "session_day" in df else idx.normalize().to_numpy()
    s = sig.reindex(idx).fillna(0).to_numpy(int)
    n = len(idx)

    trades = []
    i_ptr = 0
    last_day = None
    used_today = 0
    for i in range(n - 2):
        if s[i] == 0: continue
        e = i + 1                                   # entry bar
        if e >= n - 1: break
        if e < i_ptr: continue                      # already in a trade
        a = atr[e]
        if not np.isfinite(a) or a <= 0: continue
        d = day[e]
        if d != last_day:
            last_day = d; used_today = 0
        if max_per_day and used_today >= max_per_day:
            continue
        used_today += 1
        side = s[i]
        halfsp = sp[e] / 2 + slip
        entry = o[e] + side * halfsp                # pay the spread
        risk = sl_atr * a
        if risk_cap_atr and risk > risk_cap_atr * a: risk = risk_cap_atr * a
        stop = entry - side * risk
        targ = entry + side * tp_atr * a if tp_atr else None
        be_done = False
        exit_px = None; exit_i = None; reason = None
        hard = min(e + max_bars, n - 1)
        if exit_k is not None:
            k = exit_k.get(idx[i], None)
            if k is not None: hard = min(int(k), n - 1)
        for j in range(e, hard + 1):
            hi, lo = h[j], l[j]
            # stop first (conservative)
            if (side == 1 and lo <= stop) or (side == -1 and hi >= stop):
                exit_px = stop - side * (sp[j] / 2 + slip); exit_i = j
                reason = "be" if be_done else "stop"; break
            if targ is not None and ((side == 1 and hi >= targ) or (side == -1 and lo <= targ)):
                exit_px = targ - side * (sp[j] / 2 + slip); exit_i = j; reason = "target"; break
            # move to breakeven
            if be_at and not be_done:
                mfe = (h[j] - entry) if side == 1 else (entry - l[j])
                if mfe >= be_at * risk:
                    stop = entry; be_done = True
            # atr trail on closes
            if trail_atr:
                t = c[j] - side * trail_atr * atr[j]
                stop = max(stop, t) if side == 1 else min(stop, t)
        if exit_px is None:
            j = hard; exit_px = o[min(j + 1, n - 1)] - side * (sp[j] / 2 + slip)
            exit_i = j; reason = "timeout"
        pnl = side * (exit_px - entry)
        trades.append(dict(t_sig=idx[i], t_in=idx[e], t_out=idx[exit_i], side=side,
                           entry=entry, exit=exit_px, stop_dist=risk, atr=a,
                           pnl=pnl, R=pnl / risk, bars=exit_i - e, reason=reason,
                           day=d, spread=sp[e]))
        i_ptr = exit_i + 1
    return pd.DataFrame(trades)


def stats(tr, label="", ann_days=252):
    if tr is None or len(tr) == 0:
        return dict(label=label, n=0)
    R = tr["R"]; pnl = tr["pnl"]
    dd = (R.cumsum() - R.cumsum().cummax()).min()
    daily = tr.groupby("day")["R"].sum()
    sharpe = daily.mean() / daily.std() * np.sqrt(ann_days) if daily.std() > 0 else 0
    wins = R[R > 0]; loss = R[R <= 0]
    return dict(label=label, n=len(tr), win=round((R > 0).mean() * 100, 1),
                avgR=round(R.mean(), 4), totR=round(R.sum(), 1),
                t=round(R.mean() / R.std() * np.sqrt(len(R)), 2) if R.std() > 0 else 0,
                pf=round(wins.sum() / abs(loss.sum()), 2) if len(loss) and loss.sum() != 0 else np.nan,
                sharpe=round(sharpe, 2), maxddR=round(dd, 1),
                usd=round(pnl.sum(), 0), avg_usd=round(pnl.mean(), 2),
                bars=round(tr["bars"].mean(), 1))


def by_year(tr):
    if len(tr) == 0: return pd.DataFrame()
    t = tr.copy(); t["year"] = pd.to_datetime(t["t_in"]).dt.year
    g = t.groupby("year")["R"].agg(["size", "mean", "sum"])
    g["win%"] = t.groupby("year")["R"].apply(lambda s: (s > 0).mean() * 100)
    return g.round(3)
