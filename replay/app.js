/* Chart replay: bar-replay chart and manual paper trading, one symbol at a time
 * (?symbol=XAUUSD, ?symbol=NIFTY ...).
 *
 * Data comes from src/build_tf.py (gold: Dukascopy bid OHLC, plus ask OHLC on the 5m file) and
 * src/build_nse.py (NSE indices and stocks: last price, no bid/ask, so both sides fill at it).
 * The replay cursor is always a 5m bar. Every timeframe shows the bars that closed before
 * the cursor plus the forming bar rebuilt from the 5m bars inside it, so switching
 * timeframe mid-replay never shows the future.
 *
 * Fills (lot size per symbol, e.g. 100 oz of gold or 65 NIFTY units):
 *   market orders fill at the cursor bar's close: buys at the ask, sells at the bid
 *   limit/stop entries trigger on the 5m ask (buys) or bid (sells); a gap fills at the open
 *   longs exit on the bid and shorts on the ask, so the spread is always paid
 *   stop loss and take profit both inside one 5m bar -> the stop is assumed to hit first
 *   on the bar a pending order fills, only the stop loss is checked
 */
'use strict';

const TFS = ['5m', '15m', '1h', '4h', '1d'];
const TF_LABEL = { '5m': '5m', '15m': '15m', '1h': '1H', '4h': '4H', '1d': 'D' };
const TZS = [
  ['Asia/Kolkata', 'India (IST)', 'IST'], ['UTC', 'UTC', 'UTC'], ['Europe/London', 'London', 'London'],
  ['America/New_York', 'New York', 'NY'], ['Asia/Dubai', 'Dubai', 'Dubai'],
  ['Asia/Singapore', 'Singapore', 'SGT'], ['Asia/Tokyo', 'Tokyo', 'JST'], ['Australia/Sydney', 'Sydney', 'Sydney'],
];
const SPEEDS = [0.5, 1, 2, 4, 8, 16, 30];
const WINDOW_BARS = 5000;      // bars handed to the chart on a redraw; scrolling left loads more
const DEFAULT_ZOOM = 160;      // bars across the screen until the user zooms
const SYMBOL = (new URLSearchParams(location.search).get('symbol') || localStorage.getItem('replay-symbol') || 'XAUUSD').toUpperCase();
const STORE_KEY = SYMBOL === 'XAUUSD' ? 'gold-replay-v1' : `replay-v1-${SYMBOL}`;  // one saved session per symbol
const CDN_FALLBACK = 'https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js';
const C = {
  up: '#26a69a', down: '#ef5350', volUp: 'rgba(38,166,154,0.28)', volDown: 'rgba(239,83,80,0.28)',
  buy: '#2962ff', sell: '#f23645', sl: '#f23645', tp: '#22ab94', order: '#ff9800',
  draw: '#5b9cf6', zone: 'rgba(91,156,246,0.13)', hline: '#b2b5be', win: '#22ab94', loss: '#f23645',
};
const FIELD_NAME = { inPrice: 'order price', inSL: 'stop loss', inTP: 'take profit' };
const THEMES = {  // chart colours per theme; the page colours are CSS variables in index.html
  dark: { bg: '#131722', text: '#d1d4dc', grid: 'rgba(42,46,57,0.6)', border: '#2a2e39', watermark: 'rgba(134,137,147,0.10)', handleFill: '#131722', hline: '#b2b5be' },
  light: { bg: '#ffffff', text: '#131722', grid: '#f0f3fa', border: '#e0e3eb', watermark: 'rgba(106,109,120,0.10)', handleFill: '#ffffff', hline: '#787b86' },
};
let THEME = document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
const TOOLS = {
  trend: { clicks: 2, hint: 'Trend line: click the start, then the end' },
  ray: { clicks: 2, hint: 'Ray: click the start, then a point it passes through' },
  hline: { clicks: 1, hint: 'Horizontal line: click a price' },
  vline: { clicks: 1, hint: 'Vertical line: click a bar' },
  channel: { clicks: 3, hint: 'Parallel channel: click both ends of one side, then click to set the width' },
  rect: { clicks: 2, hint: 'Zone: click one corner, then the opposite corner' },
  fib: { clicks: 2, hint: 'Fib retracement: click the start of the move (1), then its end (0)' },
  long: { clicks: 3, hint: 'Long position: click the entry, then the stop loss, then the take profit' },
  short: { clicks: 3, hint: 'Short position: click the entry, then the stop loss, then the take profit' },
  measure: { clicks: 2, hint: 'Date and price range: click the start, then the end' },
};
const FIB_DEFAULT = [  // [level, colour, shown]; each Fib drawing can edit its own copy
  [0, '#787b86', true], [0.236, '#f23645', true], [0.382, '#ff9800', true], [0.5, '#4caf50', true],
  [0.618, '#089981', true], [0.65, '#089981', false], [0.705, '#00bcd4', false], [0.786, '#00bcd4', true],
  [1, '#787b86', true], [1.272, '#9c27b0', false], [1.618, '#2962ff', true], [2, '#f23645', false],
  [2.618, '#e91e63', false], [-0.272, '#9c27b0', false], [-0.618, '#2962ff', false],
];
const fibLevels = (d) => d.levels || FIB_DEFAULT.map(([v, color, on]) => ({ v, color, on }));
const EMA_DEFAULTS = [{ on: true, len: 20, color: '#f7a21b' }, { on: true, len: 50, color: '#5b9cf6' },
  { on: false, len: 200, color: '#e040fb' }];
const EMA_COLORS = ['#f7a21b', '#5b9cf6', '#e040fb', '#22ab94', '#f23645', '#ffeb3b', '#00bcd4', '#ff7043', '#ab47bc', '#8bc34a'];
const EMA_LENGTHS = [9, 21, 100, 34, 13, 89, 144, 233, 5, 8];
const MAX_EMAS = 10;

let LC;                        // LightweightCharts namespace
let META, D, F;                // meta.json, data per timeframe, F = D['5m'] (the replay clock)
let cursor = 0;                // index of the last revealed 5m bar
let view = null;               // what the chart holds: { tf, start, k, last } in global bar indices
let chart, candles, volume, layer, emaSeries = [];
let playing = false, timer = null;
let mode = null, pickField = null, draft = null;
let tab = 'positions';
let posVersion = 0, ordVersion = 0, tradeVersion = 0, drawVersion = 0;
const rendered = {};           // versions last drawn, per consumer

// ---------- helpers ----------

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));
const px = (x) => (x == null || !Number.isFinite(x) ? '—' : x.toFixed(2));

function upperBound(a, x) {  // first index with a[i] > x
  let lo = 0, hi = a.length;
  while (lo < hi) { const m = (lo + hi) >>> 1; if (a[m] <= x) lo = m + 1; else hi = m; }
  return lo;
}
function lowerBound(a, x) {  // first index with a[i] >= x
  let lo = 0, hi = a.length;
  while (lo < hi) { const m = (lo + hi) >>> 1; if (a[m] < x) lo = m + 1; else hi = m; }
  return lo;
}
function numOrNull(v) {
  if (v === '' || v == null) return null;
  const x = parseFloat(v);
  return Number.isFinite(x) ? x : null;
}
function money(x, signed = false) {  // in the symbol's currency: $10,000.00 or ₹5,00,000.00
  if (x == null || !Number.isFinite(x)) return '—';
  const c = META.ccy || '$';
  const s = Math.abs(x).toLocaleString(META.locale || 'en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return (x < 0 ? `−${c}` : signed && x > 0 ? `+${c}` : c) + s;
}
const fmtLots = (x) => x.toFixed((META.lotStep || 0.01) < 1 ? 2 : 0);
const signCls = (x) => (x > 0 ? 'pos' : x < 0 ? 'neg' : '');

// Seconds to add to a UTC instant to get the wall clock in `tz`, cached per UTC hour.
const tzCache = new Map();
function tzOffset(tz, t) {
  if (tz === 'UTC') return 0;
  let c = tzCache.get(tz);
  if (!c) {
    c = { hours: new Map(), fmt: new Intl.DateTimeFormat('en-US', {
      timeZone: tz, hourCycle: 'h23', year: 'numeric', month: 'numeric', day: 'numeric',
      hour: 'numeric', minute: 'numeric', second: 'numeric' }) };
    tzCache.set(tz, c);
  }
  const h = Math.floor(t / 3600);
  let off = c.hours.get(h);
  if (off === undefined) {
    const p = {};
    for (const part of c.fmt.formatToParts(new Date(h * 3600000))) p[part.type] = part.value;
    off = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour, +p.minute, +p.second) / 1000 - h * 3600;
    c.hours.set(h, off);
  }
  return off;
}
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
function fmtTime(t, withDay = false) {
  const d = new Date((t + tzOffset(S.tz, t)) * 1000);
  const iso = d.toISOString();
  return (withDay ? DOW[d.getUTCDay()] + ' ' : '') + iso.slice(0, 10) + ' ' + iso.slice(11, 16);
}
const toInputValue = (t) => new Date((t + tzOffset(S.tz, t)) * 1000).toISOString().slice(0, 16);
const tzShort = () => (TZS.find(([id]) => id === S.tz) || [, , S.tz])[2];

let toastTimer = null;
function toast(text, isError = false) {
  const el = $('#toast');
  el.textContent = text;
  el.className = isError ? 'err' : '';
  el.style.display = 'block';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.style.display = 'none'; }, isError ? 3500 : 2400);
  return false;
}

// ---------- state ----------

function defaults() {
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
  return {
    tf: '15m', tz: TZS.some(([id]) => id === tz) ? tz : 'UTC', cursorT: null, speed: 2, stepBy: 'tf',
    balance0: 10000, commission: 0, slippage: 0,
    ordType: 'market', sizeMode: 'lots', lots: 0.1, riskPct: 1,
    positions: [], orders: [], trades: [], drawings: [], seq: 1,
    emas: EMA_DEFAULTS.map((e) => ({ ...e })),
  };
}
const S = defaults();
function loadState() {  // this symbol's defaults from meta.json, then whatever was saved for it
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(STORE_KEY) || '{}'); } catch { /* start fresh */ }
  Object.assign(S, { tz: META.tz || S.tz, balance0: META.balance ?? S.balance0, lots: META.lots ?? S.lots, lotSize: META.lot ?? 100 }, saved);
  if (!TFS.includes(S.tf)) S.tf = '15m';
  if (!TZS.some(([id]) => id === S.tz)) S.tz = 'UTC';
  if (!SPEEDS.includes(S.speed)) S.speed = 2;
  if (!(S.lotSize > 0)) S.lotSize = META.lot ?? 100;
  for (const k of ['positions', 'orders', 'trades', 'drawings']) if (!Array.isArray(S[k])) S[k] = [];
  S.drawings = S.drawings.filter((d) => d && TOOLS[d.type] && Array.isArray(d.pts));
  if (!Array.isArray(S.emas)) S.emas = EMA_DEFAULTS.map((e) => ({ ...e }));
  S.emas = S.emas.filter((e) => e && e.len >= 2).slice(0, MAX_EMAS).map((e) => ({ src: 'close', width: 1, style: 'solid', ...e }));
}

let saveTimer = null;
function save() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    S.cursorT = F.t[cursor];
    try { localStorage.setItem(STORE_KEY, JSON.stringify(S)); } catch { toast('Could not save to browser storage', true); }
  }, 250);
}

// ---------- data ----------

function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.onload = resolve;
    s.onerror = () => reject(new Error('the charting library did not load (are you offline?)'));
    document.head.appendChild(s);
  });
}

async function fetchOk(url) {
  const r = await fetch(url, { cache: 'no-cache' });
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r;
}

async function loadData() {
  const metaResponse = await fetchOk(`data/${SYMBOL}/meta.json`);
  window.DATA_MODIFIED = metaResponse.headers.get('Last-Modified') || '';
  META = await metaResponse.json();
  const out = {};
  await Promise.all(TFS.map(async (tf) => {
    const m = META.tfs[tf];
    const buf = await (await fetchOk(`data/${SYMBOL}/${tf}.bin`)).arrayBuffer();
    if (buf.byteLength !== m.n * 4 * m.cols.length) throw new Error(`data/${SYMBOL}/${tf}.bin has an unexpected size; rebuild it`);
    const cols = {};
    let off = 0;
    for (const [name, kind] of m.cols) {
      cols[name] = kind === 'f4' ? new Float32Array(buf, off, m.n) : new Int32Array(buf, off, m.n);
      off += 4 * m.n;
    }
    const d = { n: m.n, sec: m.sec, t: cols.t, v: cols.v, d: cols.d };
    for (const k of ['o', 'h', 'l', 'c', 'ao', 'ah', 'al', 'ac']) {
      if (!cols[k]) continue;
      const src = cols[k], dst = new Float64Array(m.n);
      for (let i = 0; i < m.n; i++) dst[i] = src[i] / META.price_scale;
      d[k] = dst;
    }
    if (!d.ao) { d.ao = d.o; d.ah = d.h; d.al = d.l; d.ac = d.c; }  // no bid/ask: both sides trade at the last price
    out[tf] = d;
  }));
  return out;
}

// ---------- chart ----------

function setupChart() {
  const th = THEMES[THEME];
  chart = LC.createChart($('#chart'), {
    autoSize: true,
    layout: { background: { type: LC.ColorType.Solid, color: th.bg }, textColor: th.text, fontSize: 12 },
    grid: { vertLines: { color: th.grid }, horzLines: { color: th.grid } },
    crosshair: { mode: LC.CrosshairMode.Normal },
    rightPriceScale: { borderColor: th.border, scaleMargins: { top: 0.08, bottom: 0.14 } },
    timeScale: { borderColor: th.border, timeVisible: true, secondsVisible: false, rightOffset: 12, barSpacing: 8 },
    watermark: { visible: true, text: '', color: th.watermark, fontSize: 64 },
  });
  candles = chart.addCandlestickSeries({
    upColor: C.up, downColor: C.down, borderVisible: false, wickUpColor: C.up, wickDownColor: C.down,
    priceFormat: { type: 'price', precision: 2, minMove: 0.01 },
  });
  volume = chart.addHistogramSeries({
    priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false,
  });
  chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.86, bottom: 0 } });
  syncEmaSeries();
  layer = new DrawingLayer();
  candles.attachPrimitive(layer);
  chart.subscribeCrosshairMove(onCrosshair);
  chart.timeScale().subscribeVisibleLogicalRangeChange(onVisibleRangeChange);
  // Native events rather than the chart's click callback, which drops a second click inside
  // its double-click window. Pointer-down is caught in the capture phase so that grabbing a
  // drawing never starts a chart pan.
  const el = $('#chart');
  el.addEventListener('pointerdown', onPointerDown, true);
  // The chart listens to mouse and touch events; keep them from it while a drawing is held.
  el.addEventListener('mousedown', (e) => { if (drag) e.stopPropagation(); }, true);
  el.addEventListener('touchstart', (e) => { if (drag) e.stopPropagation(); }, { capture: true, passive: true });
  el.addEventListener('pointermove', onChartHover);
  el.addEventListener('pointerleave', onChartLeave);
  el.addEventListener('click', onChartClick);
  el.addEventListener('dblclick', onChartDblClick);
  el.addEventListener('contextmenu', onChartRightClick);
  window.addEventListener('pointermove', onDragMove);
  window.addEventListener('pointerup', onDragEnd);
  window.addEventListener('pointercancel', onDragEnd);
}

