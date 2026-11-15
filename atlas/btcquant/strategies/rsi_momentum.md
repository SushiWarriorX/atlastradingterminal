# RSI momentum (`rsi_momentum`)

Protocol family 5 of 12 · category: momentum · account kind: stop · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
A high RSI means persistent buying. Contrary to the textbook 'overbought' reading, strong readings in Bitcoin tend to continue, so enter on strength and leave when it fades.

## Why it might work
- The weakest-sourced family. The RSI is Wilder's (1978) indicator and its standard use is contrarian (above 70 is 'overbought'). Using it as a momentum trigger is a practitioner heuristic; I found no peer-reviewed test of it on Bitcoin.
- It is a close cousin of time-series momentum (an RSI above 50 means average gains beat average losses over the window), and it is included because the mission lists it. Treated as a hypothesis with little support, and it carries 18 of the 100 trials.

## Where it should work, and where it should fail
Strong, orderly advances. Fails in downtrends with sharp relief rallies (the RSI crosses 55 early in many small rallies) and in ranges, where the exit level is crossed often.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- RSI(n) is Wilder's. The state turns ON when RSI > enter (from OFF) and turns OFF when RSI < exit; between the two levels it keeps its previous value (hysteresis).
- Enter at the next open when the state is ON, flat and armed; exit at the next open when it turns OFF or the stop is hit. Protective stop, fixed at entry: decision close - 3 x ATR(14).

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4).

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"n": [14, 21], "enter": [55, 60, 65], "exit": [40, 45, 50]}
Configurations: 18

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: whipsaw in ranges; a threshold pair that works in one regime only; heavy multiple-testing burden.
- Implementation: RSI seeded with the simple average of the first n changes (tested by hand); Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
Behaves like a faster, noisier tsmom. Probably the least likely family to hold up outside the sample it is chosen on.

## Sources
Wilder (1978) for the indicator only. No peer-reviewed support found for this use. Details, and what each source does and does not show, are in `SOURCES.md`.
