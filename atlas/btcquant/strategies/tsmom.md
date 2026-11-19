# Time-series momentum (`tsmom`)

Protocol family 4 of 12 · category: momentum · account kind: stop · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
If Bitcoin's own return over the past L days is positive, its return over the following days is more likely positive than negative (time-series momentum).

## Why it might work
- Moskowitz, Ooi and Pedersen (2012) found that the sign of an asset's own past return over 1 to 12 months predicted its next return in 58 futures markets, with partial reversal at longer horizons. Hurst et al. (2017) extend the evidence back about a century. Liu and Tsyvinski (2021) report momentum in Bitcoin, Ripple and Ethereum at daily and weekly horizons.
- Those papers use volatility scaling, short positions and many markets. This family is long-only, unscaled and Bitcoin only, which limits what they can tell us (Kim, Tse and Wald, as summarised by Quantpedia, report that much of the original alpha depends on the scaling; journal details not checked).

## Where it should work, and where it should fail
Persistent trends. Fails in sideways markets, where the sign of the return flips often (L = 30 in particular), and at turning points (L = 365 reacts very slowly).

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- State ON when close[i] / close[i-L] - 1 > 0, otherwise OFF. Nothing is used before L + 1 closes exist.
- Enter at the next open when the state is ON, flat and armed; exit at the next open when the state turns OFF or the stop is hit. Protective stop, fixed at entry: decision close - 3 x ATR(14).

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4).

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"L": [30, 60, 90, 180, 365]}
Configurations: 5

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: trades on tiny positive returns are noise; short L overtrades, long L is too late.
- Implementation: Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
L = 30 trades often and loses to costs; L = 180 and 365 trade rarely ('too thin to judge'). Return below buy-and-hold.

## Sources
Moskowitz, Ooi and Pedersen (2012); Hurst, Ooi and Pedersen (2017); Liu and Tsyvinski (2021); Kim, Tse and Wald (as summarised by Quantpedia). Details, and what each source does and does not show, are in `SOURCES.md`.