const tfIndexAt = (tf, t) => upperBound(D[tf].t, t) - 1;           // bar of `tf` containing instant t
const lastFiveMinOf = (tf, i) => (i + 1 < D[tf].n ? lowerBound(F.t, D[tf].t[i + 1]) - 1 : F.n - 1);

function dispTime(tf, i) {
  const T = D[tf];
  if (tf === '1d') return T.d[i];                                   // trading date
  return T.t[i] + tzOffset(S.tz, T.t[i]);                           // bar open, shifted to the chart timezone
}

function closedBar(tf, i) {
  const T = D[tf];
  return { time: dispTime(tf, i), open: T.o[i], high: T.h[i], low: T.l[i], close: T.c[i], v: T.v[i] };
}

function formingBar(tf, k) {  // bar k of tf as it stands at the cursor
  if (tf === '5m') return closedBar('5m', k);
  const j0 = lowerBound(F.t, D[tf].t[k]);
  let h = -Infinity, l = Infinity, v = 0;
  for (let j = j0; j <= cursor; j++) {
    if (F.h[j] > h) h = F.h[j];
    if (F.l[j] < l) l = F.l[j];
    v += F.v[j];
  }
  return { time: dispTime(tf, k), open: F.o[j0], high: h, low: l, close: F.c[cursor], v };
}

const volOf = (b) => ({ time: b.time, value: b.v, color: b.close >= b.open ? C.volUp : C.volDown });
const candleOf = (b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close });

/* Redraw the current timeframe up to the cursor; `from` keeps a wider window loaded earlier. */
/* Redraw the current timeframe up to the cursor. With `keepZoom` the replay candle lands at
 * the right edge at the zoom the user had (see showReplayEdge); `from` keeps a wider window
 * that was loaded earlier by scrolling left. */
function renderFull(keepZoom, from = null) {
  const zoom = keepZoom ? currentZoom() : null;  // read before the data changes
  const tf = S.tf;
  const k = tfIndexAt(tf, F.t[cursor]);
  const start = from ?? Math.max(0, k - Math.max(WINDOW_BARS, 4 * (S.zoomBars || 0)));
  const bars = [];
  for (let i = start; i < k; i++) bars.push(closedBar(tf, i));
  const last = formingBar(tf, k);
  bars.push(last);
  candles.setData(bars.map(candleOf));
  volume.setData(bars.map(volOf));
  view = { tf, start, k, prevK: k, last };
  renderEmas(true);
  if (keepZoom) showReplayEdge(zoom);
  refreshOverlays();
}

const maxZoomBars = () => {  // most bars the chart can show: 0.5px per bar is its tightest spacing
  const w = chart.timeScale().width();
  return w < 50 ? 5000 : Math.max(20, Math.min(5000, w / 0.5));  // not laid out yet: no limit to apply
};

function currentZoom() {  // bars across the screen and the margin right of the replay candle
  const ts = chart.timeScale(), r = ts.getVisibleLogicalRange();
  // Before the chart is laid out its range spans every loaded bar; taking that as the user's
  // zoom would zoom all the way out, so it counts as no zoom at all.
  if (!r || !view || ts.width() < 50) return null;
  const bars = r.to - r.from;
  return bars >= 2 && bars <= maxZoomBars() ? { bars, gap: r.to - (view.k - view.start) } : null;
}

/* Put the replay candle at the right edge the way TradingView does after a timeframe change or
 * a jump: the same zoom (bars across the screen), a small margin, and the price axis back on
 * auto so the candles can never end up off-screen or squashed by an old manual scale. */
function showReplayEdge(zoom, gap = null) {
  const last = view.k - view.start;
  const bars = clamp(zoom ? zoom.bars : S.zoomBars || DEFAULT_ZOOM, 20, maxZoomBars());
  const margin = clamp(gap ?? (zoom ? zoom.gap : 5), 3, bars * 0.4);
  chart.priceScale('right').applyOptions({ autoScale: true });
  chart.timeScale().setVisibleLogicalRange({ from: Math.max(last + margin - bars, -3), to: last + margin });
}

function renderStep() {
  const tf = S.tf;
  const k = tfIndexAt(tf, F.t[cursor]);
  if (!view || view.tf !== tf || k < view.k || k - view.k > 300) return renderFull(true);
  for (let i = view.k; i < k; i++) {
    const b = closedBar(tf, i);
    candles.update(candleOf(b));
    volume.update(volOf(b));
  }
  const last = formingBar(tf, k);
  candles.update(candleOf(last));
  volume.update(volOf(last));
  view.prevK = view.k;
  view.k = k;
  view.last = last;
  renderEmas(false);
  refreshOverlays();
}

function applyTheme(name) {  // light or dark, remembered for every ticker
  THEME = name;
  const t = THEMES[name];
  document.documentElement.dataset.theme = name;
  localStorage.setItem('replay-theme', name);
  C.hline = t.hline;
  chart.applyOptions({
    layout: { background: { type: LC.ColorType.Solid, color: t.bg }, textColor: t.text },
    grid: { vertLines: { color: t.grid }, horzLines: { color: t.grid } },
    rightPriceScale: { borderColor: t.border },
    timeScale: { borderColor: t.border },
    watermark: { color: t.watermark },
  });
  $('#btnTheme').textContent = name === 'dark' ? '☀' : '☾';
  $('#btnTheme').title = name === 'dark' ? 'Light theme' : 'Dark theme';
  drawVersion++;  // horizontal lines pick up the theme's default colour
  if (view) refreshOverlays();
}

function applyTfOptions() {
  chart.applyOptions({ timeScale: { timeVisible: S.tf !== '1d' }, watermark: { text: `${SYMBOL} ${TF_LABEL[S.tf]}` } });
  $$('#tfGroup button').forEach((b) => b.classList.toggle('on', b.dataset.tf === S.tf));
}

/* Switching timeframe keeps the replay candle on screen with the same zoom (bars across the
 * screen) and right margin, the way TradingView's replay does. It never centres on an older
 * view, so there is no jump and nothing after the replay time can appear. */
function setTf(tf) {  // lands on the replay candle with the same zoom, like TradingView replay
  if (!TFS.includes(tf) || tf === S.tf) return;
  S.tf = tf;
  draft = null;
  applyTfOptions();
  renderFull(true);
  save();
}

let extending = false;
function onVisibleRangeChange(r) {  // remember the zoom; near the oldest loaded bar, load older ones
  if (!r || !view) return;
  if (!extending && chart.timeScale().width() >= 50 && r.to - r.from <= maxZoomBars()) {
    S.zoomBars = Math.round(r.to - r.from);
    save();
  }
  const last = view.k - view.start;
  $('#toEdge').style.display = last > r.to - 1 || last < r.from ? 'grid' : 'none';
  if (extending || view.start === 0 || r.from > Math.max(30, (r.to - r.from) / 2)) return;
  extending = true;
  setTimeout(() => {
    const range = chart.timeScale().getVisibleLogicalRange();
    const add = Math.min(view.start, WINDOW_BARS);
    renderFull(false, view.start - add);
    if (range) chart.timeScale().setVisibleLogicalRange({ from: range.from + add, to: range.to + add });
    extending = false;
  }, 0);
}

function setTz(tz) {
  S.tz = tz;
  const range = chart.timeScale().getVisibleLogicalRange();
  renderFull(false, view.start);
  if (range) chart.timeScale().setVisibleLogicalRange(range);
  rendered.table = null;
  updatePanels();
  $('#gotoInput').value = toInputValue(F.t[cursor] + 300);
  save();
}

// ---------- overlays: price lines, markers, legend ----------

let lines = [], linesKey = '';
function refreshOverlays() {
  const key = `${posVersion}|${ordVersion}|${drawVersion}`;
  if (key !== linesKey) {
    linesKey = key;
    for (const l of lines) candles.removePriceLine(l.line);
    lines = [];
    const add = (price, color, title, style, width = 1, posId = null) => lines.push({
      posId, line: candles.createPriceLine({ price, color, title, lineWidth: width, lineStyle: style, axisLabelVisible: true }),
    });
    const lineStyle = { solid: LC.LineStyle.Solid, dashed: LC.LineStyle.Dashed, dotted: LC.LineStyle.Dotted };
    for (const d of S.drawings) if (d.type === 'hline') add(d.pts[0].p, colorOf(d), '', lineStyle[d.style || 'solid'], widthOf(d));
    for (const o of S.orders) {
      add(o.price, C.order, `#${o.id} ${o.side.toUpperCase()} ${o.type.toUpperCase()} ${fmtLots(o.lots)}`, LC.LineStyle.Dashed);
      if (o.sl != null) add(o.sl, C.sl, `SL #${o.id}`, LC.LineStyle.Dotted);
      if (o.tp != null) add(o.tp, C.tp, `TP #${o.id}`, LC.LineStyle.Dotted);
    }
    for (const p of S.positions) {
      add(p.entry, p.side === 'buy' ? C.buy : C.sell, '', LC.LineStyle.Solid, 2, p.id);
      if (p.sl != null) add(p.sl, C.sl, `SL #${p.id}`, LC.LineStyle.Dashed);
      if (p.tp != null) add(p.tp, C.tp, `TP #${p.id}`, LC.LineStyle.Dashed);
    }
  }
  for (const l of lines) {
    if (l.posId == null) continue;
    const p = S.positions.find((x) => x.id === l.posId);
    if (p) l.line.applyOptions({ title: `#${p.id} ${p.side === 'buy' ? 'LONG' : 'SHORT'} ${fmtLots(p.lots)}  ${money(openPnl(p), true)}` });
  }
  syncMarkers();
  layer.redraw();
  showLegend(null);
}

function syncMarkers() {
  const tf = view.tf;
  const at = (t) => {
    const i = tfIndexAt(tf, t);
    return i < view.start || i > view.k ? null : dispTime(tf, i);
  };
  const ms = [];
  const entryMark = (x) => {
    const time = at(x.entryT);
    if (time == null) return;
    const long = x.side === 'buy';
    ms.push({ time, position: long ? 'belowBar' : 'aboveBar', shape: long ? 'arrowUp' : 'arrowDown', color: long ? C.buy : C.sell, text: `#${x.id}` });
  };
  for (const tr of S.trades) {
    entryMark(tr);
    const time = at(tr.exitT);
    if (time != null) {
      ms.push({ time, position: tr.side === 'buy' ? 'aboveBar' : 'belowBar', shape: 'circle',
                color: tr.pnl >= 0 ? C.win : C.loss, text: money(tr.pnl, true) });
    }
  }
  for (const p of S.positions) entryMark(p);
  ms.sort((a, b) => a.time - b.time);
  candles.setMarkers(ms);
}

function showLegend(param) {  // hovered bar, or the forming bar when the mouse is away
  if (!view) return;
  const hovered = param && param.seriesData ? param.seriesData.get(candles) : null;
  const b = hovered || view.last;
  const chg = b.close - b.open, pct = (chg / b.open) * 100;
  $('#lgMain').innerHTML =
    `<b>${SYMBOL}</b> <span class="src">· ${TF_LABEL[S.tf]} · ${META.source}${META.price === 'bid' ? ' bid' : ''}</span>` +
    `<span class="ohlc ${chg >= 0 ? 'pos' : 'neg'}">O ${px(b.open)} H ${px(b.high)} L ${px(b.low)} C ${px(b.close)} ` +
    `${chg >= 0 ? '+' : ''}${chg.toFixed(2)} (${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%)</span>`;
  syncEmaLegend();
  S.emas.forEach((cfg, i) => {
    const el = $(`#lgEmas [data-ema="${i}"] .evalue`);
    if (!el) return;
    let v = NaN;
    if (cfg.on) {
      const pt = hovered ? param.seriesData.get(emaSeries[i]) : null;
      v = hovered ? (pt ? pt.value : NaN) : emaForming(view.tf, cfg, view.k, view.last);
    }
    el.textContent = Number.isFinite(v) ? px(v) : '';
  });
}

// ---------- replay ----------

function stepTarget() {
  if (cursor >= F.n - 1) return null;
  if (S.stepBy === '5m' || S.tf === '5m') return cursor + 1;
  const k = tfIndexAt(S.tf, F.t[cursor]);
  const end = lastFiveMinOf(S.tf, k);
  return cursor < end ? end : lastFiveMinOf(S.tf, k + 1);
}

/* End the replay: go to the latest candle in the data. Open trades and pending orders play
 * out bar by bar on the way, so stops and targets are honoured rather than skipped. */
function endReplay() {
  stopPlay();
  if (cursor >= F.n - 1) return toast('Already at the latest price in the data');
  while (cursor < F.n - 1) processBar(++cursor);
  afterMove(true);
  toast(`Replay ended: latest price, ${fmtTime(F.t[cursor] + 300, true)} ${tzShort()}`);
}

function stepOnce() {
  const target = stepTarget();
  if (target == null) {
    stopPlay();
    return toast(`End of the data. Add newer days with: ${META.update || 'the build script'}`);
  }
  while (cursor < target) processBar(++cursor);
  afterMove(false);
  return true;
}

function afterMove(full) {
  if (full) renderFull(true); else renderStep();
  updatePanels();
  if (document.activeElement !== $('#gotoInput')) $('#gotoInput').value = toInputValue(F.t[cursor] + 300);
  save();
}

function togglePlay() { if (playing) stopPlay(); else startPlay(); }
function startPlay() {
  if (playing) return;
  playing = true;
  $('#btnPlay').textContent = '⏸ Pause';
  tick();
}
function stopPlay() {
  playing = false;
  clearTimeout(timer);
  $('#btnPlay').textContent = '▶ Play';
}
function tick() {
  if (!playing || !stepOnce()) return;
  timer = setTimeout(tick, 1000 / S.speed);
}

/* Moving the cursor. With open positions only a forward "Go" is allowed, and it plays
 * every bar in between so stops and targets are honoured. Otherwise the jump is a clean
 * restart: pending orders are cancelled and nothing is simulated across the gap. */
function jumpTo(target, playThrough = false) {
  target = clamp(target, 0, F.n - 1);
  stopPlay();
  if (target === cursor) return;
  if (S.positions.length) {
    if (!(playThrough && target > cursor)) return toast('Close your open positions first (only "Go" forward can run them)', true);
    while (cursor < target) processBar(++cursor);
  } else {
    if (S.orders.length) {
      S.orders = [];
      ordVersion++;
      toast('Pending orders were cancelled');
    }
    cursor = target;
  }
  afterMove(true);
}

