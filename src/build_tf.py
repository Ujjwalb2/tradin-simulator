#!/usr/bin/env python3
"""
Build multi-timeframe XAUUSD bars (5m, 15m, 1h, 4h, 1d) for charting and bar replay.

Same source as fetch_data.py -- Dukascopy 1-minute bid and ask candles -- read through its
raw .bi5 cache, so days already on disk are decoded locally and only missing days are
downloaded. The research dataset in data/processed/ is left untouched.

Sessions follow the "New York close" convention used by MT4/MT5 brokers and by TradingView
for spot metals:
  1d  runs 17:00 -> 17:00 America/New_York. Sunday evening belongs to Monday, so every
      week has five daily bars.
  4h  is aligned to that session: 17:00, 21:00, 01:00, 05:00, 09:00, 13:00 New York.
  5m, 15m and 1h are aligned to the clock.
DST is resolved per bar. Only minutes that actually ticked (volume > 0) form bars, and the
range is trimmed to whole daily sessions so no timeframe starts or ends on a partial bar.

open/high/low/close are BID prices (what MT4/MT5 and TradingView chart for metals); the ASK
OHLC sits alongside so a replayed buy can be filled at the real ask.

Outputs:
  data/tf/XAUUSD_{5m,15m,1h,4h,1d}.csv and .parquet
  replay/data/XAUUSD/                     compact columns for the browser replay tool

Usage:
    python src/build_tf.py                        # 2020-01-01 -> yesterday (UTC)
    python src/build_tf.py --start 2015-01-01 --end 2026-09-17
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_data import DECIMALS, cache_path, fetch_side  # noqa: E402
from replay_data import TIMEFRAMES, epoch_seconds, write_symbol  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TF_DIR = ROOT / "data" / "tf"

SESSION_ALIGNED = {"4h", "1d"}
NY_CLOSE_SHIFT = 7 * 3600  # New York wall clock + 7h puts the 17:00 close at midnight
PRICE_COLS = ["open", "high", "low", "close", "ask_open", "ask_high", "ask_low", "ask_close"]
REPLAY_META = {  # per-symbol settings the replay tool reads from meta.json
    "name": "Gold spot (XAU/USD)", "source": "Dukascopy", "price": "bid",
    "ccy": "$", "locale": "en-US", "lot": 100, "lotStep": 0.01, "lots": 0.1, "unit": "oz",
    "slipUnit": "$/oz", "balance": 10000, "hasSpread": True, "hasVolume": True,
    "ccyCode": "USD", "update": "python src/build_tf.py",
}
AGG = {
    "open": ("open", "first"),
    "high": ("high", "max"),
    "low": ("low", "min"),
    "close": ("close", "last"),
    "ask_open": ("ask_open", "first"),
    "ask_high": ("ask_high", "max"),
    "ask_low": ("ask_low", "min"),
    "ask_close": ("ask_close", "last"),
    "volume": ("volume", "sum"),
    "spread": ("spread", "mean"),
    "minutes": ("close", "size"),
}


def forget_unpublished(symbol: str, days: list[dt.date]) -> None:
    """fetch_data caches a 404 as an empty file meaning 'no data that day'. For the last
    week that can just mean Dukascopy has not published the file yet, so drop those markers
    and let the next run ask again instead of keeping a permanent hole."""
    today = dt.datetime.now(dt.timezone.utc).date()
    for day in days:
        if (today - day).days > 7:
            continue
        for side in ("bid", "ask"):
            path = cache_path(symbol, day, side)
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
                print(f"  note: no {side} file for {day} yet; will retry next run", flush=True)


def load_1m(symbol: str, start: dt.date, end: dt.date, workers: int) -> pd.DataFrame:
    """1-minute bid+ask candles, including the zero-volume padding Dukascopy ships."""
    days = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    days = [d for d in days if d.weekday() != 5]
    scale = 10 ** -DECIMALS.get(symbol, 5)
    print(f"{symbol}: {start} -> {end} ({len(days)} candidate days, both sides)", flush=True)

    bid = fetch_side(symbol, days, "bid", scale, workers)
    ask = fetch_side(symbol, days, "ask", scale, workers)
    forget_unpublished(symbol, days)

    lopsided = set(bid.index.date) ^ set(ask.index.date)
    if lopsided:
        print(f"  !! {len(lopsided)} day(s) present on only one side and dropped: "
              f"{', '.join(str(d) for d in sorted(lopsided)[:10])}", file=sys.stderr)

    m = bid.join(ask, lsuffix="_bid", rsuffix="_ask", how="inner")
    out = pd.DataFrame(index=m.index)
    for col in ("open", "high", "low", "close"):
        out[col] = m[f"{col}_bid"]
    for col in ("open", "high", "low", "close"):
        out[f"ask_{col}"] = m[f"{col}_ask"]
    out["volume"] = m["volume_bid"] + m["volume_ask"]
    out["spread"] = out["ask_close"] - out["close"]
    return out


def bucket_starts(ts: np.ndarray, ny_off: np.ndarray, tf: str) -> np.ndarray:
    """UTC second at which each row's bar opens."""
    sec = TIMEFRAMES[tf]
    clock = ts + ny_off + NY_CLOSE_SHIFT if tf in SESSION_ALIGNED else ts
    return ts - clock % sec


