# Donchian breakout (`donchian`)

Protocol family 2 of 12 · category: trend · account kind: stop (trailing stop) · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
A close above the highest high of the previous N days is a breakout from a trading range. Breakouts tend to start moves that last days to weeks, and a trailing stop lets the strategy ride the move while limiting what it gives back.

## Why it might work
- This is the entry idea of the Turtle traders (20 and 55 day breakouts, Faith 2007) and the 'trading range break' rule of Brock et al. (1992). Of seven trend rules tested on Bitcoin from 2010 to 2019, the trading range breakout showed the clearest forecasting power (Gerritsen et al. 2020).
- Zarattini, Pagani and Barbon (2025) report a Sharpe ratio above 1.5 for an ensemble of Donchian models across up to 20 coins with volatility-based sizing. Ours is a single lookback on Bitcoin alone with 1%-risk sizing, so their numbers do not transfer.

## Where it should work, and where it should fail
When a quiet range ends in a sustained move. Fails with false breakouts (a close above the old high that reverses at once, so the stop is hit soon after) and when price drifts up and then crashes through the stop (the fill is at the gap price, worse than the stop).

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- Entry signal at the close of candle i: close > the highest high of the previous N candles (candle i itself is not included).
- The state is ON from the entry until the stop is touched. Protective stop: the lowest low of the last N/2 candles including candle i (N/2 is whole-number division, so N = 55 gives 27), recomputed at every close and raised, never lowered. It is checked against each later candle's low.
- If the stop is touched the position leaves at the stop price (or at the open when the candle opens below it). The state is OFF at that close; a new breakout can start a new entry from the next close on. There is no other exit.

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4). The stop can be far from the entry (a 40-day low may be 25% below), which makes the position small: 1% divided by 25% is 4% of equity.

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"N": [20, 40, 55, 80]}
Configurations: 4

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: false breakouts; far stops give tiny positions; slow lookbacks (55, 80) make few trades and will often be 'too thin to judge'.
- Implementation: the stop replayed inside the signal code must match the stop the account uses (tested); a stopped-out state may not re-enter on the same candle. Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
Fewer, longer trades than sma_cross (roughly 20 to 35 trades over five years at N = 20, under 10 at N = 80). Return below buy-and-hold. Higher chance than most families of a small positive Sharpe; low chance of passing the promotion gates.

## Sources
Faith (2007); Brock, Lakonishok and LeBaron (1992); Gerritsen et al. (2020); Zarattini, Pagani and Barbon (2025); Park and Irwin (2007). Details, and what each source does and does not show, are in `SOURCES.md`.