function gotoInputTime() {
  const v = $('#gotoInput').value;
  if (!v) return toast('Pick a date and time first', true);
  const t = wallInputToUtc(v);
  if (t == null) return toast('That date is not valid', true);
  if (t - 300 < F.t[0]) toast(`Data starts ${fmtTime(F.t[0])}`, true);
  jumpTo(upperBound(F.t, t - 300) - 1, true);  // last 5m bar closed by t
}

function randomJump() {
  if (S.positions.length) return toast('Close your open positions first', true);
  const lo = 288 * 20, hi = F.n - 288 * 5;  // keep ~a month of history behind and a week ahead
  jumpTo(lo + Math.floor(Math.random() * (hi - lo)));
  toast(`Random start: ${fmtTime(F.t[cursor] + 300, true)}`);
}

function selectBar(logical) {
  const i = view.start + Math.round(logical);
  if (i > view.k) return toast('That bar has not happened yet: use Step, Play or Go', true);
  if (i < view.start) return toast('Click on a bar', true);
  jumpTo(lastFiveMinOf(view.tf, i));
}

// ---------- trading ----------

const bidNow = () => F.c[cursor];
const askNow = () => F.ac[cursor];
const pnlUsd = (side, entry, exit, lots) => (side === 'buy' ? exit - entry : entry - exit) * lots * S.lotSize;
const riskUsd = (x) => (x.sl0 != null ? Math.abs(x.entry - x.sl0) * x.lots * S.lotSize : null);
const exitPriceNow = (p) => (p.side === 'buy' ? bidNow() - S.slippage : askNow() + S.slippage);
const openPnl = (p) => pnlUsd(p.side, p.entry, exitPriceNow(p), p.lots) - S.commission * p.lots;
const balance = () => S.trades.reduce((a, t) => a + t.pnl, S.balance0);
const equity = () => S.positions.reduce((a, p) => a + openPnl(p), balance());

function sizeFor(entry, sl) {  // lots in the symbol's lot step (0.01 gold, whole NSE lots), or an error
  const step = META.lotStep || 0.01;
  if (S.sizeMode === 'risk') {
    if (sl == null) return 'Risk % sizing needs a stop loss';
    const budget = (equity() * S.riskPct) / 100;
    const perLot = Math.abs(entry - sl) * S.lotSize + S.commission;
    const lots = +(Math.floor(budget / perLot / step + 1e-9) * step).toFixed(2);
    return lots >= step ? lots : `${S.riskPct}% risk (${money(budget)}) is less than ${fmtLots(step)} lot at this stop`;
  }
  const lots = +(Math.round(S.lots / step) * step).toFixed(2);
  return lots >= step ? lots : `Size must be at least ${fmtLots(step)} lot`;
}

function placeOrder(side) {
  const type = S.ordType, long = side === 'buy';
  const bid = bidNow(), ask = askNow();
  const price = type === 'market' ? (long ? ask + S.slippage : bid - S.slippage) : numOrNull($('#inPrice').value);
  const sl = numOrNull($('#inSL').value), tp = numOrNull($('#inTP').value);
  if (price == null || price <= 0) return toast('Enter the order price', true);
  if (type === 'limit' && (long ? price >= ask : price <= bid)) return toast(long ? 'A buy limit goes below the ask' : 'A sell limit goes above the bid', true);
  if (type === 'stop' && (long ? price <= ask : price >= bid)) return toast(long ? 'A buy stop goes above the ask' : 'A sell stop goes below the bid', true);
  if (sl != null && (long ? sl >= price : sl <= price)) return toast(`Stop loss must be ${long ? 'below' : 'above'} the entry`, true);
  if (tp != null && (long ? tp <= price : tp >= price)) return toast(`Take profit must be ${long ? 'above' : 'below'} the entry`, true);
  if (type === 'market' && sl != null && (long ? sl >= bid : sl <= ask)) return toast('That stop loss is already hit at the current price', true);
  const lots = sizeFor(price, sl);
  if (typeof lots === 'string') return toast(lots, true);

  const id = S.seq++;
  if (type === 'market') {
    const t = F.t[cursor];
    S.positions.push({ id, side, type, lots, entry: price, sl, tp, sl0: sl, entryT: t, entryShownT: t + 300, fillT: null });
    posVersion++;
    toast(`#${id} ${long ? 'Bought' : 'Sold'} ${fmtLots(lots)} lot at ${px(price)}`);
  } else {
    S.orders.push({ id, side, type, lots, price, sl, tp, placedT: F.t[cursor] + 300 });
    ordVersion++;
    toast(`#${id} ${side} ${type} ${fmtLots(lots)} lot at ${px(price)} placed`);
  }
  for (const f of ['#inPrice', '#inSL', '#inTP']) $(f).value = '';
  refreshOverlays();
  updatePanels();
  save();
}

// Run pending orders and exits against 5m bar j. Called once per revealed bar.
function processBar(j) {
  const t = F.t[j];
  const bo = F.o[j], bh = F.h[j], bl = F.l[j], ao = F.ao[j], ah = F.ah[j], al = F.al[j];
  const slip = S.slippage;

  for (let n = 0; n < S.orders.length; n++) {
    const o = S.orders[n];
    let fill = null;
    if (o.side === 'buy') {
      if (o.type === 'limit' && al <= o.price) fill = Math.min(o.price, ao);
      else if (o.type === 'stop' && ah >= o.price) fill = Math.max(o.price, ao) + slip;
    } else if (o.type === 'limit' && bh >= o.price) fill = Math.max(o.price, bo);
    else if (o.type === 'stop' && bl <= o.price) fill = Math.min(o.price, bo) - slip;
    if (fill == null) continue;
    S.orders.splice(n--, 1);
    S.positions.push({ id: o.id, side: o.side, type: o.type, lots: o.lots, entry: fill, sl: o.sl, tp: o.tp, sl0: o.sl,
                       entryT: t, entryShownT: t, fillT: t });
    ordVersion++;
    posVersion++;
  }

  for (let n = 0; n < S.positions.length; n++) {
    const p = S.positions[n];
    const hit = exitCheck(p, t, bo, bh, bl, ao, ah, al, slip);
    if (!hit) continue;
    closePosition(p, hit.price, t, t, hit.reason, hit.note);
    n--;
  }
}

function exitCheck(p, t, bo, bh, bl, ao, ah, al, slip) {
  const long = p.side === 'buy';
  if (p.fillT === t) {  // filled inside this bar: only a stop can be trusted to come after the fill
    if (p.sl == null) return null;
    if (long ? p.entry <= p.sl : p.entry >= p.sl) return { price: long ? bo - slip : ao + slip, reason: 'SL', note: 'filled through the stop' };
    if (long ? bl <= p.sl : ah >= p.sl) return { price: long ? p.sl - slip : p.sl + slip, reason: 'SL', note: 'same bar as the fill' };
    return null;
  }
  if (long) {
    const slHit = p.sl != null && bl <= p.sl, tpHit = p.tp != null && bh >= p.tp;
    if (tpHit && bo >= p.tp) return { price: bo, reason: 'TP', note: 'gap' };
    if (slHit) return { price: Math.min(p.sl, bo) - slip, reason: 'SL', note: bo < p.sl ? 'gap' : tpHit ? 'SL and TP in one 5m bar' : '' };
    if (tpHit) return { price: p.tp, reason: 'TP', note: '' };
  } else {
    const slHit = p.sl != null && ah >= p.sl, tpHit = p.tp != null && al <= p.tp;
    if (tpHit && ao <= p.tp) return { price: ao, reason: 'TP', note: 'gap' };
    if (slHit) return { price: Math.max(p.sl, ao) + slip, reason: 'SL', note: ao > p.sl ? 'gap' : tpHit ? 'SL and TP in one 5m bar' : '' };
    if (tpHit) return { price: p.tp, reason: 'TP', note: '' };
  }
  return null;
}

function closePosition(p, exit, barT, shownT, reason, note) {
  const pnl = pnlUsd(p.side, p.entry, exit, p.lots) - S.commission * p.lots;
  const risk = riskUsd(p);
  S.trades.push({
    id: p.id, side: p.side, type: p.type, lots: p.lots, entry: p.entry, exit, sl0: p.sl0, sl: p.sl, tp: p.tp,
    entryT: p.entryT, entryShownT: p.entryShownT, exitT: barT, exitShownT: shownT,
    pnl, r: risk ? pnl / risk : null, reason, note,
  });
  S.positions.splice(S.positions.indexOf(p), 1);
  posVersion++;
  tradeVersion++;
}

function closeManual(id) {
  const p = S.positions.find((x) => x.id === id);
  if (!p) return;
  const t = F.t[cursor];
  closePosition(p, exitPriceNow(p), t, t + 300, 'Manual', '');
  const tr = S.trades[S.trades.length - 1];
  toast(`#${id} closed at ${px(tr.exit)}: ${money(tr.pnl, true)}`);
  refreshOverlays();
  updatePanels();
  save();
}

function cancelOrder(id) {
  S.orders = S.orders.filter((o) => o.id !== id);
  ordVersion++;
  refreshOverlays();
  updatePanels();
  save();
}

function modifyPosition(id, field, raw) {
  const p = S.positions.find((x) => x.id === id);
  if (!p) return;
  const v = numOrNull(raw), long = p.side === 'buy';
  const bid = bidNow(), ask = askNow();
  let err = null;
  if (v != null && field === 'sl' && (long ? v >= bid : v <= ask)) err = 'That stop would trigger immediately';
  if (v != null && field === 'tp' && (long ? v <= bid : v >= ask)) err = 'That target would trigger immediately';
  if (err) {
    toast(err, true);
    rendered.table = null;  // put the old value back
  } else {
    p[field] = v;
    if (field === 'sl' && p.sl0 == null) p.sl0 = v;  // the first stop defines 1R
    posVersion++;
    refreshOverlays();
    save();
  }
  updatePanels();
}

function moveToBreakeven(id) {
  const p = S.positions.find((x) => x.id === id);
  if (!p) return;
  if (p.side === 'buy' ? bidNow() <= p.entry : askNow() >= p.entry) return toast('Price has to be beyond the entry first', true);
  modifyPosition(id, 'sl', p.entry);
}

// ---------- panels ----------

function stats() {
  let gp = 0, gl = 0, wins = 0, rSum = 0, rN = 0, eq = S.balance0, peak = eq, dd = 0, ddPct = 0;
  for (const t of S.trades) {
    if (t.pnl > 0) { gp += t.pnl; wins++; } else gl -= t.pnl;
    if (t.r != null) { rSum += t.r; rN++; }
    eq += t.pnl;
    peak = Math.max(peak, eq);
    if (peak - eq > dd) { dd = peak - eq; ddPct = (dd / peak) * 100; }
  }
  const n = S.trades.length;
  return { n, win: n ? (wins / n) * 100 : null, net: gp - gl, pf: gl > 0 ? gp / gl : gp > 0 ? Infinity : null,
           avgR: rN ? rSum / rN : null, exp: n ? (gp - gl) / n : null, dd, ddPct };
}

function setText(sel, text, cls = '') {
  const el = $(sel);
  el.textContent = text;
  el.className = cls;
}

function updatePanels() {
  const bid = bidNow(), ask = askNow();
  $('#clock').textContent = `${fmtTime(F.t[cursor] + 300, true)} ${tzShort()}`;
  const atLatest = cursor >= F.n - 1;
  $('#clockLabel').textContent = atLatest ? 'Latest price (replay ended)' : 'Replay time';
  $('#btnEnd').disabled = atLatest;
  $('#qBid').textContent = px(bid);
  $('#qAsk').textContent = px(ask);
  $('#qSpr').textContent = (ask - bid).toFixed(2);
  $('#sellPx').textContent = px(bid);
  $('#buyPx').textContent = px(ask);

  const bal = balance(), eq = equity();
  setText('#accBal', money(bal));
  setText('#accEq', money(eq));
  setText('#accOpen', money(eq - bal, true), signCls(eq - bal));

  const statKey = `${tradeVersion}|${S.balance0}`;
  if (rendered.stats !== statKey) {
    rendered.stats = statKey;
    const s = stats();
    setText('#stN', String(s.n));
    setText('#stWin', s.win == null ? '—' : `${s.win.toFixed(1)}%`);
    setText('#stNet', money(s.net, true), signCls(s.net));
    setText('#stPF', s.pf == null ? '—' : s.pf === Infinity ? '∞' : s.pf.toFixed(2));
    setText('#stR', s.avgR == null ? '—' : `${s.avgR >= 0 ? '+' : ''}${s.avgR.toFixed(2)}R`, signCls(s.avgR || 0));
    setText('#stExp', s.exp == null ? '—' : money(s.exp, true), signCls(s.exp || 0));
    setText('#stDD', s.dd ? `${money(-s.dd)} (${s.ddPct.toFixed(1)}%)` : '—', s.dd ? 'neg' : '');
  }

  $('#cntPos').textContent = S.positions.length || '';
  $('#cntOrd').textContent = S.orders.length || '';
  $('#cntHist').textContent = S.trades.length || '';
  renderTables();
  updatePreview();
}

function syncTicket() {
  $$('#ordType button').forEach((b) => b.classList.toggle('on', b.dataset.type === S.ordType));
  $('#rowPrice').style.display = S.ordType === 'market' ? 'none' : '';
  $('#sizeMode').value = S.sizeMode;
  const inp = $('#inSize');
  inp.value = S.sizeMode === 'risk' ? S.riskPct : S.lots;
  inp.step = S.sizeMode === 'risk' ? '0.25' : String(META.lotStep || 0.01);
  inp.title = S.sizeMode === 'risk' ? '% of equity lost if the stop is hit' : `Lots (1 lot = ${S.lotSize} ${META.unit || 'units'})`;
  updatePreview();
}

function updatePreview() {
  const el = $('#preview');
  const bid = bidNow(), ask = askNow();
  const sl = numOrNull($('#inSL').value), tp = numOrNull($('#inTP').value);
  let entry = S.ordType === 'market' ? null : numOrNull($('#inPrice').value);
  if (S.ordType !== 'market' && entry == null) { el.textContent = 'Set a price for the pending order'; return; }
  const ref = entry ?? (bid + ask) / 2;
  const long = sl != null ? sl < ref : tp != null ? tp > ref : null;
  if (long == null) { el.textContent = 'Add a stop loss to see risk and position size'; return; }
  if (entry == null) entry = long ? ask : bid;
  const lots = sizeFor(entry, sl);
  if (typeof lots === 'string') { el.textContent = lots; return; }
  const parts = [`${long ? 'Long' : 'Short'} ${fmtLots(lots)} lot`];
  if (sl != null) {
    const risk = Math.abs(entry - sl) * S.lotSize * lots;
    parts.push(`risk ${money(risk)} (${((risk / equity()) * 100).toFixed(2)}%)`);
  }
  if (tp != null) parts.push(`target ${money(Math.abs(tp - entry) * S.lotSize * lots)}`);
  if (sl != null && tp != null) parts.push(`R:R ${(Math.abs(tp - entry) / Math.abs(entry - sl)).toFixed(2)}`);
  el.textContent = parts.join(' · ');
}

function showTab(name) {
  tab = name;
  $$('.tabs button[data-tab]').forEach((b) => b.classList.toggle('on', b.dataset.tab === name));
  rendered.table = null;
  renderTables();
}

