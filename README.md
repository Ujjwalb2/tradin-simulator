# XAUUSD — 5-minute research workbench

**Conclusion: no profitable 5-minute strategy exists in this data.**
Read [`FINDINGS.md`](FINDINGS.md).

## State (2026-09-10)

Tested on **11.7 years** (2015-01 → 2026-09, 828,668 bars) with realistic per-bar spread costs.

- **Liquidity-sweep + Fibonacci rulebook — retired.** Negative in every parameter cell.
- **AOD (Asia-Open Drift) — retired.** Looked good on 4 years, then failed a 7.6-year
  holdout at −47.9% / t = −5.53. See [`AOD_RETIRED.md`](AOD_RETIRED.md).
- **1h and 2h hold variants — retired.** Monotonically worse than the 3.5h version.
- **8 classic families × 30 configs over 11.7y — 0 profitable.**

The overnight drift in the 22:00–02:00 UTC window is real (71% of gold's 12-year return
from 15.6% of the clock), but it was **smaller than the bid-ask spread in 7 of the 8 years
before 2023**. It only cleared costs recently because gold quadrupled while the dollar
spread merely doubled. That is a regime, not an edge.

## Chart replay (manual backtesting)

**Live:** https://ujjwalb2.github.io/tradin-simulator/ (XAUUSD and NIFTY, data up to the last
build). Trades, drawings and settings are saved in each browser, per ticker.

The dashboard's data (`replay/data/`) is in the repository so the site can load it; the
research data is not. Rebuild or refresh with `src/build_tf.py` (gold) and
`src/build_nse.py` (NIFTY / other NSE tickers), then commit `replay/data/` to update the site.

`replay/` is a small TradingView-style bar-replay tool on the same Dukascopy data, from
2020-01-02: 5m / 15m / 1H / 4H / D candles, replay from any date without seeing the future
(higher timeframes show the forming bar; switching timeframe keeps the replay candle on
screen at the same zoom, like TradingView replay), paper trading with real bid/ask fills,
drawing tools (trend line, ray, horizontal and vertical line, parallel channel, zone, Fib with
editable levels, long/short position, date and price range) that select, drag, restyle and
undo like TradingView, and EMAs you edit from the chart legend (length, source, colour, width,
style).

```bash
./.venv/bin/python src/build_tf.py      # add new days: 2020-01-01 -> yesterday (UTC)
./.venv/bin/python replay/serve.py      # opens http://127.0.0.1:8765
```

Or double-click `replay/Gold Replay.command`. Everything you do in it is saved in the
browser, per ticker; *Export CSV* downloads the trade log. Needs internet once per load for
the charting library (TradingView Lightweight Charts, from a CDN).

**NIFTY and other NSE tickers.** The ticker menu (top left) switches symbols. NSE data comes
from Upstox's free historical API (no login): 1-minute candles from 2022-01-03 (the oldest it
serves), daily candles from 2015 as history. Bars follow the 09:15-15:30 IST session the way
TradingView draws NSE (1h at 09:15, 10:15 ...; 4h 09:15-13:15 and 13:15-15:30). Index data
has no bid/ask, so fills are at the last price; lot size defaults to the current futures lot
(NIFTY 65) and is editable. Add or refresh a ticker, then reload the page:

```bash
./.venv/bin/python src/build_nse.py                     # NIFTY
./.venv/bin/python src/build_nse.py --ticker BANKNIFTY  # or FINNIFTY, RELIANCE, any NSE symbol
```

Daily closes are the last traded value at 15:29, which can differ from NSE's official close
(a 30-minute average) on volatile days. investing.com was not usable as a source: its data
API answers 403 to scripts, and its downloads are daily/weekly/monthly only.

`data/tf/XAUUSD_{5m,15m,1h,4h,1d}.csv|parquet` are the same bars for any other use:
`open/high/low/close` are **bid** (what MT4/MT5 and TradingView chart), `ask_*` alongside,
`time_utc` is the bar open. Daily sessions run 17:00 → 17:00 New York (five per week) and
4h bars start at 17:00, 21:00, 01:00, 05:00, 09:00, 13:00 New York.

## Layout

```
src/fetch_data.py   Dukascopy downloader: 1m bid+ask candles -> 5m bars
src/build_tf.py     gold 5m/15m/1h/4h/1d bars from 2020 -> data/tf/ and replay/data/XAUUSD/
src/build_nse.py    NSE index/stock bars from Upstox -> data/tf/ and replay/data/<TICKER>/
src/replay_data.py  shared writer for the replay tool's data format
replay/             bar-replay chart + paper trading (index.html, app.js, serve.py)
src/aod.py          retired AOD strategy (kept for reproduction)
src/aod_signal.py   retired live signal
src/strategy.py     retired liquidity-sweep rulebook
research/           full research trail, including every failed hypothesis
data/processed/     XAUUSD_1m.parquet, XAUUSD_5m.parquet, XAUUSD_5m.csv (research set, to 2026-09-09)
data/tf/            multi-timeframe bars for charting (2020-01-02 onward)
out/research/       charts and session-level results
```

## Setup

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
```

## Data

```bash
./.venv/bin/python src/fetch_data.py --start 2015-01-01 --end 2026-09-09
```

Free Dukascopy feed, no API key, 1-minute bid **and** ask candles. Raw .bi5 files are
cached under `data/raw/`, so re-runs only fetch what is missing. The 5m file carries mid
OHLC plus a real `spread` column, so transaction costs are modelled from the actual quoted
spread of each bar traded — the single most important detail in this repo.

## Reproducing the verdict

```bash
./.venv/bin/python research/rerun2015.py     # era split + 316-window scan
./.venv/bin/python research/battery11y.py    # 8 families x 30 configs, 1-2h holds
./.venv/bin/python research/shorthold.py     # 494-window short-hold scan
./.venv/bin/python research/diag.py          # cost-vs-drift by year
./.venv/bin/python research/chart11y.py      # chart
```
