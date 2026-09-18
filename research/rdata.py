"""Shared research data layer: load 5m bars, attach calendar + feature columns."""
import numpy as np
import pandas as pd

PARQUET = "data/processed/XAUUSD_5m.parquet"

# Regime split. IS = design/fit. OOS = touched once, at the end.
IS_END = "2025-06-30"          # ~2.83y in-sample
OOS_START = "2025-07-01"       # ~1.2y out-of-sample


def load(path=PARQUET):
    df = pd.read_parquet(path)
    df = df[~df.index.duplicated(keep="first")].sort_index()
    df.index.name = "ts"
    return df


def add_calendar(df):
    ix = df.index
    df["hour"] = ix.hour
    df["minute"] = ix.minute
    df["tod"] = ix.hour * 60 + ix.minute          # minutes since UTC midnight
    df["dow"] = ix.dayofweek                       # 0=Mon
    df["date"] = ix.normalize()
    # trading day = Sun 22:00 UTC .. Fri 22:00 UTC; label by the NY date it belongs to
    df["session_day"] = (ix + pd.Timedelta(hours=2)).normalize()
    return df


def add_features(df):
    c, h, l, o = df["close"], df["high"], df["low"], df["open"]
    df["ret"] = np.log(c).diff()

    prev_c = c.shift(1)
    tr = pd.concat([h - l, (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(axis=1)
    df["tr"] = tr
    for n in (14, 50, 288):
        df[f"atr{n}"] = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()

    # realised vol over a day of 5m bars, annualised-free (just $ scale)
    df["rv288"] = df["ret"].rolling(288).std()
    df["rv_ratio"] = df["rv288"] / df["rv288"].rolling(288 * 20).mean()

    for n in (12, 24, 48, 96, 288):
        df[f"mom{n}"] = np.log(c / c.shift(n))
    for n in (20, 50, 200):
        df[f"ema{n}"] = c.ewm(span=n, adjust=False).mean()

    # position of close inside recent range
    for n in (12, 48, 96):
        hh = h.rolling(n).max()
        ll = l.rolling(n).min()
        df[f"pos{n}"] = (c - ll) / (hh - ll).replace(0, np.nan)
        df[f"hh{n}"] = hh
        df[f"ll{n}"] = ll

    # candle anatomy
    rng = (h - l).replace(0, np.nan)
    df["body_frac"] = (c - o) / rng
    df["upwick"] = (h - np.maximum(c, o)) / rng
    df["dnwick"] = (np.minimum(c, o) - l) / rng

    # cost proxy: round-trip in price units (cross half-spread twice) + slippage
    df["cost"] = df["spread"] + 0.10
    return df


def build(path=PARQUET):
    return add_features(add_calendar(load(path)))


def fwd_returns(df, horizons=(1, 3, 6, 12, 24, 48, 96)):
    """Forward log return in $ terms (close-to-close) for each horizon in bars."""
    out = {}
    c = df["close"]
    for k in horizons:
        out[f"f{k}"] = c.shift(-k) - c          # $ move, not log — costs are in $
    return pd.DataFrame(out, index=df.index)