function renderTables() {
  const key = `${tab}|${posVersion}|${ordVersion}|${tradeVersion}|${S.tz}`;
  if (rendered.table !== key) {
    rendered.table = key;
    $('#tabBody').innerHTML = tab === 'positions' ? positionsHtml() : tab === 'orders' ? ordersHtml() : historyHtml();
  }
  if (tab !== 'positions') return;
  for (const p of S.positions) {
    const pnl = openPnl(p), risk = riskUsd(p);
    const cell = (name) => $(`[data-live="${name}${p.id}"]`);
    if (!cell('px')) continue;
    cell('px').textContent = px(p.side === 'buy' ? bidNow() : askNow());
    cell('pnl').textContent = money(pnl, true);
    cell('pnl').className = signCls(pnl);
    cell('r').textContent = risk ? `${(pnl / risk).toFixed(2)}R` : '—';
  }
}

const sideCell = (side) => `<td class="${side === 'buy' ? 'buyc' : 'sellc'}">${side === 'buy' ? 'Long' : 'Short'}</td>`;

function positionsHtml() {
  if (!S.positions.length) return '<div class="empty">No open positions. Use BUY / SELL on the right.</div>';
  return `<table><thead><tr><th>#</th><th>Side</th><th>Lots</th><th>Opened</th><th>Entry</th><th>Stop loss</th>
    <th>Take profit</th><th>Price</th><th>P&amp;L</th><th>R</th><th></th></tr></thead><tbody>${S.positions.map((p) => `
    <tr><td>${p.id}</td>${sideCell(p.side)}<td>${fmtLots(p.lots)}</td><td>${fmtTime(p.entryShownT)}</td><td>${px(p.entry)}</td>
    <td><input data-pid="${p.id}" data-field="sl" type="number" step="0.01" value="${p.sl ?? ''}" placeholder="none"></td>
    <td><input data-pid="${p.id}" data-field="tp" type="number" step="0.01" value="${p.tp ?? ''}" placeholder="none"></td>
    <td data-live="px${p.id}"></td><td data-live="pnl${p.id}"></td><td data-live="r${p.id}"></td>
    <td><button data-act="be" data-id="${p.id}" title="Move the stop to the entry price">BE</button>
        <button data-act="close" data-id="${p.id}">Close</button></td></tr>`).join('')}</tbody></table>`;
}

function ordersHtml() {
  if (!S.orders.length) return '<div class="empty">No pending orders. Choose Limit or Stop in the order panel.</div>';
  return `<table><thead><tr><th>#</th><th>Side</th><th>Type</th><th>Lots</th><th>Price</th><th>Stop loss</th>
    <th>Take profit</th><th>Placed</th><th></th></tr></thead><tbody>${S.orders.map((o) => `
    <tr><td>${o.id}</td>${sideCell(o.side)}<td>${o.type}</td><td>${fmtLots(o.lots)}</td><td>${px(o.price)}</td>
    <td>${px(o.sl)}</td><td>${px(o.tp)}</td><td>${fmtTime(o.placedT)}</td>
    <td><button data-act="cancel" data-id="${o.id}">Cancel</button></td></tr>`).join('')}</tbody></table>`;
}

function historyHtml() {
  if (!S.trades.length) return '<div class="empty">No closed trades yet.</div>';
  const rows = S.trades.slice().reverse().map((t) => `
    <tr class="clickable" data-trade="${t.id}" title="Show on chart"><td>${t.id}</td>${sideCell(t.side)}<td>${fmtLots(t.lots)}</td>
    <td>${fmtTime(t.entryShownT)}</td><td>${px(t.entry)}</td><td>${fmtTime(t.exitShownT)}</td><td>${px(t.exit)}</td>
    <td>${px(t.sl0)}</td><td>${px(t.tp)}</td><td>${t.reason}${t.note ? ` <span class="small">(${t.note})</span>` : ''}</td>
    <td class="${signCls(t.pnl)}">${money(t.pnl, true)}</td><td class="${signCls(t.r || 0)}">${t.r == null ? '—' : `${t.r.toFixed(2)}R`}</td></tr>`).join('');
  return `<table><thead><tr><th>#</th><th>Side</th><th>Lots</th><th>Opened</th><th>Entry</th><th>Closed</th><th>Exit</th>
    <th>Initial SL</th><th>TP</th><th>Exit reason</th><th>P&amp;L</th><th>R</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function onTableClick(e) {
  const btn = e.target.closest('button[data-act]');
  if (btn) {
    const id = +btn.dataset.id;
    if (btn.dataset.act === 'close') closeManual(id);
    else if (btn.dataset.act === 'be') moveToBreakeven(id);
    else if (btn.dataset.act === 'cancel') cancelOrder(id);
    return;
  }
  const row = e.target.closest('tr[data-trade]');
  if (row) focusTrade(+row.dataset.trade);
}

function onTableChange(e) {
  const inp = e.target.closest('input[data-pid]');
  if (inp) modifyPosition(+inp.dataset.pid, inp.dataset.field, inp.value);
}

function focusTrade(id) {
  const t = S.trades.find((x) => x.id === id);
  if (!t) return;
  const a = tfIndexAt(view.tf, t.entryT), b = tfIndexAt(view.tf, t.exitT);
  if (b > view.k) return toast('That trade is ahead of the replay time', true);
  if (a < view.start) return toast('That trade is older than the loaded chart: switch to a higher timeframe', true);
  const pad = Math.max(25, (b - a) * 0.6);
  chart.timeScale().setVisibleLogicalRange({ from: a - view.start - pad, to: b - view.start + pad });
}

function exportCsv() {
  if (!S.trades.length) return toast('No closed trades to export', true);
  const head = ['id', 'side', 'lots', 'order_type', `entry_time_${tzShort()}`, 'entry', `exit_time_${tzShort()}`, 'exit',
                'initial_sl', 'final_sl', 'tp', 'exit_reason', 'note', `pnl_${(META.ccyCode || 'usd').toLowerCase()}`, 'r_multiple'];
  const rows = S.trades.map((t) => [t.id, t.side, t.lots, t.type, fmtTime(t.entryShownT), t.entry.toFixed(3),
    fmtTime(t.exitShownT), t.exit.toFixed(3), t.sl0 ?? '', t.sl ?? '', t.tp ?? '', t.reason, t.note,
    t.pnl.toFixed(2), t.r == null ? '' : t.r.toFixed(3)]);
  const csv = [head, ...rows].map((r) => r.join(',')).join('\n');
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  a.download = `${SYMBOL.toLowerCase()}-replay-trades-${new Date().toISOString().slice(0, 10)}.csv`;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function resetSession() {
  if (!confirm('Clear all positions, pending orders and trade history? Drawings and settings are kept.')) return;
  S.positions = [];
  S.orders = [];
  S.trades = [];
  posVersion++; ordVersion++; tradeVersion++;
  refreshOverlays();
  updatePanels();
  save();
}

// ---------- drawings ----------

/* A drawing is { type, pts: [{ t, p }, ...] } plus optional color, width, style and locked.
 * Anchors are UTC seconds and prices, so a drawing stays put across timeframes: a time maps
 * to a fractional bar position on whatever is showing. Channels add `off` (their width in
 * price); position tools add `startT` (first bar judged) and an optional `endT`. */
const PALETTE = ['#5b9cf6', '#2962ff', '#f23645', '#22ab94', '#ff9800', '#e040fb', '#f7c948', '#d1d4dc'];
const DASH = { solid: [], dashed: [6, 4], dotted: [1.5, 3] };
const TYPE_NAME = {
  trend: 'Trend line', ray: 'Ray', hline: 'Horizontal line', vline: 'Vertical line', channel: 'Parallel channel',
  rect: 'Zone', fib: 'Fib retracement', long: 'Long position', short: 'Short position', measure: 'Date and price range',
};
const COLORED = new Set(['trend', 'ray', 'hline', 'vline', 'channel', 'rect']);
const STYLED = new Set(['trend', 'ray', 'hline', 'vline', 'channel', 'rect', 'fib']);
const colorOf = (d) => d.color || (d.type === 'hline' ? C.hline : C.draw);
const widthOf = (d) => d.width || (['rect', 'fib', 'hline'].includes(d.type) ? 1 : 2);
const isPosition = (d) => d.type === 'long' || d.type === 'short';
const copyOf = (x) => JSON.parse(JSON.stringify(x));

let selected = null, hovered = null, drag = null;
let paneW = Infinity;  // pane width at the last paint, for keeping labels inside it
const paneWidth = () => chart.timeScale().width();
const paneHeight = () => $('#chart').clientHeight - chart.timeScale().height();
const undoStack = [], redoStack = [];

function timeToLogical(t) {
  const T = D[view.tf];
  const i = tfIndexAt(view.tf, t);
  if (i < view.start) return (t - T.t[view.start]) / T.sec;
  if (i >= view.k) return view.k - view.start + (t - T.t[view.k]) / T.sec;
  return i - view.start + (t - T.t[i]) / (T.t[i + 1] - T.t[i]);
}

function logicalToTime(logical) {  // snapped to a bar open
  const T = D[view.tf];
  const g = view.start + Math.round(logical);
  if (g > view.k) return T.t[view.k] + (g - view.k) * T.sec;
  if (g < 0) return T.t[0] + g * T.sec;
  return T.t[g];
}

function logicalToTimeFrac(logical) {  // exact inverse of timeToLogical
  const T = D[view.tf];
  const f = Math.floor(logical), g = view.start + f;
  if (g >= view.k) return T.t[view.k] + (view.start + logical - view.k) * T.sec;
  if (g < view.start) return T.t[view.start] + logical * T.sec;
  return T.t[g] + (logical - f) * (T.t[g + 1] - T.t[g]);
}

function logicalToX(logical) {  // the chart API only converts whole bar indices
  const ts = chart.timeScale();
  const i = Math.floor(logical), f = logical - i;
  const x0 = ts.logicalToCoordinate(i);
  if (x0 == null || !f) return x0;
  const x1 = ts.logicalToCoordinate(i + 1);
  return x1 == null ? x0 : x0 + f * (x1 - x0);
}

function toXY(pt) {
  const x = logicalToX(timeToLogical(pt.t));
  const y = candles.priceToCoordinate(pt.p);
  return x == null || y == null ? null : { x, y };
}

function channelOffset(a, b, c) {  // price distance from line a-b to point c, measured at c
  const La = timeToLogical(a.t), Lb = timeToLogical(b.t), Lc = timeToLogical(c.t);
  return c.p - (La === Lb ? a.p : a.p + ((b.p - a.p) * (Lc - La)) / (Lb - La));
}

// ---------- position tools ----------

/* A long/short position plays out like a trade from the bar after its entry bar (or the next
 * 5m bar, if it was placed on the forming bar) up to the replay cursor, or its box end, under
 * the order engine's rules: longs exit on the bid, shorts on the ask, and the stop wins when
 * stop and target are both hit inside one 5m bar. */
function positionStart(entryT) {
  const T = D[view.tf], i = tfIndexAt(view.tf, entryT);
  const next = i + 1 < T.n ? T.t[i + 1] : Infinity;
  return Math.max(entryT, Math.min(next, F.t[cursor] + 300));
}

const posEval = new WeakMap();  // drawing -> { sig, limit, j, res }, so each step only scans new bars
function positionOutcome(d) {
  const now = F.t[cursor];
  const [e, s, g] = d.pts;
  const long = d.type === 'long';
  if (e.t > now) return { status: 'waiting' };
  const limit = d.endT != null ? Math.min(now, d.endT) : now;
  const sig = `${e.p}|${s.p}|${g.p}|${d.startT}|${d.endT}`;
  let c = posEval.get(d);
  if (!c || c.sig !== sig || c.limit > limit) c = { sig, limit, j: lowerBound(F.t, d.startT), res: null };
  if (!c.res) {
    const p = { side: long ? 'buy' : 'sell', entry: e.p, sl: s.p, tp: g.p, fillT: null };
    let j = c.j;
    for (; j < F.n && F.t[j] <= limit; j++) {
      const hit = exitCheck(p, F.t[j], F.o[j], F.h[j], F.l[j], F.ao[j], F.ah[j], F.al[j], 0);
      if (hit) { c.res = { status: hit.reason, exitT: F.t[j], exitPx: hit.price }; break; }
    }
    c.j = j;
  }
  c.limit = limit;
  posEval.set(d, c);
  const rOf = (px) => (long ? px - e.p : e.p - px) / Math.abs(e.p - s.p);
  if (c.res) return { ...c.res, r: rOf(c.res.exitPx) };
  if (d.endT != null && now >= d.endT) {  // the box ended with the trade still open
    const j = Math.max(0, upperBound(F.t, d.endT) - 1);
    const px = long ? F.c[j] : F.ac[j];
    return { status: 'ended', exitT: F.t[j], exitPx: px, r: rOf(px) };
  }
  return { status: 'open', r: rOf(long ? bidNow() : askNow()) };
}

function positionBox(d, P) {  // horizontal extent: entry -> box end, else exit, else now
  const x0 = P[0].x;
  let x1 = P[P.length - 1].x, out = null;
  if (d.pts.length === 3 && d.startT != null) {
    out = positionOutcome(d);
    const xe = toXY({ t: d.endT ?? out.exitT ?? F.t[cursor], p: d.pts[0].p });
    x1 = xe ? xe.x : x0;
  }
  return { x0, x1: Math.max(x1, x0 + (d.endT != null ? 8 : 60)), out };
}

// ---------- painting ----------

const FONT = '11px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
const fmtR = (r) => `${r >= 0 ? '+' : '−'}${Math.abs(r).toFixed(2)}R`;

function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`;
}

function inkOn(hex) {  // readable text colour on a background
  const n = parseInt(hex.slice(1), 16);
  return (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) / 255 > 0.6 ? '#131722' : '#fff';
}

