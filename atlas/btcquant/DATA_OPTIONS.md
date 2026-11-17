# Data options for the research queue (step 14f, 2026-11-17)

Why this exists: the power check of step 14e (`CALIBRATION.md`, "What the procedure can see in the entries that are left") found that four years of daily Bitcoin candles hold too few trades of the three rules left in the queue (`squeeze_break`, `money_flow`, `near_high`) for the five gates to tell a premium of 2.0% a trade from chance. It named three ways out: lower the bar, add data that gives the tests more trades, or stop the queue. This document puts numbers on the second one, so the owner can choose. **Nothing was pre-registered or run, no research file and no protocol text changed, and no strategy return was computed.**

## What was done, and what was not

- Read-only. Candles were downloaded from Coinbase's public candle endpoint (free, no key, the same host and the same plain client as `data.py`) into a scratch folder outside the repository, and checked with the module's own structural checks (`data.validate`: order, duplicates, impossible highs and lows, non-positive prices, negative volume, gaps). Gaps are listed, never filled.
- The TEST period stays unseen for the new assets as for Bitcoin: Ethereum and Solana were fetched only up to 2024-12-31. The only figures that look at returns are descriptive facts about the assets (daily return correlation with Bitcoin, the size of an hourly move); nothing about any strategy.
- The "trades" below are entries of each rule's default ON/OFF schedule (`novelty.CANDIDATES`, the same schedules as step 14e), counted from one year after a dataset begins (the warm-up the Bitcoin file gets from 2019) to 2024-12-31. Counting entries needs prices and volume only.

## 1. The data

