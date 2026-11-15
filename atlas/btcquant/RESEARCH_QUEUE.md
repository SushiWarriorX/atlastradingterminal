# btcquant research queue (BUILD_PLAN step 13)

New hypotheses found in published research or practitioner sources, each screened for being genuinely new before anything is written up, pre-registered or run. Nothing in this file has been run. Research and paper only; nothing here shows that any rule makes money.

## How an idea gets from here to a result (fixed before the first screen was run)

1. **Find it.** A hypothesis about Bitcoin returns that can be computed from the stored daily candles (price and volume) and from nothing that would look ahead. Sources are named with their honest status: what was actually seen, and what is from memory.
2. **Write the rule and its planned grid first**, before looking at any data (the "rule" and "planned grid" lines of each entry below).
3. **Screen it for novelty.** `python -m atlas_api.btcquant.novelty` compares the ON/OFF state of the rule's default configuration with the state (or target weight) of all 100 configurations of the twelve families, over the TRAIN and VALIDATION days, by Pearson correlation: the same 0.90 line as protocol section 10 ("renamed copy, counted with the original"). The screen looks at timing only. It computes no return, profit or Sharpe ratio, and nothing is tuned to it. An entry at 0.90 or more is dropped as a look-alike.
4. **Priority (fixed before the screen was run).** Among the entries below 0.90, the one with the LOWEST highest-correlation goes first. If two are within 0.05 of each other, the one with a published (journal or working-paper) source goes first. The order is then not changed by anything that is seen later.
5. **Pre-register** the entry that is next: `strategies/<id>.md` (hypothesis, rationale, rules, grid, where it should fail, sources), a protocol amendment (a new version: the family, its grid, and the larger N), the family as code with tests first (including the no-look-ahead test), and the paper-account plumbing. Push all of it BEFORE running anything.
6. **Run it once** under the new protocol version on the then-current data (`research.py`: a new version is a new run, reported next to the old one), with every gate as written. The outcome is admitted, rejected or too thin to judge, and it is logged whatever it is.
7. **Each entry costs something.** Every configuration of every pre-registered family adds to N, and `CALIBRATION.md` found that on pure noise about one dataset in six admits something among twelve families: the more families are tried, the likelier a lucky admission. So the queue is short, entries are taken one at a time, and an admission would only mean "worth watching in paper".

## What is not in the queue, and why

- **Time-of-day effects** (for example Baur et al., who found them time-varying): they need hourly candles, and protocol v1 evaluates daily candles only; adding a timeframe is an amendment. A daily round trip also costs 0.30% (0.10% fee plus 0.05% slippage, each way), about 110% a year before any edge.
- **On-chain, derivatives and macro inputs**: tested already (experiments 4 to 7 in `EDGE_PLAN.md`: funding carry, net liquidity, hash rate, the Nasdaq filter; all failed), or blocked from this environment (the on-chain valuation host).
- **More moving-average, momentum and breakout variants**: look-alikes of the twelve families; the screen exists to keep them out.

## The six entries (the rules below are fixed; the screen result is in the last section)

### `monday`: the day-of-week effect (Bitcoin earns more on Mondays)
- **Sources.** Caporale and Plastun (2017), CESifo Working Paper 6716, found Monday returns higher in Bitcoin and reported that a trading simulation showed profit opportunities; Aharon and Qadan (2019), "Bitcoin and the day-of-the-week effect", found it in returns and volatility on daily data for 2010 to 2017; Kahraman and Kök (2024) report a Monday effect in Bitcoin and Ether and a rule that beat random investment. **Against:** Baur et al., on seven exchanges, found day-of-week effects that varied over time with no persistent pattern and concluded that Bitcoin is weak-form efficient. Status as seen: abstracts and summaries returned by a web search, not the papers in full; the samples mostly end before 2020, where our evaluation starts.
- **Rule (default).** Long during Mondays (UTC) only: ON at the close of the Sunday candle, sold at the close of Monday. About one day in seven.
- **Planned grid.** The weekday held, Monday to Sunday: 7 configurations (N would grow by 7).
- **Expected failure.** A round trip every week costs 0.30%, about 15.6% a year, against a position held 14% of the time; the effect would have to exceed 0.30% per Monday just to pay for itself. A calendar rule also has no stop that means anything.