function fmtDuration(sec) {
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

function strokeLine(ctx, a, b) {
  ctx.beginPath();
  ctx.moveTo(a.x, a.y);
  ctx.lineTo(b.x, b.y);
  ctx.stroke();
}

function dot(ctx, p, color) {
  ctx.save();
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(p.x, p.y, 3, 0, Math.PI * 2);
  ctx.fill();
  ctx.restore();
}

function arrow(ctx, a, b) {
  strokeLine(ctx, a, b);
  if (Math.hypot(b.x - a.x, b.y - a.y) < 10) return;
  const ang = Math.atan2(b.y - a.y, b.x - a.x);
  ctx.beginPath();
  for (const side of [-0.45, 0.45]) {
    ctx.moveTo(b.x, b.y);
    ctx.lineTo(b.x - 7 * Math.cos(ang + side), b.y - 7 * Math.sin(ang + side));
  }
  ctx.stroke();
}

function tag(ctx, text, x, y, { color = '#fff', bg = 'rgba(42,46,57,0.95)', align = 'center' } = {}) {
  ctx.save();
  ctx.setLineDash([]);
  ctx.font = FONT;
  const w = ctx.measureText(text).width + 10, h = 17;
  const bx = clamp(align === 'center' ? x - w / 2 : align === 'right' ? x - w : x, 2, paneW - w - 2);
  ctx.fillStyle = bg;
  ctx.fillRect(bx, y - h / 2, w, h);
  ctx.fillStyle = color;
  ctx.textBaseline = 'middle';
  ctx.fillText(text, bx + 5, y + 0.5);
  ctx.restore();
}

const rayEnd = (a, b) => {
  const dx = b.x - a.x, dy = b.y - a.y, len = Math.hypot(dx, dy) || 1;
  return { x: a.x + (dx / len) * 1e4, y: a.y + (dy / len) * 1e4 };
};

function channelLines(d, off) {  // the parallel side and the dashed middle, in pixels
  const shifted = (k) => [toXY({ t: d.pts[0].t, p: d.pts[0].p + k }), toXY({ t: d.pts[1].t, p: d.pts[1].p + k })];
  return { far: shifted(off), mid: shifted(off / 2) };
}

function paintChannel(ctx, d, P, off, color) {
  strokeLine(ctx, P[0], P[1]);
  if (off == null) return;
  const { far: [a2, b2], mid: [am, bm] } = channelLines(d, off);
  if (!a2 || !b2) return;
  ctx.fillStyle = rgba(color, 0.1);
  ctx.beginPath();
  ctx.moveTo(P[0].x, P[0].y);
  ctx.lineTo(P[1].x, P[1].y);
  ctx.lineTo(b2.x, b2.y);
  ctx.lineTo(a2.x, a2.y);
  ctx.closePath();
  ctx.fill();
  strokeLine(ctx, a2, b2);
  ctx.setLineDash([4, 4]);
  ctx.lineWidth = 1;
  if (am && bm) strokeLine(ctx, am, bm);
}

function paintFib(ctx, d, P, W) {
  const start = d.pts[0].p, end = d.pts[1].p;  // level 1 at the start of the move, 0 at its end
  const ext = d.extend || 'right', xl = Math.min(P[0].x, P[1].x), xr = Math.max(P[0].x, P[1].x);
  const x0 = ext === 'left' || ext === 'both' ? 0 : xl, x1 = ext === 'right' || ext === 'both' ? W : xr;
  ctx.save();
  ctx.setLineDash([4, 4]);
  ctx.lineWidth = 1;
  ctx.strokeStyle = 'rgba(178,181,190,0.6)';
  strokeLine(ctx, P[0], P[1]);
  ctx.restore();
  ctx.font = FONT;
  ctx.textBaseline = 'bottom';
  let prevY = null;
  for (const lv of fibLevels(d).filter((x) => x.on).sort((a, b) => a.v - b.v)) {
    const price = end + (start - end) * lv.v;
    const y = candles.priceToCoordinate(price);
    if (y == null) continue;
    if (prevY != null && d.fill !== false) {
      ctx.fillStyle = rgba(lv.color, 0.07);
      ctx.fillRect(x0, Math.min(prevY, y), x1 - x0, Math.abs(y - prevY));
    }
    ctx.strokeStyle = lv.color;
    strokeLine(ctx, { x: x0, y }, { x: x1, y });
    const text = [d.labels !== false ? String(lv.v) : '', d.prices !== false ? `(${price.toFixed(2)})` : ''].filter(Boolean).join(' ');
    if (text) {
      ctx.fillStyle = lv.color;
      ctx.fillText(text, x0 + 4, y - 2);
    }
    prevY = y;
  }
}

function paintMeasure(ctx, d, P) {
  const [a, b] = P, pa = d.pts[0], pb = d.pts[1];
  const dp = pb.p - pa.p, col = dp >= 0 ? '#2962ff' : '#f23645';
  const x0 = Math.min(a.x, b.x), x1 = Math.max(a.x, b.x), y0 = Math.min(a.y, b.y), y1 = Math.max(a.y, b.y);
  ctx.fillStyle = rgba(col, 0.15);
  ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
  ctx.strokeStyle = col;
  ctx.lineWidth = 1;
  ctx.setLineDash([]);
  const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
  arrow(ctx, { x: mx, y: a.y }, { x: mx, y: b.y });
  arrow(ctx, { x: a.x, y: my }, { x: b.x, y: my });
  const bars = Math.round(Math.abs(timeToLogical(pb.t) - timeToLogical(pa.t)));
  const sign = dp >= 0 ? '+' : '−';
  const text = `${sign}${Math.abs(dp).toFixed(2)} (${sign}${Math.abs((dp / pa.p) * 100).toFixed(2)}%)` +
    ` · ${bars} bar${bars === 1 ? '' : 's'}, ${fmtDuration(Math.abs(pb.t - pa.t))}`;
  tag(ctx, text, mx, dp >= 0 ? y0 - 12 : y1 + 12, { bg: rgba(col, 0.9) });
}

function paintPosition(ctx, d, P) {
  const long = d.type === 'long';
  const { x0, x1, out } = positionBox(d, P);
  const e = d.pts[0].p, ye = P[0].y, w = x1 - x0, cx = (x0 + x1) / 2;
  const pct = (v) => ((v / e) * 100).toFixed(2);
  ctx.setLineDash([]);
  if (P[1]) {
    ctx.fillStyle = 'rgba(242,54,69,0.2)';
    ctx.fillRect(x0, Math.min(ye, P[1].y), w, Math.abs(P[1].y - ye));
  }
  if (P[2]) {
    ctx.fillStyle = 'rgba(34,171,148,0.2)';
    ctx.fillRect(x0, Math.min(ye, P[2].y), w, Math.abs(P[2].y - ye));
  }
  ctx.strokeStyle = '#b2b5be';
  ctx.lineWidth = 1;
  strokeLine(ctx, { x: x0, y: ye }, { x: x1, y: ye });
  if (P[1]) {
    const s = d.pts[1].p, dist = Math.abs(e - s);
    tag(ctx, `Stop ${s.toFixed(2)} · ${dist.toFixed(2)} (${pct(dist)}%)`, cx, P[1].y + (P[1].y > ye ? 11 : -11), { bg: 'rgba(242,54,69,0.9)' });
  }
  if (!P[2]) return;
  const g = d.pts[2].p, dist = Math.abs(g - e);
  tag(ctx, `Target ${g.toFixed(2)} · ${dist.toFixed(2)} (${pct(dist)}%)`, cx, P[2].y + (P[2].y > ye ? 11 : -11), { bg: 'rgba(8,153,129,0.9)' });
  let text = `${long ? 'Long' : 'Short'} ${e.toFixed(2)} · R:R ${(dist / Math.abs(e - d.pts[1].p)).toFixed(2)}`, bg;
  if (out) {
    if (out.status === 'TP') { text += ` · target hit ${fmtR(out.r)}`; bg = 'rgba(8,153,129,0.95)'; }
    else if (out.status === 'SL') { text += ` · stopped ${fmtR(out.r)}`; bg = 'rgba(242,54,69,0.95)'; }
    else if (out.status === 'ended') { text += ` · box ended ${fmtR(out.r)}`; bg = out.r >= 0 ? 'rgba(8,153,129,0.8)' : 'rgba(242,54,69,0.8)'; }
    else if (out.status === 'open') text += ` · open ${fmtR(out.r)}`;
    else text += ' · not reached yet';
  }
  tag(ctx, text, cx, ye, { bg });
  if (out && out.exitT != null) {
    const xy = toXY({ t: out.exitT, p: out.exitPx });
    if (xy) dot(ctx, xy, out.r >= 0 ? C.win : C.loss);
  }
}

function paintDrawing(ctx, d, W, H, isDraft) {
  const P = d.pts.map(toXY);
  if (!P.length || P.some((p) => !p)) return;
  const color = colorOf(d);
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = widthOf(d);
  ctx.setLineDash(DASH[d.style] || []);
  if (isDraft) ctx.globalAlpha = 0.8;
  switch (d.type) {
    case 'trend': strokeLine(ctx, P[0], P[1]); break;
    case 'ray': strokeLine(ctx, P[0], rayEnd(P[0], P[1])); break;
    case 'vline':
      strokeLine(ctx, { x: P[0].x, y: 0 }, { x: P[0].x, y: H });
      tag(ctx, fmtTime(d.pts[0].t), P[0].x, H - 12, { bg: color, color: inkOn(color) });
      break;
    case 'rect': {
      const [a, b] = P;
      const x = Math.min(a.x, b.x), y = Math.min(a.y, b.y), w = Math.abs(b.x - a.x), h = Math.abs(b.y - a.y);
      ctx.fillStyle = rgba(color, 0.13);
      ctx.fillRect(x, y, w, h);
      ctx.strokeRect(x, y, w, h);
      break;
    }
    case 'channel':
      paintChannel(ctx, d, P, isDraft ? (d.pts.length === 3 ? channelOffset(...d.pts) : null) : d.off, color);
      break;
    case 'fib': paintFib(ctx, d, P, W); break;
    case 'measure': paintMeasure(ctx, d, P); break;
    case 'long': case 'short': paintPosition(ctx, d, P); break;
    default: break;
  }
  ctx.restore();
}

function paintHandles(ctx, d) {
  ctx.save();
  ctx.setLineDash([]);
  ctx.lineWidth = 1.5;
  ctx.strokeStyle = '#2962ff';
  ctx.fillStyle = THEMES[THEME].handleFill;
  for (const h of handlesOf(d)) {
    ctx.beginPath();
    ctx.arc(h.x, h.y, 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  ctx.restore();
}

function paintAll(ctx, W, H) {
  if (!view) return;
  paneW = W;
  const now = F.t[cursor];
  ctx.save();
  ctx.setLineDash([3, 3]);
  ctx.lineWidth = 1;
  for (const t of S.trades) {  // dashed entry -> exit path, like a strategy tester
    if (t.exitT > now) continue;
    const a = toXY({ t: t.entryT, p: t.entry }), b = toXY({ t: t.exitT, p: t.exit });
    if (!a || !b) continue;
    ctx.strokeStyle = t.pnl >= 0 ? C.win : C.loss;
    strokeLine(ctx, a, b);
  }
  ctx.restore();
  for (const d of S.drawings) if (d.type !== 'hline') paintDrawing(ctx, d, W, H, false);
  if (draft && draft.hover) paintDrawing(ctx, { ...draft, pts: [...draft.pts, draft.hover] }, W, H, true);
  for (const d of new Set([hovered, selected])) if (d && !d.locked && S.drawings.includes(d)) paintHandles(ctx, d);
}

class DrawingLayer {  // lightweight-charts series primitive that paints every drawing
  constructor() {
    this._requestUpdate = null;
    this._paneView = {
      zOrder: () => 'top',
      renderer: () => ({
        draw: (target) => target.useMediaCoordinateSpace(({ context, mediaSize }) =>
          paintAll(context, mediaSize.width, mediaSize.height)),
      }),
    };
  }
  attached({ requestUpdate }) { this._requestUpdate = requestUpdate; }
  detached() { this._requestUpdate = null; }
  updateAllViews() {}
  paneViews() { return [this._paneView]; }
  redraw() { if (this._requestUpdate) this._requestUpdate(); }
}

// ---------- editing: selection, undo, toolbar, settings, context menu ----------

function drawingsChanged() {
  drawVersion++;
  refreshOverlays();
  save();
}

function pushUndo(snapshot = JSON.stringify(S.drawings)) {
  undoStack.push(snapshot);
  if (undoStack.length > 100) undoStack.shift();
  redoStack.length = 0;
}

function restoreDrawings(from, to) {  // undo and redo move whole snapshots between the stacks
  if (draft) return setMode(null);
  if (!from.length) return toast(from === undoStack ? 'Nothing to undo' : 'Nothing to redo');
  to.push(JSON.stringify(S.drawings));
  S.drawings = JSON.parse(from.pop());
  hovered = null;
  select(null);
  drawingsChanged();
}
const undo = () => restoreDrawings(undoStack, redoStack);
const redo = () => restoreDrawings(redoStack, undoStack);

function select(d) {
  selected = d;
  refreshSelectionUi();
  layer.redraw();
}

function refreshSelectionUi() {
  const d = selected && S.drawings.includes(selected) ? selected : null;
  selected = d;
  $('#drawBar').style.display = d ? 'flex' : 'none';
  if (!d) return;
  $('#dbName').textContent = TYPE_NAME[d.type] + (d.locked ? ' (locked)' : '');
  $('#dbColors').style.display = COLORED.has(d.type) ? '' : 'none';
  $$('#dbColors button').forEach((b) => b.classList.toggle('on', b.dataset.color === colorOf(d)));
  $('#dbWidth').style.display = $('#dbStyle').style.display = STYLED.has(d.type) ? '' : 'none';
  $('#dbWidth').value = String(widthOf(d));
  $('#dbStyle').value = d.style || 'solid';
  $('#dbLock').classList.toggle('on', !!d.locked);
  $('#dbLock').title = d.locked ? 'Unlock' : 'Lock (stops accidental moves)';
}

function restyle(key, value) {
  if (!selected) return;
  pushUndo();
  selected[key] = value;
  drawingsChanged();
  refreshSelectionUi();
}

function deleteDrawing(d) {
  pushUndo();
  S.drawings.splice(S.drawings.indexOf(d), 1);
  if (hovered === d) hovered = null;
  select(null);
  drawingsChanged();
}

function cloneDrawing(d) {
  pushUndo();
  const c = copyOf(d);
  delete c.locked;
  if (c.type === 'hline') {  // nudge it so the copy is visible
    c.pts[0].p += Math.abs(candles.coordinateToPrice(0) - candles.coordinateToPrice(paneHeight())) * 0.04;
  } else moveDrawing(c, copyOf(c), 5, 0);
  S.drawings.push(c);
  select(c);
  drawingsChanged();
}

function toggleLock(d) {
  pushUndo();
  d.locked = !d.locked;
  drawingsChanged();
  refreshSelectionUi();
}

function wallInputToUtc(v) {  // "YYYY-MM-DDTHH:MM" in the chart timezone -> UTC seconds
  const wall = Date.parse(v.length === 16 ? `${v}:00Z` : `${v}Z`) / 1000;
  if (!Number.isFinite(wall)) return null;
  return wall - tzOffset(S.tz, wall - tzOffset(S.tz, wall));
}

// ---------- settings dialog: drawings and EMAs, applied live (Cancel reverts), like TradingView ----------

let dialog = null;  // { kind: 'drawing', d, before, beforeAll } or { kind: 'ema', i, before }

function openDialog(title, html, state, removable = false) {
  closeMenu();
  dialog = state;
  $('#dsTitle').textContent = title;
  $('#dsFields').innerHTML = html;
  $('#dsRemove').style.display = removable ? '' : 'none';
  $('#drawSettings').classList.add('open');
}

function closeDialog() {
  dialog = null;
  $('#drawSettings').classList.remove('open');
}

function dialogOk() {
  if (!dialog) return;
  if (dialog.kind === 'drawing') {
    if (!applyDrawingFields(true)) return;
    if (JSON.stringify(S.drawings) !== dialog.beforeAll) pushUndo(dialog.beforeAll);
    drawingsChanged();
    refreshSelectionUi();
  } else emaChanged();
  closeDialog();
}

function dialogCancel() {
  if (!dialog) return;
  if (dialog.kind === 'drawing') {
    const d = dialog.d;  // restore in place, so the selection keeps pointing at it
    for (const k of Object.keys(d)) delete d[k];
    Object.assign(d, dialog.before);
    drawingsChanged();
    refreshSelectionUi();
  } else {
    S.emas[dialog.i] = dialog.before;
    buildEmaUi();
    emaChanged();
  }
  closeDialog();
}

function dialogRemove() {
  if (dialog && dialog.kind === 'ema') {
    const i = dialog.i;
    closeDialog();
    removeEma(i);
  }
}

function onDialogInput() {
  if (!dialog) return;
  if (dialog.kind === 'ema') applyEmaFields();
  else applyDrawingFields(false);
}

function onDialogClick(e) {
  if (!dialog) return;
  if (dialog.kind === 'ema') {
    const sw = e.target.closest('[data-swatch]');
    if (sw) {
      $('#dsFields [data-k="color"]').value = sw.dataset.swatch;
      applyEmaFields();
    }
    return;
  }
  const d = dialog.d;
  const add = e.target.closest('[data-lv-add]'), del = e.target.closest('[data-lv-del]');
  const rev = e.target.closest('[data-fib-reverse]');
  if (!add && !del && !rev) return;
  applyDrawingFields(false);  // keep what was typed before the list is redrawn
  if (add) {
    const levels = fibLevels(d).map((x) => ({ ...x }));
    const used = new Set(levels.map((x) => x.v));
    const v = [1.272, 1.414, 2, 2.618, 3.618, 4.236, 0.705, 0.65].find((x) => !used.has(x)) ?? Math.max(...levels.map((x) => x.v), 1) + 0.5;
    levels.push({ v, color: '#b2b5be', on: true });
    d.levels = levels;
  } else if (del) {
    d.levels = fibLevels(d).filter((_, j) => j !== +del.dataset.lvDel);
  } else {
    d.pts = [d.pts[1], d.pts[0]];
  }
  $('#dsFields').innerHTML = drawingDialogHtml(d);
  liveUpdate(d);
}

function openSettings(d) {
  select(d);
  openDialog(TYPE_NAME[d.type], drawingDialogHtml(d), { kind: 'drawing', d, before: copyOf(d), beforeAll: JSON.stringify(S.drawings) });
}

function drawingDialogHtml(d) {
  const price = (k, label, v) => `<div class="row"><label>${label}</label>` +
    `<input type="number" step="0.01" data-k="${k}" value="${v == null ? '' : +v.toFixed(3)}"><span></span></div>`;
  const time = (k, label, t) => `<div class="row"><label>${label}</label>` +
    `<input type="datetime-local" data-k="${k}" value="${t == null ? '' : toInputValue(t)}"><span></span></div>`;
  const note = `<div class="small">Times are in ${tzShort()}. Changes show on the chart as you type; Cancel puts it back.</div>`;
  const [a, b] = d.pts;
  if (d.type === 'hline') return price('p0', 'Price', a.p) + note;
  if (d.type === 'vline') return time('t0', 'Time', a.t) + note;
  if (isPosition(d)) {
    return price('p0', 'Entry', a.p) + time('t0', 'Entry time', a.t) + price('p1', 'Stop loss', d.pts[1].p) +
      price('p2', 'Take profit', d.pts[2].p) + time('end', 'Box ends', d.endT) +
      '<div class="small">Leave "Box ends" empty to let the trade run until the stop or target is hit.</div>' + note;
  }
  const [n1, n2] = { fib: ['Start (1)', 'End (0)'], rect: ['Corner 1', 'Corner 2'], measure: ['From', 'To'] }[d.type] || ['Point 1', 'Point 2'];
  let html = price('p0', `${n1} price`, a.p) + time('t0', `${n1} time`, a.t) + price('p1', `${n2} price`, b.p) + time('t1', `${n2} time`, b.t);
  if (d.type === 'channel') html += price('off', 'Channel width', d.off);
  if (d.type === 'fib') html += fibOptionsHtml(d);
  return html + note;
}

function fibOptionsHtml(d) {
  const ext = d.extend || 'right';
  const check = (k, label) => `<label><input type="checkbox" data-k="${k}"${d[k] !== false ? ' checked' : ''}> ${label}</label>`;
  return '<h4 class="dsh">Levels</h4><div class="fiblevels">' + fibLevels(d).map((lv, j) => '<div class="fibrow">' +
      `<input type="checkbox" data-lv-on="${j}"${lv.on ? ' checked' : ''} title="Show this level">` +
      `<input type="number" step="0.001" data-lv-v="${j}" value="${lv.v}">` +
      `<input type="color" data-lv-c="${j}" value="${lv.color}" title="Colour">` +
      `<button data-lv-del="${j}" title="Remove level">✕</button></div>`).join('') +
    '</div><button class="addrow" data-lv-add>+ Add level</button>' +
    '<div class="row"><label>Extend lines</label><select data-k="extend">' +
    [['none', 'None'], ['right', 'Right'], ['left', 'Left'], ['both', 'Both']]
      .map(([v, n]) => `<option value="${v}"${ext === v ? ' selected' : ''}>${n}</option>`).join('') +
    '</select><span></span></div>' +
    `<div class="checks">${check('labels', 'Levels')}${check('prices', 'Prices')}${check('fill', 'Background')}` +
    '<button data-fib-reverse title="Swap the start and the end">⇅ Reverse</button></div>';
}

function applyDrawingFields(final) {  // dialog -> drawing; false (with a message on OK) while invalid
  const d = dialog.d;
  const field = (k) => $(`#dsFields [data-k="${k}"]`);
  const raw = (k) => { const el = field(k); return el ? (el.type === 'checkbox' ? el.checked : el.value) : undefined; };
  const next = copyOf(d);
  next.pts.forEach((pt, i) => {
    const p = numOrNull(raw(`p${i}`)), tv = raw(`t${i}`), t = tv ? wallInputToUtc(tv) : null;
    if (p != null) pt.p = p;
    if (t != null) pt.t = t;
  });
  if (d.type === 'channel' && numOrNull(raw('off')) != null) next.off = numOrNull(raw('off'));
  if (d.type === 'fib' && field('extend')) {
    const old = fibLevels(d);
    next.levels = $$('#dsFields [data-lv-v]').map((el) => {
      const j = +el.dataset.lvV;
      return { v: numOrNull(el.value) ?? old[j].v, on: $(`#dsFields [data-lv-on="${j}"]`).checked, color: $(`#dsFields [data-lv-c="${j}"]`).value };
    });
    Object.assign(next, { extend: raw('extend'), labels: raw('labels'), prices: raw('prices'), fill: raw('fill') });
  }
  if (isPosition(d)) {
    const [e, s, g] = next.pts.map((x) => x.p), long = d.type === 'long';
    if (long ? !(s < e && e < g) : !(s > e && e > g)) {
      if (final) toast(long ? 'A long needs stop < entry < target' : 'A short needs stop > entry > target', true);
      return false;
    }
    next.endT = raw('end') ? wallInputToUtc(raw('end')) : undefined;
    if (next.endT != null && next.endT <= next.pts[0].t) {
      if (final) toast('The box has to end after the entry', true);
      return false;
    }
    if (next.endT == null) delete next.endT;
    next.startT = positionStart(next.pts[0].t);
  }
  for (const k of Object.keys(d)) if (!(k in next)) delete d[k];
  Object.assign(d, next);
  liveUpdate(d);
  return true;
}

function openMenu(d, x, y) {
  select(d);
  const m = $('#ctxMenu');
  m.querySelector('[data-act="lock"]').textContent = d.locked ? 'Unlock' : 'Lock';
  m.style.display = 'block';
  const box = $('#chartWrap').getBoundingClientRect();
  m.style.left = `${Math.min(x, box.width - m.offsetWidth - 4)}px`;
  m.style.top = `${Math.min(y, box.height - m.offsetHeight - 4)}px`;
}

function closeMenu() {
  $('#ctxMenu').style.display = 'none';
}

// ---------- tools and mouse ----------

function setMode(m, field = null) {
  if (m) { select(null); closeMenu(); }
  mode = m;
  pickField = m === 'pick' ? field : null;
  draft = null;
  $$('#tools button[data-tool]').forEach((b) => b.classList.toggle('on', b.dataset.tool === m));
  $('#btnSelectBar').classList.toggle('on', m === 'select');
  $$('.pick').forEach((b) => b.classList.toggle('on', m === 'pick' && b.dataset.pick === field));
  setCursor(m ? 'crosshair' : null);
  const hint = m === 'select' ? 'Click a bar to restart the replay from it'
    : m === 'pick' ? `Click the chart to set the ${FIELD_NAME[field]}` : m ? TOOLS[m].hint : '';
  const h = $('#hint');
  h.textContent = m ? `${hint} · Esc to cancel` : '';
  h.style.display = m ? 'block' : 'none';
  layer.redraw();
}

function setCursor(kind) {  // the chart's canvases set their own cursor, so this overrides via CSS
  const el = $('#chart');
  for (const k of ['pointer', 'move', 'ns', 'ew', 'crosshair']) el.classList.toggle(`cur-${k}`, k === kind);
}

let downAt = null;
function paneXY(e) {  // pointer position inside the price pane, or null over the axes
  const box = $('#chart').getBoundingClientRect();
  const x = e.clientX - box.left, y = e.clientY - box.top;
  const ts = chart.timeScale();
  return x >= 0 && y >= 0 && x < ts.width() && y < box.height - ts.height() ? { x, y } : null;
}

function onChartClick(e) {
  if (!mode || !view || !downAt || Math.hypot(e.clientX - downAt[0], e.clientY - downAt[1]) > 4) return;  // a drag pans
  const at = paneXY(e);
  if (!at) return;
  const price = candles.coordinateToPrice(at.y);
  const logical = chart.timeScale().coordinateToLogical(at.x);
  if (price == null || logical == null) return;
  if (mode === 'pick') {
    $(`#${pickField}`).value = price.toFixed(2);
    setMode(null);
    updatePreview();
  } else if (mode === 'select') {
    setMode(null);
    selectBar(logical);
  } else {
    addPoint({ t: logicalToTime(logical), p: price });
  }
}

function addPoint(pt) {
  if (!draft) draft = { type: mode, pts: [] };
  if (isPosition(draft)) {
    const long = mode === 'long', n = draft.pts.length, e = n ? draft.pts[0].p : null;
    if (n === 1 && (long ? pt.p >= e : pt.p <= e)) return toast(`The stop of a ${mode} position goes ${long ? 'below' : 'above'} the entry`, true);
    if (n === 2 && (long ? pt.p <= e : pt.p >= e)) return toast(`The target of a ${mode} position goes ${long ? 'above' : 'below'} the entry`, true);
  }
  draft.pts.push(pt);
  if (draft.pts.length < TOOLS[mode].clicks) return layer.redraw();
  const d = { type: draft.type, pts: draft.pts };
  if (d.type === 'channel') d.off = channelOffset(...d.pts);
  if (isPosition(d)) d.startT = positionStart(d.pts[0].t);
  pushUndo();
  S.drawings.push(d);
  setMode(null);
  select(d);
  drawingsChanged();
}

function segmentDistance(x, y, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y, len2 = dx * dx + dy * dy;
  const u = len2 ? clamp(((x - a.x) * dx + (y - a.y) * dy) / len2, 0, 1) : 0;
  return Math.hypot(x - (a.x + u * dx), y - (a.y + u * dy));
}

function hitDistance(d, x, y) {
  const P = d.pts.map(toXY);
  if (P.some((p) => !p)) return Infinity;
  const box = (x0, x1, y0, y1) => Math.hypot(Math.max(x0 - x, 0, x - x1), Math.max(y0 - y, 0, y - y1));
  switch (d.type) {
    case 'hline': return Math.abs(P[0].y - y);
    case 'vline': return Math.abs(P[0].x - x);
    case 'trend': return segmentDistance(x, y, P[0], P[1]);
    case 'ray': return segmentDistance(x, y, P[0], rayEnd(P[0], P[1]));
    case 'channel': {
      const { far: [a2, b2] } = channelLines(d, d.off);
      if (!a2 || !b2) return segmentDistance(x, y, P[0], P[1]);
      if (P[0].x !== P[1].x && x >= Math.min(P[0].x, P[1].x) && x <= Math.max(P[0].x, P[1].x)) {
        const f = (x - P[0].x) / (P[1].x - P[0].x);
        const y1 = P[0].y + f * (P[1].y - P[0].y), y2 = a2.y + f * (b2.y - a2.y);
        if (y >= Math.min(y1, y2) && y <= Math.max(y1, y2)) return 0;
      }
      return Math.min(segmentDistance(x, y, P[0], P[1]), segmentDistance(x, y, a2, b2));
    }
    case 'fib': {
      const ext = d.extend || 'right', xl = Math.min(P[0].x, P[1].x), xr = Math.max(P[0].x, P[1].x);
      let best = segmentDistance(x, y, P[0], P[1]);
      if ((ext === 'left' || ext === 'both' || x >= xl) && (ext === 'right' || ext === 'both' || x <= xr)) {
        for (const lv of fibLevels(d)) {
          if (!lv.on) continue;
          const yy = candles.priceToCoordinate(d.pts[1].p + (d.pts[0].p - d.pts[1].p) * lv.v);
          if (yy != null) best = Math.min(best, Math.abs(yy - y));
        }
      }
      return best;
    }
    case 'long': case 'short': {
      const { x0, x1 } = positionBox(d, P);
      const ys = P.map((p) => p.y);
      return box(x0, x1, Math.min(...ys), Math.max(...ys));
    }
    default:  // rect, measure
      return box(Math.min(P[0].x, P[1].x), Math.max(P[0].x, P[1].x), Math.min(P[0].y, P[1].y), Math.max(P[0].y, P[1].y));
  }
}

/* Drag points of a drawing: { x, y, cursor, set(pt) } where pt is the pointer's bar time and
 * price. Positions keep stop < entry < target (the other way round for shorts). */
function handlesOf(d) {
  const P = d.pts.map(toXY);
  if (!P.length || P.some((p) => !p)) return [];
  const H = (x, y, set, cursor = 'move') => ({ x, y, set, cursor });
  const point = (i) => H(P[i].x, P[i].y, (pt) => { d.pts[i] = pt; });
  switch (d.type) {
    case 'hline': return [H(paneWidth() / 2, P[0].y, (pt) => { d.pts[0] = { t: d.pts[0].t, p: pt.p }; }, 'ns')];
    case 'vline': return [H(P[0].x, paneHeight() / 2, (pt) => { d.pts[0] = { t: pt.t, p: d.pts[0].p }; }, 'ew')];
    case 'rect': return [point(0), point(1),
      H(P[0].x, P[1].y, (pt) => { d.pts[0] = { t: pt.t, p: d.pts[0].p }; d.pts[1] = { t: d.pts[1].t, p: pt.p }; }),
      H(P[1].x, P[0].y, (pt) => { d.pts[1] = { t: pt.t, p: d.pts[1].p }; d.pts[0] = { t: d.pts[0].t, p: pt.p }; })];
    case 'channel': {
      const { far: [a2, b2] } = channelLines(d, d.off);
      const hs = [point(0), point(1)];
      if (a2) hs.push(H(a2.x, a2.y, (pt) => { d.off = pt.p - d.pts[0].p; }, 'ns'));
      if (b2) hs.push(H(b2.x, b2.y, (pt) => { d.off = pt.p - d.pts[1].p; }, 'ns'));
      return hs;
    }
    case 'long': case 'short': {
      const long = d.type === 'long', { x0, x1 } = positionBox(d, P), tick = 0.01;
      const e = () => d.pts[0].p;
      return [
        H(x0, P[0].y, (pt) => {  // entry moves in time and price; stop and target keep their prices
          const lo = long ? d.pts[1].p : d.pts[2].p, hi = long ? d.pts[2].p : d.pts[1].p;
          d.pts[0] = { t: pt.t, p: clamp(pt.p, lo + tick, hi - tick) };
          d.startT = positionStart(pt.t);
        }),
        H(x0, P[1].y, (pt) => { d.pts[1] = { t: d.pts[1].t, p: long ? Math.min(pt.p, e() - tick) : Math.max(pt.p, e() + tick) }; }, 'ns'),
        H(x0, P[2].y, (pt) => { d.pts[2] = { t: d.pts[2].t, p: long ? Math.max(pt.p, e() + tick) : Math.min(pt.p, e() - tick) }; }, 'ns'),
        H(x1, P[0].y, (pt) => { d.endT = Math.max(pt.t, d.pts[0].t + D[view.tf].sec); }, 'ew'),
      ];
    }
    default: return [point(0), point(1)];  // trend, ray, fib, measure
  }
}

function hitTestAt(x, y) {  // handles first (the selected drawing's before the rest), then bodies
  const top = S.drawings.slice().reverse();
  const order = selected ? [selected, ...top.filter((d) => d !== selected)] : top;
  for (const d of order) {
    if (d.locked) continue;
    for (const h of handlesOf(d)) if (Math.hypot(h.x - x, h.y - y) <= 7) return { d, handle: h };
  }
  for (const d of top) if (hitDistance(d, x, y) <= 6) return { d, handle: null };
  return null;
}

function moveDrawing(d, orig, bars, dp) {  // shift the drag-start copy by whole bars and a price step
  const shift = (t) => (bars ? logicalToTimeFrac(timeToLogical(t) + bars) : t);
  d.pts = orig.pts.map((pt) => ({ t: d.type === 'hline' ? pt.t : shift(pt.t), p: d.type === 'vline' ? pt.p : pt.p + dp }));
  if (orig.endT != null) d.endT = shift(orig.endT);
  if (isPosition(d)) d.startT = positionStart(d.pts[0].t);
}

function liveUpdate(d) {
  if (d.type === 'hline') { drawVersion++; refreshOverlays(); } else layer.redraw();
}

function onPointerDown(e) {  // capture phase: runs before the chart, so grabbing a drawing never pans
  downAt = e.button === 0 ? [e.clientX, e.clientY] : null;
  if (!e.target.closest('#ctxMenu')) closeMenu();
  if (e.button !== 0 || mode || !view) return;
  const at = paneXY(e);
  if (!at) return;
  const hit = hitTestAt(at.x, at.y);
  if (!hit) { if (selected) select(null); return; }
  select(hit.d);
  if (hit.d.locked) return;
  e.preventDefault();
  e.stopPropagation();
  $('#chart').setPointerCapture(e.pointerId);
  drag = { d: hit.d, handle: hit.handle, x: at.x, y: at.y, moved: false, before: JSON.stringify(S.drawings), orig: copyOf(hit.d),
           L: chart.timeScale().coordinateToLogical(at.x), p: candles.coordinateToPrice(at.y) };
}

function onDragMove(e) {
  if (!drag) return;
  const box = $('#chart').getBoundingClientRect(), ts = chart.timeScale();
  const x = clamp(e.clientX - box.left, 0, ts.width() - 1), y = clamp(e.clientY - box.top, 0, box.height - ts.height() - 1);
  if (!drag.moved && Math.hypot(x - drag.x, y - drag.y) < 3) return;
  if (!drag.moved) { drag.moved = true; pushUndo(drag.before); }
  const price = candles.coordinateToPrice(y), logical = ts.coordinateToLogical(x);
  if (price == null || logical == null) return;
  if (drag.handle) drag.handle.set({ t: logicalToTime(logical), p: price });
  else moveDrawing(drag.d, drag.orig, Math.round(logical - drag.L), price - drag.p);
  liveUpdate(drag.d);
}

function onDragEnd() {
  if (!drag) return;
  const moved = drag.moved;
  drag = null;
  if (moved) drawingsChanged();
  refreshSelectionUi();
}

function onChartHover(e) {  // cursor and hover handles, like TradingView
  if (drag || !view) return;
  if (mode) return setCursor('crosshair');
  const at = paneXY(e);
  const hit = at ? hitTestAt(at.x, at.y) : null;
  setCursor(hit ? (hit.handle ? hit.handle.cursor : 'pointer') : at && emaHitAt(at.x, at.y) >= 0 ? 'pointer' : null);
  const d = hit ? hit.d : null;
  if (d !== hovered) { hovered = d; layer.redraw(); }
}

function onChartLeave() {
  if (drag || !hovered) return;
  hovered = null;
  layer.redraw();
}

function onCrosshair(param) {
  if (draft && param.point) {
    const logical = chart.timeScale().coordinateToLogical(param.point.x);
    const price = candles.coordinateToPrice(param.point.y);
    if (logical != null && price != null) {
      draft.hover = { t: logicalToTime(logical), p: price };
      layer.redraw();
    }
  }
  showLegend(param && param.point ? param : null);
}

function onChartRightClick(e) {
  e.preventDefault();
  if (mode) return setMode(null);
  const at = paneXY(e);
  const hit = at ? hitTestAt(at.x, at.y) : null;
  if (hit) openMenu(hit.d, at.x, at.y); else closeMenu();
}

function onChartDblClick(e) {  // a drawing's settings, or an EMA's when its line is double-clicked
  if (mode) return;
  const at = paneXY(e);
  if (!at) return;
  const hit = hitTestAt(at.x, at.y);
  if (hit) return openSettings(hit.d);
  const i = emaHitAt(at.x, at.y);
  if (i >= 0) openEmaSettings(i);
}

// ---------- indicators ----------

const SOURCES = { close: 'Close', open: 'Open', high: 'High', low: 'Low', hl2: '(H+L)/2', hlc3: '(H+L+C)/3', ohlc4: '(O+H+L+C)/4' };

function srcValue(src, o, h, l, c) {
  switch (src) {
    case 'open': return o;
    case 'high': return h;
    case 'low': return l;
    case 'hl2': return (h + l) / 2;
    case 'hlc3': return (h + l + c) / 3;
    case 'ohlc4': return (o + h + l + c) / 4;
    default: return c;
  }
}

const emaCache = new Map();
function emaValues(tf, len, src = 'close') {  // EMA of closed bars over the whole history, seeded with an SMA
  const key = `${tf}:${len}:${src}`;
  let out = emaCache.get(key);
  if (out) return out;
  const T = D[tf], n = T.n, a = 2 / (len + 1);
  out = new Float64Array(n).fill(NaN);
  if (n >= len) {
    const x = (i) => srcValue(src, T.o[i], T.h[i], T.l[i], T.c[i]);
    let e = 0;
    for (let i = 0; i < len; i++) e += x(i);
    e /= len;
    out[len - 1] = e;
    for (let i = len; i < n; i++) { e += a * (x(i) - e); out[i] = e; }
  }
  emaCache.set(key, out);
  return out;
}

function emaForming(tf, cfg, k, bar) {  // the forming bar only knows its prices so far
  const prev = k > 0 ? emaValues(tf, cfg.len, cfg.src)[k - 1] : NaN;
  return prev + (2 / (cfg.len + 1)) * (srcValue(cfg.src, bar.open, bar.high, bar.low, bar.close) - prev);
}

const lineStyleOf = (s) => ({ solid: LC.LineStyle.Solid, dashed: LC.LineStyle.Dashed, dotted: LC.LineStyle.Dotted })[s || 'solid'];

function syncEmaSeries() {  // one line series per EMA, in the same order
  while (emaSeries.length > S.emas.length) chart.removeSeries(emaSeries.pop());
  while (emaSeries.length < S.emas.length) {
    emaSeries.push(chart.addLineSeries({ priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false }));
  }
  S.emas.forEach((cfg, s) => emaSeries[s].applyOptions({ color: cfg.color, lineWidth: cfg.width || 1, lineStyle: lineStyleOf(cfg.style) }));
}

function renderEmas(full) {
  const tf = view.tf;
  S.emas.forEach((cfg, s) => {
    const series = emaSeries[s];
    if (!cfg.on) { if (full) series.setData([]); return; }
    const ema = emaValues(tf, cfg.len, cfg.src);
    const from = full ? view.start : view.prevK;
    const pts = [];
    for (let i = from; i < view.k; i++) if (Number.isFinite(ema[i])) pts.push({ time: dispTime(tf, i), value: ema[i] });
    const f = emaForming(tf, cfg, view.k, view.last);
    if (Number.isFinite(f)) pts.push({ time: view.last.time, value: f });
    if (full) series.setData(pts);
    else pts.forEach((p) => series.update(p));
  });
}

function emaAt(i, g) {  // EMA i on bar g of the showing timeframe
  const cfg = S.emas[i];
  return g === view.k ? emaForming(view.tf, cfg, view.k, view.last) : emaValues(view.tf, cfg.len, cfg.src)[g];
}

function emaHitAt(x, y) {  // index of a visible EMA line within 5px of (x, y), or -1
  const L = chart.timeScale().coordinateToLogical(x);
  if (L == null) return -1;
  const g = view.start + Math.round(L);
  if (g < view.start || g > view.k) return -1;
  let best = -1, bestDist = 5;
  S.emas.forEach((cfg, i) => {
    if (!cfg.on) return;
    const yy = candles.priceToCoordinate(emaAt(i, g));
    if (yy != null && Math.abs(yy - y) < bestDist) { bestDist = Math.abs(yy - y); best = i; }
  });
  return best;
}

function addEma() {
  if (S.emas.length >= MAX_EMAS) return toast(`Up to ${MAX_EMAS} EMAs`, true);
  const lens = new Set(S.emas.map((e) => e.len)), colors = new Set(S.emas.map((e) => e.color));
  S.emas.push({
    on: true, len: EMA_LENGTHS.find((n) => !lens.has(n)) ?? 10, src: 'close', width: 1, style: 'solid',
    color: EMA_COLORS.find((c) => !colors.has(c)) ?? EMA_COLORS[0],
  });
  buildEmaUi();
  emaChanged();
  return S.emas.length - 1;
}

function removeEma(i) {
  S.emas.splice(i, 1);
  buildEmaUi();
  emaChanged();
}

function openEmaSettings(i) {
  const e = S.emas[i];
  const opt = (list, cur) => list.map(([v, n]) => `<option value="${v}"${String(v) === String(cur) ? ' selected' : ''}>${n}</option>`).join('');
  openDialog(`EMA ${e.len}`,
    `<div class="row"><label>Length</label><input type="number" data-k="len" min="2" max="1000" step="1" value="${e.len}"><span></span></div>` +
    `<div class="row"><label>Source</label><select data-k="src">${opt(Object.entries(SOURCES), e.src || 'close')}</select><span></span></div>` +
    `<div class="row"><label>Colour</label><span class="swatches">${EMA_COLORS.map((c) => `<button data-swatch="${c}" style="background:${c}" title="${c}"></button>`).join('')}` +
    `<input type="color" data-k="color" value="${e.color}" title="Any colour"></span><span></span></div>` +
    `<div class="row"><label>Line width</label><select data-k="width">${opt([[1, '1 px'], [2, '2 px'], [3, '3 px'], [4, '4 px']], e.width || 1)}</select><span></span></div>` +
    `<div class="row"><label>Line style</label><select data-k="style">${opt([['solid', 'Solid'], ['dashed', 'Dashed'], ['dotted', 'Dotted']], e.style || 'solid')}</select><span></span></div>` +
    `<div class="row"><label>Visible</label><input type="checkbox" data-k="on"${e.on ? ' checked' : ''}><span></span></div>` +
    '<div class="small">Changes show on the chart as you edit; Cancel puts them back.</div>',
    { kind: 'ema', i, before: copyOf(e) }, true);
}

function applyEmaFields() {
  const e = S.emas[dialog.i], f = (k) => $(`#dsFields [data-k="${k}"]`);
  const len = Math.round(numOrNull(f('len').value));
  if (len >= 2 && len <= 1000) e.len = len;
  Object.assign(e, { src: f('src').value, color: f('color').value, width: +f('width').value, style: f('style').value, on: f('on').checked });
  $('#dsTitle').textContent = `EMA ${e.len}`;
  buildEmaUi();
  emaChanged();
}

const ICON = {
  eye: '<svg viewBox="0 0 20 20"><path d="M2 10s3-5.5 8-5.5 8 5.5 8 5.5-3 5.5-8 5.5S2 10 2 10z"/><circle cx="10" cy="10" r="2.5"/></svg>',
  eyeOff: '<svg viewBox="0 0 20 20"><path d="M2 10s3-5.5 8-5.5 8 5.5 8 5.5-3 5.5-8 5.5S2 10 2 10z"/><path d="M3 17L17 3"/></svg>',
  gear: '<svg viewBox="0 0 20 20"><path d="M3 6h14M3 14h14"/><circle cx="7.5" cy="6" r="2" style="fill:var(--panel)"/><circle cx="12.5" cy="14" r="2" style="fill:var(--panel)"/></svg>',
  cross: '<svg viewBox="0 0 20 20"><path d="M5 5l10 10M15 5L5 15"/></svg>',
};

let emaLegendKey = '';
function syncEmaLegend() {  // one legend row per EMA, rebuilt only when the EMAs change so clicks land
  const key = JSON.stringify(S.emas.map((e) => [e.len, e.src, e.color, e.on]));
  if (key === emaLegendKey) return;
  emaLegendKey = key;
  $('#lgEmas').innerHTML = S.emas.map((e, i) => `<div class="emaitem${e.on ? '' : ' off'}" data-ema="${i}" title="Click for settings">` +
    `<span class="ename" style="color:${e.color}">EMA ${e.len} ${e.src || 'close'}</span><span class="evalue" style="color:${e.color}"></span>` +
    `<span class="eicons"><button data-eact="toggle" title="${e.on ? 'Hide' : 'Show'}">${e.on ? ICON.eye : ICON.eyeOff}</button>` +
    `<button data-eact="settings" title="Settings">${ICON.gear}</button><button data-eact="remove" title="Remove">${ICON.cross}</button></span></div>`).join('');
}

function onLegendClick(ev) {
  const item = ev.target.closest('[data-ema]');
  if (!item) return;
  const i = +item.dataset.ema, btn = ev.target.closest('[data-eact]'), act = btn ? btn.dataset.eact : 'settings';
  if (act === 'toggle') {
    S.emas[i].on = !S.emas[i].on;
    buildEmaUi();
    emaChanged();
  } else if (act === 'remove') removeEma(i);
  else openEmaSettings(i);
}

function buildEmaUi() {
  $('#emaRows').innerHTML = S.emas.map((e, s) => '<div class="emarow">' +
    `<input type="checkbox" data-ema="${s}"${e.on ? ' checked' : ''} title="Show or hide">` +
    `<input type="color" data-emacolor="${s}" value="${e.color}" title="Colour">` +
    `<button class="emaname" data-emaset="${s}" title="All settings">EMA</button>` +
    `<input type="number" data-emalen="${s}" min="2" max="1000" step="1" value="${e.len}" title="Length in bars">` +
    `<button data-emadel="${s}" title="Remove this EMA">✕</button></div>`).join('') +
    (S.emas.length < MAX_EMAS ? '<button id="emaAdd" class="addrow">+ Add EMA</button>' : '');
}

function emaChanged() {
  syncEmaSeries();
  renderEmas(true);
  showLegend(null);
  save();
}

let emaTyping = null;
function onEmaInput(ev) {  // colour applies while picking; a typed length after a short pause
  const el = ev.target;
  if (el.dataset.emacolor != null) {
    const s = +el.dataset.emacolor;
    S.emas[s].color = el.value;
    emaSeries[s].applyOptions({ color: el.value });
    showLegend(null);
    save();
  } else if (el.dataset.emalen != null) {
    clearTimeout(emaTyping);
    emaTyping = setTimeout(() => onEmaChange({ target: el }), 350);
  }
}

function onEmaChange(ev) {
  const el = ev.target;
  if (el.dataset.ema != null) S.emas[+el.dataset.ema].on = el.checked;
  else if (el.dataset.emalen != null) {
    const s = +el.dataset.emalen, v = Math.round(numOrNull(el.value));
    if (!(v >= 2 && v <= 1000)) {  // still typing: wait; left the box: put the old length back
      if (ev.type === 'change') el.value = S.emas[s].len;
      return;
    }
    if (S.emas[s].len === v) return;
    S.emas[s].len = v;
  } else if (el.dataset.emacolor == null) return;
  emaChanged();
}

function onEmaClick(ev) {
  const del = ev.target.closest('[data-emadel]'), set = ev.target.closest('[data-emaset]');
  if (set) return openEmaSettings(+set.dataset.emaset);
  if (del) removeEma(+del.dataset.emadel);
  else if (ev.target.closest('#emaAdd')) addEma();
}

// ---------- wiring ----------

function bindNumber(sel, key, min) {
  const el = $(sel);
  el.value = S[key];
  el.onchange = () => {
    const v = numOrNull(el.value);
    if (v == null || v < min) { el.value = S[key]; return; }
    S[key] = v;
    refreshOverlays();
    updatePanels();
    save();
  };
}

function onKey(e) {
  const el = e.target instanceof Element ? e.target : document.body;
  if (el.closest('input, select, textarea')) return;
  if ((e.metaKey || e.ctrlKey) && !e.altKey && ['z', 'Z', 'y'].includes(e.key)) {  // undo / redo drawings
    e.preventDefault();
    if (e.key === 'y' || e.shiftKey) redo(); else undo();
    return;
  }
  if (e.altKey && e.code === 'KeyR') {  // like TradingView's reset: replay candle, default zoom, auto scale
    e.preventDefault();
    return showReplayEdge({ bars: DEFAULT_ZOOM, gap: 5 });
  }
  if (e.metaKey || e.ctrlKey || e.altKey) return;
  if (el.tagName === 'BUTTON') el.blur();  // so Space does not also click the focused button
  if (e.key === 'ArrowRight') { e.preventDefault(); stopPlay(); stepOnce(); }
  else if (e.key === 'End') { e.preventDefault(); endReplay(); }
  else if (e.key === ' ') { e.preventDefault(); togglePlay(); }
  else if (e.key === 'Escape') {
    if ($('#drawSettings').classList.contains('open')) dialogCancel();
    else if ($('#help').classList.contains('open')) $('#help').classList.remove('open');
    else { closeMenu(); setMode(null); select(null); }
  } else if ((e.key === 'Delete' || e.key === 'Backspace') && selected) {
    e.preventDefault();
    deleteDrawing(selected);
  } else if (/^[1-5]$/.test(e.key)) setTf(TFS[+e.key - 1]);
}

function bindUi() {
  $$('#tfGroup button').forEach((b) => { b.onclick = () => setTf(b.dataset.tf); });
  $('#btnPlay').onclick = togglePlay;
  $('#btnStep').onclick = () => { stopPlay(); stepOnce(); };
  $('#btnEnd').onclick = endReplay;
  const speed = $('#speedSel');
  speed.innerHTML = SPEEDS.map((v) => `<option value="${v}">${v} bar${v === 1 ? '' : 's'}/s</option>`).join('');
  speed.value = String(S.speed);
  speed.onchange = () => { S.speed = +speed.value; save(); };
  const step = $('#stepSel');
  step.value = S.stepBy;
  step.onchange = () => { S.stepBy = step.value; save(); };
  $('#btnSelectBar').onclick = () => setMode(mode === 'select' ? null : 'select');
  $('#btnGoto').onclick = gotoInputTime;
  $('#gotoInput').onkeydown = (e) => { if (e.key === 'Enter') gotoInputTime(); };
  $('#btnRandom').onclick = randomJump;
  $$('#tools button[data-tool]').forEach((b) => { b.onclick = () => setMode(mode === b.dataset.tool ? null : b.dataset.tool); });
  $('#btnUndoDraw').onclick = undo;
  $('#btnClearDraw').onclick = () => {
    if (!S.drawings.length || !confirm('Remove all drawings?')) return;
    pushUndo();
    S.drawings = [];
    select(null);
    drawingsChanged();
  };
  $('#dbColors').innerHTML = PALETTE.map((c) => `<button data-color="${c}" style="background:${c}" title="${c}"></button>`).join('');
  $('#dbColors').onclick = (e) => { const b = e.target.closest('button[data-color]'); if (b) restyle('color', b.dataset.color); };
  $('#dbWidth').onchange = () => restyle('width', +$('#dbWidth').value);
  $('#dbStyle').onchange = () => restyle('style', $('#dbStyle').value);
  $('#dbSettings').onclick = () => { if (selected) openSettings(selected); };
  $('#dbClone').onclick = () => { if (selected) cloneDrawing(selected); };
  $('#dbLock').onclick = () => { if (selected) toggleLock(selected); };
  $('#dbDelete').onclick = () => { if (selected) deleteDrawing(selected); };
  $('#ctxMenu').onclick = (e) => {
    const b = e.target.closest('button[data-act]');
    if (!b || !selected) return;
    const d = selected;
    closeMenu();
    ({ settings: openSettings, clone: cloneDrawing, lock: toggleLock, delete: deleteDrawing })[b.dataset.act](d);
  };
  $('#dsOk').onclick = dialogOk;
  $('#dsCancel').onclick = dialogCancel;
  $('#dsRemove').onclick = dialogRemove;
  $('#drawSettings').onclick = (e) => { if (e.target.id === 'drawSettings') dialogCancel(); };
  $('#drawSettings').onkeydown = (e) => { if (e.key === 'Enter' && e.target.tagName !== 'BUTTON') dialogOk(); };
  $('#dsFields').addEventListener('input', onDialogInput);
  $('#dsFields').addEventListener('change', onDialogInput);
  $('#dsFields').addEventListener('click', onDialogClick);
  $('#lgEmas').addEventListener('click', onLegendClick);
  $('#btnAddEma').onclick = () => { const i = addEma(); if (typeof i === 'number') openEmaSettings(i); };
  document.addEventListener('pointerdown', (e) => { if (!e.target.closest('#ctxMenu')) closeMenu(); });
  const tz = $('#tzSel');
  tz.innerHTML = TZS.map(([id, name]) => `<option value="${id}">${name}</option>`).join('');
  tz.value = S.tz;
  tz.onchange = () => setTz(tz.value);
  $('#btnHelp').onclick = () => $('#help').classList.add('open');
  $('#toEdge').onclick = () => showReplayEdge(currentZoom(), 5);
  $('#btnTheme').onclick = () => applyTheme(THEME === 'dark' ? 'light' : 'dark');
  $('#help').onclick = (e) => { if (e.target.id === 'help' || e.target.closest('[data-close]')) $('#help').classList.remove('open'); };

  $$('#ordType button').forEach((b) => { b.onclick = () => { S.ordType = b.dataset.type; syncTicket(); save(); }; });
  $$('.pick').forEach((b) => { b.onclick = () => setMode(mode === 'pick' && pickField === b.dataset.pick ? null : 'pick', b.dataset.pick); });
  $('#sizeMode').onchange = () => { S.sizeMode = $('#sizeMode').value; syncTicket(); save(); };
  $('#inSize').oninput = () => {
    const v = numOrNull($('#inSize').value);
    if (v != null && v > 0) { if (S.sizeMode === 'risk') S.riskPct = v; else S.lots = v; save(); }
    updatePreview();
  };
  for (const f of ['#inPrice', '#inSL', '#inTP']) $(f).oninput = updatePreview;
  $('#btnBuy').onclick = () => placeOrder('buy');
  $('#btnSell').onclick = () => placeOrder('sell');

  buildEmaUi();
  $('#emaRows').addEventListener('input', onEmaInput);
  $('#emaRows').addEventListener('change', onEmaChange);
  $('#emaRows').addEventListener('click', onEmaClick);
  bindNumber('#setBal', 'balance0', 100);
  bindNumber('#setComm', 'commission', 0);
  bindNumber('#setSlip', 'slippage', 0);
  bindNumber('#setLot', 'lotSize', 0.0001);

  $$('.tabs button[data-tab]').forEach((b) => { b.onclick = () => showTab(b.dataset.tab); });
  $('#tabBody').addEventListener('click', onTableClick);
  $('#tabBody').addEventListener('change', onTableChange);
  $('#btnExport').onclick = exportCsv;
  $('#btnReset').onclick = resetSession;
  document.addEventListener('keydown', onKey);

  const day = (t) => new Date(t * 1000).toISOString().slice(0, 10);
  $('#dataInfo').textContent = `${META.name}: ${META.source}, ${META.price === 'bid' ? 'bid' : 'last'} prices. ` +
    `Replay ${fmtTime(F.t[0]).slice(0, 10)} → ${fmtTime(F.t[F.n - 1]).slice(0, 10)} (${F.n.toLocaleString()} five-minute bars)` +
    (D['1d'].d[0] < F.t[0] - 86400 ? `, daily history from ${day(D['1d'].d[0])}` : '') +
    `. Built ${META.built_utc} UTC. Add newer days with: ${META.update || 'the build script'}`;
  bindSymbolUi();
}

async function bindSymbolUi() {  // ticker menu, currency and lot labels, bid/ask or last-price quote
  document.title = `${SYMBOL} Replay`;
  localStorage.setItem('replay-symbol', SYMBOL);
  let symbols = [{ symbol: SYMBOL, name: META.name }];
  try { symbols = await (await fetchOk('data/symbols.json')).json(); } catch { /* one symbol only */ }
  const sel = $('#symbolSel');
  sel.innerHTML = symbols.map((x) => `<option value="${x.symbol}" title="${x.name}">${x.symbol}</option>`).join('');
  sel.value = SYMBOL;
  sel.onchange = () => { location.search = `?symbol=${encodeURIComponent(sel.value)}`; };
  $('#commUnit').textContent = `${META.ccy || '$'}/lot`;
  $('#slipUnit').textContent = META.slipUnit || '$/oz';
  $('#lotUnit').textContent = META.unit || 'units';
  $('#fillInfo').textContent = META.hasSpread === false
    ? 'No bid/ask in this data: buys and sells fill at the last price. Add slippage to cover costs.'
    : `Buys fill at the real ${META.source} ask, sells at the bid.`;
  if (META.hasSpread === false) {
    $('#qBidLbl').textContent = 'Last';
    $('#qAskBox').style.display = $('#qSprBox').style.display = 'none';
    $('.quote').style.gridTemplateColumns = '1fr';
  }
}

/* An update to the page or script while this tab is open shows a Reload banner. It compares
 * against the versions actually running (the script as loaded, the page as cached), not what
 * the server says at load time, so a copy served from the browser cache is caught too. */
const stampOf = (x) => Date.parse(x) || 0;

async function serverStamps() {
  const head = async (url) => stampOf((await fetch(url, { method: 'HEAD', cache: 'no-store' })).headers.get('Last-Modified'));
  return { app: await head('app.js'), page: await head(location.pathname), data: await head(`data/${SYMBOL}/meta.json`) };
}

async function watchForUpdates() {
  const running = { app: stampOf(window.APP_MODIFIED), page: stampOf(document.lastModified), data: stampOf(window.DATA_MODIFIED) };
  for (;;) {
    try {
      const now = await serverStamps();
      const newer = ['app', 'page', 'data'].some((k) => running[k] && now[k] > running[k] + 1000);
      if (newer) {
        $('#updateBar').style.display = 'flex';
        return;
      }
    } catch { /* offline or server stopped: nothing to compare against */ }
    await new Promise((r) => setTimeout(r, 15000));
  }
}

async function reloadFresh() {  // refresh the cached page and script first, or reload could reuse them
  try {
    await Promise.all([fetch(location.pathname + location.search, { cache: 'reload' }), fetch('app.js', { cache: 'reload' })]);
  } catch { /* reload anyway */ }
  location.reload();
}

async function init() {
  watchForUpdates();
  $('#updateReload').onclick = reloadFresh;
  try {
    if (!window.LightweightCharts) await loadScript(CDN_FALLBACK);
    LC = window.LightweightCharts;
    D = await loadData();
    F = D['5m'];
    loadState();
  } catch (err) {
    $('#loading').innerHTML = `Could not start: ${err.message}<br><small>Start it with <code>python replay/serve.py</code> and open the address it prints.</small>`;
    return;
  }
  cursor = S.cursorT != null
    ? clamp(upperBound(F.t, S.cursorT) - 1, 0, F.n - 1)
    : clamp(lowerBound(F.t, Date.UTC(2025, 0, 2, 8) / 1000), 0, F.n - 1);
  setupChart();
  volume.applyOptions({ visible: META.hasVolume !== false });
  bindUi();
  applyTheme(THEME);
  applyTfOptions();
  syncTicket();
  showTab('positions');
  renderFull(true);
  updatePanels();
  $('#gotoInput').value = toInputValue(F.t[cursor] + 300);
  $('#loading').remove();
}

init();
