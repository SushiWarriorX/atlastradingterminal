# Research run, protocol 1.4, data to 2026-11-16

Run once on 2026-11-17T04:38:09Z UTC on 2,877 daily BTC-USD candles (2019-01-01 to 2026-11-16, Coinbase; hash `b4c1003086af7178`). Everything below is a simulation on past prices. It is not a recommendation and nothing in it shows that any rule will make money.

This run covers the 1 family pre-registered under protocol 1.4 (`three_down`). The families pre-registered under other protocol versions are not part of this run: their results stand as they were reported in their own run files and are not repeated here. The number of trials behind the deflated Sharpe ratio is 104, every configuration of every family.

## Headline

**No family was admitted.** Every family either had too few trades to judge or failed at least one admission gate. The main portfolio stays in cash, and no challenger account was opened.

## Families

| family | chosen on TRAIN | outcome | trades | TRAIN Sharpe | VALIDATION Sharpe | info ratio TRAIN / VALIDATION | VALIDATION timing p | stable | failed gates |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `three_down` | {"streak": 2} | **rejected** | 213 | -0.26 | -0.22 | -0.63 / -1.31 | 0.77 | no | A2, A3, A4, A5 |

Sharpe ratios are annualised, after costs, from a flat start with $10,000. The information ratio is the Sharpe ratio of the returns in excess of holding the same average share of Bitcoin all the time (it removes the drift of simply being invested). The timing p is the share of 612 shifted copies of the strategy's own schedule that did at least as well on the 2023-2024 VALIDATION days (small means the timing matters).

## What each family did against holding

| family | VALIDATION return | hold | exposure-matched hold | max drawdown | exposure | costs doubled: Sharpe | walk-forward Sharpe / hold | positive windows | trips |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `three_down` | -0.9% | 463.8% | 3.9% | 3.2% | 2% | -0.72 | -0.36 / 0.39 | 6 of 10 | 0 |

The walk-forward re-chooses each family's settings every six months from 2022 and scores them on the following six months; its later windows overlap the TEST period, as pre-registered.

## What was not tested or not shown

- The TEST period (2025 onward) has not been used to choose or admit anything. It overlaps data that earlier experiments in this repository already scored, so it can never be a clean test; only the forward paper record is clean.
- Deflated Sharpe ratios are reported in the JSON file but are not gates: on raw returns they reward the market's drift, and on excess returns they cannot be passed with this much history (`CALIBRATION.md`).
- Prices are Coinbase BTC-USD, not Binance BTC/USDT (that host is blocked from this environment).
- Nothing is traded: no order was placed anywhere, and exchange minimum sizes, outages, taxes and market impact are not modelled.

## Credibly profitable?

No. Nothing here is evidence that a rule makes money. The forward paper record, accumulated day by day from now on, is the only clean evidence there will be.
