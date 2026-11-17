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
- **Changed before any run (2026-11-15, protocol 1.3; the text above was written before the screen and is kept as it was).** The grid is Monday alone, one configuration, not seven: every source claims Monday and none another day, a weekday is a category so the neighbour-smoothed selection and gate A4 have no meaning for it, and six more configurations would raise N for no hypothesis. The family runs in weight mode (no stop, the whole account through the Monday candle). Reasons, the amended A4 for a one-setting family, and the calibration on synthetic data are in `PROTOCOL.md` (amendment v1.3), `strategies/monday.md` and `CALIBRATION.md` (thirteen families). Nothing of it has been run on the real data.

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
- **Pre-registered before any run (2026-11-17, protocol 1.4; the text above was written before the screen and is kept as it was).** The rule, the default of 3 and the grid of 2, 3, 4 are exactly as planned. What the entry did not say is now fixed: a lower close is a close strictly below the one before it (an equal close is not lower, and the first candle has none); the family is stop-based, with the protocol's fixed 3 x ATR stop and 1% risk sizing like the other two mean-reversion families, not a whole-account weight rule like `monday`; N becomes 104. Reasons, the calibration on synthetic data and what a rejection will mean are in `PROTOCOL.md` (amendment v1.4), `strategies/three_down.md` and `CALIBRATION.md` (fourteen families). Nothing of it has been run on the real data.

