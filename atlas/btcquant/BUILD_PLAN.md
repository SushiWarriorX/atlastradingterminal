# btcquant build plan (the owner's mission of 2026-11-15)

The owner asked for an autonomous Bitcoin quantitative research and paper trading system: strategy library, rigorous backtests, champion versus challenger, persistent paper accounts that record every trade on signal, daily reports, retained experiment history, and a daily run at 00:15 UTC. The rules are in `PROTOCOL.md` (pre-registered, version 1). **Anyone continuing the work (including an hourly cycle) takes the first unchecked step below, writes its tests first, and marks it done here with the commit.**

Code lives in `atlas/backend/atlas_api/btcquant/`, tests in `atlas/backend/tests/test_btcquant_*.py`, artifacts (data, state, reports, registry, strategy notes) in `atlas/btcquant/`.

## Steps

- [x] 0. Protocol written and pushed before any code (`PROTOCOL.md`).
- [x] 1. Data layer (`btcquant/data.py`, 24 tests): Coinbase BTC-USD daily and hourly download with paging, validation, complete-versus-incomplete candle flag, manifest (`btcquant/data/manifest.json`), CSV storage; 4-hour candles built from complete hours; first download committed 2026-11-15: 2,875 daily candles 2019-01-01 to 2026-11-14 with no gaps, 68,990 hourly candles with 9 reported gaps (1 to 5 missing hours each, never filled).
- [x] 2. Indicators (`btcquant/indicators.py`, 10 tests with hand-worked numbers).
- [x] 3. Account and execution engine (`btcquant/account.py`, 30 tests; 41 deliberate breakages each caught by a failing test, run clean): next-open fills, fee and slippage, 1% risk sizing, stops, armed re-entry, circuit breaker, weight mode, as one step function with a signal-time order ledger.
- [x] 4. Strategy families 1 to 12 plus benchmarks as code (`btcquant/strategies.py`, 54 tests; 47 deliberate breakages each caught), with `strategies/<family>.md` notes and `SOURCES.md` pushed first (commit 420babb, protocol v1.1) and a future-perturbation test over all 100 configurations. Nothing has been run on real data.
- [x] 5. Metrics (`btcquant/metrics.py`, 20 tests with hand-worked numbers; 48 deliberate breakages each caught): every number of protocol section 6, regimes with their equality boundaries, the exposure-matched hold with costs.
- [x] 6. Backtest runner (`btcquant/backtest.py`, 19 tests; 32 deliberate breakages each caught): periods on the calendar, benchmarks, exposure-matched hold, full-exposure and cost sensitivities, regimes, circuit-breaker cool-off; no look-ahead from the runner's point of view.
- [ ] 7. Validation: selection with neighbour smoothing, parameter stability, walk-forward, cost sensitivity, deflated Sharpe, random-timing null, gates; tests including boundaries.
- [ ] 8. Registry: candidate log with spec hash and duplicate check, champions and challengers, freeze guard, holdout log.
- [ ] 9. Paper engine with persistent state, ledger on signal, idempotent daily processing, catch-up after missed days; parity test with the backtest.
- [ ] 10. Daily runner (`python -m atlas_api.btcquant.daily`), markdown report, `dashboard.json`.
- [ ] 11. First full research run, once, under the protocol; results and honest conclusion in the report; challengers admitted by the gates start their paper accounts.
- [ ] 12. Schedule (00:15 UTC), loop documents, a Signal card for the paper accounts.
- [ ] 13. Research queue: new hypotheses found online, each checked for being genuinely new (position-series correlation under 0.90) and pre-registered before running.

## Rules for continuing

- Never run a family or a candidate before its protocol entry and note exist and are pushed.
- Never change a family after its VALIDATION or TEST result is seen; make a new version.
- Mutation-check the accounting and the gates (break one comparison, expect a failing test).
- Say plainly what is not verified. Do not claim anything makes money.
