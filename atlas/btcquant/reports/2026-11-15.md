# BTC paper trading report, 2026-11-15

Protocol 1.2. **Real trading is disabled**: every trade below is a line in a file. Prices are Coinbase BTC-USD daily candles; a candle counts only once it is complete (UTC).

## Data

- Latest complete candle: **2026-11-14** (close $64,118.79); 2,875 daily candles stored; 0 gap(s); hash `c9cb205d1d501e6a`.
- Update: 0 new candle(s) added.

## Accounts

| account | stage | equity | today | since start | in Bitcoin | drawdown | trades | breaker | pending order |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bollinger_mr-c251886b` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | enter (signal) at the next open |
| `buy_hold` | benchmark | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | rebalance (benchmark) at the next open |
| `cash` | benchmark | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `donchian-4a2e999e` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `ma_atr_trend-c0011d2a` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `mom_vol-07954965` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `portfolio` | portfolio | $100,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `regime_switch-9c030efe` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | enter (signal) at the next open |
| `rsi_momentum-a41fee0c` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `rsi_oversold-a8d8143b` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | enter (signal) at the next open |
| `sma_cross-c0f76650` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `sma_filter-4df990f4` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | rebalance (signal) at the next open |
| `tsmom-39fed1cb` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `vol_breakout-a1fdbb9e` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `vol_target-2dbe9ef1` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | rebalance (signal) at the next open |

## Challengers against holding

No strategy has been admitted as a challenger, so there is nothing to compare yet. The benchmarks above keep running.

## Monitored strategies (not admitted)

These strategies did not pass the admission gates in the research run. Each still has a paper account so that every strategy's trades are recorded on signal and so that the forward record can show whether rejecting it was right. They cannot be promoted without first passing the admission gates, and a good forward week proves nothing: twelve accounts watched at once will always have a lucky one.

| strategy | days | return | buy and hold | exposure-matched hold | in Bitcoin | trades | pending order |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bollinger_mr-c251886b` | 0 | 0.00% | n/a | n/a | 0% | 0 | enter (signal) |
| `donchian-4a2e999e` | 0 | 0.00% | n/a | n/a | 0% | 0 | none |
| `ma_atr_trend-c0011d2a` | 0 | 0.00% | n/a | n/a | 0% | 0 | none |
| `mom_vol-07954965` | 0 | 0.00% | n/a | n/a | 0% | 0 | none |
| `regime_switch-9c030efe` | 0 | 0.00% | n/a | n/a | 0% | 0 | enter (signal) |
| `rsi_momentum-a41fee0c` | 0 | 0.00% | n/a | n/a | 0% | 0 | none |
| `rsi_oversold-a8d8143b` | 0 | 0.00% | n/a | n/a | 0% | 0 | enter (signal) |
| `sma_cross-c0f76650` | 0 | 0.00% | n/a | n/a | 0% | 0 | none |
| `sma_filter-4df990f4` | 0 | 0.00% | n/a | n/a | 0% | 0 | rebalance (signal) |
| `tsmom-39fed1cb` | 0 | 0.00% | n/a | n/a | 0% | 0 | none |
| `vol_breakout-a1fdbb9e` | 0 | 0.00% | n/a | n/a | 0% | 0 | none |
| `vol_target-2dbe9ef1` | 0 | 0.00% | n/a | n/a | 0% | 0 | rebalance (signal) |

## Champions and the main portfolio

No champions: the main portfolio is in cash. The $100,000 portfolio holds $100,000.00, all in cash.

A champion needs a forward paper record of at least 90 days and 5 closed trades, and all the promotion gates in `PROTOCOL.md`; none has been promoted.

## Research

The one-off research run of protocol 1.2 (data to 2026-11-14) admitted 0 of 12 families as challengers; see `reports/research_1.2.md` for what was tested, what was admitted and why, and what was not shown.

## What this does not show

These are simulations on past and forward prices with assumed fees (0.10%) and slippage (0.05%). A paper profit is not a profit; nothing here is advice, a forecast or a claim that any rule makes money. Orders were modelled as filled at the 00:00 UTC open although the run happens at 00:15.
