# Volatility breakout (`vol_breakout`)

Protocol family 9 of 12 · category: volatility · account kind: stop · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
A one-day rise larger than k times the recent average daily range signals the start of a volatility expansion with an upward drift over the next several days.

## Why it might work
- Volatility clusters (large moves tend to follow large moves), and Williams (1999) and Crabel (1990) describe breakout entries scaled by the recent range for futures markets (Crabel's is intraday). A secondary source says Williams later wrote that the rule works less well than it used to; not checked against the book.
- Whether the direction continues after the shock is the whole hypothesis. I found no peer-reviewed support for this exact rule on Bitcoin.

## Where it should work, and where it should fail
Fresh news-driven moves that continue for a week or two. Fails when a large up day is followed by giving it back (Bitcoin often does), and the rule trades rarely at k = 2.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- At the close of candle i: close[i] - close[i-1] > k x ATR(14)[i-1] (the ATR of the previous candle, so the move being tested is not part of its own yardstick). Up moves only.
- The state is then ON for `hold` closes (ON at the closes of i, i+1, ... i+hold-1) and then OFF. While ON, new breakouts are ignored, and a breakout on the day a hold ends is ignored too. Protective stop, fixed at entry: decision close - 3 x ATR(14).

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4). After a large move the ATR is high, so the stop is wide and the position small.

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"k": [1.0, 1.5, 2.0], "hold": [5, 10, 20]}
Configurations: 9

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: reversal after a spike; few signals, so 'too thin to judge' is likely at k = 2.
- Implementation: the ATR must be the previous candle's, not the current one's (tested); Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
Few trades, a wide spread of outcomes, a Sharpe ratio that depends on a handful of events. Low chance of passing A1 or the promotion gates.

## Sources
Williams (1999) and Crabel (1990) as practitioner context; Liu and Tsyvinski (2021) for short-horizon momentum in crypto. Details, and what each source does and does not show, are in `SOURCES.md`.
