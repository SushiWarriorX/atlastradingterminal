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

## Reproduce

```bash
cd atlas/backend
PYTHONDONTWRITEBYTECODE=1 python -m atlas_api.btcquant.calibration null_drift 1 51 /tmp/null_drift_1.json
```

Each dataset takes about 10 seconds. The record of the 400 datasets behind the table is not committed (it is large and regenerated by the command above from the seeds 1 to 100 of each world); the confirmation used seeds 201 to 225.
