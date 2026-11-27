# Bollinger band mean reversion (`bollinger_mr`)

Protocol family 7 of 12 · category: mean_reversion · account kind: stop · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
After a close well below its recent average (more than k standard deviations), Bitcoin tends to snap back toward that average within days, because short-term selling overshoots.

## Why it might work
- Bollinger (2001) describes the bands as a way to judge whether prices are high or low relative to their own recent history. Short-term reversal exists in some markets, but I found no solid peer-reviewed evidence that this rule is profitable in Bitcoin after costs, and Park and Irwin (2007) found contrarian technical rules less supported than trend rules.
- Included because the mission lists mean reversion. The prior is weak.

## Where it should work, and where it should fail
Ranging markets with sharp, short selloffs. Fails in downtrends (every oversold close is followed by lower prices) and when costs of 0.30% a round trip eat a bounce of a few percent.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- Middle band = SMA_n(close); sigma_n = population standard deviation of the last n closes; lower band = middle - k x sigma_n.
- The state turns ON when the close is below the lower band and OFF when the close is at or above the middle band; in between it keeps its value. Enter at the next open when ON, flat and armed; exit at the next open when OFF or the stop is hit. Protective stop, fixed at entry: decision close - 3 x ATR(14).

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4).

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"n": [20, 30], "k": [1.5, 2.0, 2.5]}
Configurations: 6

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: catching a falling knife; the 3 ATR stop caps each loss at about 1% of equity but repeated stops add up.
- Implementation: population (not sample) standard deviation, as stated; Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
Profitable in ranges, losing in declines; after costs probably negative overall (the protocol's stated expectation for mean-reversion families).

## Sources
Bollinger (2001); Park and Irwin (2007). Details, and what each source does and does not show, are in `SOURCES.md`.
