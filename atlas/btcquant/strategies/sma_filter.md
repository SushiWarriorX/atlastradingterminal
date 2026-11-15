# Simple trend filter exposure (`sma_filter`)

Protocol family 12 of 12 · category: risk_managed · account kind: weight · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
Holding Bitcoin only while it is above its long-term average, and cash otherwise, keeps most of the upside and avoids most of the large drawdowns.

## Why it might work
- This is the trend-filter timing rule of Faber (2007), tested there on monthly data across asset classes, and the moving-average rule of Brock et al. (1992). Hurst et al. (2017) give the long-run case for trend following in general.
- Not specific to Bitcoin. A 200-day average on daily data only approximates Faber's 10-month rule.

## Where it should work, and where it should fail
Large bull markets and large bear markets (in cash during the bear). Fails in ranges, where the price crosses the average repeatedly and each crossing costs 0.30% on 100% of equity.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- Target weight at each close: 1 if close > SMA_L, else 0 (nothing before L closes exist). A new order is created whenever the target changes (a change from 0 to 1 is larger than the 0.10 band). It trades the whole position at the next open. No stop.

## Position sizing
Weight mode: 100% of equity when ON, flat when OFF. No 1% rule, so the exposure is 100% and costs are paid on the whole account; this is the family most exposed to the 15% breaker.

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"L": [100, 150, 200, 250]}
Configurations: 4

## Costs and risk limits
Fee 0.10% and slippage 0.05% on the amount traded at each rebalance; four cost settings in the sensitivity runs. Exempt from the 1% rule because the exposure itself is the risk control; capped at 100% of equity, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off).

## Failure modes
- Idea: whipsaws around the average; a slow exit after a sharp fall; full exposure means a crash from a high can be 15% or more before the filter turns.
- Implementation: Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
Return below buy-and-hold in a strong bull market, drawdown shallower than buy-and-hold's. L = 250 will probably be 'too thin to judge'.

## Sources
Faber (2007); Brock, Lakonishok and LeBaron (1992); Hurst, Ooi and Pedersen (2017). Details, and what each source does and does not show, are in `SOURCES.md`.
