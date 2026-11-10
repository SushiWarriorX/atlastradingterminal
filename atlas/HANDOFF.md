# Shared handoff: Claude and ChatGPT take turns on this repo

Read this first, every cycle, before anything else. Update the STATE BOARD (the table under the heading `## STATE BOARD`, not any other table) last. Times are UTC (change the shift table in one place if the owner moves it).

## Shifts (owner request 2026-11-09)
| Who | Hours (UTC) | Branch it pushes to |
| --- | --- | --- |
| Claude | every hour, all day (owner request 2026-11-10: use the full quota) | `feature/research-modules` |
| ChatGPT | 12:00 to 24:00 | `chatgpt/<job>-<yyyymmdd>`, then a DRAFT pull request into `feature/research-modules` |

ChatGPT works only 12:00 to 24:00 UTC on its own `chatgpt/...` branches; Claude now runs every hour on `feature/research-modules` (the two never write to the same branch). Read `EDGE_PLAN.md` first: strategy hours follow it. If you are unsure of the hour, use `date -u`.

## One job per hour (same rotation for both, by the UTC hour you start)
| Hour (UTC) | Job | | Hour (UTC) | Job |
| --- | --- | --- | --- | --- |
| 00 / 12 | improve | | 06 / 18 | improve |
| 01 / 13 | strategy | | 07 / 19 | strategy |
| 02 / 14 | data | | 08 / 20 | data |
| 03 / 15 | skills | | 09 / 21 | skills |
| 04 / 16 | strategy | | 10 / 22 | strategy |
| 05 / 17 | data | | 11 / 23 | data |

A job means one cycle as written in `LOOP.md` (improve), `STRATEGY_LOOP.md`, `DATA_LOOP.md`, `SKILLS_LOOP.md`. If a job has nothing worth doing, log "no change" and stop; never pad.

## Avoiding collisions
- Strategy queue: Claude takes ideas from the FRONT of the queue, ChatGPT from the BACK. Never take an id the other side has on the state board.
- Log files (`IMPROVEMENT_LOG.md`, `SKILLS_LOG.md`, `DATA_SOURCES.md`, `CAPABILITIES.md`) are append-only. On a merge conflict keep both sides.
- `tracker_ledger.json` and `strategies.py`: only add, never edit another entry. Rebase on the latest `feature/research-modules` before you push.
- Merging is the owner's decision. Nobody merges; ChatGPT's draft PRs wait for the owner. Claude may read them and comment in the state board.
- All hard rules in `.claude/skills/atlas-loop-rules/SKILL.md` apply to both.

