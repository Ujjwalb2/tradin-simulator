#!/usr/bin/env python3
"""
Build 5m/15m/1h/4h/1d bars for a Binance spot pair (BTCUSDT by default) from Binance's public
data files, for charting and the replay tool.

    python src/build_binance.py                       # BTCUSDT from 2020
    python src/build_binance.py --symbol ETHUSDT
    python src/build_binance.py --start 2017-08-17    # all of BTCUSDT's history

The files at data.binance.vision are plain downloads with no login. Binance's REST API is not
used: it refuses US addresses, which is where GitHub's runners are. Whole months come as one
file, recent days as one file each, all cached in data/raw/binance/<SYMBOL>/, so reruns only
fetch what is new. The files switched from millisecond to microsecond timestamps in 2025.

Crypto trades around the clock, so bars are plain UTC buckets, the way Binance and TradingView
draw them: 4h bars at 00, 04 ... 20 UTC and a daily bar from 00:00 to 00:00 UTC, seven days a
week. Prices are the last traded price (klines carry no bid/ask), volume is in the base coin.
Outputs: data/tf/<SYMBOL>_<tf>.csv|parquet and replay/data/<SYMBOL>/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import ssl
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import certifi
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_data import PRICE_SCALE, TIMEFRAMES, epoch_seconds, write_symbol  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "binance"
TF_DIR = ROOT / "data" / "tf"
BASE_URL = "https://data.binance.vision/data/spot"
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
QUOTES = ("USDT", "USDC", "FDUSD")         # dollar-priced pairs only: the app shows $ amounts
NAMES = {"BTC": "Bitcoin", "ETH": "Ethereum", "SOL": "Solana", "BNB": "BNB"}
AGG = {"open": ("open", "first"), "high": ("high", "max"), "low": ("low", "min"),
       "close": ("close", "last"), "volume": ("volume", "sum")}


def download(url: str, retries: int = 6) -> bytes | None:
    """The file's bytes, or None when Binance has not published it (yet)."""
    delay = 1.0
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": "chart-replay/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            raise SystemExit(f"Binance answered {exc.code} for {url}")
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise SystemExit(f"no answer from {url}")
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise SystemExit(f"no answer from {url}")


def fetch(symbol: str, kind: str, stamp: str) -> bytes | None:
    """One monthly or daily kline file, from the cache when it has been fetched before. Only
    files that exist are cached, so a day that is not published yet is asked for again."""
    name = f"{symbol}-5m-{stamp}.zip"
    path = RAW / symbol / "5m" / name
    if path.exists():
        return path.read_bytes()
    raw = download(f"{BASE_URL}/{kind}/klines/{symbol}/5m/{name}")
    if raw is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    return raw


