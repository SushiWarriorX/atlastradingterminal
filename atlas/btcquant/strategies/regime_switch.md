# Trend versus ranging regime switch (`regime_switch`)

Protocol family 10 of 12 · category: regime · account kind: stop · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
Markets alternate between trending and ranging states. Follow the trend when it is strong and buy dips when it is not, and the combination does better than either part alone.

## Why it might work
- ADX is Wilder's (1978) gauge of trend strength; his rule of thumb treats readings above about 25 as a trend. Switching between a trend rule and a mean-reversion rule by an ADX threshold is a common practitioner design. I found no peer-reviewed evidence that it adds value, and its two parts are themselves weakly supported for Bitcoin.
- Its two branches resemble sma_cross (50/200) and bollinger_mr, so the duplicate check (position correlation of 0.90 or more) may flag it.

## Where it should work, and where it should fail
Markets that really do switch between clear trends and clear ranges. Fails because ADX is itself a lagging measure; the branch can change just when the market does, which causes churn.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- ADX(14) is Wilder's. If ADX > threshold ('trending'): the state is ON when SMA_50 > SMA_200. Otherwise ('ranging'): the state is ON when close < SMA_20 - 1.5 x sigma_20 (population standard deviation of the last 20 closes).
- There is no hysteresis: the state is re-evaluated at every close, so an entry in the ranging branch usually lasts a day or two. Enter at the next open when ON, flat and armed; exit at the next open when OFF or the stop is hit. Protective stop, fixed at entry: decision close - 3 x ATR(14).

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4).

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"adx": [20, 25, 30]}
Configurations: 3

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: churn at branch changes; two weak parts do not make a strong whole.
- Implementation: ADX needs 28 candles and SMA_200 needs 200, so the trend branch cannot fire before the 200th candle (the 2019 warm-up covers this). Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
A mixture of the behaviour of its two parts; probably no better than the better of them. Only 3 configurations, so little multiple-testing burden.

## Sources
Wilder (1978) for ADX; Brock, Lakonishok and LeBaron (1992) for moving averages; Bollinger (2001). Details, and what each source does and does not show, are in `SOURCES.md`.