### `money_flow`: closes near the day's high on heavy volume (accumulation)
- **Source.** Practitioner: Chaikin money flow (from memory); no rigorous Bitcoin test was found.
- **Rule (default).** Long while the 20-day Chaikin money flow (the volume-weighted position of the close within the day's range, averaged) is above 0.05.
- **Planned grid.** Window 10, 20, 40; threshold 0, 0.05, 0.10: 9 configurations.
- **Expected failure.** The position of the close within a day's range is noisy in a market that never closes (the UTC day boundary is arbitrary), and it will probably follow the trend rules.

If all six were pre-registered as planned, N would grow from 100 to 149; with `monday` as one configuration it is 101 now, and the other five as planned would add 42 (143).

## Screen result (run 2026-11-15 after the rules above were pushed; `python -m atlas_api.btcquant.novelty`, written to `reports/novelty.json`)

Data: 2,875 daily Coinbase BTC-USD candles to 2026-11-14 (hash `c9cb205d1d501e6a`), compared over the 1,827 TRAIN and VALIDATION days against all 100 configurations of the twelve families. **None of the six is a renamed copy (all are below 0.90).**

| order | id | ON share of days | highest correlation | closest existing configuration | renamed? | source, as seen |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `monday` | 14% | +0.02 | `vol_target` (target 0.3, window 20) | no | working paper and a journal paper; contested by a third study |
| 2 | `three_down` | 10% | +0.12 | `rsi_oversold` (enter 30, exit 50, n 7) | no | mostly intraday; thin at the daily horizon |
| 3 | `volume_surge` | 12% | +0.44 | `vol_breakout` (hold 5, k 1.5) | no | a predictability paper, not a trading rule |
| 4 | `squeeze_break` | 17% | +0.45 | `donchian` (N 20) | no | practitioner |
| 5 | `money_flow` | 56% | +0.49 | `rsi_momentum` (n 14, enter 55, exit 50) | no | practitioner |
| 6 | `near_high` | 30% | +0.69 | `rsi_momentum` (n 21, enter 60, exit 50) | no | a stocks paper; none found for crypto |

The order is the fixed priority rule applied to these numbers (lowest highest-correlation first; where two are within 0.05, a published source first: `volume_surge` before `squeeze_break` and `money_flow`).

What the screen says and does not say. The calendar rule and the reversal rule are almost uncorrelated with anything already tested, so a result for them could not be an old result in disguise. The other four are different position series, but they share 0.4 to 0.7 of their timing with a trend or momentum family: if one of them had an edge it could be the trend edge already rejected. The screen compares the default configuration only (a member of a planned grid could overlap more; the registry flags a renamed copy again at logging time, on the chosen configuration's exposure), uses state series rather than the engine's sized positions, and says nothing about returns. A low correlation is not evidence for a rule.

## Before the first entry can be run (engineering; items 1 and 2 were done on 2026-11-15 16:xx UTC, see protocol amendment v1.2b)

1. ~~**A protocol version bump must not change any existing specification hash.**~~ **Done.** Each family carries the protocol version it was pre-registered under (`Family.since`) and that goes into its specification hash; a test checks all 100 configurations of the real run and all 15 accounts against a bump to 1.3 and 2.0.
2. ~~**A research run must be able to evaluate only the families pre-registered under the new version.**~~ **Done.** `run_research` covers the families of its own version (refuses with `NothingToRun` when a version added none), the trial count N includes every configuration of every family, and the dashboard, the daily report and the phone view read the runs of all versions as one record (tested end to end on a toy family under version 1.3: the first report file is byte for byte unchanged, one new account is opened and no duplicates).
3. ~~**The calibration** (`CALIBRATION.md`: about one noise dataset in six admits something among twelve families) must be restated for thirteen families.~~ **Done 2026-11-15 (19:xx UTC).** The new family alone was run on 1,000 further datasets of each no-skill world and of three worlds with a planted Monday premium: false admission 0.1% to 0.2%, power 6% / 29% / 71% at a premium of 0.3% / 0.6% / 1.0% a day; the thirteen-family share is still about one dataset in six (`CALIBRATION.md`).
4. **The entry itself:** `strategies/<id>.md`, the protocol amendment (v1.3: the family, its grid, N), the family as code with its tests first (including the no-look-ahead test), a short code for its logo in the phone view (`view.SHORT`; a test fails until it has one), pushed before the run; then one run, and a monitor account for it (the existing code opens one for a non-admitted chosen configuration). **Pre-registered and pushed 2026-11-15 (19:xx UTC) for `monday`; the one run follows and is logged below when it has been made.**

## Run results

### `monday` (protocol 1.3), run once on 2026-11-15 at 19:45 UTC, after the pre-registration was pushed (commit 779d9b8, 19:45)

Data: 2,875 daily Coinbase BTC-USD candles to 2026-11-14 (hash `c9cb205d1d501e6a`). Record: `reports/research_1.3.md` and `.json`, `registry/`.

**Rejected** by gates A2, A3 and A5. A1 passed (482 position changes), A4 was "not applicable (one setting)" and passed on the configuration's own TRAIN Sharpe ratio (0.31). The pre-registered expectation ("rejected, most likely by A2 and A5; it will mean no premium large enough to see and keep after costs, not that there is no Monday effect") held.

| after costs, $10,000 start | TRAIN 2020-2022 | VALIDATION 2023-2024 |
| --- | --- | --- |
| return | +16.1% | +17.5% |
| buy-and-hold | +1,303% | +464% |
| the same average exposure (13% to 14%) held every day | +21.8% | +30.3% |
| Sharpe ratio | 0.31 | 0.45 |
| information ratio against that matched hold (A2 needs above 0 in both) | +0.09 | -0.12 |
| maximum drawdown | 40.3% | 26.7% |
| round trips | 140 | 101 |
| fees paid | $3,932 | $2,123 |
| circuit-breaker trips | 4 | 1 |

Random-timing p on VALIDATION: 0.284 (174 of 612 shifted copies of the schedule did at least as well; A3 needs 0.05 or less). Doubled costs: Sharpe -0.08 (A5 needs above 0). Across the cost settings of the sensitivity table, TRAIN / VALIDATION return: +50.8% / +38.1% at 0.07% a side, +16.1% / +17.5% at the default 0.15%, -20.6% / -8.5% at 0.30%, -67.7% / -37.9% at 0.45%. Walk-forward (reported, not a gate here): stitched Sharpe 0.10 against 0.39 for holding, positive in 3 of 10 windows. Deflated Sharpe ratio with N = 101: 0.04 on raw returns, 0.006 on the excess returns (reported, not gates).

**Exploratory context, computed after the result, on the TRAIN and VALIDATION days only, and not a test (nothing was decided or changed from it):** the average daily return of a Monday candle was +0.46% in 2020-2022 and +0.52% in 2023-2024, against +0.10% and +0.23% on the other days: a difference of +0.36 and +0.30 percentage points a Monday, with standard errors of 0.39 and 0.34 (t about 0.9 each; 1.2 pooled over 261 Mondays). The Monday medians are +0.14% and +0.04%, so a few large up-Mondays carry the average, and Wednesday was as high as Monday (+0.50% and +0.49%). A pooled difference of about +0.33 points is, by coincidence, about the 0.30% a weekly round trip costs: even taken at face value it would be a wash after costs, and it cannot be told from chance.

**What this means.** In 2020 to 2024 on Coinbase prices, holding Bitcoin only through Mondays earned a positive return after costs, but no more than holding the same average amount of Bitcoin on all days would have, its timing was not distinguishable from random weekday timing, and it stopped working when costs were doubled. It does not show that Bitcoin has no Monday effect: the procedure sees a premium of 0.6% a day only about three times in ten (`CALIBRATION.md`), and a sample average of +0.33 points a Monday is below that. It does not show that anything makes money. The `monday` account is paper-traded as a monitor from the next daily run, and the queue goes on with `three_down` (the lowest highest-correlation after `monday`), which needs its own pass through the list above (calibration for fourteen families, note, amendment v1.4, the family with tests, push, one run).

### `three_down` (protocol 1.4), run once on 2026-11-17 at 04:38 UTC, after the pre-registration was pushed (commit 3da34a8, 04:38)

Data: 2,877 daily Coinbase BTC-USD candles to 2026-11-16 (hash `b4c1003086af7178`). Record: `reports/research_1.4.md` and `.json`, `registry/`.

**Rejected** by gates A2, A3, A4 and A5. A1 passed (213 completed trades on TRAIN plus VALIDATION). The setting chosen on TRAIN was a run of 2 lower closes (selection scores -0.375, -0.384 and -0.448 for runs of 2, 3 and 4: no setting had a TRAIN Sharpe ratio above zero, -0.26, -0.49 and -0.40), and A4 is computed only when the chosen setting's TRAIN Sharpe is above zero, so it failed. The pre-registered expectation ("rejected, most likely by A3, A2 and A5; it will mean that no premium large enough to see and to keep after costs was present, not that there is no short-term reversal") held; A4 failed as well because every setting lost money after costs on TRAIN.

| after costs, $10,000 start, run of 2 | TRAIN 2020-2022 | VALIDATION 2023-2024 |
| --- | --- | --- |
| return | -1.7% | -0.9% |
| buy-and-hold | +1,303% | +464% |
| the same average exposure (1.2% / 2.0% of the account) held every day | +2.0% | +3.9% |
| Sharpe ratio | -0.26 | -0.22 |
| information ratio against that matched hold (A2 needs above 0 in both) | -0.63 | -1.31 |
| maximum drawdown | 5.4% | 3.2% |
| completed trades (average holding) | 125 (1.64 days) | 88 (1.72 days) |
| winning trades | 65.6% | 59.1% |
| fees paid / slippage paid | $166 / $83 | $166 / $83 |
| circuit-breaker trips | 0 | 0 |

Before fees and slippage the account was up $83 (2020-2022) and $157 (2023-2024) on $10,000; costs of $249 and $248 turned that into the losses above. Random-timing p on VALIDATION: 0.770 (471 of 612 shifted copies of the schedule did at least as well; A3 needs 0.05 or less). Doubled costs: Sharpe -0.72 (A5 needs above 0). Across the cost settings of the sensitivity table, TRAIN / VALIDATION return: -0.4% / +0.4% at 0.07% a side, -1.7% / -0.9% at the default 0.15%, -4.1% / -3.4% at 0.30%, -6.4% / -5.7% at 0.45%. The same signals at full exposure (100% when long, no risk cap; a labelled sensitivity): -23.1% on TRAIN with 8 circuit-breaker trips and +0.2% on VALIDATION with 2. Walk-forward (reported, not a gate here): stitched Sharpe -0.36 against 0.39 for holding, positive in 6 of 10 windows. Deflated Sharpe ratio with N = 104: 0.0005 on raw returns and 0.0000006 on the excess returns (reported, not gates). The two settings that were not chosen (runs of 3 and 4) had VALIDATION Sharpe ratios of +0.25 and +1.12 on 55 and 27 TRAIN trades; they were not used for anything and are not a result (a setting picked because it did well on VALIDATION would be picked after the fact).

**Exploratory context, computed after the result, on the TRAIN and VALIDATION days only, and not a test (nothing was decided or changed from it):** the average open-to-close return of a candle that followed a run of at least 2, 3 and 4 lower closes was +0.26%, +0.18% and +0.08% in 2020-2022 (227, 102 and 47 candles) and +0.26%, +0.48% and +0.82% in 2023-2024 (161, 72 and 29 candles), against +0.13% to +0.16% and +0.25% to +0.27% for the other candles of each period: differences of +0.13, +0.03 and -0.08 points, then -0.01, +0.23 and +0.57 points, with standard errors of 0.22 to 0.80 points (t from -0.10 to +1.54). Pooled over both periods the differences are +0.07, +0.12 and +0.17 points (t 0.33 to 0.39). The candle after a run rose a little more often than other candles (55% to 60% against 50% to 52%). A pooled premium of about +0.1 points a candle is below the roughly +0.15 points a candle held that a trade needs to pay for itself (0.30% a round trip over about 1.7 candles), and it cannot be told from chance.

**What this means.** In 2020 to 2024 on Coinbase prices, buying Bitcoin after a run of lower daily closes and selling at the first close that was not lower earned a little before costs and lost a little after them, in 213 trades of about 1.7 days with a win rate of 59% to 66%: the fees and slippage of so many short trades were larger than the small gross gains, the timing was not distinguishable from random timing (p 0.77), and it did not survive doubled costs. It does not show that Bitcoin has no short-term reversal: the procedure sees a premium of 1.0% a candle only about four times in ten (`CALIBRATION.md`), and the sample averages above (+0.07 to +0.17 points) are far smaller than that and smaller than the cost of a trade. It does not show that anything makes money. The `three_down` account (`three_down-e7923e48`) is paper-traded as a monitor from the next daily run, and the queue goes on with `volume_surge` (the third entry by the fixed priority rule), which needs its own pass (calibration for fifteen families, with a synthetic volume series, note, amendment v1.5, the family with tests, push, one run).
