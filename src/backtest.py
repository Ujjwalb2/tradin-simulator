#!/usr/bin/env python3
"""
Execution layer for the Gold Liquidity Sweep strategy.

Takes the setups produced by strategy.py and simulates them bar by bar:

  entry      next bar's open after the reclaim, filled at ask (long) / bid (short)
  initial SL lowest low / highest high of the previous N completed candles
  +1R        stop moves to entry (breakeven)
  after BE   structure trail: lowest low / highest high of the last M completed candles
  21:25      blocks new entries only; an open trade keeps running on the trail
  daily      max 2 trades. Only a full initial-stop loss opens the second attempt —
             a win OR a breakeven scratch ends the day.

Intrabar ambiguity (a bar whose range covers both the stop and the +1R level) is always
resolved against the trade: the stop is assumed to have come first. Results are therefore
a conservative floor, not a best case.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from strategy import Config, add_atr, run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "XAUUSD_5m.parquet"


@dataclass
class ExecConfig:
    trail_lookback: int = 5      # M completed candles for the structure trail
    exit_mode: str = "trail"     # "trail": structure trail; "fixed": fixed R target
    target_r: float = 2.0        # the R multiple, when exit_mode == "fixed"
    trail_arm_r: float = 1.0     # R at which the trail switches on (rulebook: +1R)
    use_be: bool = True          # also force the stop to entry at that point (rulebook: yes)
    max_trades_per_day: int = 2
    slippage: float = 0.0        # extra $ per side, on top of the real spread
    risk_per_trade: float = 0.01  # fraction of equity risked, for the $ curve
    start_equity: float = 10_000.0


def simulate(bars_ist: pd.DataFrame, setups: pd.DataFrame, xc: ExecConfig) -> pd.DataFrame:
    """Walk each session's setups in order, honouring the daily trade rules."""
    if setups.empty:
        return pd.DataFrame()

    idx = bars_ist.index
    pos = {ts: i for i, ts in enumerate(idx)}
    highs = bars_ist["high"].to_numpy()
    lows = bars_ist["low"].to_numpy()
    opens = bars_ist["open"].to_numpy()
    closes = bars_ist["close"].to_numpy()
    spreads = bars_ist["spread"].fillna(0.0).to_numpy()
    dates = np.array([ts.date() for ts in idx])

    trades: list[dict] = []
    valid = setups[setups["status"] == "VALID"]

    for day, day_setups in valid.groupby("date", sort=True):
        taken = 0
        busy_until = -1  # bar index the previous trade closed on

        for _, s in day_setups.iterrows():
            if taken >= xc.max_trades_per_day:
                break
            e = pos.get(s["entry_ts"])
            if e is None or e <= busy_until:
                continue  # overlaps the previous trade, or fell off the end

            long = s["side"] == "long"
            half = spreads[e] / 2 + xc.slippage
            entry = opens[e] + half if long else opens[e] - half
            stop = float(s["sl"])
            risk = (entry - stop) if long else (stop - entry)
            if risk <= 0:
                continue

            arm_px = (entry + xc.trail_arm_r * risk if long
                      else entry - xc.trail_arm_r * risk)
            tgt_px = (entry + xc.target_r * risk if long else entry - xc.target_r * risk)
            be_armed = False
            exit_i = exit_px = None
            exit_reason = ""

            j = e
            last = len(idx) - 1
            while j <= last and dates[j] <= day + pd.Timedelta(days=1).to_pytimedelta():
                # Stop first, always — never let a bar's favourable extreme be assumed
                # to have printed before its adverse one.
                if (long and lows[j] <= stop) or (not long and highs[j] >= stop):
                    exit_i, exit_px = j, stop
                    exit_reason = ("breakeven" if be_armed and abs(stop - entry) < 1e-9
                                   else "trail" if be_armed else "initial_stop")
                    break

                if xc.exit_mode == "fixed":
                    if (long and highs[j] >= tgt_px) or (not long and lows[j] <= tgt_px):
                        exit_i, exit_px, exit_reason = j, tgt_px, "target"
                        break

                if not be_armed:
                    if (long and highs[j] >= arm_px) or (not long and lows[j] <= arm_px):
                        be_armed = True
                        if xc.use_be:
                            stop = entry

                if be_armed and j > e and xc.exit_mode == "trail":
                    lo = max(e, j - xc.trail_lookback + 1)
                    trail = lows[lo:j + 1].min() if long else highs[lo:j + 1].max()
                    stop = max(stop, trail) if long else min(stop, trail)

                j += 1

            if exit_i is None:  # ran out of data
                exit_i = min(j, last)
                exit_px = closes[exit_i]
                exit_reason = "eod_data"

            half_out = spreads[exit_i] / 2 + xc.slippage
            fill = exit_px - half_out if long else exit_px + half_out
            pnl = (fill - entry) if long else (entry - fill)
            r = pnl / risk

            trades.append({
                "date": day, "side": s["side"],
                "entry_ts": s["entry_ts"], "entry": entry,
                "init_sl": float(s["sl"]), "risk": risk,
                "exit_ts": idx[exit_i], "exit": fill,
                "exit_reason": exit_reason, "r": r,
                "bars_held": exit_i - e,
                "pen_atr": s.get("pen_atr", np.nan),
                "space_atr": s.get("space_atr", np.nan),
                "trade_no": taken + 1,
            })

            taken += 1
            busy_until = exit_i
            # A win or a breakeven scratch closes the day; only a real SL buys another go.
            if exit_reason != "initial_stop":
                break

    tr = pd.DataFrame(trades)
    if tr.empty:
        return tr

    eq = xc.start_equity
    curve = []
    for r in tr["r"]:
        eq += eq * xc.risk_per_trade * r
        curve.append(eq)
    tr["equity"] = curve
    return tr


