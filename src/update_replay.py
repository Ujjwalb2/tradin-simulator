#!/usr/bin/env python3
"""
Top up the published replay data with the newest days, instead of rebuilding years of it.

    python src/update_replay.py                    # every symbol in replay/data/
    python src/update_replay.py --symbol NIFTY
    python src/update_replay.py --days 14          # redo a longer tail

It reads what is already in replay/data/<SYMBOL>/, fetches only the last few days from the
same source, rebuilds those sessions and replaces the tail with them. Rebuilding a stretch
that is already published, rather than only what is missing, means a day the source has since
revised gets corrected instead of doubled.

This is what the daily GitHub job runs. A full rebuild has to download about 4,200 Dukascopy
day files, which that feed is far too rate-limited to serve inside a job's time limit.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_nse  # noqa: E402
import build_tf  # noqa: E402
from replay_data import PRICE_SCALE, REPLAY_DATA, epoch_seconds, read_symbol, write_symbol  # noqa: E402

GENERATED = {"symbol", "price_scale", "built_utc", "tfs", "first", "last"}  # write_symbol fills these in


def ticker_of(symbol: str, meta: dict) -> str:
    """The name the source knows the symbol by: recorded when it was built, or read back out
    of the build command that older data carries, or the symbol itself."""
    found = re.search(r"--ticker\s+(\S+)", meta.get("update", ""))
    return meta.get("ticker") or (found.group(1) if found else symbol)


def fresh_gold(symbol: str, since: dt.date, workers: int) -> dict[str, pd.DataFrame] | None:
    """Rebuild Dukascopy sessions from `since` on: a couple of dozen day files, not years."""
    yesterday = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    if since > yesterday:
        return None
    # A session opens the evening before its trading date, so fetch one extra day.
    df1m = build_tf.load_1m(symbol, since - dt.timedelta(days=1), yesterday, workers)
    bars = build_tf.build(df1m, since)
    if not len(bars["5m"]):
        return None
    build_tf.validate(bars)
    return bars


def fresh_nse(ticker: str, since: dt.date) -> dict[str, pd.DataFrame] | None:
    """Rebuild NSE sessions from `since` on: one Upstox request per calendar month touched."""
    yesterday = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=build_nse.IST_OFFSET)).date() \
        - dt.timedelta(days=1)
    if since > yesterday:
        return None
    inst = build_nse.resolve(ticker)
    symbol = re.sub(r"[^A-Z0-9&_-]", "", ticker.strip().upper())
    minutes = build_nse.frame(build_nse.fetch_minutes(inst["key"], build_nse.RAW / symbol, since, yesterday))
    if minutes.empty:
        return None
    no_context = pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                              index=pd.DatetimeIndex([], tz="UTC", name="time_utc"))
    bars = build_nse.build(minutes, no_context)
    build_nse.validate(bars)
    return bars


def merge(old: dict[str, pd.DataFrame], fresh: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Published bars from before the rebuilt stretch, then the rebuilt stretch. The rebuilt
    bars are cut down to the published columns, which is everything the replay tool reads."""
    return {tf: pd.concat([old[tf][old[tf].index < new.index[0]], new[old[tf].columns]])
            for tf, new in fresh.items()}


