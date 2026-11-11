---
name: atlas-experiments
description: How to run a strategy or signal experiment in ATLAS so a result can be trusted: pre-register the rule and the pass bar, test once, log everything, and say what was not verified. Use before testing any trading idea.
---

<!-- Source: written for this repo from the experiments in atlas/EDGE_PLAN.md (volatility targeting, funding carry) and the rules in STRATEGY_LOOP.md. Own words, no third-party text. -->

# Running an experiment you can trust

The aim is not to find a winner; it is to find out, cheaply and honestly, whether an idea has an edge. A backtest that was shaped after seeing its result proves nothing.

## Before you run anything
1. **Write the rule with every number in it** (windows, thresholds, costs, caps, data, universe, the date split). Put it in `atlas/EDGE_PLAN.md` under a heading that says "pre-registered" and the time.
2. **Write the pass bar in the same place.** Use conditions that can be checked with numbers and that include a fair comparison: against simply holding, and against the simplest version of the idea (for example "hold the same average amount", "hold the equal-weighted list"). An idea that only beats a straw man has not passed.
3. **Commit and push that file first.** The commit time is the evidence that the bar was set before the result.
4. **Name the known biases** you cannot remove (for example "the coin list is made of coins listed today, so survivors only") and decide in advance how the result will be worded because of them.

## Building the test
- Only use information available at the decision time. Decide at a close, trade at the next open, charge fees and slippage on the amount traded.
- Seal the last 30% of the history. Judge on it. Do not look at it while designing.
- Validate the simulator itself with hand-worked numbers, a no-look-ahead test (a prefix of the series gives the same decisions), a costs test, and agreement with the existing engine in a case both can run.
- Do not fill gaps in the data; report them and make the rule handle them.

## Running it
- **Once.** No variants, no "just one more setting", no rescue. A different idea is a new experiment with its own pre-registration.
- Report the numbers for the sealed period and the whole history, and for every comparison named in the bar.

## After
- Say plainly pass or fail against the bar written down. A fail is a result: keep it in the findings log with its numbers.
- A pass is only a candidate. It still needs the library-wide luck check (more rules tried means a higher bar) and a forward record on new data before anyone relies on it.
- Every report states: what improved, what was verified, what was NOT verified, and whether anything passed. Never write that something "makes money".
- Count the cost of searching: each extra test of the same kind makes a lucky winner more likely. Prefer different kinds of ideas over variants of one.
