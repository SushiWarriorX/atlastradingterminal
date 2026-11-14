# What seven pre-registered experiments tell us (2026-11-14)

Research only. Nothing here is advice, and nothing here says any rule makes money.

## The short answer

**Nothing I tested is credibly profitable.** No rule beat simply holding Bitcoin by a margin that survived a bar written down before the run, so the search is **paused**. That is a statement about these ideas on free public data, not a proof that no edge exists anywhere.

## What "tested" means here

- Every idea had its rule and its pass bar written down and pushed to the repository **before** any code or result existed, was run **once**, and was never retuned. A failure is kept and shown, not deleted.
- The last 30% of Bitcoin's history was held back for judging (for the latest five, 22 June 2023 to 13 November 2026). Fees and slippage are included; cash earns nothing.
- To pass, a rule needed all of: a return-per-unit-of-risk (Sharpe) at least 0.10 above holding, a result better than 95% of random placements of its own on/off timing, a worst drop at least 10 points shallower than holding's, and a positive return after costs with enough switches.
- Before these seven, 40 or more single-Bitcoin price rules (trend, breakout, oscillators and so on) were tested the same way: none beat holding with an evidence label of "moderate" or better.

## The seven

| # | Idea | Information used | Judged result against holding | Verdict |
| --- | --- | --- | --- | --- |
| 1 | Hold less Bitcoin when it has been jumping around | Bitcoin's own price | +116.8% against +159.3% | Failed |
| 2 | Each week hold the five coins (of 28) that rose most in 90 days | Coin prices | +206.2% against +174.6%, but a worst drop of -63.0% against -53.1% and a lower Sharpe than Bitcoin | Failed one condition (near miss); the coin list is flattered by survivors |
| 3 | The same, only while Bitcoin is above its 200-day average | Coin prices | +345.2% against +174.6%, worst drop -60.0% against -53.1% | Failed one condition (near miss); same survivor flattery; a second look at one idea |
| 4 | Hold Bitcoin, short the future, collect funding when it beats bills | Derivatives funding rates | +0.66% a year against 3.78% in bills over the last year | Failed (it paid well in 2024, not lately) |
| 5 | Hold Bitcoin only while US net liquidity is rising | The Fed's balance sheet | +25.4% against +127.2%; random timing did as well 62% of the time | Failed |
| 6 | Hold Bitcoin only while miners are not stressed | Mining power (hash rate) | +47.4% against +127.2%; random timing did as well 60% of the time | Failed |
| 7 | Hold Bitcoin only while the Nasdaq is above its 200-day average | US stock prices | +73.1% against +127.2%; random timing did as well 73% of the time | Failed |

The judged windows ended on different days, so the "holding" figure differs between rows.

## What I think it means

1. **Holding Bitcoin is what made money in this data** (+24,249% since 2015 and +127% in the last 3.4 years), but it came with drops of -53% to -84%. That is a bet on a risky asset continuing to rise, not an edge a rule found, and nothing here says it will continue.
2. **Rules that cut exposure gave up return and mostly missed the biggest fall** (Bitcoin from about $125,000 in October 2025 to about $58,500 in June 2026). That fall was specific to crypto: stock prices, Fed liquidity and mining power did not warn in time.
3. **The one thing that looked good on a long sample was the Nasdaq filter over 2015 to 2023** (+52,964% against +24,249% over the whole history, with a shallower worst drop). It rests on two bear markets (late 2018 and 2022) and did not repeat in the judged years. That is a reason for care and for asking for forward evidence, not a reason to trade it.
4. **Failure is the expected outcome.** Simple rules on free daily data are crowded, and the bar is strict on purpose. Each failure rules something out.
5. **Limits:** one asset, one market cycle in the judged window, survivor bias in the coin list, and only the data free sources offer (no options, order books or on-chain valuation; the hosts for those are blocked in this environment).

## What would change this answer (not a promise)

- **Forward evidence:** a rule fixed in advance and followed on new data for at least 60 days. The 19 frozen rules in the tracker were frozen between 8 and 10 November, so the first 60-day mark is **7 January 2027** (all 19 currently rate "weak" or "none" for evidence).
- **Different data:** on-chain valuation and a longer Bitcoin price history need two hosts allowed in the environment's network settings (`community-api.coinmetrics.io`, `www.bitstamp.net`).
- **An idea of yours,** pre-registered the same way. One of my eight planned slots is unused and reserved for it (or for Fear & Greed, which I rate weak because most of it is built from Bitcoin's own price, by the index's published description, which I did not re-check from this machine).

## Decisions waiting for you

1. Keep the search **paused** (my recommendation), or spend the last slot.
2. Optional: allow the two hosts above.
3. What should the cloud image serve now? The Docker files still try to build the removed terminal.
4. ETF price histories (send CSV exports, or allow automated pulls), only if the ETF idea is wanted.
5. Set the SEC contact setting on your PC to switch on SEC filings in Signal.
6. Whether Signal may show the Cboe VIX, the Freddie Mac mortgage rate and the University of Michigan consumer sentiment from FRED: each is third-party copyrighted data that FRED reprints with permission (licence line "Copyrighted: Citation Required", read on 14 November). The ICE credit spreads are different: their licence line is "Pre-Approval Required" (reproduction needs ICE's own written permission), so they stay off unless ICE gives it.
7. Run `pip install --upgrade` inside your `.signal-venv` to bring an older install level.

Full numbers for each experiment are in `EDGE_PLAN.md` (findings log); the raw output of experiments 4 to 7 is in `docs/experiment4_result.json` to `docs/experiment7_result.json`; and the app shows the record under Bitcoin, "Experiments record".
