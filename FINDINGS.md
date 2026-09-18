# XAUUSD 5-minute research — final findings

**Bottom line: there is no profitable 5-minute strategy in this data.** Not at 1-hour
holds, not at 2-hour holds, not at 4-hour holds, long or short. The bid-ask spread is
larger than every directional edge that exists at these horizons, and has been for most
of the past decade.

Data: Dukascopy bid+ask, **828,668 five-minute bars, 2015-01-01 → 2026-09-09** (11.7
years), with a real per-bar spread column. Gold ranges $1,046 → $5,598 across the sample.

**Era split.** The strategy in §2 was designed on 2022-09 → 2025-06 and walked forward on
2025-07 → 2026-09. Extending the data back to 2015 created a **7.6-year holdout that was
never seen during design** — a far stronger test than any in-sample split. That test is
what settled the question.

Costs are modelled as **the actual quoted spread of the bar being traded, plus $0.10
slippage per side** — never an average.

---

## 1. Gold 5m direction is unpredictable

5m return autocorrelation is within **±0.012 at every lag 1–12, in every session block**.
No linear serial dependence.

The backtest engine was validated on random signals: it lost exactly the round-trip cost
(−$0.54 vs −$0.56 expected), so it carries no bias. Then eight classic families were run
across the **full 11.7 years**, with holds capped at 1h and 2h — 30 configurations:

| family | best avg $/trade | holdout | recent |
|---|---|---|---|
| ORB 12:00 UTC | −0.42 | −0.47 | −0.32 |
| ORB 13:30 UTC | −0.44 | −0.43 | −0.47 |
| Asia-range breakout → London | −0.48 | −0.53 | −0.39 |
| Fade extreme 30m move | −0.51 | −0.51 | −0.52 |
| ORB 07:00 UTC | −0.55 | −0.53 | −0.60 |
| Momentum ignition | −0.57 | −0.52 | −0.68 |
| Squeeze breakout | −0.61 | −0.59 | −0.65 |
| EMA20 pullback in trend | −0.63 | −0.64 | −0.63 |

**Profitable over 11.7 years: 0 of 30. Profitable in both eras: 0 of 30.** Every one loses
approximately the spread, in every era. These are not mistuned good ideas — they are noise
plus transaction costs.

This also confirms the earlier liquidity-sweep + Fibonacci rulebook result: its sweep was
negative in every cell. **That strategy has no edge. Retired.**

## 2. The overnight drift is real — and still too small to trade

Splitting all 11.7 years by hour (gap bars removed), the Asia-open window is genuinely the
best block, and by a wide margin:

| window (UTC) | share of bars | log return captured | positive years |
|---|---|---|---|
| **22:00–01:59 (Asia open)** | **15.6%** | **+54.5%** | **10 / 12** |
| 02:00–06:59 (Asia) | 21.8% | +22.6% | 7 / 12 |
| 17:00–21:59 (NY pm) | 18.5% | +13.2% | 6 / 12 |
| 07:00–11:59 (London) | 21.8% | −0.8% | 7 / 12 |
| 12:00–16:59 (NY overlap) | 21.8% | −13.1% | 5 / 12 |

Gold's total 12-year return is +76.3%, so the Asia window delivers **71% of all return from
15.6% of the clock**. The effect is real, robust, and economically sensible — it is the
standard close-to-open risk premium.

**It is still not tradeable.** With locked parameters:

| era | n | mean bp | t | Sharpe | total | max DD | win |
|---|---|---|---|---|---|---|---|
| **HOLDOUT 2015–2022** | 1581 | **−3.03** | **−5.53** | **−2.21** | **−47.9%** | −48.2% | 39.7% |
| DESIGN 2022–2025 | 585 | +0.94 | 0.99 | 0.65 | +5.5% | −4.4% | 50.1% |
| FWD 2025–2026 | 247 | +5.91 | 1.63 | 1.65 | +14.6% | −5.3% | 54.3% |
| **ALL 11.7y** | 2413 | **−1.15** | −2.02 | −0.65 | **−27.7%** | −51.6% | 43.7% |

Negative in **8 of 12 years**.

### Why: the cost line crossed the drift line

This is the whole story in one table — gross drift per session vs round-trip cost, both in
basis points, inside the Asia window:

| year | gold price | spread $ | cost bp | drift bp | drift ÷ cost |
|---|---|---|---|---|---|
| 2015 | 1,161 | 0.36 | 4.82 | 1.98 | 0.41 |
| 2016 | 1,256 | 0.36 | 4.46 | 3.09 | 0.69 |
| 2017 | 1,260 | 0.27 | 3.77 | 1.57 | 0.42 |
| 2018 | 1,267 | 0.26 | 3.61 | 3.03 | 0.84 |
| 2019 | 1,394 | 0.32 | 3.71 | 3.17 | 0.85 |
| 2020 | 1,777 | 0.63 | 4.67 | 4.92 | 1.05 |
| 2021 | 1,798 | 0.39 | 3.26 | 1.99 | 0.61 |
| 2022 | 1,800 | 0.42 | 3.45 | −2.11 | −0.61 |
| 2023 | 1,944 | 0.36 | 2.88 | 5.13 | **1.78** |
| 2024 | 2,395 | 0.41 | 2.56 | 2.84 | **1.11** |
| 2025 | 3,438 | 0.71 | 2.63 | 7.67 | **2.91** |
| 2026 | 4,546 | 0.90 | 2.42 | 13.03 | **5.39** |