def same_bars(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    """Equal once written: prices to the 1/1000 the files store, volume as float32."""
    if not a.index.equals(b.index):
        return False
    for col in a.columns:
        x, y = a[col].to_numpy(), b[col].to_numpy()
        if col == "date":
            equal = (x == y).all()
        elif col == "volume":
            equal = np.array_equal(np.nan_to_num(x).astype("f4"), np.nan_to_num(y).astype("f4"))
        else:
            equal = np.array_equal(np.rint(x * PRICE_SCALE), np.rint(y * PRICE_SCALE))
        if not equal:
            return False
    return True


def check(bars: dict[str, pd.DataFrame], symbol: str) -> None:
    """The promise the replay tool relies on, re-checked across the join: bars only move
    forward, and every higher bar is exactly the aggregate of its 5m bars. Daily history from
    before the minute data (NSE context) sits ahead of the 5m series and is not aggregated."""
    f = bars["5m"]
    assert f.index.is_monotonic_increasing and not f.index.has_duplicates, f"{symbol} 5m bars are out of order"
    t5 = epoch_seconds(f.index)
    for tf, b in bars.items():
        assert b.index.is_monotonic_increasing and not b.index.has_duplicates, f"{symbol} {tf} bars are out of order"
        if tf == "5m":
            continue
        k = np.searchsorted(epoch_seconds(b.index), t5, side="right") - 1
        assert (k >= 0).all(), f"{symbol}: 5m bars before the first {tf} bar"
        inside = b.iloc[k[0]:]  # skips daily context, keeps a bar that opens before its first 5m bar
        k -= k[0]
        g = f.groupby(k).agg(open=("open", "first"), high=("high", "max"),
                             low=("low", "min"), close=("close", "last"))
        assert len(g) == len(inside), f"{symbol} {tf}: {len(g)} groups vs {len(inside)} bars"
        for col in ("open", "high", "low", "close"):
            diff = np.abs(g[col].to_numpy() - inside[col].to_numpy()).max()
            assert diff < 1e-6, f"{symbol} {tf} {col} differs from its 5m aggregate by {diff}"


def update(symbol: str, days: int, workers: int) -> bool:
    """Returns whether anything new was published."""
    meta, old = read_symbol(symbol)
    was = old["5m"].index[-1]
    print(f"\n=== {symbol}: published through {was:%Y-%m-%d %H:%M} UTC", flush=True)

    if meta.get("source", "").startswith("Upstox"):
        ist = was + pd.Timedelta(seconds=build_nse.IST_OFFSET)
        fresh = fresh_nse(ticker_of(symbol, meta), (ist - pd.Timedelta(days=days)).date())
    else:
        fresh = fresh_gold(symbol, (was - pd.Timedelta(days=days)).date(), workers)
    if fresh is None:
        print("  the source has nothing past that yet")
        return False

    bars = merge(old, fresh)
    check(bars, symbol)
    if all(same_bars(bars[tf], old[tf]) for tf in bars):
        print(f"  no new sessions, and the last {days} days are unchanged")
        return False
    write_symbol(symbol, bars, {k: v for k, v in meta.items() if k not in GENERATED})
    now = bars["5m"].index[-1]
    print(f"  now through {now:%Y-%m-%d %H:%M} UTC "
          f"({len(bars['5m']) - len(old['5m']):+,} five-minute bars, {len(bars['5m']):,} total)"
          + ("; no new session, but the source revised recent bars" if now == was else ""))
    return True


def verify(symbol: str) -> None:
    """Read a symbol back from its files and check it, so a half-written update is caught
    before it is published rather than on someone's screen."""
    meta, bars = read_symbol(symbol)
    check(bars, symbol)
    print(f"  {symbol}: {len(bars['5m']):,} five-minute bars, through {meta['last']}, reads back clean")


def main() -> None:
    ap = argparse.ArgumentParser(description="Add the newest days to the published replay data.")
    ap.add_argument("--symbol", action="append", help="default: every symbol in replay/data/")
    ap.add_argument("--days", type=int, default=7, help="how much of the tail to rebuild")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--verify", action="store_true", help="only re-read and check what is already published")
    args = ap.parse_args()

    symbols = args.symbol or sorted(p.name for p in REPLAY_DATA.iterdir() if (p / "meta.json").exists())
    if args.verify:
        print("checking the published files")
        for symbol in symbols:
            verify(symbol)
        return

    failed = []
    for symbol in symbols:
        try:
            update(symbol, args.days, args.workers)
        except (Exception, SystemExit) as exc:  # the fetchers exit on HTTP errors; keep going
            print(f"  !! {symbol} not updated: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            if os.environ.get("GITHUB_ACTIONS") == "true":  # shows on the run's page, not just the log
                print(f"::warning title={symbol} not updated::{type(exc).__name__}: {exc}", flush=True)
            failed.append(symbol)
    if failed and len(failed) == len(symbols):
        raise SystemExit(f"no symbol could be updated ({', '.join(failed)})")
    if failed:
        print(f"\nleft at the last published bars: {', '.join(failed)}", file=sys.stderr)


if __name__ == "__main__":
    main()
