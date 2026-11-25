# BTC paper trading report, 2026-11-25

Protocol 1.5. **Real trading is disabled**: every trade below is a line in a file. Prices are Coinbase BTC-USD daily candles; a candle counts only once it is complete (UTC).

## Data

- Latest complete candle: **2026-11-24** (close $59,740.87); 2,885 daily candles stored; 0 gap(s); hash `3faf53ca5f6913e0`.
- Update: 1 new candle(s) added.

## Accounts

| account | stage | equity | today | since start | in Bitcoin | drawdown | trades | breaker | pending order |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `bollinger_mr-c251886b` | monitor | $9,898.13 | $0.00 | -1.02% | 0% | 1.2% | 1 | ok | none |
| `buy_hold` | benchmark | $9,303.25 | -$225.66 | -6.97% | 100% | 8.5% | 0 | ok | none |
| `cash` | benchmark | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `donchian-4a2e999e` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `ma_atr_trend-c0011d2a` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `mom_vol-07954965` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `monday-9db66957` | monitor | $9,974.58 | -$14.84 | -0.25% | 0% | 0.3% | 1 | ok | none |
| `portfolio` | portfolio | $100,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `regime_switch-9c030efe` | monitor | $9,898.13 | $0.00 | -1.02% | 0% | 1.2% | 1 | ok | none |
| `rsi_momentum-a41fee0c` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `rsi_oversold-a8d8143b` | monitor | $9,898.13 | $0.00 | -1.02% | 0% | 1.2% | 1 | ok | none |
| `sma_cross-c0f76650` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `sma_filter-4df990f4` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `three_down-e7923e48` | monitor | $9,974.89 | $0.00 | -0.25% | 0% | 0.3% | 1 | ok | none |
| `tsmom-39fed1cb` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `vol_breakout-a1fdbb9e` | monitor | $10,000.00 | $0.00 | 0.00% | 0% | 0.0% | 0 | ok | none |
| `vol_target-2dbe9ef1` | monitor | $9,303.25 | -$225.66 | -6.97% | 100% | 8.5% | 0 | ok | none |
| `volume_surge-9c042d26` | monitor | $9,898.11 | $0.00 | -1.02% | 0% | 1.0% | 1 | ok | none |

## Challengers against holding

No strategy has been admitted as a challenger, so there is nothing to compare yet. The benchmarks above keep running.

## Monitored strategies (not admitted)

These strategies did not pass the admission gates in the research run. Each still has a paper account so that every strategy's trades are recorded on signal and so that the forward record can show whether rejecting it was right. They cannot be promoted without first passing the admission gates, and a good forward week proves nothing: 15 accounts watched at once will always have a lucky one.

| strategy | days | return | buy and hold | exposure-matched hold | in Bitcoin | trades | pending order |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `bollinger_mr-c251886b` | 10 | -1.02% | -6.97% | -0.33% | 0% | 1 | none |
| `donchian-4a2e999e` | 10 | 0.00% | -6.97% | 0.00% | 0% | 0 | none |
| `ma_atr_trend-c0011d2a` | 10 | 0.00% | -6.97% | 0.00% | 0% | 0 | none |
| `mom_vol-07954965` | 10 | 0.00% | -6.97% | 0.00% | 0% | 0 | none |
| `monday-9db66957` | 8 | -0.25% | -7.97% | -1.01% | 0% | 1 | none |
| `regime_switch-9c030efe` | 10 | -1.02% | -6.97% | -0.33% | 0% | 1 | none |
| `rsi_momentum-a41fee0c` | 10 | 0.00% | -6.97% | 0.00% | 0% | 0 | none |
| `rsi_oversold-a8d8143b` | 10 | -1.02% | -6.97% | -0.33% | 0% | 1 | none |
| `sma_cross-c0f76650` | 10 | 0.00% | -6.97% | 0.00% | 0% | 0 | none |
| `sma_filter-4df990f4` | 10 | 0.00% | -6.97% | 0.00% | 0% | 0 | none |
| `three_down-e7923e48` | 7 | -0.25% | -8.05% | -0.17% | 0% | 1 | none |
| `tsmom-39fed1cb` | 10 | 0.00% | -6.97% | 0.00% | 0% | 0 | none |
| `vol_breakout-a1fdbb9e` | 10 | 0.00% | -6.97% | 0.00% | 0% | 0 | none |
| `vol_target-2dbe9ef1` | 10 | -6.97% | -6.97% | -6.97% | 100% | 0 | none |
| `volume_surge-9c042d26` | 7 | -1.02% | -8.05% | -0.27% | 0% | 1 | none |

## Champions and the main portfolio

No champions: the main portfolio is in cash. The $100,000 portfolio holds $100,000.00, all in cash.

A champion needs a forward paper record of at least 90 days and 5 closed trades, and all the promotion gates in `PROTOCOL.md`; none has been promoted.

## Research

The research runs so far (protocols 1.2 and 1.3 and 1.4 and 1.5; the latest used data to 2026-11-16) admitted 0 of 15 families as challengers; see `reports/research_1.2.md` and `reports/research_1.3.md` and `reports/research_1.4.md` and `reports/research_1.5.md` for what was tested, what was admitted and why, and what was not shown.

## What this does not show

These are simulations on past and forward prices with assumed fees (0.10%) and slippage (0.05%). A paper profit is not a profit; nothing here is advice, a forecast or a claim that any rule makes money. Orders were modelled as filled at the 00:00 UTC open although the run happens at 00:15.
