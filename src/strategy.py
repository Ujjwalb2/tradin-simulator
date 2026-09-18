#!/usr/bin/env python3
"""
Gold Liquidity Sweep + Fibonacci strategy — setup detection.

Implements the rulebook as an explicit state machine, per trading day:

  1. RANGE   11:30-12:30 IST, body-only high/low (wicks ignored).
  2. FIB     0 = range low, 1 = range high; outer triggers are -1 (long) and 2 (short).
  3. ARMED   from 14:25 IST, a 5-min candle that CLOSES beyond the outer level arms a
             sweep. Deeper excursions update the stored extreme and refresh the clock.
  4. RECLAIM a LATER candle closing back inside the level completes the sequence.
  5. SETUP   breathable-space check (ATR-based) marks the setup valid or blocked.

Detection and filtering are kept separate on purpose: a setup blocked by the space
filter is still recorded as a setup, so tightening or loosening the threshold never
erases the underlying market structure. See rulebook section 7.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

FIB_LEVELS = [-1.0, -0.62, -0.5, 0.0, 0.5, 1.0, 1.27, 1.62, 2.0]


@dataclass
class Config:
    tz: str = "Asia/Kolkata"
    range_start: str = "11:30"      # inclusive
    range_end: str = "12:30"        # exclusive — the 12:30 bar is not part of the range
    entry_start: str = "14:25"      # inclusive
    entry_end: str = "21:25"        # inclusive: last bar allowed to trigger a reclaim
    fib_long: float = -1.0          # outer level swept for a long setup
    fib_short: float = 2.0          # outer level swept for a short setup
    sweep_mode: str = "close"       # "close": candle closes beyond the level; "wick": pierce only
    same_candle_reclaim: bool = True  # a wick that pierces and closes back inside is a complete sweep
    min_pen_atr: float = 0.0        # "a mere touch is not enough": min penetration, in ATR units
    reclaim_depth_r: float = 0.0    # how far back INSIDE the level the reclaim must close,
                                    # in units of range size (0.38 = the next fib in)
    ema_period: int = 7             # confirmation EMA measured on the reclaim candle
    sweep_expiry_bars: int = 12     # armed sweep goes stale after this many bars
    sl_mode: str = "atr"            # "atr": stop is a multiple of ATR; "structure": prior-candle extreme
    sl_atr_mult: float = 1.5        # k in  stop = entry -/+ k * ATR
    sl_lookback: int = 5            # N completed candles, used when sl_mode == "structure"
    atr_period: int = 14
    min_space_atr: float = 0.25     # breathable space, in ATR units
    min_range: float = 0.0          # optional: ignore days with a degenerate range


def fib_price(low: float, high: float, level: float) -> float:
    return low + (high - low) * level


def add_atr(df: pd.DataFrame, period: int) -> pd.Series:
    prev_close = df["close"].shift(1)
    tr = pd.concat(
        [
            df["high"] - df["low"],
            (df["high"] - prev_close).abs(),
            (df["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def build_range(day_bars: pd.DataFrame, cfg: Config) -> dict | None:
    """Body-only high/low over the range window. Wicks are deliberately ignored."""
    window = day_bars.between_time(cfg.range_start, cfg.range_end, inclusive="left")
    if window.empty:
        return None
    body_high = window[["open", "close"]].max(axis=1)
    body_low = window[["open", "close"]].min(axis=1)
    high, low = float(body_high.max()), float(body_low.min())
    if high - low <= cfg.min_range:
        return None
    return {
        "range_high": high,
        "range_low": low,
        "range_size": high - low,
        "range_bars": len(window),
        "fibs": {lvl: fib_price(low, high, lvl) for lvl in FIB_LEVELS},
    }


def scan_day(day_bars: pd.DataFrame, cfg: Config) -> tuple[list[dict], dict]:
    """Run the state machine over one day. Returns (setups, per-day diagnostics)."""
    rng = build_range(day_bars, cfg)
    diag = {"sweep_events": 0, "sweep_bars": 0, "reclaims": 0, "setups": 0,
            "valid": 0, "blocked": 0, "expired": 0}
    if rng is None:
        diag["note"] = "no range window"
        return [], diag

    lvl_long = rng["fibs"][cfg.fib_long]
    lvl_short = rng["fibs"][cfg.fib_short]

    entry_zone = day_bars.between_time(cfg.entry_start, cfg.entry_end, inclusive="both")
    if entry_zone.empty:
        diag["note"] = "no entry window"
        return [], diag

    idx = day_bars.index
    pos = {ts: i for i, ts in enumerate(idx)}
    setups: list[dict] = []

    # One independent armed state per direction.
    armed = {"long": None, "short": None}

    for ts, bar in entry_zone.iterrows():
        i = pos[ts]

        for side, level in (("long", lvl_long), ("short", lvl_short)):
            depth = cfg.reclaim_depth_r * rng["range_size"]
            if side == "long":
                pierced = bar["low"] < level
                closed_beyond = bar["close"] < level
                closed_inside = bar["close"] >= level + depth
            else:
                pierced = bar["high"] > level
                closed_beyond = bar["close"] > level
                closed_inside = bar["close"] <= level - depth
            swept = pierced if cfg.sweep_mode == "wick" else closed_beyond

            state = armed[side]

            # Expire a stale sweep before doing anything else with it.
            if state is not None and (i - state["last_sweep_i"]) > cfg.sweep_expiry_bars:
                diag["expired"] += 1
                armed[side] = state = None

            if swept:
                # Sweep candle: arm, or deepen an existing sweep and refresh its clock.
                diag["sweep_bars"] += 1
                extreme = float(bar["low"] if side == "long" else bar["high"])
                if state is None:
                    diag["sweep_events"] += 1
                    armed[side] = state = {
                        "first_sweep_ts": ts,
                        "last_sweep_ts": ts,
                        "last_sweep_i": i,
                        "extreme": extreme,
                        "sweep_bars": 1,
                    }
                else:
                    state["last_sweep_ts"] = ts
                    state["last_sweep_i"] = i
                    state["sweep_bars"] += 1
                    state["extreme"] = (
                        min(state["extreme"], extreme) if side == "long"
                        else max(state["extreme"], extreme)
                    )
                # A wick that pierces and closes back inside completes the sequence on
                # this same candle; otherwise stay armed and wait for a later close.
                if not (closed_inside and cfg.same_candle_reclaim and cfg.sweep_mode == "wick"):
                    continue
            elif state is None or not closed_inside:
                continue

            # Reclaim: price is back inside the level with a sweep on the books.
            diag["reclaims"] += 1
            armed[side] = None

            if i + 1 >= len(idx):
                continue  # no next bar to fill on
            entry_ts = idx[i + 1]
            entry_bar = day_bars.iloc[i + 1]
            entry = float(entry_bar["open"])

            # ATR is read off the reclaim candle, which has already closed — no lookahead.
            atr = float(bar["atr"]) if np.isfinite(bar.get("atr", np.nan)) else np.nan
            if not (atr and np.isfinite(atr)):
                continue
            struct_sl = {}
            for n_lb in (4, 5, 6):
                lb = day_bars.iloc[max(0, i + 1 - n_lb): i + 1]
                struct_sl[n_lb] = float(lb["low"].min() if side == "long" else lb["high"].max())
            if cfg.sl_mode == "atr":
                sl = entry - cfg.sl_atr_mult * atr if side == "long" else entry + cfg.sl_atr_mult * atr
            else:
                sl = struct_sl[cfg.sl_lookback]
            risk = entry - sl if side == "long" else sl - entry

            # 7-EMA confirmation, measured on the reclaim candle that has already closed.
            ema = float(bar.get("ema", np.nan))
            ema_ok = bool(bar["close"] > ema if side == "long" else bar["close"] < ema) \
                if np.isfinite(ema) else False
            space = abs(entry - level)
            space_atr = space / atr if atr and np.isfinite(atr) else np.nan
            risk_atr = risk / atr if atr and np.isfinite(atr) else np.nan
            pen = (level - state["extreme"]) if side == "long" else (state["extreme"] - level)
            pen_atr = pen / atr if atr and np.isfinite(atr) else np.nan

            ok_space = np.isfinite(space_atr) and space_atr >= cfg.min_space_atr
            ok_risk = risk > 0
            ok_pen = cfg.min_pen_atr <= 0 or (np.isfinite(pen_atr) and pen_atr >= cfg.min_pen_atr)
            status = "VALID" if (ok_space and ok_risk and ok_pen) else "BLOCKED"
            reasons = []
            if not ok_risk:
                reasons.append("stop on wrong side of entry")
            if not ok_space:
                reasons.append(f"space {space_atr:.2f} ATR < {cfg.min_space_atr}")
            if not ok_pen:
                reasons.append(f"penetration {pen_atr:.2f} ATR < {cfg.min_pen_atr}")

            diag["setups"] += 1
            diag["valid" if status == "VALID" else "blocked"] += 1

            setups.append(
                {
                    "date": ts.date(),
                    "side": side,
                    "status": status,
                    "block_reason": "; ".join(reasons),
                    "range_low": rng["range_low"],
                    "range_high": rng["range_high"],
                    "range_size": rng["range_size"],
                    "fib_level": level,
                    "first_sweep_ts": state["first_sweep_ts"],
                    "last_sweep_ts": state["last_sweep_ts"],
                    "sweep_bars": state["sweep_bars"],
                    "sweep_extreme": state["extreme"],
                    "penetration": pen,
                    "pen_atr": pen_atr,
                    "ema": ema,
                    "ema_ok": ema_ok,
                    "sl_struct_4": struct_sl[4],
                    "sl_struct_5": struct_sl[5],
                    "sl_struct_6": struct_sl[6],
                    "reclaim_ts": ts,
                    "reclaim_close": float(bar["close"]),
                    "entry_ts": entry_ts,
                    "entry": entry,
                    "sl": sl,
                    "risk": risk,
                    "atr": atr,
                    "space": space,
                    "space_atr": space_atr,
                    "risk_atr": risk_atr,
                    "spread": float(entry_bar.get("spread", np.nan)),
                }
            )

    return setups, diag


def run(bars_utc: pd.DataFrame, cfg: Config) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scan every day in `bars_utc` (UTC-indexed 5m bars). Returns (setups, diagnostics)."""
    df = bars_utc.tz_convert(cfg.tz).copy()
    df["atr"] = add_atr(df, cfg.atr_period)
    df["ema"] = df["close"].ewm(span=cfg.ema_period, adjust=False).mean()

    all_setups: list[dict] = []
    diags: list[dict] = []
    for day, day_bars in df.groupby(df.index.date, sort=True):
        setups, diag = scan_day(day_bars, cfg)
        diag["date"] = day
        diags.append(diag)
        all_setups.extend(setups)

    setups_df = pd.DataFrame(all_setups)
    diag_df = pd.DataFrame(diags).set_index("date")
    return setups_df, diag_df
