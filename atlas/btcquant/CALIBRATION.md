# Calibration of the research procedure on synthetic data

Written 2026-11-15, before any strategy was run on the real Bitcoin data. Code: `atlas_api/btcquant/calibration.py`; tests: `tests/test_btcquant_calibration.py`.

## Why this exists

A pass bar is only worth something if it can be passed when there is an edge and is hard to pass when there is none. The only way to know is to run the same procedure on data we made, where the truth is known. The first version of the admission gates (protocol 1.1) failed this check badly: on 24 datasets per world, they admitted at least one family in **75%** of pure-noise datasets that had an upward drift, in 25% of pure-noise datasets with a mild drift, and in only **17%** and **13%** of datasets with a planted trend edge (strong, weak). They were measuring the market's drift, not skill. Bitcoin's drift over 2020 to 2024 is large, so on the real data those gates would have admitted something almost whatever the truth. They were replaced (protocol 1.2) before the real data was touched.

## The worlds

Each dataset is 2,875 synthetic daily candles on the same calendar as the real data (2019-01-01 to 2026-11-14), made from a seeded random number generator.

- `null_mild`: no skill, mild drift (buy-and-hold Sharpe about 0.2).
- `null_drift`: no skill, strong drift (buy-and-hold Sharpe about 0.8).
- `planted_weak`: planted trend edge, weak (drift +-0.25% a day).
- `planted_strong`: planted trend edge, strong (drift +-0.40% a day).

The null worlds are independent daily returns with a daily volatility of 3.5%; no rule can have skill in them. The planted worlds have a hidden two-state trend: the daily drift is plus or minus a fixed amount (volatility 2.5%), switching sign with probability 2% a day (regimes of about 50 days). A trend rule can capture part of that, not all of it, because it only notices a regime after it has begun. Real Bitcoin is not like either: it has fat tails, volatility clusters, structural breaks and a very large drift. These worlds test the machinery, not the market.

## The procedure that was calibrated

The whole research procedure of `PROTOCOL.md` (selection on TRAIN, check on VALIDATION, the five admission gates A1 to A5), run on each dataset exactly as it will be run on the real data. The only free setting was the p-value limit of gate A3. It was chosen as the loosest limit on the grid below for which **the share of no-skill datasets in which something is admitted stays at about 15% or less**. That target was set after a first look at 24 datasets per world and before the 100-dataset table; the table is the evidence for the choice, not a pre-registered test of it.

## Result with the final gates (A3: p at most 0.05)

Share of datasets in which at least one of the 12 families was admitted (95% interval in brackets), 100 datasets per world:

| world | any family admitted | families admitted per dataset | trend families admitted | mean-reversion families admitted |
| --- | --- | --- | --- | --- |
| no skill, mild drift (buy-and-hold Sharpe about 0.2) | 12 of 100 = 12% (7% to 20%) | 0.16 | 9 | 3 |
| no skill, strong drift (buy-and-hold Sharpe about 0.8) | 16 of 100 = 16% (10% to 24%) | 0.17 | 14 | 2 |
| planted trend edge, weak (drift +-0.25% a day) | 19 of 100 = 19% (13% to 28%) | 0.35 | 23 | 0 |
| planted trend edge, strong (drift +-0.40% a day) | 60 of 100 = 60% (50% to 69%) | 1.35 | 109 | 0 |

Confirmation with the final code on 25 fresh datasets per world (different seeds):

| world | any family admitted | families admitted per dataset |
| --- | --- | --- |
| no skill, mild drift (buy-and-hold Sharpe about 0.2) | 5 of 25 = 20% (9% to 39%) | 0.28 |
| no skill, strong drift (buy-and-hold Sharpe about 0.8) | 7 of 25 = 28% (14% to 48%) | 0.36 |
| planted trend edge, weak (drift +-0.25% a day) | 6 of 25 = 24% (11% to 43%) | 0.36 |
| planted trend edge, strong (drift +-0.40% a day) | 11 of 25 = 44% (27% to 63%) | 1.28 |

Pooled over the 125 datasets per world (the 100 used to choose the limit plus the 25 fresh ones), A3 at 0.05, and for comparison at 0.03:

