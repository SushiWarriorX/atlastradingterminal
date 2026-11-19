# Volatility-targeted exposure (`vol_target`)

Protocol family 11 of 12 · category: risk_managed · account kind: weight · written 2026-11-15, before any run of this family; no result of it has been looked at.

## Hypothesis
Holding a fraction of equity that shrinks when recent volatility is high and grows when it is low keeps risk roughly constant. If returns do not rise with volatility, that raises the Sharpe ratio and cuts the worst drawdowns.

## Why it might work
- Moreira and Muir (2017) and Harvey et al. (2018) report better Sharpe ratios and fewer extreme returns for volatility-managed or volatility-targeted portfolios of equities and other risk assets; Harvey et al. found no Sharpe gain for commodities. Cederburg et al. (2020) found no systematic out-of-sample benefit in 103 equity strategies. Mixed evidence, none about Bitcoin.
- Bitcoin's volatility (often 40% to 90% a year) is usually at or above the targets used here (30% to 50%), so the weight sits mostly between about 0.4 and 1.0 for a target of 0.40: this is a way of staying invested and sizing down in stress, not a timing rule.

## Where it should work, and where it should fail
Bitcoin's volatility spikes in crashes, so the weight shrinks as damage happens (with a lag). Fails when volatility is high on the way up (the weight is small in a rally) and when a crash comes out of calm.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- Target weight at each close = min(1, target / realised volatility over `window`), where realised volatility is the standard deviation (ddof 1) of the last `window` daily returns times the square root of 365.
- A new order is created only when the target differs from the last target by more than 0.10 (the rebalance band); it trades the difference at the next open. No stop.

## Position sizing
Weight mode: exposure is the target weight. No 1% rule. Never above 100%.

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"target": [0.3, 0.4, 0.5], "window": [20, 40]}
Configurations: 6

## Costs and risk limits
Fee 0.10% and slippage 0.05% on the amount traded at each rebalance; four cost settings in the sensitivity runs. Exempt from the 1% rule because the exposure itself is the risk control; capped at 100% of equity, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off).

## Failure modes
- Idea: the lag of the volatility estimate; holding 40 to 100% of equity in Bitcoin means drawdowns of 20 to 60% are possible, so the 15% breaker will trip and the cool-off matters.
- Implementation: the weight at close i may use only returns up to i (tested); the band must be measured from the last TARGET, not from the achieved weight. Using the unfinished candle; an indicator that includes the candle being decided on (guarded by a test that changes later candles and checks that no earlier signal moves); a fill before the open; a gap through the stop filled at the stop instead of the open (tested).

## Expectation written down before running
Return between cash and buy-and-hold; drawdown smaller than buy-and-hold's but far larger than the 15% limit; Sharpe close to buy-and-hold's. This is the family most likely to behave like a scaled-down version of the benchmark.

## Sources
Moreira and Muir (2017); Harvey et al. (2018); Cederburg, O'Doherty, Wang and Yan (2020); Barroso and Santa-Clara (2015). Details, and what each source does and does not show, are in `SOURCES.md`.
