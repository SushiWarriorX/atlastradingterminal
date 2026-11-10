# Edge plan: finding something worth trading, honestly

Owner goal (2026-11-10): build a research app and a strategy the owner can make money from. This file is the working plan for the hourly loop. It is research and paper only: nothing here places a trade, and nothing here is advice.

## Where we honestly are
- 40 BTC rules tested on Coinbase daily bars (2015 to now), fees and slippage included, last 30% sealed, luck check across the whole library. **None has beaten simply holding BTC with a moderate-or-better evidence label.** Several cut the worst drop roughly in half (about -25 to -32% against -53%) but gave up return; that is a risk trade, not a free edge.
- The library now covers the classic published families. More look-alike rules only make the luck check stricter. So the loop stops adding them (see STRATEGY_LOOP.md) and tests different kinds of ideas instead.
- A strategy only counts as a candidate if it passes the bar in STRATEGY_LOOP.md ("credibly profitable"). Until then the loop says "not yet". It never says "profitable" from a backtest alone, and the forward record (new bars after the freeze) is the only real new evidence.

## Findings log (newest first)
- **2026-11-10, funding carry (spot long plus perpetual short, price moves cancel, collect funding):** Hyperliquid BTC funding summed to about 8.7% (May to Dec 2023), 24.2% (2024), 10.6% (2025) and 4.8% annualised so far in 2026; 20% of 2026 hours were negative (the short pays). Before fees and exchange risk. With 4-week and 13-week Treasury bills auctioning near 4.1% in October 2026 (see the bill auction card), the carry is currently **no better than bills while adding exchange and basis risk**. Not worth building as a strategy now; worth re-checking if funding rises. Exploratory look only, not a registered test.

## Next experiments, in order (each: write the rule and settings FIRST, test once, log whatever happens)
1. **Risk-managed holding (volatility targeting)**: hold BTC but scale the size down when recent volatility is high, up to 1x. Needs the simulator to accept fractional positions (it takes -1, 0, +1 today). Goal is realistic: less drawdown than holding at similar return, judged by Sharpe and worst drop on the sealed last 30%. Settings to fix up front: 20-day realised volatility, 40% annual target, cap 1x.
2. **Cross-sectional crypto momentum** (rank the largest coins by 90-day return, hold the top few): a well-documented effect, needs daily bars for about 20 coins from Coinbase (free) and a multi-asset simulator. Fix the universe by market cap at a stated date to avoid survivor bias, or say plainly that survivorship bias is not removed.
3. **Stock side (the research app's real use):** the fundamentals-first screens (revenue growth, Rule of 40, valuation) are research tools, not a backtested strategy. A stock strategy needs point-in-time data we do not have free; say so, and do not backtest on today's constituents.
4. **Forward record:** every frozen rule keeps being followed on new bars (tracker). After 60 days it starts to count.

## What would change the plan
- A candidate passing the bar: write it up with every caveat, then watch it forward before anything else.
- Funding rising well above bills: revisit carry.
- A free, point-in-time stock data source: revisit stock backtests.

## Rules the loop keeps
Research and paper only; no invented data; settings fixed before results; no retuning; bad results kept; every report says what was NOT verified. Do not claim anything "makes money".
