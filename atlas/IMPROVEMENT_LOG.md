# Improvement log

Newest entry first. Written by the scheduled improvement loop (see `LOOP.md`) and by hand.

## 2026-11-07, cycle 4: small source and date captions are readable on every card
- **Found:** the grey captions that carry each figure's source and date (for example "SEC EDGAR 10-K · as of 2026-12-31") were close to invisible on the brighter top Discover card (contrast about 1.1 to 1), and below the accessibility minimum on ordinary cards too (about 2.9 to 1 at the top of a card). Those captions are how the app keeps its "every number has a source and a date" promise.
- **Changed:** the "faint" text colour is lighter (`#9AA0AB`) and the highlight card is a cooler, darker steel-blue instead of a bright grey. The silver and graphite look is unchanged elsewhere. New `lib/contrast.ts` and a unit test that fails if small captions or secondary text drop below 4.5:1 on any card gradient stop or on the screen background.
- **Verified:** phone unit tests (37, two new), phone type check, backend 830 tests, web checks, browser suite 44 of 44; viewed the new Discover screenshot, captions now clear.
- **Not verified:** the terminal's small captions use a different CSS palette and were not measured this cycle.
- **Next candidates:** run the same contrast check on the terminal's CSS colours; Stocks empty-state suggestions; loading states for Discover and Strategy Lab on the phone.

## 2026-11-07, cycle 3: the silver glow no longer ends in a hard edge
- **Found:** on every phone tab the glow behind the header stopped in a visible straight edge about 300 points down (the right-hand corner of the second gradient was still slightly lit where the box ended).
- **Changed:** `TopGlow` now ends with a final fade into the screen colour, so no corner can end abruptly. One small change in `Gradient.tsx`; no colours or layout changed.
- **Verified:** phone type check and unit tests, backend 830 tests, web checks, browser suite 44 of 44; compared before and after screenshots of the Stocks, Journal and Macro tabs: the edge is gone.
- **Not verified:** a real phone's GPU rendering (checked in the browser only).
- **Next candidates:** Stocks empty-state suggestions; loading states for Discover and Strategy Lab on the phone; keyboard shortcuts for the five terminal desks.

## 2026-11-07, cycle 2: a plain Journal note is no longer tagged "Long"
- **Found:** a note with only a symbol and some text (no size or prices) showed a "Long" tag in the phone list and "long" in the terminal table, because the form's side defaults to long. That reads as if a position had been taken.
- **Changed:** notes now show "Note" instead of a side (phone tag, accessibility label, terminal table); trades still show Long or Short. New helper `sideLabel` with a unit test; the browser test now fails if a bare note ever looks like a long or short.
- **Why this one:** it is a misleading label in a place where a beginner records their own decisions; honesty beats polish.
- **Verified:** backend 830 tests, web and phone type checks and unit tests (phone 35), browser suite 44 of 44; viewed the new Journal screenshot.
- **Still open:** the top-of-screen silver glow ends in a faint hard edge near 600px on every phone tab (add a final fade to the background colour): next cycle's candidate. Also: Stocks empty-state suggestions; loading states for Discover and Strategy Lab.

## 2026-11-07, cycle 1: Macro says "indicators unavailable" once, in plain words
- **Found:** with the official data unreachable, the Macro screen listed eight red rows reading "Unavailable: unavailable (CPIAUCSL)": repetitive, and raw series codes mean nothing to a beginner.
- **Changed:** `macro_brief.py` now returns an empty indicator list plus one `indicators_note` when none load (a different note in demo mode). A single failed indicator among working ones stays listed, with a plain reason ("no data came back from the source"). The technical detail stays in the "Some sources failed" box. Phone and terminal show the note.
- **Why this one:** it affects every first-time user who has no connection to FRED, and it keeps the honesty rule (missing data is said to be missing) while being readable.
- **Verified:** backend 830 tests pass (2 new, 1 updated because it asserted the old raw-code wording), web and phone type checks and unit tests pass, browser suite 44 of 44 including a stricter Macro check; viewed the phone screenshot.
- **Not verified:** live FRED data from the sandbox (indicators show as unavailable here).
- **Next candidates:** the top-of-screen glow ends in a faint hard edge near 600px on phone screens (add a final fade to the background colour); Stocks empty state could offer one-tap suggestions; Discover and Strategy Lab phone loading states.

## 2026-11-06: loop set up
- Added `LOOP.md` (the rules and the cycle) and this log.
- State at start: Signal phone app and ATLAS terminal both have the five destinations (BTC, Stocks, Macro, Discover, Journal), the BTC Strategy Lab, Stock Research, Macro Intelligence, Discover and the Journal, in the silver gradient look.
- Not yet verified against live data: Yahoo prices (blocked in the sandbox), so Discover prices, earnings dates and stock valuation have only been tested with fakes.
- Known gaps (see the backlog in `LOOP.md`): Discover covers about 100 large caps; Macro shows only the 2-year and 10-year yields; PCE and GDP release dates are not loaded.