def summarise(tr: pd.DataFrame, label: str = "") -> dict:
    if tr.empty:
        return {"label": label, "trades": 0}
    r = tr["r"]
    wins, losses = r[r > 0], r[r <= 0]
    cum = r.cumsum()
    dd = (cum - cum.cummax()).min()
    return {
        "label": label,
        "trades": len(r),
        "win%": round(100 * len(wins) / len(r), 1),
        "avg_R": round(r.mean(), 3),
        "total_R": round(r.sum(), 1),
        "expectancy": round(r.mean(), 3),
        "pf": round(wins.sum() / abs(losses.sum()), 2) if losses.sum() else np.inf,
        "max_dd_R": round(dd, 1),
        "best": round(r.max(), 1),
        "worst": round(r.min(), 1),
        "final_eq": round(tr["equity"].iloc[-1], 0),
    }


def load(cfg: Config) -> pd.DataFrame:
    bars = pd.read_parquet(DATA)
    ist = bars.tz_convert(cfg.tz).copy()
    ist["atr"] = add_atr(ist, cfg.atr_period)
    return ist


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2022-09-01")
    ap.add_argument("--end", default="2026-09-08")
    ap.add_argument("--min-space-atr", type=float, default=0.25)
    ap.add_argument("--min-pen-atr", type=float, default=0.0)
    ap.add_argument("--sl-mode", choices=["atr", "structure"], default="atr")
    ap.add_argument("--sl-atr-mult", type=float, default=1.5)
    ap.add_argument("--sl-lookback", type=int, default=5)
    ap.add_argument("--sweep-mode", choices=["close", "wick"], default="close")
    ap.add_argument("--trail-lookback", type=int, default=5)
    ap.add_argument("--sweep-expiry-bars", type=int, default=12)
    ap.add_argument("--no-same-candle", action="store_true")
    ap.add_argument("--slippage", type=float, default=0.0)
    ap.add_argument("--exit-mode", choices=["trail", "fixed"], default="trail")
    ap.add_argument("--target-r", type=float, default=2.0)
    ap.add_argument("--ema-filter", action="store_true",
                    help="require the reclaim candle to close on the trade's side of the 7 EMA")
    ap.add_argument("--reclaim-depth-r", type=float, default=0.0)
    ap.add_argument("--no-be", action="store_true",
                    help="diagnostic: arm the trail at +1R but do NOT force the stop to entry")
    ap.add_argument("--csv")
    args = ap.parse_args()

    cfg = Config(min_space_atr=args.min_space_atr, min_pen_atr=args.min_pen_atr,
                 sl_mode=args.sl_mode, sl_atr_mult=args.sl_atr_mult,
                 sl_lookback=args.sl_lookback, sweep_expiry_bars=args.sweep_expiry_bars,
                 sweep_mode=args.sweep_mode, same_candle_reclaim=not args.no_same_candle,
                 reclaim_depth_r=args.reclaim_depth_r)
    xc = ExecConfig(trail_lookback=args.trail_lookback, slippage=args.slippage,
                    use_be=not args.no_be, exit_mode=args.exit_mode, target_r=args.target_r)

    bars = pd.read_parquet(DATA)
    ist_all = bars.tz_convert(cfg.tz)
    mask = (ist_all.index >= f"{args.start} 00:00:00+05:30") & (ist_all.index <= f"{args.end} 23:59:59+05:30")
    window = bars[mask]

    setups, diag = run(window, cfg)
    if args.ema_filter and not setups.empty:
        setups.loc[~setups["ema_ok"].astype(bool), "status"] = "BLOCKED"
    ist = ist_all[mask].copy()
    ist["atr"] = add_atr(ist, cfg.atr_period)

    tr = simulate(ist, setups, xc)

    print("=" * 92)
    print(f"BACKTEST  XAUUSD 5m  {args.start} .. {args.end}")
    sl_desc = (f"SL {args.sl_atr_mult}xATR" if args.sl_mode == "atr"
               else f"SL structure({args.sl_lookback})")
    print(f"sweep={args.sweep_mode}  space>={args.min_space_atr}ATR  pen>={args.min_pen_atr}ATR  "
          f"{sl_desc}  trail {args.trail_lookback}  slippage ${args.slippage}")
    print("=" * 92)
    print(f"sessions {len(diag):,}   setups {len(setups):,}   "
          f"valid {(setups['status'] == 'VALID').sum():,}   trades {len(tr):,}")
    if tr.empty:
        print("no trades")
        return
    s = summarise(tr)
    for k, v in s.items():
        if k != "label":
            print(f"  {k:>11}: {v}")
    print("\nby exit reason:")
    print(tr.groupby("exit_reason")["r"].agg(["count", "mean", "sum"]).round(3).to_string())
    print("\nby year:")
    tr["year"] = pd.to_datetime(tr["entry_ts"]).dt.year
    print(tr.groupby("year")["r"].agg(["count", "mean", "sum"]).round(3).to_string())
    print("\nby side:")
    print(tr.groupby("side")["r"].agg(["count", "mean", "sum"]).round(3).to_string())
    if args.csv:
        tr.to_csv(args.csv, index=False)
        print(f"\nwritten -> {args.csv}")


if __name__ == "__main__":
    main()
