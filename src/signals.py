#!/usr/bin/env python3
"""
Generate and print Gold Liquidity Sweep signals for recent days, in a form you can
check candle-by-candle against your own chart.

Usage:
    python src/signals.py --days 10
    python src/signals.py --start 2026-08-26 --end 2026-09-08 --min-space-atr 0.0
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from strategy import Config, add_atr, build_range, run

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "processed" / "XAUUSD_5m.parquet"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10, help="number of most recent trading days")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--min-space-atr", type=float, default=0.25)
    ap.add_argument("--sl-lookback", type=int, default=5)
    ap.add_argument("--sweep-expiry-bars", type=int, default=12)
    ap.add_argument("--sweep-mode", choices=["wick", "close"], default="close")
    ap.add_argument("--sl-mode", choices=["atr", "structure"], default="atr")
    ap.add_argument("--sl-atr-mult", type=float, default=1.5)
    ap.add_argument("--min-pen-atr", type=float, default=0.0)
    ap.add_argument("--no-same-candle", action="store_true",
                    help="require the reclaim on a LATER candle than the sweep")
    ap.add_argument("--csv", help="also write the signal table to this path")
    args = ap.parse_args()

    cfg = Config(
        min_space_atr=args.min_space_atr,
        sl_lookback=args.sl_lookback,
        sweep_expiry_bars=args.sweep_expiry_bars,
        sweep_mode=args.sweep_mode,
        sl_mode=args.sl_mode, sl_atr_mult=args.sl_atr_mult,
        min_pen_atr=args.min_pen_atr,
        same_candle_reclaim=not args.no_same_candle,
    )

    bars = pd.read_parquet(DATA)
    local = bars.tz_convert(cfg.tz)

    # A "day" only counts if it actually has a range window; weekend sessions and the
    # partial current day have no 11:30-12:30 bars and would otherwise eat the count.
    rw = local.between_time(cfg.range_start, cfg.range_end, inclusive="left")
    all_days = sorted({d for d in rw.index.date})
    if args.start:
        sel = [d for d in all_days if str(d) >= args.start and (not args.end or str(d) <= args.end)]
    else:
        sel = all_days[-args.days:]

    mask = pd.Series(local.index.date, index=local.index).isin(sel).values
    window = bars[mask]

    setups, diag = run(window, cfg)

    ist = local[mask].copy()
    ist["atr"] = add_atr(ist, cfg.atr_period)

    print("=" * 100)
    print(f"GOLD LIQUIDITY SWEEP + FIB  |  XAUUSD 5m  |  timezone {cfg.tz} (IST)")
    print(f"range {cfg.range_start}-{cfg.range_end} (body only)   entry window "
          f"{cfg.entry_start}-{cfg.entry_end}")
    mode = ("candle WICK pierces" if cfg.sweep_mode == "wick" else "candle CLOSES beyond")
    same = "same-candle reclaim allowed" if cfg.same_candle_reclaim else "reclaim must be a later candle"
    print(f"sweep = {mode} Fib {cfg.fib_long} (long) / Fib {cfg.fib_short} (short); {same}")
    print(f"min penetration {cfg.min_pen_atr} x ATR")
    print(f"expiry {cfg.sweep_expiry_bars} bars   SL lookback {cfg.sl_lookback} candles   "
          f"space filter >= {cfg.min_space_atr} x ATR({cfg.atr_period})")
    print(f"days {sel[0]} .. {sel[-1]}  ({len(sel)} sessions)")
    print("=" * 100)

    for day in sel:
        day_bars = ist[ist.index.date == day]
        rng = build_range(day_bars, cfg)
        print(f"\n### {day}  ({day_bars.index[0].strftime('%a')})")
        if rng is None:
            print("   no valid 11:30-12:30 range — skipped")
            continue
        f = rng["fibs"]
        print(f"   range   low {rng['range_low']:.2f}   high {rng['range_high']:.2f}   "
              f"size {rng['range_size']:.2f}   ({rng['range_bars']} bars, bodies only)")
        print(f"   fib -1  {f[-1.0]:.2f}   fib 0 {f[0.0]:.2f}   fib 1 {f[1.0]:.2f}   "
              f"fib 2 {f[2.0]:.2f}")

        d = diag.loc[day]
        print(f"   funnel  sweeps {d['sweep_events']} ({d['sweep_bars']} bars)   "
              f"reclaims {d['reclaims']}   "
              f"setups {d['setups']}  (valid {d['valid']}, blocked {d['blocked']})   "
              f"expired {d['expired']}")

        if setups.empty:
            continue
        day_setups = setups[setups["date"] == day]
        for _, s in day_setups.iterrows():
            tag = "BUY " if s["side"] == "long" else "SELL"
            mark = "OK " if s["status"] == "VALID" else "XX "
            span = f"{s['first_sweep_ts']:%H:%M}"
            if s["sweep_bars"] > 1:
                span += f"..{s['last_sweep_ts']:%H:%M}"
            print(f"   {mark}{tag}  sweep {span} ({s['sweep_bars']} bars, "
                  f"extreme {s['sweep_extreme']:.2f}, pen {s['penetration']:.2f})")
            print(f"        reclaim {s['reclaim_ts']:%H:%M} close {s['reclaim_close']:.2f}"
                  f"  ->  ENTRY {s['entry_ts']:%H:%M} @ {s['entry']:.2f}"
                  f"   SL {s['sl']:.2f}   risk {s['risk']:.2f}"
                  f"   space {s['space_atr']:.2f}ATR   ATR {s['atr']:.2f}")
            if s["status"] != "VALID":
                print(f"        blocked: {s['block_reason']}")

    print("\n" + "=" * 100)
    if setups.empty:
        print("No sweep+reclaim setups in this window.")
    else:
        v = setups[setups["status"] == "VALID"]
        print(f"TOTAL   setups {len(setups)}   valid {len(v)}   "
              f"blocked {len(setups) - len(v)}")
        print(f"        longs {(setups['side'] == 'long').sum()}   "
              f"shorts {(setups['side'] == 'short').sum()}")
        cols = ["date", "side", "status", "first_sweep_ts", "reclaim_ts", "entry_ts",
                "entry", "sl", "risk", "space_atr", "penetration"]
        print("\n" + setups[cols].to_string(index=False, float_format=lambda x: f"{x:.2f}"))
        if args.csv:
            setups.to_csv(args.csv, index=False)
            print(f"\nwritten -> {args.csv}")


if __name__ == "__main__":
    main()