| world | any family admitted at 0.05 | at 0.03 |
| --- | --- | --- |
| no skill, mild drift (buy-and-hold Sharpe about 0.2) | 17 of 125 = 14% (9% to 21%) | 15 of 125 = 12% (7% to 19%) |
| no skill, strong drift (buy-and-hold Sharpe about 0.8) | 23 of 125 = 18% (13% to 26%) | 15 of 125 = 12% (7% to 19%) |
| planted trend edge, weak (drift +-0.25% a day) | 25 of 125 = 20% (14% to 28%) | 19 of 125 = 15% (10% to 23%) |
| planted trend edge, strong (drift +-0.40% a day) | 71 of 125 = 57% (48% to 65%) | 50 of 125 = 40% (32% to 49%) |

The limit was picked on the first 100 datasets, so their figures are a little optimistic; the fresh 25 are the honest check, and they came out higher in the no-skill worlds (20% and 28%, with wide intervals) and lower in the strong-edge world (44%). The pooled figures are the best single estimate: about one no-skill dataset in six admits something, and a strong planted edge is found in about six out of ten.


### The choice of the limit for gate A3

Share of the 100 datasets per world with at least one family admitted, for different limits of the validation timing p-value (the other gates unchanged). Computed from the stored records; no new simulation is needed because the limit only changes the cut-off.

| A3 limit | null_mild | null_drift | planted_weak | planted_strong |
| --- | --- | --- | --- | --- |
| 0.01 | 5% | 3% | 10% | 28% |
| 0.02 | 11% | 6% | 12% | 33% |
| 0.03 | 12% | 9% | 15% | 40% |
| 0.05 | 12% | 16% | 19% | 60% |
| 0.075 | 16% | 21% | 23% | 65% |
| 0.1 | 23% | 29% | 39% | 73% |
| 0.15 | 34% | 38% | 46% | 81% |

On the first 100 datasets, a limit of 0.05 keeps the false-admission share in the no-skill worlds at 12% and 16% and admits something in 60% of the strong-edge datasets. A weak edge is mostly invisible with this much history: the weak world admits something in 19% of datasets, barely above the no-skill worlds.

### How often each gate is passed

Share of (dataset, family) pairs that pass each gate, for the version at the time of the run (A3 at 0.10):

| world | A1 trades | A2 information ratios | A3 timing p | A4 stability | A5 doubled costs |
| --- | --- | --- | --- | --- | --- |
| null_mild | 91% | 29% | 9% | 42% | 80% |
| null_drift | 91% | 27% | 8% | 63% | 94% |
| planted_weak | 86% | 42% | 17% | 42% | 75% |
| planted_strong | 86% | 62% | 30% | 53% | 82% |

## What an admission means

- An admission is not evidence of an edge. If the Bitcoin data were noise like the no-skill worlds, the chance that at least one of the twelve families is admitted is roughly 14% to 18% (pooled estimate), and when something is admitted it is usually one or two families.
- If there were a strong trend edge of the planted kind, the chance is about 57% (pooled). A weak edge is very likely to be missed.
- The mean-reversion families were almost never admitted in the planted worlds (their timing is worse than random there), which is the right answer, and a few times in the no-skill worlds, which is the false-alarm rate.
- Trend families that look alike (the 15 crossover pairs, the Donchian lengths) are strongly correlated, so several admissions in one dataset usually count as one idea; the registry flags such renamed copies.
- Admission only opens a shadow paper account. Promotion to the main portfolio needs a forward record and much stronger evidence (gates P1 to P6), and the same data cannot supply it.

## What this does not show

- That the real market behaves like these worlds. It does not. The calibration shows the procedure does not hallucinate edges from drift and can detect a strong, persistent, simple trend structure; it says nothing about whether such a structure exists in Bitcoin.
- The power for realistic effect sizes. A trend edge that is real but small (an information ratio of 0.3 to 0.5 a year) is far below what 5 to 7 years of daily data can establish; the weak world is the closest to that.
- The behaviour on data with other features (a bear market without drift, volatility regimes, gaps). More worlds can be added; every change to the gates would be a new protocol version.

