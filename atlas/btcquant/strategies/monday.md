# Day-of-week holding (`monday`)

Protocol family 13, the only family pre-registered under protocol 1.3 · category: calendar · account kind: weight · written 2026-11-15, before any run of this family. No result of it has been looked at: the returns of Mondays in the real candles have not been computed (the novelty screen in `RESEARCH_QUEUE.md` compared only WHEN the rule is invested with when the other families are, never what it earned).

## Hypothesis
Bitcoin earns more on Mondays (UTC) than on other days of the week. Holding it only through Mondays and being in cash the other six days would earn that premium while being invested one day in seven.

## Why it might work
- Several studies report a Monday effect in Bitcoin: Caporale and Plastun (2017), CESifo Working Paper 6716, found Monday returns higher and reported that a trading simulation showed profit opportunities; Aharon and Qadan (2019), "Bitcoin and the day-of-the-week effect", report effects in returns and volatility in daily data for 2010 to 2017; Kahraman and Kök (2024) report a Monday effect in Bitcoin and Ether and a rule that beat random investment. **Status of these sources: abstracts and summaries returned by a web search on 2026-11-15; none was read in full, and volumes and pages are not confirmed** (`SOURCES.md`).
- **Against:** Baur et al., on seven exchanges, found day-of-week effects that varied over time with no persistent pattern and concluded that Bitcoin is weak-form efficient (also a summary only).
- The samples of the supporting studies mostly end before 2020, which is where this evaluation starts, and they use other exchanges and possibly other day boundaries. This family therefore tests the claim on data most of those studies did not cover.

## Where it should work, and where it should fail
It can work only if a Monday premium exists in 2020 to 2024, persists, and is larger than what trading it costs. A round trip every week costs 0.30% of the account (0.10% fee plus 0.05% slippage, each way), about 15.6% a year, against a position held one day in seven: the premium must exceed 0.30% per Monday just to pay for itself, and 0.60% to survive the doubled costs of admission gate A5. It should fail wherever the effect is absent or time-varying (the contrary evidence above), and a calendar rule has no stop that means anything, so a violent Monday is taken in full.

## Rules (completed daily candles only; the decision is made at the close of candle i and the order executes at the open of candle i+1)
- The target weight at the close of every candle is 1 if that candle is a Sunday (UTC) and 0 otherwise. A Sunday close therefore orders a purchase of the whole account at the Monday 00:00 UTC open, and the Monday close orders the sale at the Tuesday 00:00 UTC open: the account is in Bitcoin through the Monday candle. The weekday is taken from the candle's own open time (day 0 of the epoch, 1970-01-01, was a Thursday). Nothing but that timestamp is read: no price, no volume, no indicator, no warm-up.
- No stop. Every day is UTC; no local time, daylight saving or exchange calendar is involved.

## Position sizing
Weight mode: 100% of equity through the Monday candle, flat otherwise. The 1% risk rule does not apply because there is no stop (section 4 of the protocol exempts weight mode); the account's risk control is the 15% circuit breaker.

## Parameters (fixed grid; no value outside it may be tried without a new version)
Grid: {"day": [0]}
Configurations: 1

`day` is the weekday held, 0 = Monday. **Changed from the queue's planned grid before any run.** `RESEARCH_QUEUE.md` planned the weekday held as a grid of seven (Monday to Sunday). It is one configuration because every source claims Monday and none claims another day (six of the seven would test nothing anyone published), because a weekday is a category (the selection by neighbours and the stability gate A4 of the protocol have no meaning for it: the neighbour of Monday would be Tuesday), and because six more configurations would raise the number of trials for no hypothesis. The code accepts any weekday (a test uses all seven); the grid does not. Trying another day would be a new version.

## Costs and risk limits
Fee 0.10% and slippage 0.05% per side on the whole account, twice a week of trading (a purchase and a sale): the four cost settings of the sensitivity runs apply. Cash earns nothing. Capped at 100% of equity, no leverage, no shorting. Circuit breaker at 15% below the running peak (research accounts resume after a 30-day cool-off).

## Failure modes
- Idea: no effect after 2019; an effect that is an artefact of where the day boundary falls (the data here cut the day at 00:00 UTC); an effect smaller than the 0.30% weekly cost; one exchange's prices; a single weekday picked from the literature and tested on a sample the literature did not cover.
- Implementation: the weekday read from the wrong end of the candle (a test checks the second before midnight); an off-by-one between the candle that is held and the candle that gives the order (a test follows a Sunday close to the Monday open and a hand-worked cost chain through the account engine); look-ahead (none is possible: the rule reads only the candle's own timestamp, and the future-perturbation test covers it).

## Gates, as amended for this family (protocol 1.3)
Gates A1, A2, A3 and A5 apply as written. A4 (parameter stability) has no neighbours to look at, so it asks only that the configuration's own TRAIN Sharpe ratio is above zero and is reported as "not applicable (one setting)", never as "stable". The random-timing test of gate A3 shifts the rule's own on/off schedule around a circle by whole days; for a weekly schedule one shift in seven puts the rule back on a Monday, so its null contains near-copies of itself. That makes the test harder to pass for a real effect, not easier for a false one (on pure noise its p-value was at or below 0.05 in 4.6% to 4.9% of 2,000 synthetic datasets). Measured on synthetic data, before the real run (`CALIBRATION.md`, thirteen families): the family alone is admitted in 0.1% to 0.2% of no-skill datasets; with a planted Monday premium of 0.3% a day in 6% of datasets, of 0.6% in 29%, of 1.0% in 71%.

## Expectation written down before running
**Rejected.** The most likely reasons are gates A2 and A5, which are largely cost hurdles for a rule that trades every week: a Monday premium would have to be well above 0.30% a day to show, and the procedure sees a premium of 0.6% a day only about three times in ten. **"Rejected" will therefore mean that no Monday premium large enough to see and to keep after costs was present in 2020 to 2024. It will not mean that there is no Monday effect.** "Too thin to judge" cannot happen (about 450 position changes on TRAIN plus VALIDATION). If it were admitted, that would be unusual by luck on the synthetic data (about 1 in 700), but real prices have fat tails and volatility clusters that the synthetic data do not, so the real false-admission rate is unknown; admission would be a reason to watch the paper account, not evidence of an edge.

## Sources
Caporale and Plastun (2017); Aharon and Qadan (2019); Kahraman and Kök (2024); Baur et al. (against). Details, and what each source does and does not show, are in `SOURCES.md`.