## STATE BOARD (update at the end of every cycle: newest first, keep the last 20 lines)
| When (UTC) | Who | Job | What changed | Next suggestion |
| --- | --- | --- | --- | --- |
| 2026-11-10 23:20 | Claude | plan | Wrote `EDGE_PLAN.md` (honest status: none of 40 rules beats holding; carry trade currently ~ bills; next: volatility-targeted holding, cross-sectional momentum); routine now hourly all day | Next strategy hour: build fractional positions in the simulator, then test the volatility-targeted holding rule with settings fixed in EDGE_PLAN.md |
| 2026-11-10 11:17 | Claude | data | NY Fed primary dealer Treasury positions (live; change check passes; maturity breakdown held back, does not add up); `treasury.cjs` now covers five panels; capabilities 82 | Next improve job: the older phone card 'Interest the Treasury pays' shows a raw date (Bills · 2026-10-31). ChatGPT shift starts 12:00 UTC |
| 2026-11-10 10:17 | Claude | strategy | No change (queue empty for Claude; owner decision on strategy hours still pending) | Hour 11 = data; ChatGPT shift starts 12:00 UTC (no ChatGPT branch seen yet) |
| 2026-11-10 09:17 | Claude | skills | Catalog empty (4th time); added four Treasury FiscalData lessons to AGENT_NOTES.md | Hour 10 = strategy: queue empty for Claude (owner decision pending); hour 11 = data |
| 2026-11-10 08:18 | Claude | data | Treasury marketable borrowing (DTS public debt transactions; live; self-check passes); `treasury.cjs` now covers four panels; capabilities 81 | Data queue: DefiLlama TVL (host blocked) only; next data job searches again |
| 2026-11-10 07:24 | Claude | strategy | No change: queue empty on Claude's side; the library covers the classic families and extra look-alike rules only make the luck check stricter | Owner decision: new-data ideas, or give strategy hours to data/improve. ChatGPT may take `zscore_momentum`, `elder_bull` |
| 2026-11-10 06:17 | Claude | improve | Screenshot-checked the terminal Interest, Buybacks and Bills panels (fine); added the Interest bar caption and `web/e2e/treasury.cjs` | ChatGPT shift starts 12:00 UTC; no ChatGPT branch seen yet. Run treasury.cjs after touching Macro panels |
| 2026-11-10 05:17 | Claude | data | Treasury bill auctions (live; source itself ~26 days behind, shown as OVERDUE); capabilities 80 | Queue: DefiLlama TVL (host blocked), Daily Treasury Statement debt issues/redemptions. Terminal Interest, Buybacks and Bills panels still need a screenshot |
| 2026-11-10 04:17 | Claude | strategy | Added kama_trend (trades ~286 times; weak: +59.5% vs hold +177.8% in the last 30%; library 39; capabilities 79) | Queue left: `zscore_momentum`, `elder_bull` for ChatGPT. Claude's front is empty: needs new published ideas with fixed settings |
| 2026-11-10 03:17 | Claude | skills | Catalog empty (3rd time); added five lessons to AGENT_NOTES.md (file edits, table edits, clock-dependent tests, hand-derived numbers, degenerate stops) | Hour 04 = strategy: ChatGPT-free back items `elder_bull`, `zscore_momentum`, `kama_trend`; front of queue is empty for Claude, so propose new ideas or skip |
| 2026-11-10 02:19 | Claude | data | Treasury buyback operations (live; independent sum matches); capabilities 78 | Next data job: queue empty, search again; terminal Interest and Buybacks panels still need a screenshot |
| 2026-11-10 01:17 | Claude | strategy | Added nr7_breakout (acts like buy-and-hold: entered 2015, never exited; label none; library 38; capabilities 77) | Free for ChatGPT from the BACK: `elder_bull`, `zscore_momentum`, `kama_trend`. A trailing NR7 would be a new idea, not a retune |
| 2026-11-10 00:17 | Claude | improve | Interest card/panel read in plain words (month name, sentence comparison), phone e2e now checks it with a real screenshot; fixed my misplaced state-board rows | Look at a screenshot of the terminal Interest panel; ChatGPT shift 12:00 UTC: no branch from ChatGPT yet |
| 2026-11-09 11:21 | Claude | data | Treasury interest expense (live, self-checked against the source's own YTD); capabilities 76 | Next: look at screenshots of the new Interest panel/card; queue now empty, next data job searches for a new free source (Treasury bill auction results already live) |
| 2026-11-09 10:18 | Claude | strategy | Added pi_cycle, heikin_trend, trix_cross (weak/none; library 37; capabilities 75) | Queue front now `nr7_breakout`; ChatGPT back items free: `elder_bull`, `zscore_momentum`, `kama_trend` |
| 2026-11-09 09:17 | Claude | skills | Catalog empty; wrote repo skill `atlas-research-engine` (capabilities 72) | Next Claude hour 10 = strategy (front of queue `trix_cross`) |
| 2026-11-09 | Claude | strategy+skills | Added mayer_cap, donchian_mid, hull_trend (all weak); repo skill; capability count 71 | Strategy queue front now `trix_cross`..; back items free for ChatGPT: `donchian_mid` done, take `elder_bull`, `zscore_momentum` |

## Open items for whoever is next
- Strategy loop: library 34, none credibly profitable; stop at 60 and ask the owner.
- Phone question box in Ask ChatGPT looks blank in headless screenshots; styles verified in the DOM only.
- Not built: Position Scenarios page, research connectors, stock strategy lab, cloud deploy.
- SEC data is unverified live until the owner sets `ATLAS_SEC_CONTACT`.
