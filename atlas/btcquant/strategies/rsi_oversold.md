# RSI oversold reversal (`rsi_oversold`)

Protocol family 8 of 12 · category: mean_reversion · account kind: stop · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
A very low RSI marks an exhausted selloff; Bitcoin tends to rebound over the following days.

## Why it might work
- Connors and Alvarez (2009) describe a short-term RSI(2) system for US stocks (buy when RSI(2) is very low while the price is above its 200-day average, sell when the price recovers above its 5-day average). That is practitioner evidence, not peer reviewed, in a different market, and the book was not read in full for this note.
- This family has no trend filter and uses other lengths and thresholds, so it is NOT their system. It is the plain contrarian reading of Wilder's (1978) indicator.

## Where it should work, and where it should fail
Ranging markets and shallow pullbacks inside uptrends. Fails in crashes, where RSI(7) stays below 25 for days while price keeps falling; oversold readings cluster in exactly those stretches.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- The state turns ON when RSI(n) < enter and OFF when RSI(n) > exit; in between it keeps its value. Enter at the next open when ON, flat and armed; exit at the next open when OFF or the stop is hit. Protective stop, fixed at entry: decision close - 3 x ATR(14).

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4).

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"n": [7, 14], "enter": [20, 25, 30], "exit": [50, 55]}
Configurations: 12

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: as for bollinger_mr; also strongly correlated with it (both buy weakness), so a duplicate check applies.
- Implementation: Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
After costs probably negative; any good result is more likely a lucky few trades than an edge.

## Sources
Wilder (1978) for the indicator; Connors and Alvarez (2009) as the practitioner context only. Details, and what each source does and does not show, are in `SOURCES.md`.