## Thirteen families (added 2026-11-15 under protocol 1.3, before the thirteenth family was run on the real data)

The protocol's first lesson is to test every gate for feasibility before a run. For a calendar rule, `monday` (family 13, `strategies/monday.md`), two gates were doubtful on paper: the stability gate A4 needs neighbours (a weekday has none; see amendment v1.3) and the random-timing test of A3 shifts the rule's schedule by whole days (for a weekly schedule, one shift in seven puts the rule back on the same weekday). Both were checked on synthetic data, before the real data was touched, by running the new family alone through selection and the admission gates (`calibration.run_family_world`; about 0.1 s a dataset). Nothing here reads the real candles.

Two new kinds of world: the no-skill worlds above (no weekday effect at all), and three worlds with **a planted Monday premium** (independent daily returns, drift 0.04%, volatility 3.5%, plus 0.3%, 0.6% or 1.0% on every Monday candle). A Monday-only holder pays about 0.30% of the account in fees and slippage every week (0.60% at the doubled costs of gate A5), so 0.3% is exactly the cost of a round trip and 0.6% the level of A5.

Share of datasets in which `monday` alone was admitted (95% interval): the first 100 seeds and the 25 fresh seeds are the ones used for the twelve-family table above; the 1,000 are seeds 1001 to 2000.

| world | first 100 seeds | fresh 25 seeds | 1,000 further datasets |
| --- | --- | --- | --- |
| no skill, mild drift | 1 of 100 = 1.0% | 0 of 25 | **1 of 1,000 = 0.1% (0.0% to 0.6%)** |
| no skill, strong drift | 1 of 100 = 1.0% | 0 of 25 | **2 of 1,000 = 0.2% (0.1% to 0.7%)** |
| Monday premium 0.3% | 10 of 100 = 10.0% | 1 of 25 | **57 of 1,000 = 5.7% (4.4% to 7.3%)** |
| Monday premium 0.6% | 36 of 100 = 36.0% | 9 of 25 | **294 of 1,000 = 29.4% (26.7% to 32.3%)** |
| Monday premium 1.0% | 68 of 100 = 68.0% | 17 of 25 | **708 of 1,000 = 70.8% (67.9% to 73.5%)** |

What the gates did on the 1,000 datasets of each world (share of datasets in which the gate failed; A1 never failed, about 450 to 500 position changes on TRAIN plus VALIDATION):

| world | A2 (information ratio, both periods) | A3 (timing p at most 0.05) | A4 (own TRAIN Sharpe above zero) | A5 (doubled costs) | share with timing p at most 0.05 |
| --- | --- | --- | --- | --- | --- |
| no skill, mild drift | 97% | 95% | 76% | 98% | 4.9% |
| no skill, strong drift | 98% | 95% | 64% | 95% | 4.6% |
| Monday premium 0.3% | 80% | 83% | 37% | 82% | 17.2% |
| Monday premium 0.6% | 42% | 61% | 8% | 33% | 39.3% |
| Monday premium 1.0% | 5% | 29% | 0% | 1% | 71.4% |

What this says.
- **The timing test is not broken by the weekly schedule.** On pure noise its p-value was at most 0.05 in 4.9% and 4.6% of datasets, as it should be, even though its null contains near-copies of the rule. The near-copies make it harder to pass for a real effect, not easier for a false one.
- **A2 and A5 are mostly cost hurdles for this rule.** With no weekday effect the rule loses its weekly costs against a hold that pays almost none, so A2 and A5 fail in 95% to 98% of datasets; with a premium of 0.3% (equal to the cost of a round trip) they still fail in about 80%.
- **The false-admission rate of the new family is very low (0.1% to 0.2%) and its power is limited.** A premium of 0.6% a day was found in about three datasets in ten and one of 1.0% in about seven in ten; one of 0.3% almost never. The procedure cannot see a Monday premium much below 0.6% a day, and it could not be kept after costs anyway. So **a rejection of `monday` will mean that no premium of about 0.6% a day or more was present, not that there is no Monday effect**, and an admission would be an unusual event by luck on this kind of data (about 1 in 700), though real prices have fat tails and volatility clusters that these worlds do not.

