# Project notes — chart replay simulator

Everything needed to pick this project up cold: what it is, how it is built, what was already
decided, what was already verified, and what is left. Written 2026-09-19.

- **Live:** https://ujjwalb2.github.io/tradin-simulator/
- **Repo:** https://github.com/Ujjwalb2/tradin-simulator (public, GitHub Pages from `main`, root)
- **Local:** `~/XAUUSD`, Python in `./.venv` (`./.venv/bin/python`, deps in `requirements.txt`)
- **Commits from here use:** Ujjwal &lt;customgpt@houseofedtech.in&gt;

## Resume in a new chat

Paste this:

> I have a TradingView-style bar-replay and manual backtesting tool at `~/XAUUSD` (public repo
> github.com/Ujjwalb2/tradin-simulator, live at ujjwalb2.github.io/tradin-simulator).
> Read `PROJECT.md` first, then `README.md`. Do not rebuild or re-verify what those say is
> already done. Here is what I want next: ...

## What this repo is

Two separate things share it:

1. **The replay dashboard (`replay/`) — the live work.** A TradingView-style bar replay with
   manual paper trading, drawing tools and EMAs, on gold, Bitcoin and NSE data.
2. **Retired gold research (`FINDINGS.md`, `AOD_RETIRED.md`, `research/`, `src/aod*.py`,
   `src/strategy.py`).** Conclusion: no profitable 5-minute gold strategy exists in 11.7 years
   of data; the spread beats every intraday edge tested. Do not restart it without a new idea.

## Data

| | gold | Bitcoin (BTCUSDT, any `…USDT` pair) | NSE (NIFTY and any other ticker) |
|---|---|---|---|
| source | Dukascopy `.bi5` 1-minute bid **and** ask candles | Binance public files, data.binance.vision (5m klines) | Upstox v3 public historical API, no login |
| history | 5m from 2020-01-01 (research set has 1m from 2015) | 5m from 2020-01-01 (`--start 2017-08-17` for all of it) | 1m from 2022-01-03 (oldest served), daily from 2015 as context |
| prices | OHLC are **bid**, ask OHLC alongside on 5m | last traded price, no bid/ask; volume in BTC | last traded price only, no bid/ask |
| sessions | 17:00 → 17:00 New York, 5 per week; 4h at 17, 21, 01, 05, 09, 13 NY | 24/7, plain UTC buckets: daily 00:00 → 00:00 UTC, 4h at 00, 04 … 20 UTC | 09:15–15:30 IST; 1h at 09:15, 10:15 …; 4h = 09:15–13:15 and 13:15–15:30 |
| builder | `src/build_tf.py` | `src/build_binance.py --symbol BTCUSDT` | `src/build_nse.py --ticker NIFTY` |

- Raw downloads live in `data/raw/` and are **not** in git (large, re-downloadable). The
  dashboard's data in `replay/data/` **is** committed — the site loads it directly.
- `replay/data/<SYMBOL>/<tf>.bin` is column-major little-endian: int32 UTC seconds, int32
  prices ×1000, float32 volume; the 5m file adds ask OHLC, the 1d file adds the trading date.
  `meta.json` holds row counts, the column layout and the per-symbol settings the dashboard
  reads (currency, lot size, whether there is a spread, etc.). `symbols.json` is the ticker menu.
  Reader and writer are both in `src/replay_data.py`.
- Add any NSE ticker with `./.venv/bin/python src/build_nse.py --ticker BANKNIFTY`, then reload
  the page — the ticker menu picks it up from `symbols.json`.

**Checked against known events:** gold 2074.80 (Aug 2020) and 3499.92 (Apr 2025); NIFTY
7,610.25 (Mar 2020 low), 26,277.35 (Sep 2024 high), 21,281.45 (Jun 2024 election-day low);
BTCUSDT 3,782.13 (13 Mar 2020 low), 69,000.00 (10 Nov 2021 high), 15,476.00 (FTX low, 21 Nov
2022), 126,199.63 (all-time high, 6 Oct 2025) — all exact.

