---
name: atlas-experiments
description: How to run a strategy or signal experiment in ATLAS so a result can be trusted: pre-register the rule and the pass bar, test once, log everything, and say what was not verified. Use before testing any trading idea.
---

<!-- Source: written for this repo from the experiments in atlas/EDGE_PLAN.md (volatility targeting, funding carry, Fed net liquidity) and the rules in STRATEGY_LOOP.md. Own words, no third-party text. Lessons section added 2026-11-14 from experiments 4 and 5. -->

# Running an experiment you can trust

The aim is not to find a winner; it is to find out, cheaply and honestly, whether an idea has an edge. A backtest that was shaped after seeing its result proves nothing.

## Before you run anything
1. **Write the rule with every number in it** (windows, thresholds, costs, caps, data, universe, the date split). Put it in `atlas/EDGE_PLAN.md` under a heading that says "pre-registered" and the time.
2. **Write the pass bar in the same place.** Use conditions that can be checked with numbers and that include a fair comparison: against simply holding, and against the simplest version of the idea (for example "hold the same average amount", "hold the equal-weighted list"). An idea that only beats a straw man has not passed.
3. **Commit and push that file first.** The commit time is the evidence that the bar was set before the result.
4. **Name the known biases** you cannot remove (for example "the coin list is made of coins listed today, so survivors only") and decide in advance how the result will be worded because of them.
5. **Commit the runner and its tests before the first run**, and write any clarification of the wording (what counts as a switch, which weeks of data are "used", how a shuffle is built) into the plan file first. Looking at the DATA's ranges, gaps and units before the run is allowed; looking at returns or any strategy number is not. Say in the log that the data look happened and that nothing was changed because of a result.

## Building the test
- Only use information available at the decision time. Decide at a close, trade at the next open, charge fees and slippage on the amount traded.
- Seal the last 30% of the history. Judge on it. Do not look at it while designing.
- Validate the simulator itself with hand-worked numbers, a no-look-ahead test (a prefix of the series gives the same decisions), a costs test, and agreement with the existing engine in a case both can run.
- Do not fill gaps in the data; report them and make the rule handle them.
- Test the comparison machinery with a planted case and an empty one: data where the rule truly leads price must pass every condition, data where it does not must fail the luck check. Also test the paths that make a run INVALID (a hole in the inputs, a wrong unit): invalid is not a fail, and it prints no performance numbers.
- A random-timing check keeps what the rule holds and breaks only the alignment: shift the rule's own on/off schedule around a circle by whole weeks (same exposure, same weekday for every switch) and compare against many shifts. It separates timing skill from simply holding less in a bad stretch.
- Know exactly what the simulator trades: which weight is first used, whether the last one is ever traded, whether the entry from flat costs money, and test it with a flat price so only costs move the curve.

## Running it
- **Once.** No variants, no "just one more setting", no rescue. A different idea is a new experiment with its own pre-registration.
- Report the numbers for the sealed period and the whole history, and for every comparison named in the bar.

## After
- Say plainly pass or fail against the bar written down. A fail is a result: keep it in the findings log with its numbers.
- A pass is only a candidate. It still needs the library-wide luck check (more rules tried means a higher bar) and a forward record on new data before anyone relies on it.
- Every report states: what improved, what was verified, what was NOT verified, and whether anything passed. Never write that something "makes money".
- Count the cost of searching: each extra test of the same kind makes a lucky winner more likely. Prefer different kinds of ideas over variants of one.

## Lessons from experiments 4 and 5 (2026-11-14)
- **Check a result a second way before believing it, a NEGATIVE one most of all.** Recompute the headline number with a plain, independent method (for example close-to-close) and read what the rule did on a few well-known dates. A wiring bug can fake a failure as easily as a success.
- **Break your own checks on purpose.** Change a limit or skip a test, and confirm a test fails; a check nothing tests is decoration. Do this for every data check a loader makes.
- **When a test fails, find out whether the code or the test is wrong before touching either.** In both experiments the first failures were slips in the test's own arithmetic.
- **Finish the loop in the app.** Add the result to `btclab/experiments_ledger.json` so Signal's Experiments record shows it, update the counts the tests and the browser script expect, and read the screenshot of the newest entry.
- **A rate limit or a refusal is not a result.** Retry a rate limit with a pause (nothing changes in the rule); a host that refuses the client is BLOCKED and the experiment waits for the owner.
