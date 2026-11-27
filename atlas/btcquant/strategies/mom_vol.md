# Momentum with a volatility filter (`mom_vol`)

Protocol family 6 of 12 · category: momentum · account kind: stop · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
Momentum is more reliable when volatility is not extreme. The crashes that wreck momentum strategies happen in high-volatility stretches, so switching momentum off above a volatility cap avoids the worst of them.

## Why it might work
- Barroso and Santa-Clara (2015) report that scaling momentum by its own recent volatility roughly doubled its Sharpe ratio (0.53 to 0.97) and nearly removed its crash risk in US stocks. Moreira and Muir (2017) find that volatility-managed equity portfolios improve Sharpe ratios.
- Cederburg, O'Doherty, Wang and Yan (2020) tested 103 equity strategies and found no systematic out-of-sample benefit from volatility management. The evidence is mixed and none of it is about Bitcoin.

## Where it should work, and where it should fail
Steady advances in calm markets. Fails because Bitcoin's volatility is high even in good times (often 40% to 80% a year), so a cap of 0.6 may keep the strategy out of most uptrends, and because volatility also rises on the way up.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- State ON when the return over L days is above zero AND the realised volatility (standard deviation of the last 20 daily returns, ddof 1, times the square root of 365) is at most the cap; otherwise OFF.
- Enter at the next open when ON, flat and armed; exit at the next open when OFF or the stop is hit. Protective stop, fixed at entry: decision close - 3 x ATR(14).

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4).

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"L": [30, 60, 90], "cap": [0.6, 0.8, 1.0]}
Configurations: 9

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: the cap removes the trending days that make momentum work; a volatility estimate from 20 days is noisy.
- Implementation: the volatility window ends at the decision candle; Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
Lower return and a shallower drawdown than tsmom with the same L. A cap of 0.6 may leave the account in cash for long periods ('too thin to judge').

## Sources
Barroso and Santa-Clara (2015); Moreira and Muir (2017); Cederburg, O'Doherty, Wang and Yan (2020). Details, and what each source does and does not show, are in `SOURCES.md`.