**Known data quirks**
- NIFTY daily closes are the last traded value at 15:29, which differs from NSE's official
  close (a 30-minute average) on volatile days.
- investing.com was tried and rejected as a source: its data API answers 403 to scripts
  (Cloudflare) and its downloads are daily/weekly/monthly only.
- Binance's files switched from millisecond to **microsecond** timestamps on 2025-01-01; the
  builder reads both. Binance's REST API is avoided on purpose: it refuses US addresses, which
  is where GitHub's runners are. The 5m series has 504 missing bars, all Binance maintenance
  outages (longest 5h50m on 2020-02-19); zero-volume klines are dropped like gold's padding.
- Dukascopy answers 503 under load; the downloader retries. A missing day file is cached as an
  empty file meaning "no data that day", and those markers are forgotten for the last 7 days so
  a not-yet-published day is retried.

## Daily update (GitHub Action)

`.github/workflows/update-data.yml` runs at 05:30 UTC (11:00 IST), commits and pushes new bars.
The site picks them up about a minute later.

It runs `src/update_replay.py`, which reads the bars already published, rebuilds **only the last
7 days** from the source and replaces the tail. This matters: the job used to rebuild gold from
2020 every run, which on a fresh runner meant ~4,200 Dukascopy files from a feed that serves
about one every 10 seconds — it hit the 60-minute limit at 49 minutes and NIFTY never ran.
The incremental version needs ~16 files (~4 min cold, seconds with the cache).

- Recent bars the source has since revised are republished; one source failing does not stop the
  other ticker (it posts a warning on the run page instead).
- The commit step runs `python src/update_replay.py --verify` first, so half-written files are
  never published.
- Run it by hand from the Actions tab; the *days* input redoes a longer stretch after an outage.
- `src/build_tf.py` / `src/build_nse.py` still do full rebuilds, and are the only way to add a
  new ticker.

**Verified:** rewinding the published data 3, 10 and 40 days and running the updater reproduces
a full rebuild **byte for byte**, for both tickers.

## The dashboard (`replay/`)

`index.html` (markup, CSS variables for both themes, and a loader that fetches `app.js` with
`cache: 'no-cache'`), `app.js` (~2,350 lines, everything else), `serve.py` (local static server
on :8765, opens the browser; detects an instance already running), `Gold Replay.command`
(double-click launcher). Charting is TradingView Lightweight Charts 4.2.0 from jsDelivr, with
an unpkg fallback — the only network dependency at runtime.

**The core invariant:** the replay cursor is always a **5-minute bar**. Every timeframe shows
the bars that closed before the cursor plus the forming bar rebuilt from the 5m bars inside it.
That is why switching timeframe mid-replay can never show the future, and why every higher
timeframe must be exactly the aggregate of its 5m bars — the builders and the updater all
assert this.

**Fills** (in `processBar` / `exitCheck`, `app.js:676`):
market orders fill at the cursor bar's close, buys at the ask and sells at the bid; limit/stop
entries trigger on the 5m ask (buys) or bid (sells), and a gap fills at the open; longs exit on
the bid and shorts on the ask, so the spread is always paid; if stop loss and take profit both
fall inside one 5m bar the **stop is assumed to hit first**; on the bar a pending order fills,
only the stop loss is checked. NSE has no bid/ask, so both sides fill at the last price.

**Other pieces**
- Drawing tools: trend line, ray, horizontal and vertical line, parallel channel, zone, Fib
  (editable levels), long/short position, date and price range. They select, drag, restyle,
  clone, lock and undo like TradingView. Hit-testing is `hitTestAt`, dragging is `moveDrawing`,
  settings dialogs are `openDialog`/`applyDrawingFields`.
- Up to 10 EMAs, each with length, source, colour, width and style, edited from the chart legend
  (click the row, the ⚙, the ƒx button, or double-click the line itself). `emaValues` runs over
  closed bars; `emaForming` handles the forming bar.
