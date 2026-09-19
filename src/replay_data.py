"""
Write bars in the replay tool's format and list the symbol in its ticker menu.

    replay/data/<SYMBOL>/<tf>.bin   column-major little-endian arrays: int32 UTC seconds,
                                    int32 prices in 1/1000, float32 volume; the 5m file may
                                    add ask OHLC, the 1d file adds the trading date
    replay/data/<SYMBOL>/meta.json  row counts, column layout and per-symbol settings
    replay/data/symbols.json        every symbol that has been built
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPLAY_DATA = ROOT / "replay" / "data"
TIMEFRAMES = {"5m": 300, "15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}
PRICE_SCALE = 1000


def epoch_seconds(idx: pd.DatetimeIndex) -> np.ndarray:
    """Wall-clock seconds since 1970 for a naive or tz-aware index (in its own zone)."""
    naive = idx.tz_localize(None) if idx.tz is not None else idx
    return naive.values.astype("datetime64[s]").astype(np.int64)


def read_symbol(symbol: str) -> tuple[dict, dict[str, pd.DataFrame]]:
    """meta.json and the published bars, in the same shape the builders produce, so a new
    stretch of bars can be merged onto what is already published."""
    folder = REPLAY_DATA / symbol
    meta = json.loads((folder / "meta.json").read_text())
    names = {"o": "open", "h": "high", "l": "low", "c": "close",
             "ao": "ask_open", "ah": "ask_high", "al": "ask_low", "ac": "ask_close"}
    bars: dict[str, pd.DataFrame] = {}
    for tf, spec in meta["tfs"].items():
        n, raw = spec["n"], (folder / f"{tf}.bin").read_bytes()
        cols = {name: np.frombuffer(raw, dtype="<" + kind, count=n, offset=i * 4 * n)
                for i, (name, kind) in enumerate(spec["cols"])}
        df = pd.DataFrame(index=pd.DatetimeIndex(pd.to_datetime(cols["t"], unit="s", utc=True), name="time_utc"))
        if "d" in cols:
            df["date"] = pd.to_datetime(cols["d"], unit="s").date
        for short, full in names.items():
            if short in cols:
                df[full] = cols[short] / meta["price_scale"]
        df["volume"] = cols["v"].astype(float)
        bars[tf] = df
    return meta, bars


def write_symbol(symbol: str, bars: dict[str, pd.DataFrame], meta: dict) -> Path:
    """`bars` maps each timeframe to a frame indexed by bar-open UTC time with open, high,
    low, close, volume (optional ask_open..ask_close on 5m) and a `date` column on 1d."""
    out = REPLAY_DATA / symbol
    out.mkdir(parents=True, exist_ok=True)
    has_ask = "ask_open" in bars["5m"].columns
    info = {
        "symbol": symbol,
        "price_scale": PRICE_SCALE,
        "built_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M"),
        **meta,
        "tfs": {},
    }
    for tf, b in bars.items():
        cols = [("t", "i4", epoch_seconds(b.index))]
        names = [("o", "open"), ("h", "high"), ("l", "low"), ("c", "close")]
        if tf == "5m" and has_ask:
            names += [("ao", "ask_open"), ("ah", "ask_high"), ("al", "ask_low"), ("ac", "ask_close")]
        cols += [(short, "i4", np.rint(b[col].to_numpy() * PRICE_SCALE)) for short, col in names]
        cols.append(("v", "f4", b["volume"].fillna(0).to_numpy()))
        if tf == "1d":
            days = pd.to_datetime(b["date"]).to_numpy().astype("datetime64[s]").astype(np.int64)
            cols.append(("d", "i4", days))
        with open(out / f"{tf}.bin", "wb") as fh:
            for _, kind, arr in cols:
                fh.write(np.asarray(arr).astype("<" + kind).tobytes())
        info["tfs"][tf] = {"n": len(b), "sec": TIMEFRAMES[tf], "cols": [[n, k] for n, k, _ in cols]}
    info["first"] = str(bars["5m"].index[0])
    info["last"] = str(bars["5m"].index[-1])
    (out / "meta.json").write_text(json.dumps(info, indent=1, ensure_ascii=False))

    index_path = REPLAY_DATA / "symbols.json"
    symbols = json.loads(index_path.read_text()) if index_path.exists() else []
    symbols = [s for s in symbols if s["symbol"] != symbol]
    symbols.append({"symbol": symbol, "name": meta.get("name", symbol)})
    symbols.sort(key=lambda s: (s["symbol"] != "XAUUSD", s["symbol"]))
    index_path.write_text(json.dumps(symbols, indent=1, ensure_ascii=False))
    return out