| dataset | from to (candles) | missing | structural problems | flags | requests | notes |
| --- | --- | --- | --- | --- | --- | --- |
| BTC-USD daily, before the stored series | 2015-07-20 to 2018-12-31 (1,261) | none | none | none | 5 | The earliest candle the endpoint serves is 2015-07-20. The last close (3,691.86) and the first stored open (3,691.87) join without a jump. |
| ETH-USD daily | 2016-05-18 to 2024-12-31 (3,148 of 3,150) | 2 candles, one gap, 2016-05-20 | none | -43.3% on 2020-03-12 (the day of Bitcoin's -38.8%; real) | 11 | Later days were not fetched (TEST). |
| SOL-USD daily | 2021-06-17 to 2024-12-31 (1,294 of 1,294) | none | none | -42.6% on 2022-11-09 (the FTX collapse; real) | 5 | Later days were not fetched (TEST). |
| BTC-USD hourly, before 2019 | 2015-07-20 21:00 to 2018-12-31 23:00 (30,207 of 30,243) | 36 candles in 12 gaps, the longest 15 hours | none | 3 flat candles | 120 (18 empty pages before the data begin), 26 seconds | |
| BTC-USD hourly, already stored | 2019-01-01 to 2026-11-15 08:00 (68,990) | 9 candles in 9 gaps of 1 to 3 hours (to 2024-12-31: 52,599 of 52,608) | none | none | already in the repository | `btcusd_1h.csv.gz`. The daily run does not refresh it: `python -m atlas_api.btcquant.data 1h` does. |

Request budget: 300 candles a request. All 141 requests above took about 31 seconds (about 4.5 a second, with a pause of 0.13 seconds between them) and none was rate-limited. Bringing ETH and SOL up to today would add about 3 requests each; the early hourly file is the only large download (120 requests).

Not checked: any price against a second source (Binance, Bitstamp, Kraken and Bitfinex refuse this machine, `DATA_SOURCES.md`), so these are one exchange's candles; any other coin; anything after 2024-12-31 for ETH and SOL.

## 2. How many trades the six schedules would get

Entries of each rule's default schedule (and, in brackets, the days it holds), after a year of warm-up, to 2024-12-31:

| dataset (days) | `monday` | `three_down` | `volume_surge` | `squeeze_break` | `money_flow` | `near_high` |
| --- | --- | --- | --- | --- | --- | --- |
| BTC stored, 2020 to 2024 (1,827): what the research uses | 261 | 98 | 39 | **21** | 87 | 69 |
| BTC 2016-07-20 to 2018-12-31 (896) | 128 | 43 | 19 | 8 | 36 | 23 |
| ETH 2020 to 2024 (1,827) | 261 | 93 | 35 | 15 | 106 | 76 |
| ETH 2017-05-18 to 2024-12-31 (2,785) | 398 | 155 | 70 | 25 | 159 | 94 |
| SOL 2022-06-17 to 2024-12-31 (929) | 133 | 63 | 15 | 10 | 42 | 23 |
| **All of it added up** (BTC 2020 to 2024, BTC early, ETH 2017 to 2024, SOL) | 920 | 359 | 143 | **64** | 324 | 209 |

These add up to far less evidence than they look like. **The assets move together:** the daily return correlation with Bitcoin is 0.835 for Ethereum (2020 to 2024, 1,827 days) and 0.681 for Solana (from 2021-06-17, 1,293 days; 0.732 for 2022 to 2024). Entries also coincide: of Bitcoin's 21 `squeeze_break` entries in 2020 to 2024, 6 have an Ethereum entry within three days (29%); the figure is 59% for `money_flow` (51 of 87) and 48% for `near_high` (33 of 69). So the sum above is an upper bound on the independent trades.

## 3. How far each rule is from being testable

From step 14e, the premium (a gross effect per trade, before the 0.30% a trade costs) that the five gates find in half and in eight of ten datasets, in the best case (read off the table of 14e; extended in a straight line for `squeeze_break`, whose table stops at 60%); and, by a rough rule, what changes with more trades. The rule is that the premium found a given share of the time falls with the square root of the number of independent trades; it is the usual one for an average of trades and was **not measured here**.

| rule | trades now | premium found half the time | premium found 8 in 10 | trades needed to find 2.0% 8 in 10 | trades if all the data above were independent | premium found 8 in 10 with those trades |
| --- | --- | --- | --- | --- | --- | --- |
| `monday` (run) | 261 | about 0.8% | about 1.1% | about 80 | 920 | about 0.6% |
| `three_down` (run) | 98 | about 1.4% | about 1.9% | about 90 | 359 | about 1.0% |
| `volume_surge` (run) | 39 | about 3.7% | about 5.5% | about 300 | 143 | about 2.9% |
| `near_high` | 69 | about 4.0% | about 5.9% | about 600 | 209 | about 3.4% |
| `money_flow` | 87 | about 6.2% | about 9.2% | about 1,800 | 324 | about 4.8% |
| `squeeze_break` | 21 | about 10.5% | about 15% | about 1,200 | 64 | about 8.6% |

**Only rules that trade often enough can be tested with the data that exists** (`monday` and `three_down`, both run and both rejected). The three left need 600 to 1,800 trades to see a premium of 2.0%; every extra dataset together would give them 64 to 324 trades at most, and fewer independent ones, so they stay 3 to 19 times short. Even if all of it counted as independent, the premium found 8 times in 10 would only fall to about 3.4% (`near_high`), 4.8% (`money_flow`) and 8.6% (`squeeze_break`) a trade; with the partial independence the true figures lie between those and today's.

There is a second limit that more data of this kind does not touch: gate A3 judges VALIDATION alone, two years, in which `squeeze_break` makes 7 trades. Extra years before 2019 could only join TRAIN, and extra assets would need an A3 that pools their own out-of-sample years: a protocol amendment, and a new calibration of the whole procedure.

## 4. The ways out, with what the numbers say

The numbering follows `BUILD_PLAN.md` 14e: (1) lower the bar, (2) add data, which splits here into daily data (2a) and finer candles (2b), (3) stop the queue.

- (1) **Lower the bar and run the three anyway.** N goes from 113 to 143 and the chance that some family is admitted by luck goes up with it. The answer is almost fixed in advance: "rejected" in 85% to 92% of datasets even if a premium of 2.0% a trade were there (`CALIBRATION.md`).
- (2a) **More daily data (earlier Bitcoin, Ethereum, Solana).** Sections 2 and 3: it would roughly triple the trade counts at most (21 to 64 for `squeeze_break`), with partly the same events and correlated returns, still 3 to 19 times short of what a premium of 2.0% needs. It costs a protocol amendment (periods and a pooled A3 for several assets), code that stores, updates and researches more than one product (`data.py` fetches `BTC-USD` only; the engine, gates and registry are single-asset) and a new calibration. At best it would let the three rules left be tested for premiums of about 3% to 9% a trade, which are large effects.
- (2b) **Finer candles (the hourly file is already stored).** The only option that changes the number of trades by a large factor: "three lower closes in a row" fires 2,480 times on hourly bars in 2020 to 2024 against 98 times on daily bars. But an hour is a small move: the median hourly close-to-close move in 2020 to 2024 was 0.255% (daily: 1.50%), below the 0.30% a round trip costs, and 44% of hours moved by more than 0.30%. A rule on hourly bars has to earn several times a typical hour's move on each trade to pay for itself. It means new families (not the queued ones, which are defined on days), an hourly version of the synthetic worlds and of the power tool (both are daily today), and a protocol amendment.
- (3) **Stop the queue here.** The fifteen families stay the record, the daily run keeps paper-trading the chosen configuration of every family that was run and every day adds data nobody has looked at; the TEST period (2025-01-01 on) is sealed and has never been run. Stopping loses nothing that the other options would give, and waiting does not fix the power problem either (a year adds about 4 trades to `squeeze_break`); what the days that pass give is data nobody has looked at, which is what the paper accounts and the sealed TEST period are for.

**Recommendation.** Option (3) for the daily queue: no amount of the extra daily data makes these slow rules testable at realistic effect sizes, so another family of this kind would add to N and to the chance of a lucky admission while it can hardly add information. If the owner wants the search for a strategy to go on, option (2b) is the only direction with enough trades, and the first piece of work would be an hourly power tool (my estimate: about three strategy hours), before any family is written; I would not start it without the owner's say, because it is a change of scope (rules that trade many times a week, each trade small) and not a continuation of the queue.

## What was not verified

- The square-root rule of section 3 (the power study measured the premiums at 21 to 261 trades only; the extrapolation to hundreds of trades is a rule of thumb).
- That the extra Coinbase candles are right: one exchange, no second source; early candles come from a thin market.
- The independence of the extra assets' trades (the correlations and overlaps above say it is partial, nothing more).
- Any rule's returns on any of this data: none was computed.

Reproduce (read-only): the scratch scripts are not in the repository; the downloads are `GET https://api.exchange.coinbase.com/products/<product>/candles?granularity=<seconds>&start=<iso>&end=<iso>` (at most 300 candles a request) and the checks are `atlas_api.btcquant.data.validate`; the schedule counts are `novelty.CANDIDATES[<id>].fn(strategies.Bars(candles))`.
