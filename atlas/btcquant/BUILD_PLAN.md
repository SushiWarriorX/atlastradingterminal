# btcquant build plan (the owner's mission of 2026-11-15)

The owner asked for an autonomous Bitcoin quantitative research and paper trading system: strategy library, rigorous backtests, champion versus challenger, persistent paper accounts that record every trade on signal, daily reports, retained experiment history, and a daily run at 00:15 UTC. The rules are in `PROTOCOL.md` (pre-registered, version 1). **Anyone continuing the work (including an hourly cycle) takes the first unchecked step below, writes its tests first, and marks it done here with the commit.**

Code lives in `atlas/backend/atlas_api/btcquant/`, tests in `atlas/backend/tests/test_btcquant_*.py`, artifacts (data, state, reports, registry, strategy notes) in `atlas/btcquant/`.

## Steps

- [x] 0. Protocol written and pushed before any code (`PROTOCOL.md`).
- [ ] 1. Data layer: Coinbase BTC-USD daily and hourly download with paging, validation, complete-versus-incomplete candle flag, manifest, CSV storage; 4-hour candles built from complete hours; tests; first download committed.
- [ ] 2. Indicators (SMA, Wilder ATR and RSI, ADX, Bollinger, realised volatility) with hand-checked tests.
- [ ] 3. Account and execution engine (next-open fills, fee and slippage, 1% risk sizing, stops, armed re-entry, circuit breaker, weight mode) as one step function; tests including the accounting identity and gap and same-candle cases.
- [ ] 4. Strategy families 1 to 12 plus benchmarks, with `strategies/<family>.md` notes written first; tests including a future-perturbation test (signals never change when later candles change).
- [ ] 5. Metrics (all of section 6 of the protocol) with hand-worked tests.
- [ ] 6. Backtest runner by period, benchmarks, exposure-matched hold, full-exposure sensitivity, regimes; tests (buy-and-hold equals the price ratio less costs; cash is flat).
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