The twelve-family table above is unchanged by the thirteenth family, which is evaluated on its own. The share of no-skill datasets in which at least one of the thirteen families is admitted is at most the old share plus the new family's admissions on the same seeds (an upper bound, because the per-dataset records of the twelve were not kept):

| world | twelve families, first 100 seeds | thirteen, at most | twelve, pooled 125 | thirteen, at most |
| --- | --- | --- | --- | --- |
| no skill, mild drift | 12 of 100 | 13 of 100 | 17 of 125 = 13.6% | 18 of 125 = 14.4% |
| no skill, strong drift | 16 of 100 | 17 of 100 | 23 of 125 = 18.4% | 24 of 125 = 19.2% |

Still about one no-skill dataset in six. These are independent normal returns with a premium on one weekday: real Bitcoin has fat tails, volatility clusters and structural breaks, so the real false-admission rate of any family is unknown.

Reproduce (about 2 minutes a world on one core):

```bash
cd atlas/backend
PYTHONDONTWRITEBYTECODE=1 python -m atlas_api.btcquant.calibration planted_monday_mid 1001 2001 /tmp/monday_mid.json monday
```

The worlds are `null_mild`, `null_drift`, `planted_monday_small`, `planted_monday_mid` and `planted_monday_big`; the records are not committed.

## Fourteen families (added 2026-11-17 under protocol 1.4, before the fourteenth family was run on the real data)

`three_down` (family 14, `strategies/three_down.md`) is a short-term reversal rule: it buys at the open after the n-th lower close in a row (n = 2, 3 or 4) and sells at the open after the first close that is not lower, with the protocol's 3 x ATR stop and 1% risk sizing. On paper two gates were doubtful: the stability gate A4 (the three settings are nested, and every neighbour must keep 70% of the chosen one's Sharpe ratio) and the random-timing test A3 (a schedule of 20 to 90 short trades in two years is a small sample). Both were measured, with the other gates, before the real data was touched, by running the new family alone through selection and the five gates (`calibration.run_family_world`; about 0.1 s a dataset). Nothing here reads the real candles.

Three new worlds with **a planted reversal premium**: independent daily returns, drift 0.04%, volatility 3.5%, plus 0.3%, 0.6% or 1.0% on every candle that follows three or more lower closes in a row (about one candle in eight). A trade costs about 0.30% of the amount traded and lasts about two candles (one, plus one more for each further lower close), so a premium of about 0.15% a candle held pays for the trade and about 0.30% survives the doubled costs of gate A5: the three worlds are 2, 4 and 6.7 times the break-even.

Share of datasets in which `three_down` alone was admitted (95% interval): the first 100 seeds and the 25 fresh seeds are the ones used for the twelve- and thirteen-family tables above; the 1,000 are seeds 1001 to 2000.

| world | first 100 seeds | fresh 25 seeds | 1,000 further datasets |
| --- | --- | --- | --- |
| no skill, mild drift | 2 of 100 = 2.0% | 0 of 25 | **8 of 1,000 = 0.8% (0.4% to 1.6%)** |
| no skill, strong drift | 3 of 100 = 3.0% | 0 of 25 | **8 of 1,000 = 0.8% (0.4% to 1.6%)** |
| reversal premium 0.3% | 5 of 100 = 5.0% | 2 of 25 | **57 of 1,000 = 5.7% (4.4% to 7.3%)** |
| reversal premium 0.6% | 14 of 100 = 14.0% | 4 of 25 | **159 of 1,000 = 15.9% (13.8% to 18.3%)** |
| reversal premium 1.0% | 33 of 100 = 33.0% | 12 of 25 | **383 of 1,000 = 38.3% (35.3% to 41.4%)** |

What the gates did on the 1,000 datasets of each world (share of datasets in which the gate failed; A1 never failed, with at least 32 trades on TRAIN plus VALIDATION in any dataset of any world and a median of 53 to 105):

