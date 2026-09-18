#!/usr/bin/env python3
"""
Fetch XAUUSD (or any Dukascopy instrument) 1-minute OHLCV candles and resample to 5-minute.

Source: Dukascopy public datafeed, one LZMA-compressed .bi5 file per day per side.
  https://datafeed.dukascopy.com/datafeed/<SYM>/<yyyy>/<mm-1 zero-padded>/<dd>/<SIDE>_candles_min_1.bi5

Record layout (24 bytes, big-endian): time_offset_s:int32, open:int32, close:int32,
low:int32, high:int32, volume:float32.  Integer prices are in points; XAUUSD has 3
decimals, so divide by 1000.

Raw .bi5 files are cached under data/raw/ so re-runs are cheap.

Usage:
    python src/fetch_data.py --start 2022-09-01 --end 2026-09-08
"""
from __future__ import annotations

import argparse
import datetime as dt
import lzma
import ssl
import struct
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import certifi
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

BASE_URL = "https://datafeed.dukascopy.com/datafeed"
RECORD = struct.Struct(">5if")
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
SSL_CTX = ssl.create_default_context(cafile=certifi.where())

# Price scale by instrument decimals. XAUUSD quotes to 3 dp on Dukascopy.
DECIMALS = {"XAUUSD": 3, "XAGUSD": 3, "EURUSD": 5, "GBPUSD": 5, "USDJPY": 3}


def day_url(symbol: str, day: dt.date, side: str) -> str:
    return (
        f"{BASE_URL}/{symbol}/{day.year:04d}/{day.month - 1:02d}/{day.day:02d}"
        f"/{side.upper()}_candles_min_1.bi5"
    )


def cache_path(symbol: str, day: dt.date, side: str) -> Path:
    return RAW / symbol / side.lower() / f"{day:%Y-%m-%d}.bi5"


def download_day(symbol: str, day: dt.date, side: str, retries: int = 6) -> bytes | None:
    """Return raw bi5 bytes for one day, or None if the feed has no file (weekend/holiday).

    Dukascopy intermittently answers 503 under load, so transient failures are retried
    with backoff; a 404 is a real 'no data for this day'.
    """
    path = cache_path(symbol, day, side)
    if path.exists():
        return path.read_bytes()

    url = day_url(symbol, day, side)
    delay = 0.4
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45, context=SSL_CTX) as resp:
                raw = resp.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            return raw
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"")  # cache the "no data" answer
                return b""
            if attempt == retries - 1:
                raise
            if exc.code == 429:
                # Rate limited: the feed wants us to slow down properly, not nibble.
                time.sleep(min(10.0 * (attempt + 1), 60.0))
                continue
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries - 1:
                raise
        time.sleep(delay)
        delay = min(delay * 1.8, 8.0)
    return None


def decode_day(raw: bytes, day: dt.date, scale: float) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()
    data = lzma.LZMADecompressor(format=lzma.FORMAT_AUTO).decompress(raw)
    n = len(data) // RECORD.size
    if n == 0:
        return pd.DataFrame()

    arr = np.frombuffer(data[: n * RECORD.size], dtype=">i4").reshape(n, 6)
    vol = np.frombuffer(data[: n * RECORD.size], dtype=">f4").reshape(n, 6)[:, 5]

    base = pd.Timestamp(day, tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": base + pd.to_timedelta(arr[:, 0].astype("int64"), unit="s"),
            "open": arr[:, 1] * scale,
            "close": arr[:, 2] * scale,
            "low": arr[:, 3] * scale,
            "high": arr[:, 4] * scale,
            "volume": vol.astype("float64"),
        }
    )


def fetch_side(symbol: str, days: list[dt.date], side: str, scale: float, workers: int) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    failed: list[dt.date] = []
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_day, symbol, d, side): d for d in days}
        for fut in as_completed(futures):
            day = futures[fut]
            try:
                raw = fut.result()
            except Exception as exc:  # noqa: BLE001 - collect and repair below
                print(f"  ! {side} {day}: {exc}", file=sys.stderr)
                failed.append(day)
                continue
            df = decode_day(raw, day, scale)
            if not df.empty:
                frames.append(df)
            done += 1
            if done % 100 == 0:
                print(f"  {side}: {done}/{len(days)} days", flush=True)

    # Repair pass: a silently dropped day becomes a silent hole in the backtest,
    # so retry failures one at a time until they stick or we truly give up.
    for attempt in range(3):
        if not failed:
            break
        print(f"  repair pass {attempt + 1}: {len(failed)} missing {side} day(s)", flush=True)
        retry, failed = failed, []
        for day in retry:
            time.sleep(0.3)
            try:
                raw = download_day(symbol, day, side, retries=8)
            except Exception as exc:  # noqa: BLE001
                print(f"  ! retry {side} {day}: {exc}", file=sys.stderr)
                failed.append(day)
                continue
            df = decode_day(raw, day, scale)
            if not df.empty:
                frames.append(df)
    if failed:
        print(f"  !! {side}: {len(failed)} day(s) UNRECOVERED: "
              f"{', '.join(str(d) for d in sorted(failed)[:10])}", file=sys.stderr)

    if not frames:
        raise SystemExit(f"No data downloaded for side {side}")
    out = pd.concat(frames, ignore_index=True).sort_values("timestamp")
    return out.drop_duplicates("timestamp").set_index("timestamp")


