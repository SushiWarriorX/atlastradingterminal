# Capability inventory (goal: +5% over baseline)

Owner goal (2026-11-09): grow the system's tools and skills by at least 5% so the product keeps improving. Count only things that exist and are tested/logged; never pad.

Baseline counted 2026-11-09:
| Kind | Count | Where counted |
| --- | --- | --- |
| Live data sources | 29 | `DATA_SOURCES.md` LIVE table |
| Strategy library rules | 31 (now 34) | `btclab/strategies.py` (tracker ledger holds 11 frozen) |
| AI desk tools | 7 | `backend/atlas_api/ai/tools.py` |
| Repo skills | 0 (now 2) | `atlas/.claude/skills/` |
| **Total** | **67** | |

Target: at least 71 (67 x 1.05 = 70.35, rounded up). Each loop adds its own kind; update the table and the current total when something ships.

Current total: 72 (baseline 67 + 3 strategies + 2 skills). Target of 71 reached on 2026-11-09; keep adding only what fills a real gap.

## Added since baseline
| Date | Kind | Name | Source/loop |
| --- | --- | --- | --- |
| 2026-11-09 | Strategy | `mayer_cap` | Strategy loop |
| 2026-11-09 | Strategy | `donchian_mid` | Strategy loop |
| 2026-11-09 | Strategy | `hull_trend` | Strategy loop |
| 2026-11-09 | Skill | `atlas-loop-rules` (repo skill) | Skills loop |
| 2026-11-09 | Skill | `atlas-research-engine` (repo skill) | Skills loop |

## Loop budget (measured 2026-11-09)
- Strategy cycle with 3 rules and the full backend suite: about 4 minutes wall time. Improvement cycle with all suites: roughly 20 to 45 minutes. Skills and data cycles: a few minutes each, data often blocked by hosts the sandbox cannot reach.
- Strategy loop has a natural limit: 7 queue ideas left and a stop at 60 rules (library is 34), so at most about 9 more cycles before it needs new ideas or your decision.
- The real daily limit is your usage quota, which this repo cannot measure. Recommended plan: strategy up to 9 cycles then pause, data 12, skills 6, improvement 4.

