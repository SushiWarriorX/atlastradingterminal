# Capability inventory (goal: +5% over baseline)

Owner goal (2026-11-09): grow the system's tools and skills by at least 5% so the product keeps improving. Count only things that exist and are tested/logged; never pad.

Baseline counted 2026-11-09:
| Kind | Count | Where counted |
| --- | --- | --- |
| Live data sources | 29 (now 35) | `DATA_SOURCES.md` LIVE table |
| Strategy library rules | 31 (now 39) | `btclab/strategies.py` (tracker ledger holds 11 frozen) |
| AI desk tools | 7 | `backend/atlas_api/ai/tools.py` |
| Repo skills | 0 (now 3) | `atlas/.claude/skills/` |
| **Total** | **67** | |

Target: at least 71 (67 x 1.05 = 70.35, rounded up). Each loop adds its own kind; update the table and the current total when something ships.

Current total: 88 (baseline 67 + 8 strategies + 3 skills + 10 data sources). Note: `nr7_breakout` behaves like buy-and-hold on BTC history (see log), so it adds to the count but little else. Target of 71 reached on 2026-11-09; keep adding only what fills a real gap.

## Added since baseline
| Date | Kind | Name | Source/loop |
| --- | --- | --- | --- |
| 2026-11-09 | Strategy | `mayer_cap` | Strategy loop |
| 2026-11-09 | Strategy | `donchian_mid` | Strategy loop |
| 2026-11-09 | Strategy | `hull_trend` | Strategy loop |
| 2026-11-11 | Skill | `atlas-experiments` (repo skill: pre-register, test once, log everything) | Skills loop |
| 2026-11-11 | Data source | Coinbase daily candles for 28 coins (multi-asset research) | Data loop |
| 2026-11-10 | Data source | NY Fed primary dealer Treasury positions | Data loop |
| 2026-11-10 | Data source | Treasury marketable borrowing (Daily Treasury Statement) | Data loop |
| 2026-11-10 | Data source | Treasury bill auction results | Data loop |
| 2026-11-10 | Strategy | `kama_trend` | Strategy loop |
| 2026-11-10 | Data source | Treasury buyback operations | Data loop |
| 2026-11-10 | Strategy | `nr7_breakout` (degenerate: acts like holding) | Strategy loop |
| 2026-11-09 | Strategy | `pi_cycle` | Strategy loop |
| 2026-11-09 | Strategy | `heikin_trend` | Strategy loop |
| 2026-11-09 | Strategy | `trix_cross` | Strategy loop |
| 2026-11-09 | Data source | Treasury interest expense on the public debt | Data loop |
| 2026-11-09 | Skill | `atlas-loop-rules` (repo skill) | Skills loop |
| 2026-11-09 | Skill | `atlas-research-engine` (repo skill) | Skills loop |
| 2026-11-11 | Data source | CFTC futures positioning (S&P 500, Nasdaq-100, 2-year and 10-year Treasury, dollar index) | Data loop |
| 2026-11-11 | Data source | CFTC commodity positioning (gold, crude oil, copper, natural gas) | Data loop |
| 2026-11-11 | Data source | US Treasury real (TIPS) yields and breakeven inflation, 5 to 30 years | Data loop |
| 2026-11-11 | Data source | CFTC currency and volatility positioning (euro, yen, pound, VIX futures) | Data loop |

## Loop budget (measured 2026-11-09)
- Strategy cycle with 3 rules and the full backend suite: about 4 minutes wall time. Improvement cycle with all suites: roughly 20 to 45 minutes. Skills and data cycles: a few minutes each, data often blocked by hosts the sandbox cannot reach.
- Strategy loop has a natural limit: 7 queue ideas left and a stop at 60 rules (library is 34), so at most about 9 more cycles before it needs new ideas or your decision.
- The real daily limit is your usage quota, which this repo cannot measure. Recommended plan: strategy up to 9 cycles then pause, data 12, skills 6, improvement 4.

