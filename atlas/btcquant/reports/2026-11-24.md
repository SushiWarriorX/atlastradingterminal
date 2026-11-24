# BTC paper trading report, 2026-11-24

Protocol 1.5. **Real trading is disabled**: every trade below is a line in a file. Prices are Coinbase BTC-USD daily candles; a candle counts only once it is complete (UTC).

## Data

- Latest complete candle: **2026-11-23** (close $61,189.97); 2,884 daily candles stored; 0 gap(s); hash `65e92f0400baad56`.
- Update: 5 new candle(s) added.

## Accounts

| account | stage | equity | today | since start | in Bitcoin | drawdown | trades | breaker | pending order |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bollinger_mr-c251886b` | monitor | $9,898.13 | $0.00 | -1.02% | 0% | 1.2% | 1 | ok | none |
| `buy_hold` | benchmark | $9,528.91 | $4.20 | -4.71% | 100% | 6.3% | 0 | ok | none |
| `cash` | benchmark | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `donchian-4a2e999e` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `ma_atr_trend-c0011d2a` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `mom_vol-07954965` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `monday-9db66957` | monitor | $9,989.42 | -$10.58 | -0.11% | 100% | 0.1% | 0 | ok | rebalance (signal) at the next open |
| `portfolio` | portfolio | $100,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `regime_switch-9c030efe` | monitor | $9,898.13 | $0.00 | -1.02% | 0% | 1.2% | 1 | ok | none |
| `rsi_momentum-a41fee0c` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `rsi_oversold-a8d8143b` | monitor | $9,898.13 | $0.00 | -1.02% | 0% | 1.2% | 1 | ok | none |
| `sma_cross-c0f76650` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `sma_filter-4df990f4` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `three_down-e7923e48` | monitor | $9,974.89 | $0.00 | -0.25% | 0% | 0.3% | 1 | ok | none |
| `tsmom-39fed1cb` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `vol_breakout-a1fdbb9e` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `vol_target-2dbe9ef1` | monitor | $9,528.91 | $4.20 | -4.71% | 100% | 6.3% | 0 | ok | none |
| `volume_surge-9c042d26` | monitor | $9,898.11 | $0.00 | -1.02% | 0% | 1.0% | 1 | ok | none |

## Challengers against holding

No strategy has been admitted as a challenger, so there is nothing to compare yet. The benchmarks above keep running.

## Monitored strategies (not admitted)

These strategies did not pass the admission gates in the research run. Each still has a paper account so that every strategy's trades are recorded on signal and so that the forward record can show whether rejecting it was right. They cannot be promoted without first passing the admission gates, and a good forward week proves nothing: 15 accounts watched at once will always have a lucky one.

| strategy | days | return | buy and hold | exposure-matched hold | in Bitcoin | trades | pending order |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bollinger_mr-c251886b` | 9 | -1.02% | -4.71% | -0.24% | 0% | 1 | none |
| `donchian-4a2e999e` | 9 | 0.00% | -4.71% | 0.00% | 0% | 0 | none |
| `ma_atr_trend-c0011d2a` | 9 | 0.00% | -4.71% | 0.00% | 0% | 0 | none |
| `mom_vol-07954965` | 9 | 0.00% | -4.71% | 0.00% | 0% | 0 | none |
| `monday-9db66957` | 7 | -0.11% | -5.74% | -0.82% | 100% | 0 | rebalance (signal) |
| `regime_switch-9c030efe` | 9 | -1.02% | -4.71% | -0.24% | 0% | 1 | none |
| `rsi_momentum-a41fee0c` | 9 | 0.00% | -4.71% | 0.00% | 0% | 0 | none |
| `rsi_oversold-a8d8143b` | 9 | -1.02% | -4.71% | -0.24% | 0% | 1 | none |
| `sma_cross-c0f76650` | 9 | 0.00% | -4.71% | 0.00% | 0% | 0 | none |
| `sma_filter-4df990f4` | 9 | 0.00% | -4.71% | 0.00% | 0% | 0 | none |
| `three_down-e7923e48` | 6 | -0.25% | -5.82% | -0.14% | 0% | 1 | none |
| `tsmom-39fed1cb` | 9 | 0.00% | -4.71% | 0.00% | 0% | 0 | none |
| `vol_breakout-a1fdbb9e` | 9 | 0.00% | -4.71% | 0.00% | 0% | 0 | none |
| `vol_target-2dbe9ef1` | 9 | -4.71% | -4.71% | -4.71% | 100% | 0 | none |
| `volume_surge-9c042d26` | 6 | -1.02% | -5.82% | -0.22% | 0% | 1 | none |

## Champions and the main portfolio

No champions: the main portfolio is in cash. The $100,000 portfolio holds $100,000.00, all in cash.

A champion needs a forward paper record of at least 90 days and 5 closed trades, and all the promotion gates in `PROTOCOL.md`; none has been promoted.

## Research

The research runs so far (protocols 1.2 and 1.3 and 1.4 and 1.5; the latest used data to 2026-11-16) admitted 0 of 15 families as challengers; see `reports/research_1.2.md` and `reports/research_1.3.md` and `reports/research_1.4.md` and `reports/research_1.5.md` for what was tested, what was admitted and why, and what was not shown.

## What this does not show

These are simulations on past and forward prices with assumed fees (0.10%) and slippage (0.05%). A paper profit is not a profit; nothing here is advice, a forecast or a claim that any rule makes money. Orders were modelled as filled at the 00:00 UTC open although the run happens at 00:15.
