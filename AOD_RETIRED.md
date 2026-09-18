# ❌ RETIRED — AOD failed its holdout. DO NOT TRADE THIS.

> **Verdict (2026-09-10):** tested on 11.7 years (2015-01 → 2026-09) instead of 4.
> On the 7.6-year holdout it never saw during design, AOD returns **−3.03 bp/session,
> t = −5.53, Sharpe −2.21, −47.9% cumulative, −48.2% max drawdown**, win rate 39.7%.
> Negative in **8 of 12 years**. The 2h and 1h variants are worse.
>
> The overnight drift is real, but for most of the past decade it was **smaller than the
> bid-ask spread**. It only cleared costs in 2023–2026 because gold quadrupled (shrinking
> percentage costs) while the drift itself grew. That is a regime, not an edge.
>
> Kept only as a record of what was tested. See `FINDINGS.md` §2.

---

*Original specification below — superseded.*

**Status: candidate, not validated. Paper-trade before risking money.** See `FINDINGS.md`
for the statistics and the honest case against it.

## The idea

Gold earns a positive drift in the thin hours right after the COMEX daily settlement
break, when liquidity and risk-bearing capacity are lowest. This is the standard
overnight / close-to-open risk premium. It is the only effect in four years of 5m gold
data that clears the bid-ask spread and keeps the same sign in and out of sample.

## Rules

| | |
|---|---|
| **Instrument** | XAUUSD, 5-minute bars |
| **Direction** | **LONG ONLY** — never short |
| **Session anchor** | the daily **reopen** = first bar after a >10 min hole in the tape |
| **Entry** | buy at the open of bars **k = 2, 3, 4** after the reopen (3 equal slices) |
| **Exit** | sell at the open of bars **k = 36, 42, 48** after the reopen (3 equal slices) |
| **Stop loss** | **NONE** |
| **Filters** | none, except: **skip the Sunday-night reopen** |
| **Skip** | any session with fewer than 200 bars (half-days, broken tape) |

Nine legs in total (3 entries × 3 exits), each 1/9 of the position. This averages over the
parameter plateau instead of betting on one cell.

In IST that is roughly **buy 03:40–03:50, sell 06:30–07:30**. The exact clock time shifts
with US daylight saving, which is why the rules anchor to the reopen and not to a clock.

### Why there is no stop loss

Every ATR stop tested (1.0×, 1.5×, 2.0×, 3.0×) turned the edge **negative**:

| stop | mean bp/trade | win rate |
|---|---|---|
| none | **+2.41** | 51% |
| 3.0 × ATR | −1.27 | 36% |
| 2.0 × ATR | −1.39 | 26% |
| 1.5 × ATR | −1.79 | 20% |
| 1.0 × ATR | −1.82 | 13% |

The edge is a smooth drift, not a directional call. A stop converts ordinary noise into
realised losses and truncates the winners that pay for them. **Risk is controlled by
position size, not by a stop.**

This is the opposite of retail doctrine, and it is the single most important rule here.
If you cannot hold a position without a stop, do not trade this.

### Why long only

396 intraday windows were scanned. Only 2 had a gross drift negative enough to clear the
spread on the short side, and neither held out of sample. **There is no short edge in the
intraday gold clock.**

## Risk and sizing

Unlevered (1× notional) the strategy returned **+20.0% over 4 years** with a **−5.3% max
drawdown** and only **9.4% time in market**.

Position size is the only risk control. Because there is no stop, a single session's loss
is unbounded in principle — the worst observed session was **−349 bp (−3.5%)** of notional.

| leverage | ~annual return | ~max DD (backtest) | tail-session loss |
|---|---|---|---|
| 1× | 5% | 5% | 3.5% |
| 3× | 15% | 16% | 10% |
| 5× | 25% | 27% | 17% |

**Do not exceed 3×** until the strategy has produced live results. Gold gapped 8%+ intraday
in 2026; a 5× position through one of those is an account-ending event.

## Operating notes

- **Automate it.** Entries are ~03:40 IST. Manual execution is not realistic.
- **Costs are half the edge.** Gross drift is ~3.5 bp; round-trip cost is ~2.6 bp on the
  Dukascopy spread. On a broker 0.20 wider, the edge roughly halves. **Broker choice
  matters as much as the signal.** Check your actual XAUUSD spread at 22:00–02:00 UTC
  before trading this.
- **Use limit orders.** Entry is not urgent. Resting the buy at the touch rather than
  crossing lifted backtest Sharpe from 1.09 to 1.65. Treat that as an upper bound —
  passive fills carry adverse selection the backtest cannot see.
- **Watch swaps.** The position is closed before the next break, so there is no overnight
  financing. Do not let a leg run past its exit.

## Kill switches

Stop trading and re-examine if any of these trigger:

1. Rolling 100-session mean return goes negative.
2. Drawdown exceeds **2×** the backtested max (i.e. >11% unlevered).
3. Your broker's 22:00–02:00 UTC round-trip cost exceeds **$0.90** — the edge is gone.
4. 12 months pass with no new equity high.

## Files

```
src/aod.py           strategy core (session marking, signals, portfolio, stats)
src/aod_signal.py    live daily plan + last-N-session audit
research/            the full research trail, including everything that failed
out/research/        equity curve, session-level results
```

```bash
./.venv/bin/python src/aod_signal.py            # today's plan
./.venv/bin/python src/aod_signal.py --last 20  # audit recent sessions
```