def resample_5m(df1m: pd.DataFrame) -> pd.DataFrame:
    """5-minute bars from 1-minute mid prices.

    Only minutes that actually traded (volume > 0) form a bar, so weekend/holiday
    padding and dead no-tick minutes never invent price action.
    """
    live = df1m[df1m["volume"] > 0]
    agg = live.resample("5min").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        spread=("spread", "mean"),
        minutes=("close", "size"),
    )
    return agg.dropna(subset=["open"])


def main() -> None:
    ap = argparse.ArgumentParser(description="Download Dukascopy 1m candles and build 5m bars.")
    ap.add_argument("--symbol", default="XAUUSD")
    ap.add_argument("--start", default="2022-09-01")
    ap.add_argument("--end", default=(dt.date.today() - dt.timedelta(days=1)).isoformat())
    ap.add_argument("--workers", type=int, default=12)
    args = ap.parse_args()

    symbol = args.symbol.upper()
    scale = 10 ** -DECIMALS.get(symbol, 5)
    start = dt.date.fromisoformat(args.start)
    end = dt.date.fromisoformat(args.end)

    # Skip Saturdays outright; the feed has no session data for them.
    days = [
        d for d in (start + dt.timedelta(days=i) for i in range((end - start).days + 1))
        if d.weekday() != 5
    ]
    print(f"{symbol}: {start} -> {end} ({len(days)} candidate days, both sides)", flush=True)

    bid = fetch_side(symbol, days, "bid", scale, args.workers)
    ask = fetch_side(symbol, days, "ask", scale, args.workers)

    bid_days = {ts.date() for ts in bid.index}
    ask_days = {ts.date() for ts in ask.index}
    lopsided = (bid_days ^ ask_days)
    if lopsided:
        print(f"  !! {len(lopsided)} day(s) present on only one side and dropped by the join: "
              f"{', '.join(str(d) for d in sorted(lopsided)[:10])}", file=sys.stderr)

    merged = bid.join(ask, lsuffix="_bid", rsuffix="_ask", how="inner")
    out = pd.DataFrame(index=merged.index)
    for col in ("open", "high", "low", "close"):
        out[col] = (merged[f"{col}_bid"] + merged[f"{col}_ask"]) / 2
        out[f"bid_{col}"] = merged[f"{col}_bid"]
        out[f"ask_{col}"] = merged[f"{col}_ask"]
    out["volume"] = merged["volume_bid"] + merged["volume_ask"]
    out["spread"] = merged["close_ask"] - merged["close_bid"]
    out.index.name = "timestamp"

    PROCESSED.mkdir(parents=True, exist_ok=True)
    p1 = PROCESSED / f"{symbol}_1m.parquet"
    out.to_parquet(p1)

    bars = resample_5m(out)
    p5 = PROCESSED / f"{symbol}_5m.parquet"
    bars.to_parquet(p5)
    bars.to_csv(PROCESSED / f"{symbol}_5m.csv")

    traded = out[out["volume"] > 0]
    print(f"\n1m bars : {len(out):,} rows ({len(traded):,} with ticks) -> {p1}")
    print(f"5m bars : {len(bars):,} rows -> {p5}")
    print(f"range   : {bars.index[0]} .. {bars.index[-1]}  (UTC)")
    print(f"price   : {bars['low'].min():.2f} .. {bars['high'].max():.2f}")
    print(f"spread  : median {bars['spread'].median():.3f}  p90 {bars['spread'].quantile(0.9):.3f}")

    sessions = sorted({ts.date() for ts in bars.index})
    weekdays = [d for d in days if d.weekday() < 5]
    missing = sorted(set(weekdays) - set(sessions))
    print(f"coverage: {len(sessions)} sessions with data; "
          f"{len(missing)} weekday(s) with none"
          + (f" -> {', '.join(str(d) for d in missing[:10])}" if missing else ""))


if __name__ == "__main__":
    main()
