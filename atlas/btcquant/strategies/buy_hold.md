# Buy and hold (benchmark) (`buy_hold`)

Protocol benchmark B1 · account kind: hold · written 2026-11-15, before any run.

## Purpose
The standard every other row is compared with. It is not a strategy being tested for an edge.

## Rules
At the first open of the period, convert all cash to Bitcoin (one entry; fee 0.10% and slippage 0.05% on that one purchase) and never trade again. No stop, no circuit breaker.

## Why it is a hard benchmark
Over 2020 to 2024 Bitcoin rose by a large multiple, so buy-and-hold has a very high return and Sharpe ratio in that window. A strategy that is in the market less will almost always have a smaller return; the report therefore also compares risk-adjusted numbers and an exposure-matched hold.

## Failure modes
None as a rule. The risk is the benchmark's own: drawdowns of 50 to 80% in a bear market.

## Expectation
Beats nearly every family on total return over the whole period; loses on drawdown.

## Sources
None needed.

## Parameters
Grid: {}
Configurations: 1