def build(df1m: pd.DataFrame, start: dt.date) -> dict[str, pd.DataFrame]:
    data_end = epoch_seconds(df1m.index).max() + 60  # the padding runs to the last minute

    live = df1m[df1m["volume"] > 0]
    ts = epoch_seconds(live.index)
    ny_off = epoch_seconds(live.index.tz_convert("America/New_York")) - ts

    # Keep whole sessions only: trading date >= start, and the session closed before the
    # data ran out (DST changes fall on weekends, so a trading session is always 24h).
    session = bucket_starts(ts, ny_off, "1d")
    trade_day = (ts + ny_off + NY_CLOSE_SHIFT) // 86400
    start_day = (dt.datetime.combine(start, dt.time()) - dt.datetime(1970, 1, 1)).days
    keep = (trade_day >= start_day) & (session + 86400 <= data_end)
    live, ts, ny_off = live[keep], ts[keep], ny_off[keep]

    bars: dict[str, pd.DataFrame] = {}
    for tf in TIMEFRAMES:
        b = live.groupby(bucket_starts(ts, ny_off, tf), sort=True).agg(**AGG)
        b.index = pd.to_datetime(b.index, unit="s", utc=True)
        b.index.name = "time_utc"
        b[PRICE_COLS] = b[PRICE_COLS].round(3)
        b["spread"] = b["spread"].round(4)
        b["volume"] = b["volume"].round(5)
        if tf == "1d":
            server = b.index.tz_convert("America/New_York").tz_localize(None) + pd.Timedelta(hours=7)
            assert (server == server.normalize()).all(), "daily bars must open at 17:00 New York"
            b.insert(0, "date", server.normalize().date)
        bars[tf] = b
    return bars


def validate(bars: dict[str, pd.DataFrame]) -> None:
    """The replay tool rebuilds a forming higher-timeframe bar from the 5m bars inside it,
    so every higher bar must be exactly the aggregate of its 5m bars."""
    f = bars["5m"]
    t5 = epoch_seconds(f.index)
    for tf in ("15m", "1h", "4h", "1d"):
        b = bars[tf]
        k = np.searchsorted(epoch_seconds(b.index), t5, side="right") - 1
        assert (k >= 0).all(), f"5m bars before the first {tf} bar"
        g = f.groupby(k).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                             close=("close", "last"), ask_high=("ask_high", "max"),
                             ask_low=("ask_low", "min"), volume=("volume", "sum"))
        assert len(g) == len(b), f"{tf}: {len(g)} groups vs {len(b)} bars"
        for col in ("open", "high", "low", "close", "ask_high", "ask_low"):
            diff = np.abs(g[col].to_numpy() - b[col].to_numpy()).max()
            assert diff < 1e-6, f"{tf} {col} differs from its 5m aggregate by {diff}"
        vdiff = np.abs(g["volume"].to_numpy() - b["volume"].to_numpy()).max()
        assert vdiff < 1e-3, f"{tf} volume differs from its 5m aggregate by {vdiff}"

    ny = bars["4h"].index.tz_convert("America/New_York")
    assert set(ny.hour) <= {17, 21, 1, 5, 9, 13}, f"4h bars open at NY hours {sorted(set(ny.hour))}"
    assert (ny.minute == 0).all()
    weekdays = pd.to_datetime(bars["1d"]["date"]).dt.weekday
    assert (weekdays < 5).all(), "a daily bar landed on a weekend"


def write_tables(bars: dict[str, pd.DataFrame], symbol: str) -> None:
    TF_DIR.mkdir(parents=True, exist_ok=True)
    for tf, b in bars.items():
        b.to_parquet(TF_DIR / f"{symbol}_{tf}.parquet")
        b.to_csv(TF_DIR / f"{symbol}_{tf}.csv", date_format="%Y-%m-%d %H:%M:%S")


def write_replay(bars: dict[str, pd.DataFrame], symbol: str) -> None:
    write_symbol(symbol, bars, REPLAY_META)


def main() -> None:
    yesterday = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    ap = argparse.ArgumentParser(description="Build 5m/15m/1h/4h/1d XAUUSD bars from Dukascopy 1m data.")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--start", default="2020-01-01", help="first trading date to keep")
    ap.add_argument("--end", default=yesterday.isoformat(), help="last UTC day to fetch (max: yesterday)")
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()

    symbol = args.symbol.upper()
    start = dt.date.fromisoformat(args.start)
    end = min(dt.date.fromisoformat(args.end), yesterday)  # today's file is still being written

    # Fetch one extra day in front: the first session opens at 17:00 New York the day before.
    df1m = load_1m(symbol, start - dt.timedelta(days=1), end, args.workers)
    bars = build(df1m, start)
    validate(bars)
    write_tables(bars, symbol)
    write_replay(bars, symbol)

    print()
    for tf, b in bars.items():
        print(f"{tf:>4}: {len(b):>9,} bars  {b.index[0]:%Y-%m-%d %H:%M} -> {b.index[-1]:%Y-%m-%d %H:%M} UTC")
    d = bars["1d"]
    print(f"daily: {d['date'].iloc[0]} -> {d['date'].iloc[-1]} ({len(d):,} sessions), "
          f"price {d['low'].min():.2f} .. {d['high'].max():.2f}")
    sessions = set(d["date"])
    weekdays = pd.bdate_range(d["date"].iloc[0], d["date"].iloc[-1]).date
    missing = [day for day in weekdays if day not in sessions]
    print(f"weekdays with no session (holidays): {len(missing)}"
          + (f" -> {', '.join(str(x) for x in missing[:12])}" + (" ..." if len(missing) > 12 else "") if missing else ""))
    print(f"\ntables : {TF_DIR}\nreplay : replay/data/{symbol}/")


if __name__ == "__main__":
    main()
