#!/usr/bin/env python3
"""
Build 5m/15m/1h/4h/1d bars for any NSE index or stock from Upstox's free historical-candle
API (no login, no API key), for charting and the replay tool.

    python src/build_nse.py                      # NIFTY 50
    python src/build_nse.py --ticker BANKNIFTY
    python src/build_nse.py --ticker RELIANCE    # any NSE equity symbol

Upstox serves 1-minute candles from 2022-01-03. Daily candles go back much further, so the
daily chart also gets older bars (from --context-start) as history; those cannot be replayed
because there are no minutes inside them.

Bars follow the NSE session, 09:15-15:30 IST, aligned the way TradingView draws NSE charts:
5m and 15m bars from 09:15, 1h bars at 09:15, 10:15 ... 15:15, 4h bars 09:15-13:15 and
13:15-15:30, one daily bar per session. Pre-open and post-close prints are dropped, and so is
an evening Muhurat session. Index data has no bid/ask, so the replay fills at the last price.

Complete months are cached in data/raw/upstox/<SYMBOL>/, so reruns only fetch what is new.
Outputs: data/tf/<SYMBOL>_<tf>.csv|parquet and replay/data/<SYMBOL>/.
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import certifi
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from replay_data import epoch_seconds, write_symbol  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "upstox"
TF_DIR = ROOT / "data" / "tf"
API = "https://api.upstox.com/v3/historical-candle"
MASTER_URL = "https://assets.upstox.com/market-quote/instruments/exchange/NSE.json.gz"
SSL_CTX = ssl.create_default_context(cafile=certifi.where())
IST_OFFSET = 19800                         # seconds; India has no daylight saving
FIRST_MINUTE_DAY = dt.date(2022, 1, 3)     # oldest 1-minute candle Upstox serves
SESSION_OPEN = 9 * 60 + 15                 # minutes after midnight IST
SESSION_MINUTES = 375                      # 09:15 -> 15:30
TF_MINUTES = {"5m": 5, "15m": 15, "1h": 60, "4h": 240, "1d": SESSION_MINUTES}
AGG = {"open": ("open", "first"), "high": ("high", "max"), "low": ("low", "min"),
       "close": ("close", "last"), "volume": ("volume", "sum"), "minutes": ("close", "size")}


def get_json(url: str, retries: int = 6) -> dict:
    delay = 1.0
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "gold-replay/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay)
                delay = min(delay * 2, 30)
                continue
            raise SystemExit(f"Upstox answered {exc.code} for {url}: {exc.read()[:300]!r}")
        except (urllib.error.URLError, TimeoutError):
            if attempt == retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 30)
    raise SystemExit(f"no answer from {url}")


def load_master() -> list[dict]:
    """Upstox's public list of NSE instruments, refreshed weekly."""
    path = RAW / "NSE.json.gz"
    if not path.exists() or time.time() - path.stat().st_mtime > 7 * 86400:
        RAW.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(MASTER_URL, headers={"User-Agent": "gold-replay/1.0"})
        with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as resp:
            path.write_bytes(resp.read())
    return json.load(gzip.open(path))


def resolve(ticker: str) -> dict:
    """Ticker -> instrument key, display name and a default lot size. Indices take the lot size
    of their nearest future; stocks default to one share."""
    t = ticker.strip().upper()
    rows = load_master()
    for segment in ("NSE_INDEX", "NSE_EQ"):
        for r in rows:
            if r.get("segment") == segment and (r.get("trading_symbol") or "").upper() == t:
                is_index = segment == "NSE_INDEX"
                lot = 1
                if is_index:
                    futs = [f for f in rows if f.get("segment") == "NSE_FO" and f.get("instrument_type") == "FUT"
                            and (f.get("underlying_symbol") or "").upper() == t]
                    if futs:
                        lot = int(min(futs, key=lambda f: f.get("expiry") or 0).get("lot_size") or 1)
                return {"key": r["instrument_key"], "name": (r.get("name") or t).upper() if is_index else r.get("name") or t,
                        "lot": lot, "is_index": is_index}
    raise SystemExit(f"{ticker}: not found among NSE indices or stocks (try the NSE trading symbol, e.g. NIFTY, BANKNIFTY, RELIANCE)")