- Session marks (`paintSessionBreaks`, `paintSessionBands`, toggled under *Sessions* in the side
  panel): a dotted line at each day boundary, and a high/low box per market session. The four
  sessions are defined in `SESSIONS` by each city's own local hours, so daylight saving is the
  timezone's problem, not ours. Boxes are built from revealed 5m bars only, so they grow with the
  replay; they are skipped on the daily chart and past `SESSION_MAX_DAYS` on screen. They default
  on where `meta.json` has `fxSessions` (gold, crypto) or the market has a spread, off for NSE.
- Lot sizes follow each symbol's `lotStep` (0.01 gold, 0.001 BTC, 1 for NSE) for rounding and
  display (`lotDecimals`).
- Session state (`S`) is saved per symbol in localStorage: `gold-replay-v1` for gold,
  `replay-v1-<SYMBOL>` for everything else. Trades, drawings, EMAs, theme and zoom all live
  there — nothing is stored server-side.
- View model: `WINDOW_BARS = 5000` bars handed to the chart per redraw (scrolling left loads
  more), `DEFAULT_ZOOM = 160` bars across.
- Light and dark themes; the timezone menu changes all displayed times.

## Gotchas already paid for

Do not re-learn these:

- **GitHub Pages caches for 10 minutes.** A published fix can appear not to work because the
  browser reuses the old `app.js`. Hence the no-cache loader and the "new version available"
  banner (`watchForUpdates`, `reloadFresh`). When testing the live site, always check the
  running version first.
- **Lightweight Charts swallows the second click** inside its double-click window, so tools use
  native DOM click events, not `subscribeClick`.
- **`logicalToCoordinate` only converts whole bar indices** and returns 0 for fractional ones —
  `logicalToX` interpolates instead.
- **The library listens to mouse/touch events**, so cancelling `pointerdown` in the capture
  phase is what stops the chart panning while a drawing is dragged.
- **Reading the visible range before the chart has laid out** returns every bar, which once got
  saved as the zoom and made the chart open zoomed out — `maxZoomBars()` guards it.
- **The price axis stays manual once touched**, so every timeframe switch and jump re-enables
  autoscale, otherwise the candles drift off screen.
- Banner and toast elements need `pointer-events: none` or they eat chart clicks.
- Hidden browser tabs run no animation frames, which matters when driving the page for tests.

## Already verified (don't redo)

- The order engine was checked against an independent reference implementation across market,
  limit and stop orders in both directions: **0 mismatches**.
- Forming-bar equality (higher timeframe rebuilt from 5m == the real bar) checked thousands of
  times; EMA values match an independent computation to 1e-11, exactly for `hl2`.
- No future data leaks when switching timeframes mid-replay (checked over hundreds of switches).
- The incremental updater reproduces a full rebuild byte for byte (see above).

## Decisions already made

- The repo is **public**, chosen knowingly (market data redistribution and each source's
  personal-use terms were flagged first).
- **No draggable SL/TP** on the chart — asked for and removed.
- Switching timeframe keeps the **replay candle** on screen at the same zoom, TradingView-style
  (an earlier "land where you were looking" behaviour showed already-replayed candles and was
  removed).
- Both a light and a dark theme.
- The data updates itself daily rather than being rebuilt by hand.

## State on 2026-09-21

- Three tickers: XAUUSD and NIFTY through **2026-09-18** (Friday), BTCUSDT through
  **2026-09-20**. The daily job keeps them current; GitHub often starts scheduled runs hours
  late (the 2026-09-20 one ran at 09:54 UTC, not 05:30), which is harmless.
- The gold timeout fix is confirmed on GitHub: run 35434160290, whole job 4½ minutes.
- BTCUSDT was added on 2026-09-21. Its top-up is verified locally (byte-identical to a full
  build after rewinding 3, 10 and 40 days) but **not yet on GitHub's runners** — the first run
  after it was pushed shows whether data.binance.vision answers from there.
- Everything local is committed and pushed.

**Possible next steps, none started:** a percentage fee setting (crypto exchanges charge a % of
the trade; the app's commission is a fixed amount per lot), more tickers (one command each),
gold history before 2020 (the 1-minute research data reaches back to 2015), a trade-statistics
panel, or exporting a replay session for review.
