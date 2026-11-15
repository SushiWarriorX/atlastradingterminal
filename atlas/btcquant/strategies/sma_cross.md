# Moving-average crossover (`sma_cross`)

Protocol family 1 of 12 · category: trend · account kind: stop · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
When the average of the last `fast` closes is above the average of the last `slow` closes, Bitcoin has been rising for long enough that holding it over the following days and weeks has a better expected outcome than staying in cash.

## Why it might work
- Prices can trend because information, capital and attention reach a market gradually (herding, slow-moving funds, people chasing a rising price). A crossover is a delayed, noise-reducing way to notice a trend.
- Published tests of moving-average rules found predictive power in US stocks (Brock, Lakonishok and LeBaron 1992) and in Bitcoin (Gerritsen et al. 2020; Hudson and Urquhart 2021). None of those tests is this test: the data, rules, costs and periods differ, and Park and Irwin (2007) warn that much of this literature suffers from data snooping and understated costs.

## Where it should work, and where it should fail
Long steady advances (it is in) and long declines (it is out). Fails in sideways, choppy markets (many crossovers, each losing a little, plus 0.30% costs on the amount traded) and after sharp reversals (both averages lag, so it leaves only after a sizeable fall).

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- State ON when SMA_fast(close) > SMA_slow(close), both fully formed (nothing is used before `slow` closes exist); otherwise OFF.
- Enter at the next open when the state is ON, the account is flat and armed. Exit at the next open when the state turns OFF, or when the protective stop is hit.
- Protective stop, fixed at entry: decision close - 3 x ATR(14).

## Position sizing
Stop-based: quantity = the smaller of (1% of strategy equity divided by (entry fill - stop)) and (100% of equity, fee reserved). With a 3 ATR stop on Bitcoin that is typically 7 to 15% of equity, so raw returns are small by construction. Every report also shows the same signals at full exposure and an exposure-matched hold (protocol section 4).

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"fast": [10, 20, 30, 50], "slow": [50, 100, 150, 200]}
Configurations: 15

## Costs and risk limits
Fee 0.10% and slippage 0.05% on each side, also on stop fills; four cost settings in the sensitivity runs (protocol section 3). Planned loss at the stop 1% of strategy equity, exposure never above 100%, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off, protocol section 4). A stop fills at the stop price, or at the open when a candle opens below it.

## Failure modes
- Idea: whipsaws in ranges; late exits; 15 near-copies of one idea (all 15 count as trials anyway); the slow pairs make only a handful of trades, so they will often be 'too thin to judge'.
- Implementation: Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
Positive but lower total return than buy-and-hold over 2020 to 2024. The fast pairs lose to costs in choppy stretches. A smaller worst drawdown than the same exposure held constantly only if exits come early. Chance that any configuration passes the promotion gates: low.

## Sources
Brock, Lakonishok and LeBaron (1992); Gerritsen, Bouri, Ramezanifar and Roubaud (2020); Hudson and Urquhart (2021); Park and Irwin (2007). Details, and what each source does and does not show, are in `SOURCES.md`.