Cost in **percentage** terms fell from 4.8bp to 2.4bp — not because spreads tightened, but
because **gold quadrupled while the dollar spread merely doubled**. At the same time the
drift itself grew during the bull market. The ratio crossed 1.0 only in 2023.

So the 4-year study was not wrong about the recent period. It was wrong to treat a
**price-level and volatility regime** as a persistent edge. Spreads are plausible
throughout (median $0.25–0.40 in 2015–19), so this is not a data artifact.

## 3. Short holds (your 1–2 hour constraint) are structurally worse

The drift accrues **roughly uniformly** across the window — ~0.1–0.7 bp per 30-minute
slice. Cost, however, is charged **once per trade regardless of duration**. So a shorter
hold takes proportionally less drift while paying the identical cost:

- Cumulative gross drift across eight 30-min slices: **2.33 bp**
- Total hurdle if traded as eight separate 30-min trades: **28.67 bp**
- Every single 30-min slice is net-negative.

Measured directly, with locked parameters:

| variant | hold | holdout mean bp | t | holdout total |
|---|---|---|---|---|
| full | 3.5 h | −3.03 | −5.53 | −47.9% |
| short | 2.0 h | −3.26 | −6.44 | −51.6% |
| one-hour | 1.0 h | −3.88 | −12.77 | −61.3% |

**The shorter the hold, the worse it gets** — monotonically, exactly as the arithmetic
predicts.

Exhaustive scans confirm there is no short-hold window anywhere in the session:

- **494 windows** at 1h and 2h holds, every start offset, 11.7 years: **0 net-positive.**
- **316 windows** at 1h–4h holds: **0 beat the hurdle on the holdout; 0 in both eras.**
- **0 shortable windows anywhere**, at any hold length.

A 1–2 hour gold trade needs to predict a move of **~2.5–4.8 bp** (about $1.00–$2.00 at
current prices) just to break even. Nothing in the price history predicts that.

## 4. Everything tested and rejected

| tested | verdict |
|---|---|
| 8 classic families × 30 configs, 11.7y, 1–2h holds | **0 profitable.** |
| AOD overnight drift, 3.5h hold | **Failed 7.6y holdout** (t = −5.53). |
| 2-hour and 1-hour variants | Worse, monotonically. |
| Sunday-session short (IS t = −2.81) | Failed OOS. Selection noise. |
| Low-vol filter (IS t = 2.06) | Failed OOS. |
| High-vol / trend filters | Inconsistent or weaker than unfiltered. |
| Vol-targeted position sizing | Hurt returns. |
| Dip entry inside the window | No structure; deeper dips did worse. |
| Second (London) leg | Sharpe 0.11. |
| ATR stops 1.0×–3.0× | All turned the drift edge negative. |
| Event study: spikes at 12:30/13:30/14:00 UTC | t ≤ 1.0. Noise. |
| Turn-of-month / day-of-month | n = 34/bucket, 22 buckets. Noise. |
| Time-series momentum 5–120d | Apparent Sharpe 5–7 is an artifact of overlapping windows and a 77%-long signal in a bull market. Beta, not skill. |

Three traps worth naming, because each nearly produced a fake strategy:

1. **The reopen gap.** The 22:00/23:00 UTC slots appeared to hold +23% of all return at
   double the normal spread. That is the price gap across the maintenance break, not
   tradeable drift. Removing those bars is what makes the rest trustworthy.
2. **Cost masquerading as a short edge.** Scanning *net* returns made short windows look
   superb (t = −6.2). That was just the spread — a long loses it and so does a short.
   Re-running on **gross** drift dissolved the effect entirely.
3. **A regime mistaken for an edge.** The one that actually fooled me for a full round of
   research. A 4-year sample that happens to sit inside a historic bull market will show a
   drift edge that 12 years does not support.

## 5. What I would actually do

1. **Do not trade any 5-minute gold system built on this data.** The spread eats every
   edge that exists. This is the honest answer to the original question.
2. **If you want to trade gold intraday, the binding constraint is execution, not signal.**
   Gross drift in the best window is currently ~13 bp/session against ~2.4 bp of cost. If
   you can get institutional spreads, that window is worth revisiting — but as a
   *cost-advantage* business, not a pattern-recognition one. Measure your broker's actual
   22:00–02:00 UTC spread before anything else.
3. **Longer horizons are where gold's edge lives.** Costs amortise over days, not hours.
   The same overnight premium at a weekly hold pays the spread once instead of 250 times a
   year. That is the direction with a real chance.
4. **A different input is needed for intraday.** Price history is exhausted here. Anything
   further would need an economic calendar, COT positioning, real yields, or ETF flows.
5. If you do revisit the recent regime, treat it as an explicit bet that gold stays above
   ~$3,000 with elevated overnight drift, size it small, and set a hard kill-switch on the
   drift÷cost ratio falling back below 1.0.

## Reproducing

```bash
./.venv/bin/python research/rerun2015.py     # era split, locked-param test, 316-window scan
./.venv/bin/python research/battery11y.py    # 8 families x 30 configs, 1-2h holds, 11.7y
./.venv/bin/python research/shorthold.py     # drift profile + 494-window short-hold scan
./.venv/bin/python research/diag.py          # the cost-vs-drift table above
./.venv/bin/python research/chart11y.py      # the chart
```
