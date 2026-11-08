# Skills log

Newest first. Decision: SUGGESTED (card offered, user decides) / ADOPTED (our own note in AGENT_NOTES.md) / REJECTED.

| Date | Candidate | Source | Decision | Why |
| --- | --- | --- | --- | --- |
| 2026-11-08 | Data (Anthropic): validate-data, statistical-analysis | Plugin catalog | SUGGESTED | Fits checking each new data source and backtest statistics. Install card shown; user decides. |
| 2026-11-08 | Our own project notes | This repo | ADOPTED | `atlas/AGENT_NOTES.md`: lessons from this build (bars per year, sealed holdout, source checks, tooling traps) in our own words. |
| 2026-11-08 | Playwright (Microsoft MCP) | Plugin catalog | REJECTED | Playwright is already installed here and our browser tests use it. |
| 2026-11-08 | E2E Test Generator (community) | Plugin catalog | REJECTED | We already have scripted end-to-end suites; marginal gain. |
| 2026-11-08 | QuanterLab, Spera, Blocksize Market Data | Plugin catalog | REJECTED | Need an outside account and overlap the Strategy Lab. Spera and QuanterLab are strategy platforms; not adding third-party accounts without the user asking. |
| 2026-11-08 | FXMacroData (community) | Plugin catalog | DEFERRED | Official-source macro, central-bank and COT data is relevant, but it runs through an outside account and its price and terms are unknown. Raise with the user before anything is set up. |
| 2026-11-08 | Finance, InternetData, Kobiton Testing | Plugin catalog | REJECTED | Accounting, IP databases and mobile device testing: not a fit. |
| 2026-11-08 | A11y Enforcer: WCAG Accessibility Checker (community, runs inside the session only) | Plugin catalog | SUGGESTED | Signal only tests colour contrast today; labels, keyboard and focus are unchecked. Card shown; user decides. |
| 2026-11-08 | Network-fetch checklist | This repo | ADOPTED | Added to `atlas/AGENT_NOTES.md` in our own words, from the last three data sources (timeouts, XML safety, link checks, fixtures). |
| 2026-11-08 | finecomb (security audit checklist) | Plugin catalog | REJECTED | Overlaps the built-in security review; our own short checklist covers what we need. |
| 2026-11-08 | Code Review, claude-code-review-council, code-review-harness | Plugin catalog | REJECTED | The built-in code review already exists. The council plugin also hooks tool calls (broader access than needed). |
| 2026-11-08 | Ireview | Plugin catalog | REJECTED | Sends code to other AI models outside this setup; not without the user asking. |
| 2026-11-08 | Axe Accessibility (Deque) | Plugin catalog | DEFERRED | Good tool, but it connects to an outside server. Raise only if the user wants a deeper accessibility audit than A11y Enforcer. |
