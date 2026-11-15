# Research run, protocol 1.2, data to 2026-11-14

Run once on 2026-11-15T10:34:08Z UTC on 2,875 daily BTC-USD candles (2019-01-01 to 2026-11-14, Coinbase; hash `c9cb205d1d501e6a`). Everything below is a simulation on past prices. It is not a recommendation and nothing in it shows that any rule will make money.

## Headline

**No family was admitted.** Every family either had too few trades to judge or failed at least one admission gate. The main portfolio stays in cash, and no challenger account was opened.

## Families

| family | chosen on TRAIN | outcome | trades | TRAIN Sharpe | VALIDATION Sharpe | info ratio TRAIN / VALIDATION | VALIDATION timing p | stable | failed gates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `sma_cross` | {"fast": 10, "slow": 50} | **rejected** | 21 | 1.12 | 1.50 | 0.86 / 0.10 | 0.40 | yes | A3 |
| `donchian` | {"N": 20} | **rejected** | 33 | 0.95 | 1.65 | 0.59 / 0.69 | 0.17 | yes | A3 |
| `ma_atr_trend` | {"L": 100, "m": 3} | **rejected** | 20 | 0.49 | 1.56 | 0.09 / 0.33 | 0.16 | no | A3, A4 |
| `tsmom` | {"L": 30} | **rejected** | 69 | 1.41 | 1.93 | 1.12 / 0.73 | 0.12 | yes | A3 |
| `rsi_momentum` | {"enter": 55, "exit": 45, "n": 14} | **rejected** | 31 | 1.16 | 1.63 | 0.87 / 0.27 | 0.34 | yes | A3 |
| `mom_vol` | {"L": 30, "cap": 1.0} | **rejected** | 73 | 1.22 | 1.93 | 0.88 / 0.73 | 0.12 | yes | A3 |
| `bollinger_mr` | {"k": 2.5, "n": 30} | **rejected** | 16 | -0.17 | 0.44 | -0.46 / -0.34 | 0.53 | no | A2, A3, A4, A5 |
| `rsi_oversold` | {"enter": 20, "exit": 50, "n": 14} | **too thin** | 2 | 0.65 | 0.66 | 0.59 / 0.34 | 0.29 | yes | A1, A3 |
| `vol_breakout` | {"hold": 20, "k": 2.0} | **rejected** | 20 | 1.11 | 1.51 | 0.82 / 0.76 | 0.11 | no | A3, A4 |
| `regime_switch` | {"adx": 20} | **rejected** | 28 | 1.04 | 0.85 | 0.82 / -0.59 | 0.86 | yes | A2, A3 |
| `vol_target` | {"target": 0.4, "window": 40} | **rejected** | 87 | 0.80 | 1.97 | 0.11 / 0.29 | 0.31 | yes | A3 |
| `sma_filter` | {"L": 150} | **rejected** | 49 | 0.93 | 0.93 | 0.44 / -1.04 | 0.95 | yes | A2, A3 |

Sharpe ratios are annualised, after costs, from a flat start with $10,000. The information ratio is the Sharpe ratio of the returns in excess of holding the same average share of Bitcoin all the time (it removes the drift of simply being invested). The timing p is the share of 612 shifted copies of the strategy's own schedule that did at least as well on the 2023-2024 VALIDATION days (small means the timing matters).

## What each family did against holding

| family | VALIDATION return | hold | exposure-matched hold | max drawdown | exposure | costs doubled: Sharpe | walk-forward Sharpe / hold | positive windows | trips |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `sma_cross` | 19.7% | 463.8% | 19.0% | 4.8% | 9% | 1.17 | 0.80 / 0.39 | 6 of 10 | 0 |
| `donchian` | 16.9% | 463.8% | 11.0% | 3.8% | 5% | 1.21 | 0.76 / 0.39 | 6 of 10 | 0 |
| `ma_atr_trend` | 15.9% | 463.8% | 13.3% | 3.8% | 6% | 1.00 | 0.65 / 0.39 | 7 of 10 | 0 |
| `tsmom` | 25.4% | 463.8% | 18.8% | 3.5% | 9% | 1.55 | 0.90 / 0.39 | 6 of 10 | 0 |
| `rsi_momentum` | 20.4% | 463.8% | 18.2% | 3.3% | 9% | 1.30 | 0.76 / 0.39 | 6 of 10 | 0 |
| `mom_vol` | 25.4% | 463.8% | 18.8% | 3.5% | 9% | 1.44 | 0.90 / 0.39 | 6 of 10 | 0 |
| `bollinger_mr` | 1.1% | 463.8% | 1.9% | 1.6% | 1% | -0.00 | -0.21 / 0.39 | 4 of 10 | 0 |
| `rsi_oversold` | 0.7% | 463.8% | 0.3% | 0.2% | 0% | 0.64 | 0.30 / 0.39 | 2 of 10 | 0 |
| `vol_breakout` | 9.5% | 463.8% | 5.3% | 2.4% | 3% | 1.24 | 0.29 / 0.39 | 4 of 10 | 0 |
| `regime_switch` | 6.9% | 463.8% | 10.7% | 3.3% | 5% | 0.93 | 0.20 / 0.39 | 5 of 10 | 0 |
| `vol_target` | 298.1% | 463.8% | 274.6% | 35.3% | 74% | 1.26 | 0.60 / 0.39 | 6 of 10 | 12 |
| `sma_filter` | 76.3% | 463.8% | 207.4% | 37.4% | 62% | 0.89 | 0.45 / 0.39 | 5 of 10 | 13 |

The walk-forward re-chooses each family's settings every six months from 2022 and scores them on the following six months; its later windows overlap the TEST period, as pre-registered.

## What was not tested or not shown

- The TEST period (2025 onward) has not been used to choose or admit anything. It overlaps data that earlier experiments in this repository already scored, so it can never be a clean test; only the forward paper record is clean.
- Deflated Sharpe ratios are reported in the JSON file but are not gates: on raw returns they reward the market's drift, and on excess returns they cannot be passed with this much history (`CALIBRATION.md`).
- Five families (RSI momentum, Bollinger bands, RSI oversold, volatility breakout, regime switch) have no peer-reviewed test on Bitcoin behind them (`strategies/SOURCES.md`).
- Prices are Coinbase BTC-USD, not Binance BTC/USDT (that host is blocked from this environment).
- Nothing is traded: no order was placed anywhere, and exchange minimum sizes, outages, taxes and market impact are not modelled.

## Credibly profitable?

No. Nothing here is evidence that a rule makes money. The forward paper record, accumulated day by day from now on, is the only clean evidence there will be.