def read_klines(raw: bytes) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(raw)) as z, z.open(z.namelist()[0]) as fh:
        df = pd.read_csv(fh, header=None).iloc[:, :6]
    df.columns = ["t", "open", "high", "low", "close", "volume"]
    df = df[pd.to_numeric(df["t"], errors="coerce").notna()].astype(float)  # drops a header row
    t = df.pop("t").to_numpy(dtype=np.int64)
    t = np.where(t >= 10**14, t // 1_000_000, t // 1000)  # microseconds from 2025, milliseconds before
    df.index = pd.DatetimeIndex(pd.to_datetime(t, unit="s", utc=True), name="time_utc")
    return df


def load_5m(symbol: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    """5-minute klines for the UTC days start..end: one file per whole month, one per day for
    the rest, and per day for a month whose file is not out yet."""
    frames: list[pd.DataFrame] = []
    missing: list[dt.date] = []
    months = 0
    first = start.replace(day=1)
    while first <= end:
        nxt = (first + dt.timedelta(days=32)).replace(day=1)
        last = nxt - dt.timedelta(days=1)
        raw = fetch(symbol, "monthly", f"{first:%Y-%m}") if first >= start and last <= end else None
        if raw is not None:
            frames.append(read_klines(raw))
        else:
            day = max(first, start)
            while day <= min(last, end):
                raw = fetch(symbol, "daily", f"{day:%Y-%m-%d}")
                if raw is None:
                    missing.append(day)
                else:
                    frames.append(read_klines(raw))
                day += dt.timedelta(days=1)
        months += 1
        if months % 12 == 0:
            print(f"  {first:%Y-%m}: {sum(len(f) for f in frames):,} candles so far", flush=True)
        first = nxt
    if missing:
        recent = [d for d in missing if (end - d).days < 3]
        older = [d for d in missing if (end - d).days >= 3]
        if recent:
            print(f"  note: {', '.join(map(str, recent))} not published yet; the next run will add it", flush=True)
        if older:
            print(f"  !! no file for {len(older)} older day(s): {', '.join(map(str, older[:8]))}", file=sys.stderr)
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"],
                            index=pd.DatetimeIndex([], tz="UTC", name="time_utc"))
    df = pd.concat(frames).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    lo = pd.Timestamp(start, tz="UTC")
    hi = pd.Timestamp(end + dt.timedelta(days=1), tz="UTC")
    return df[(df.index >= lo) & (df.index < hi) & (df["volume"] > 0)]  # no trades: an outage, not a price


def build(df5: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ts = epoch_seconds(df5.index)
    bars: dict[str, pd.DataFrame] = {}
    for tf, sec in TIMEFRAMES.items():
        b = df5.groupby(ts - ts % sec, sort=True).agg(**AGG)
        b.index = pd.DatetimeIndex(pd.to_datetime(b.index, unit="s", utc=True), name="time_utc")
        if tf == "1d":
            b.insert(0, "date", b.index.tz_localize(None).date)
        bars[tf] = b
    return bars


def validate(bars: dict[str, pd.DataFrame]) -> None:
    """The replay tool rebuilds a forming higher-timeframe bar from the 5m bars inside it, so
    every higher bar must be exactly the aggregate of its 5m bars."""
    f = bars["5m"]
    t5 = epoch_seconds(f.index)
    assert (t5 % 300 == 0).all(), "5m bars must open on the 5-minute grid"
    for tf in ("15m", "1h", "4h", "1d"):
        b = bars[tf]
        tb = epoch_seconds(b.index)
        assert (tb % TIMEFRAMES[tf] == 0).all(), f"{tf} bars must open on UTC boundaries"
        k = np.searchsorted(tb, t5, side="right") - 1
        assert (k >= 0).all(), f"5m bars before the first {tf} bar"
        g = f.groupby(k).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"),
                             close=("close", "last"), volume=("volume", "sum"))
        assert len(g) == len(b), f"{tf}: {len(g)} groups vs {len(b)} bars"
        for col in ("open", "high", "low", "close"):
            diff = np.abs(g[col].to_numpy() - b[col].to_numpy()).max()
            assert diff < 1e-6, f"{tf} {col} differs from its 5m aggregate by {diff}"
        vdiff = np.abs(g["volume"].to_numpy() - b["volume"].to_numpy()) / np.maximum(b["volume"].to_numpy(), 1)
        assert vdiff.max() < 1e-9, f"{tf} volume differs from its 5m aggregate"


def pair(symbol: str) -> tuple[str, str]:
    for quote in QUOTES:
        if symbol.endswith(quote) and len(symbol) > len(quote):
            return symbol[: -len(quote)], quote
    raise SystemExit(f"{symbol}: only dollar-priced pairs are supported ({', '.join(QUOTES)})")


def replay_meta(symbol: str) -> dict:
    base, quote = pair(symbol)
    return {
        "name": f"{NAMES.get(base, base)} ({base}/{quote})", "source": "Binance", "price": "last",
        "ccy": "$", "locale": "en-US", "lot": 1, "lotStep": 0.001, "lots": 0.01, "unit": base,
        "slipUnit": f"$/{base}", "balance": 10000, "hasSpread": False, "hasVolume": True,
        "ccyCode": "USD", "fxSessions": True, "update": f"python src/update_replay.py --symbol {symbol}",
    }


def main() -> None:
    yesterday = dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)
    ap = argparse.ArgumentParser(description="Build 5m/15m/1h/4h/1d bars for a Binance spot pair.")
    ap.add_argument("--symbol", default="BTCUSDT", help="Binance spot pair: BTCUSDT, ETHUSDT ...")
    ap.add_argument("--start", default="2020-01-01", help="first UTC day (BTCUSDT's data begins 2017-08-17)")
    ap.add_argument("--end", default=str(yesterday), help="last UTC day to fetch (max: yesterday)")
    ap.add_argument("--no-tables", action="store_true", help="skip the CSV/parquet exports (the replay data is still written)")
    args = ap.parse_args()

    symbol = args.symbol.strip().upper()
    meta = replay_meta(symbol)
    start = dt.date.fromisoformat(args.start)
    end = min(dt.date.fromisoformat(args.end), yesterday)  # today's file is still being written
    print(f"{symbol}: {start} -> {end}", flush=True)

    df5 = load_5m(symbol, start, end)
    if df5.empty:
        raise SystemExit(f"Binance has no 5m klines for {symbol} in that range")
    ticks = df5[["open", "high", "low", "close"]].to_numpy() * PRICE_SCALE
    if np.abs(ticks - np.rint(ticks)).max() > 1e-6:
        raise SystemExit(f"{symbol} is priced finer than 1/{PRICE_SCALE}, which the replay files cannot store")
    bars = build(df5)
    validate(bars)

    if not args.no_tables:
        TF_DIR.mkdir(parents=True, exist_ok=True)
        for tf, b in bars.items():
            b.to_parquet(TF_DIR / f"{symbol}_{tf}.parquet")
            b.to_csv(TF_DIR / f"{symbol}_{tf}.csv", date_format="%Y-%m-%d %H:%M:%S")
    write_symbol(symbol, bars, meta)

    print()
    for tf, b in bars.items():
        print(f"{tf:>4}: {len(b):>9,} bars  {b.index[0]:%Y-%m-%d %H:%M} -> {b.index[-1]:%Y-%m-%d %H:%M} UTC")
    print("tables : " + ("skipped" if args.no_tables else str(TF_DIR)) + f"\nreplay : replay/data/{symbol}/")


if __name__ == "__main__":
    main()