def month_ranges(start: dt.date, end: dt.date):
    first = start.replace(day=1)
    while first <= end:
        nxt = (first.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        yield max(first, start), min(nxt - dt.timedelta(days=1), end), nxt - dt.timedelta(days=1)
        first = nxt


def fetch_minutes(key: str, cache: Path, start: dt.date, end: dt.date) -> list[list]:
    """1-minute candles, one request per calendar month (Upstox's limit for minute data)."""
    cache.mkdir(parents=True, exist_ok=True)
    out: list[list] = []
    months = list(month_ranges(start, end))
    for n, (a, b, month_end) in enumerate(months, 1):
        path = cache / f"1m_{a:%Y-%m}.json"
        whole_month = a.day == 1 and b == month_end
        if whole_month and path.exists():
            candles = json.loads(path.read_text())
        else:
            url = f"{API}/{urllib.parse.quote(key, safe='')}/minutes/1/{b}/{a}"
            candles = (get_json(url).get("data") or {}).get("candles") or []
            if whole_month:
                path.write_text(json.dumps(candles))
            time.sleep(0.25)
        out.extend(candles)
        if n % 12 == 0 or n == len(months):
            print(f"  minutes: {n}/{len(months)} months, {len(out):,} candles", flush=True)
    return out


def fetch_days(key: str, start: dt.date, end: dt.date) -> list[list]:
    """Daily candles, at most a decade per request."""
    out: list[list] = []
    a = start
    while a <= end:
        b = min(dt.date(a.year + 9, 12, 31), end)
        url = f"{API}/{urllib.parse.quote(key, safe='')}/days/1/{b}/{a}"
        out.extend((get_json(url).get("data") or {}).get("candles") or [])
        a = b + dt.timedelta(days=1)
    return out


def frame(candles: list[list]) -> pd.DataFrame:
    """Upstox rows are [time, open, high, low, close, volume, open interest], newest first."""
    df = pd.DataFrame([c[:6] for c in candles], columns=["ts", "open", "high", "low", "close", "volume"])
    df.index = pd.DatetimeIndex(pd.to_datetime(df.pop("ts"), utc=True), name="time_utc")
    return df[~df.index.duplicated()].sort_index().astype(float)


def build(minutes: pd.DataFrame, days: pd.DataFrame) -> dict[str, pd.DataFrame]:
    ts = epoch_seconds(minutes.index)
    ist = ts + IST_OFFSET
    midnight = ist - ist % 86400
    m = (ist - midnight) // 60 - SESSION_OPEN  # minutes since 09:15
    keep = (m >= 0) & (m < SESSION_MINUTES)
    live, ts, midnight, m = minutes[keep], ts[keep], midnight[keep], m[keep]

    bars: dict[str, pd.DataFrame] = {}
    for tf, span in TF_MINUTES.items():
        start = midnight - IST_OFFSET + (SESSION_OPEN + (m // span) * span) * 60
        b = live.groupby(start, sort=True).agg(**AGG)
        b.index = pd.DatetimeIndex(pd.to_datetime(b.index, unit="s", utc=True), name="time_utc")
        b[["open", "high", "low", "close"]] = b[["open", "high", "low", "close"]].round(2)
        if tf == "1d":
            b.insert(0, "date", (b.index + pd.Timedelta(seconds=IST_OFFSET)).tz_localize(None).normalize().date)
            first = b["date"].iloc[0]
            old = days[(days.index + pd.Timedelta(seconds=IST_OFFSET)).tz_localize(None).normalize().date < first]
            if len(old):  # history before the minute data: official daily candles, context only
                ctx = old[["open", "high", "low", "close", "volume"]].copy()
                ctx.insert(0, "date", (ctx.index + pd.Timedelta(seconds=IST_OFFSET)).tz_localize(None).normalize().date)
                ctx.index = pd.DatetimeIndex(pd.to_datetime(ctx["date"]) + pd.Timedelta(minutes=SESSION_OPEN), name="time_utc")
                ctx.index = ctx.index.tz_localize("Asia/Kolkata").tz_convert("UTC")
                ctx["minutes"] = 0
                b = pd.concat([ctx, b])
        bars[tf] = b
    return bars


def validate(bars: dict[str, pd.DataFrame]) -> None:
    """The replay tool rebuilds a forming bar from the 5m bars inside it, so each higher bar
    must be exactly the aggregate of its 5m bars (the daily history before 2022 aside)."""
    f = bars["5m"]
    t5 = epoch_seconds(f.index)
    for tf in ("15m", "1h", "4h", "1d"):
        b = bars[tf][bars[tf]["minutes"] > 0] if tf == "1d" else bars[tf]
        k = np.searchsorted(epoch_seconds(b.index), t5, side="right") - 1
        assert (k >= 0).all(), f"5m bars before the first {tf} bar"
        g = f.groupby(k).agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
        assert len(g) == len(b), f"{tf}: {len(g)} groups vs {len(b)} bars"
        for col in ("open", "high", "low", "close"):
            diff = np.abs(g[col].to_numpy() - b[col].to_numpy()).max()
            assert diff < 1e-6, f"{tf} {col} differs from its 5m aggregate by {diff}"
    for tf, allowed in (("1h", {555, 615, 675, 735, 795, 855, 915}), ("4h", {555, 795})):
        ist = (epoch_seconds(bars[tf].index) + IST_OFFSET) % 86400 // 60
        assert set(np.unique(ist)) <= allowed, f"{tf} bars open at unexpected times: {sorted(set(np.unique(ist)) - allowed)}"


def main() -> None:
    yesterday = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=IST_OFFSET)).date() - dt.timedelta(days=1)
    ap = argparse.ArgumentParser(description="Build 5m/15m/1h/4h/1d bars for an NSE index or stock from Upstox.")
    ap.add_argument("--ticker", default="NIFTY", help="NSE trading symbol: NIFTY, BANKNIFTY, FINNIFTY, RELIANCE ...")
    ap.add_argument("--start", default=str(FIRST_MINUTE_DAY), help="first day of minute data (not before 2022-01-03)")
    ap.add_argument("--end", default=str(yesterday), help="last day to fetch (max: yesterday, IST)")
    ap.add_argument("--context-start", default="2015-01-01", help="daily-only history before the minute data")
    ap.add_argument("--no-tables", action="store_true", help="skip the CSV/parquet exports (the replay data is still written)")
    args = ap.parse_args()

    inst = resolve(args.ticker)
    symbol = re.sub(r"[^A-Z0-9&_-]", "", args.ticker.strip().upper())
    start = max(dt.date.fromisoformat(args.start), FIRST_MINUTE_DAY)
    end = min(dt.date.fromisoformat(args.end), yesterday)
    print(f"{symbol} ({inst['key']}, {inst['name']}): minutes {start} -> {end}", flush=True)

    minutes = frame(fetch_minutes(inst["key"], RAW / symbol, start, end))
    if minutes.empty:
        raise SystemExit("Upstox returned no minute data for that range")
    days = frame(fetch_days(inst["key"], dt.date.fromisoformat(args.context_start), start - dt.timedelta(days=1)))
    bars = build(minutes, days)
    validate(bars)

    if not args.no_tables:
        TF_DIR.mkdir(parents=True, exist_ok=True)
        for tf, b in bars.items():
            b.to_parquet(TF_DIR / f"{symbol}_{tf}.parquet")
            b.to_csv(TF_DIR / f"{symbol}_{tf}.csv", date_format="%Y-%m-%d %H:%M:%S")
    write_symbol(symbol, bars, {
        "name": inst["name"], "source": "Upstox (NSE)", "price": "last", "ccy": "₹", "locale": "en-IN",
        "tz": "Asia/Kolkata", "lot": inst["lot"], "lotStep": 1, "lots": 1, "unit": "units" if inst["is_index"] else "shares",
        "slipUnit": "pts", "balance": 500000, "hasSpread": False, "hasVolume": not inst["is_index"],
        "replayFrom": str(bars["5m"].index[0].tz_convert("Asia/Kolkata").date()),
        "ccyCode": "INR", "ticker": args.ticker.strip().upper(),
        "update": f"python src/update_replay.py --symbol {symbol}",
    })

    print()
    for tf, b in bars.items():
        print(f"{tf:>4}: {len(b):>9,} bars  {b.index[0]:%Y-%m-%d %H:%M} -> {b.index[-1]:%Y-%m-%d %H:%M} UTC")
    d = bars["1d"]
    live = d[d["minutes"] > 0]
    print(f"daily: {d['date'].iloc[0]} -> {d['date'].iloc[-1]} ({len(d):,} sessions, {len(live):,} replayable from {live['date'].iloc[0]})")
    short = live[live["minutes"] < SESSION_MINUTES - 5]
    print(f"short sessions (special or missing minutes): {len(short)}"
          + (f" -> {', '.join(str(x) for x in short['date'].head(8))}" if len(short) else ""))
    print(f"lot size default: {inst['lot']}\ntables : " + ("skipped" if args.no_tables else str(TF_DIR)) + f"\nreplay : replay/data/{symbol}/")


if __name__ == "__main__":
    main()