### `volume_surge`: a heavy-volume up day starts a short continuation
- **Source.** Balcilar, Bouri, Gupta and Roubaud (2017), *Economic Modelling* 64, 74 to 81: with a nonparametric causality-in-quantiles test on daily data from December 2011 to April 2016, trading volume predicted Bitcoin returns across most of the distribution (quantiles 0.25 to 0.75) except in bear and bull regimes, and did not predict volatility. That paper tests predictability, not a trading rule: this rule is our own proxy for it (status as seen: the abstract).
- **Rule (default).** A day whose volume is at least 2.0 times the mean of the previous 20 days and whose close is above the previous close; long for 5 candles including that day.
- **Planned grid.** Ratio 1.5, 2, 3; hold 3, 5, 10: 9 configurations.
- **Expected failure.** Volume spikes mark turning points in both directions (capitulation and blow-off); Coinbase volume is one venue's; the paper's own result excludes the bull and bear regimes where most of the return is made.

### `near_high`: price close to its recent high keeps rising
- **Sources.** George and Hwang (2004), *Journal of Finance* 59(5), the 52-week-high effect in stocks (from memory, not re-checked). For Bitcoin, CXO Advisory's "Predictable Bitcoin Momentum or Reversion?" relates next-week returns to the price relative to its 13-week high and low (the method was seen; the finding was not). No crypto-specific study of the 52-week high was found.
- **Rule (default).** Long while the close is at least 95% of the highest close of the last 91 days (13 weeks), today included.
- **Planned grid.** Window 63, 91, 182, 365 days; fraction 0.90, 0.95, 0.98: 12 configurations.
- **Expected failure.** It carries much the same information as a trend rule (price above a long average); the screen says how much.

### `squeeze_break`: a volatility squeeze, then a break upward
- **Source.** Practitioner: Bollinger's bands and bandwidth (Bollinger, *Bollinger on Bollinger Bands*, 2001, from memory). Press commentary (CoinDesk and others) records weekly bandwidth lows before volatility bursts in Bitcoin but says the direction is unresolved and gives no test; no rigorous out-of-sample test was found. Status: a practitioner claim, with selection bias in the examples it cites.
- **Rule (default).** Enter when the close is above the upper Bollinger band (20 days, 2 standard deviations) and the band width of the previous day was in the lowest 20% of the widths of the 180 days before it; stay long until the close is below the 20-day average.
- **Planned grid.** Percentile 10, 20, 30; lookback 120, 180, 250 days: 9 configurations.
- **Expected failure.** Squeezes are rare, so few trades: most likely "too thin to judge". The direction of the break is close to a coin flip.

### `three_down`: short-term reversal after a losing streak
- **Sources.** Equities: Jegadeesh (1990), short-term reversal (from memory). Bitcoin: De Nicola found negative first-order autocorrelation at one, two and four hours on Bitstamp, with larger moves reversing more; Corbet and Katsiampa (2018) found asymmetric mean reversion across frequencies; Quantpedia's daily backtests of buying local minima are mixed (less profitable but less risky than buying maxima, no significant seasonality in a later revisit, drawdowns above 80%). Status as seen: summaries from a web search; the evidence is mostly intraday, and thin at the daily horizon.
- **Rule (default).** Buy after three lower closes in a row; sell at the first close that is not lower than the one before.
- **Planned grid.** Streak 2, 3, 4: 3 configurations.
- **Expected failure.** Falling markets keep falling (2022); and it overlaps the RSI and Bollinger mean-reversion families already tested, which were rejected.

### `money_flow`: closes near the day's high on heavy volume (accumulation)
- **Source.** Practitioner: Chaikin money flow (from memory); no rigorous Bitcoin test was found.
- **Rule (default).** Long while the 20-day Chaikin money flow (the volume-weighted position of the close within the day's range, averaged) is above 0.05.
- **Planned grid.** Window 10, 20, 40; threshold 0, 0.05, 0.10: 9 configurations.
- **Expected failure.** The position of the close within a day's range is noisy in a market that never closes (the UTC day boundary is arbitrary), and it will probably follow the trend rules.

If all six were pre-registered, N would grow from 100 to 149.

## Screen result

Not yet run. The screen is run after this file, the rules above and `atlas_api/btcquant/novelty.py` (with its tests) are pushed, so that the rules are fixed before anyone sees how they overlap.