| world | A2 (information ratio, both periods) | A3 (timing p at most 0.05) | A4 (neighbours keep 70%) | A5 (doubled costs) | share with timing p at most 0.05 |
| --- | --- | --- | --- | --- | --- |
| no skill, mild drift | 84% | 94% | 79% | 74% | 5.9% |
| no skill, strong drift | 86% | 95% | 68% | 61% | 5.2% |
| reversal premium 0.3% | 63% | 87% | 47% | 41% | 12.6% |
| reversal premium 0.6% | 39% | 78% | 22% | 14% | 22.2% |
| reversal premium 1.0% | 18% | 59% | 4% | 2% | 40.7% |

What this says.
- **Every gate can be passed by this kind of rule, and the timing test is the one that limits the power.** With a premium of 1.0% a day after a run (6.7 times the break-even) the family was admitted in 38% of datasets, and A3 failed in 59% of them: VALIDATION alone is two years, which hold about 20 trades of a streak-4 rule and about 90 of a streak-2 rule. A2 and A5 are mostly cost hurdles on noise (they failed in 84% to 86% and 61% to 74%) and stop being obstacles as the premium grows. A4, which was the worry, failed in only 4% of datasets at a premium of 1.0%.
- **The timing test is not broken by short trades.** On pure noise its p-value was at or below 0.05 in 5.9% and 5.2% of datasets, close to the 5% it should be (the 95% interval of 5.9% in 1,000 datasets is 4.6% to 7.5%).
- **The false-admission rate of the new family is low (0.8%) and its power is limited.** A reversal premium of 1.0% a candle was found in about four datasets in ten, one of 0.6% in about 1.6 in ten and one of 0.3% in about one in seventeen. So **a rejection of `three_down` will mean that no premium of about 1% a day or more was present, not that there is no short-term reversal**, and an admission would be unusual by luck on this kind of data (about 1 in 125), though real prices have fat tails and volatility clusters that these worlds do not.
- **The procedure chooses an end setting.** In the planted worlds the chosen setting on TRAIN was 2 in 37% to 42% of datasets, 4 in 57% to 58% and 3 in only 0.4% to 6.7% (on noise: 35% to 44% for 2, 12.7% to 13.5% for 3, 42% to 52% for 4), probably because the score of an end setting averages two Sharpe ratios and so varies more than the middle one's, which averages three, and the best of the three scores is more often an end one. The default of 3 named in the queue is therefore rarely the setting that is tested on VALIDATION. This is how the selection rule of the protocol works for a grid of three; nothing was changed for it.

The twelve- and thirteen-family tables above are unchanged by the fourteenth family, which is evaluated on its own. The share of no-skill datasets in which at least one of the fourteen families is admitted is at most the thirteen-family bound plus the new family's admissions on the same seeds (an upper bound, because the per-dataset records of the earlier families were not kept):

| world | thirteen families, first 100 seeds (at most) | fourteen, at most | thirteen, pooled 125 (at most) | fourteen, at most |
| --- | --- | --- | --- | --- |
| no skill, mild drift | 13 of 100 | 15 of 100 | 18 of 125 = 14.4% | 20 of 125 = 16.0% |
| no skill, strong drift | 17 of 100 | 20 of 100 | 24 of 125 = 19.2% | 27 of 125 = 21.6% |

Every family tried raises the chance of a lucky admission (the point of keeping the queue short): it is now about one no-skill dataset in six to one in five, up from about one in six. These are independent normal returns with a premium after runs of lower closes: real Bitcoin has fat tails, volatility clusters and structural breaks, so the real false-admission rate of any family is unknown.

Reproduce (about 2 minutes a world on one core):

```bash
cd atlas/backend
PYTHONDONTWRITEBYTECODE=1 python -m atlas_api.btcquant.calibration planted_reversal_mid 1001 2001 /tmp/reversal_mid.json three_down
```

The worlds are `null_mild`, `null_drift`, `planted_reversal_small`, `planted_reversal_mid` and `planted_reversal_big`; the records are not committed.

## Reproduce

```bash
cd atlas/backend
PYTHONDONTWRITEBYTECODE=1 python -m atlas_api.btcquant.calibration null_drift 1 51 /tmp/null_drift_1.json
```

Each dataset takes about 10 seconds. The record of the 400 datasets behind the table is not committed (it is large and regenerated by the command above from the seeds 1 to 100 of each world); the confirmation used seeds 201 to 225.
