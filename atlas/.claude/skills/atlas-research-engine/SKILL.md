---
name: atlas-research-engine
description: Rules for changing the fundamentals research engine (SEC filings, revenue analysis, Rule of 40, valuation, discovery) in ATLAS. Use before touching atlas/backend/atlas_api/research or discover.
---

<!-- Source: written for this repo from the research engine's own code, tests and past bugs. Own words, no third-party text. -->

# Research engine rules

## Reading SEC company facts
- Facts come as flows (a period with start and end dates) and instants (a single date). Keep form, filing date and accession so every figure can link to its filing.
- A "reported" quarter is a three-month figure the company filed. A "derived" quarter is the difference between cumulative 3, 6, 9 and 12 month totals; the fourth quarter is never filed alone, so it is always derived. Label each as one or the other.
- Trailing twelve months (TTM) needs four consecutive quarters. A gap means TTM is unavailable, not estimated.
- If a figure was restated, the latest filing wins.
- Only US-GAAP filers are covered. Foreign filers (20-F, IFRS) and segment or geography data are not in this data; say "not covered".
- Companies use different concept names for the same thing (revenue has several). Use a fixed fallback order and show which concept was used.

## Growth and ratios
- Growth is undefined (None, with the reason shown) when the base is zero, negative or missing. Never show a made-up percentage.
- Rule of 40 uses free cash flow margin by default; the EBITDA version is shown separately and labelled. State the exact definition on screen and show N/A when an input is missing.
- Per-share figures need a reliable share count; if it is doubtful, show a visible warning.

## Valuation honesty
- Scenarios (bear, base, bull) are estimates and are tagged as such, with their assumptions listed. The reverse DCF shows what the current price implies instead of predicting.
- Evidence grade is never "strong" from a single method. If evidence is thin, the label is "Insufficient evidence", not a forced verdict.
- The label policy (band, minimum evidence, bull/bear ratio) is configuration, not hidden logic.

## Discovery
- A new listing counts as new only when confirmed (pricing date and first trade). Shell companies (SPACs) are labelled and are not offered for research. Foreign depositary shares have their own exclusion reason.
- Unknown filter values are counted as unknown and never pass a filter.
- Candidate scoring needs enough history (eight quarters, known growth, quality inputs, not stale). Cap two per sector; cool down a repeat for 30 days unless something material changed.

## Tests
Use synthetic companies in the SEC format (`backend/tests/research_fixtures.py`), never real-looking invented names for real tickers. Cover five company types: mature, software, loss-making, recent IPO, bank. Every new rule gets a hand-checkable number and a failure-path test.
