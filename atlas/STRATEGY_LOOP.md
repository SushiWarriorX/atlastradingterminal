# Strategy loop (every 10 minutes)

Goal: add one new BTC trading RULE per cycle to the Strategy Lab, backtest it once, show it in the Strategy tracker section, and then follow it forward on new bars. Research only: nothing here places a trade or says "buy".

## Each cycle
1. Read `atlas/backend/atlas_api/btclab/tracker_ledger.json` (what is already tracked) and the QUEUE below. Take the first idea whose id is not in `strategies.py`.
2. Implement it in `atlas/backend/atlas_api/btclab/strategies.py` with the FIXED settings written in the queue. Use `hold(enter, leave)`. The position on bar i may only use bars up to i.
   Add a unit test with hand-checkable numbers for any new indicator and the no-look-ahead check (see `tests/test_tracker.py` for the pattern).
3. Backtest once, on all history, with the tracker: `cd atlas/backend && python3 -m atlas_api.btclab.track_cli add <id> --idea "..." --why "..."`. This freezes the result in the ledger. It refuses to rerun an id, on purpose.
4. Run `python3 -m pytest -q` (backend). If the UI changed, run the mobile and web checks as in `atlas/AGENT_NOTES.md`.
5. Update `atlas/IMPROVEMENT_LOG.md` (one short entry), commit the strategy, tests and ledger, push to `feature/research-modules`. Never merge.
6. Reply with a 3-line update: **strategy added** (name and one-line rule), **backtest** (whole history and last 30% versus holding BTC, worst drop, evidence label and the main reason), **where** (Strategy tracker: terminal BTC desk, Signal BTC page).

## Rules that keep this honest
- Settings come from the queue (the published or conventional values) and are never chosen by looking at BTC results. No trying variants of the same idea in one cycle, and no retuning a rule after seeing its result.
- A bad result is kept and reported exactly as it is. Never delete or hide a strategy because it did badly.
- Every strategy added makes the luck check stricter for every strategy (it counts the whole library). Say so when the library passes 30 rules. At 60 rules, stop and ask the user whether to continue.
- The backtest is a hypothesis; only the forward record counts as new evidence, and under 60 days it says nothing. Never claim a strategy "works" from the backtest. The evidence label is the tool's, not the loop's.
- Do not change `DEFAULT_FIVE` or `FINDINGS` in `strategies.py` unless the user asks.
- No secrets, no paid data. Spot daily bars from Coinbase only (perpetual funding does not cover the full history).

## QUEUE (fixed settings; first not yet in strategies.py goes next)
1. `adx_trend` ADX trend (Wilder, 1978): ADX(14) > 25 and +DI > -DI to enter; exit when +DI < -DI.
2. `psar_trend` Parabolic SAR (Wilder, 1978; 0.02 step, 0.2 max): long while the close is above the SAR; exit when below.
3. `ichimoku_cloud` Ichimoku cloud (9, 26, 52): long while the close is above both cloud lines (cloud shifted forward 26 bars, no peeking); exit when below the cloud.
4. `tsmom_12_1` Time-series momentum (12 minus 1): long while the return from 365 bars ago to 30 bars ago is positive.
5. `keltner_breakout` Keltner channel: enter on a close above EMA(20) + 2 x ATR(10); exit on a close below EMA(20).
6. `vortex_cross` Vortex indicator (14): long while VI+ > VI-.
7. `stoch_uptrend` Stochastic pullback in an uptrend: %K(14,3) crosses up through 20 while close > SMA(200); exit when %K > 80.
8. `mfi_reversion` Money Flow Index(14): enter below 20; exit above 70.
9. `cci_trend` CCI(20): enter above +100; exit below 0.
10. `obv_trend` On-balance volume trend: long while OBV is above its 50-bar average and the close is above SMA(50).
11. `mayer_cap` Mayer multiple cap: long while close > SMA(200) and close / SMA(200) < 2.4 (stand aside when stretched).
12. `pi_cycle` Pi Cycle: stand aside from when SMA(111) crosses above 2 x SMA(350) until it crosses back below; otherwise long.
13. `heikin_trend` Heikin-Ashi trend: enter after two consecutive green Heikin-Ashi candles with no lower wick; exit on a red one.
14. `trix_cross` TRIX(15) crossing its 9-bar signal line.
15. `nr7_breakout` NR7: after the narrowest daily range of 7 bars, enter on a close above that bar's high; exit on a close below its low.
16. `kama_trend` Kaufman adaptive average (10, 2, 30): long while the close is above KAMA.
17. `hull_trend` Hull moving average (55): long while it is rising.
18. `zscore_momentum` 90-bar return z-score (against the past 365 bars) above +1 to enter; below 0 to exit.
19. `elder_bull` Elder-ray bull power (13): long while EMA(13) is rising and bull power (high minus EMA) is positive and rising.
20. `donchian_mid` Donchian midline (50): long while the close is above the midpoint of the 50-bar high and low.
