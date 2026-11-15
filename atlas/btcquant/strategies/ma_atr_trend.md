# Moving-average trend filter with ATR exit (`ma_atr_trend`)

Protocol family 3 of 12 · category: trend · account kind: stop (trailing stop) · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
Bitcoin above its long average is in an uptrend. Staying in until a volatility-scaled trailing stop is hit, instead of until the price merely falls back under the average, keeps most of a trend and cuts a failing trade early when volatility is low.

## Why it might work
- A trend filter on a long average is the best-documented timing rule: Faber (2007) holds an asset only while it is above its 10-month average, and Hurst, Ooi and Pedersen (2017) trace trend following across 67 markets and about a century. ATR trailing stops (Wilder 1978) scale the exit to current volatility.
- None of this is specific to Bitcoin, and all of it is mostly about assets with much lower volatility.

## Where it should work, and where it should fail
Sustained uptrends with moderate pullbacks. Fails when the stop is tight relative to Bitcoin's normal swings (m = 2 is stopped out of healthy uptrends and then waits for a dip under the average before it can re-enter) and in ranges.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- Entry at the next open when the close is above SMA_L, the account is flat and armed. Armed at the start and again whenever a close is at or below SMA_L.
- Stop candidate at each close: close - m x ATR(14). At entry the stop is that candidate; afterwards it is raised to each higher candidate, never lowered.
- Exit when the stop is touched (stop price, or the open if it gapped below). After a stop-out the strategy needs a close at or below SMA_L before it can enter again.

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4). The stop distance is m x ATR: about 6% for m = 2 (a position near 16% of equity) and about 12% for m = 4 (near 8%).

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"L": [100, 150, 200], "m": [2, 3, 4]}
Configurations: 9

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: stop too tight (whipsaw) or too loose (gives back a large part of the trend); waiting for a close under the average after a stop-out can miss a quick recovery.
- Implementation: the replayed trailing stop must match the account's (tested); the armed flag must reset exactly when the close is at or below the average. Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
Fewer trades than sma_cross, return below buy-and-hold, part of the largest drawdowns avoided. L = 200 will probably be 'too thin to judge'. Low chance of passing the promotion gates.

## Sources
Faber (2007); Hurst, Ooi and Pedersen (2017); Wilder (1978); Park and Irwin (2007). Details, and what each source does and does not show, are in `SOURCES.md`.
