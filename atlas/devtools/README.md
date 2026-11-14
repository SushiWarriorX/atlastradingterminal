# Development tooling

This folder is for developing the project. Nothing in the app or the phone app imports it, and it never touches trading or research execution.

## Development-skills review (`skills_review.py`)

A routine that looks for skills that would help *development* (testing, debugging, security, financial-data validation, backtesting, performance, cloud deployment, mobile usability, documentation), compares them with what is already installed, and tells you only when something is worth your attention. It does not install anything by itself and it is not an AI loop: it uses 0 Claude tokens unless you turn `use_claude` on.

### What it inspects here (checked 2026-11-08)

- A skill is a folder with a `SKILL.md` whose header has a `name` and a `description` (and optionally a `version`), plus optional scripts, references and assets.
- Installed skills live in three places: the project (`.claude/skills/`, none yet), your user folder (`~/.claude/skills/`), and the account-synced folder (`~/.claude/skills/synced/...`). Synced skills are managed by your account: the tool lists them and never modifies them.
- Candidates can come from: a local folder, an inbox file filled with `add-candidate` (this is how skills found by searching the Claude plugin catalog get in, because the catalog search only works inside a Claude Code session), or a public GitHub repository (not reachable from the build machine, so the GitHub path is tested with a mock only; it should work from GitHub Actions).

### Everyday commands (run from the repository root)

```bash
python3 atlas/devtools/skills_review.py run --force      # manual trigger: run the review now
python3 atlas/devtools/skills_review.py status            # last/next run, pending actions, candidate and installed lists
python3 atlas/devtools/skills_review.py inventory         # what is installed and where
python3 atlas/devtools/skills_review.py needs             # the demonstrated development needs it found
python3 atlas/devtools/skills_review.py inspect PATH      # static security check of any skill folder (never executes it)
python3 atlas/devtools/skills_review.py add-candidate NAME --source ... --link ... --version ... --description ... [--path FOLDER]
python3 atlas/devtools/skills_review.py approve NAME [--scope project|user]
python3 atlas/devtools/skills_review.py reject NAME --reason "..."
python3 atlas/devtools/skills_review.py apply NAME        # copies an approved skill into place and keeps a backup
python3 atlas/devtools/skills_review.py evaluate NAME     # tries it in an isolated git worktree and runs the project's checks there
python3 atlas/devtools/skills_review.py record-eval NAME --task "..." --result improved|neutral|regressed --notes "..."
python3 atlas/devtools/skills_review.py adopt NAME        # only after passing checks AND a recorded "improved" task
python3 atlas/devtools/skills_review.py rollback NAME     # restores the previous version, or removes the skill
```

The latest report is `SKILLS_REVIEW.md`; the full history (review dates, findings, decisions, next run, installed versions) is `skills_ledger.json`.

### How a candidate is judged

1. **Needs.** It counts how often each development need appears in the improvement log, recent commit subjects, the failing-test cache and the agent notes (keyword matching: frequency, not importance). A candidate scores only on needs that were actually demonstrated, weighted by your priority order in `skills_review.config.json`.
2. **Comparison.** Rejected or skipped when it is redundant with an installed skill (word overlap of 0.6 or more), not newer than the installed version, an account-managed skill, a copy you have customised, or addresses no demonstrated need.
3. **Static inspection (nothing is executed).** Rejected when its text or scripts ask for secrets, weaken tests or safeguards, bypass permissions, act without asking, pipe downloads into a shell, force-push, touch credential files, mention live trading, or request unrestricted tool access. Network calls, running programs, reading environment variables, obfuscated code, hooks and deletes are flagged for a human look. A candidate known only from catalog metadata is shown as NOT INSPECTED and can never be installed until its files are downloaded and inspected. A passing check does not prove a skill is safe.
4. **Record.** For each worthwhile candidate: name, source link, version, the problem it addresses, expected benefit and overlap, compatibility, dependencies, permissions, potential cost, security result and a four-step evaluation plan.

### Approval, evaluation and rollback

- Nothing is installed or updated until you run `approve`, unless a source and scope are already listed under `authorized_installs` in the config (empty by default). It never grants permissions and never overwrites a skill you made or edited.
- `apply` re-checks that the files are exactly the ones that were inspected. It keeps a backup of anything it replaces under `skills_backup/`.
- `evaluate` copies the repository to a temporary git worktree, installs the skill there, and runs the commands in `regression_commands`. Your working tree is untouched. The "does it actually help" half cannot be automated: run one representative task in a Claude Code session with and without the skill and record the result with `record-eval`.
- `adopt` requires both. `rollback` always works because every install is backed up.

### Frequency, the shared budget, and alerts

- Weekly by default (`interval_days`), with a manual trigger that always works.
- With `respect_shared_budget` on (default) it reads the production scheduler's database **read-only** and applies the same interval rules as the scheduler at the lowest priority: it slows down when the Claude allowance is low, and defers (retry in a day) when only the usage reserve is left or the scheduler is paused or on emergency stop. If the database cannot be read here it says so and uses the preferred interval. A manual `--force` run is your choice and still runs.
- An alert (exit code 10, and the CI issue) happens only for a useful recommendation, a serious security problem in a relevant skill, or an action required, and not again for the same unchanged set. "Nothing worthwhile found" is logged without an alert.

### Is it running on its own?

**No, not yet.** Honest status:

- This session's own timer is session-only and expires after 7 days, so it cannot hold a weekly schedule.
- `/.github/workflows/skills-review.yml` is a supported weekly schedule (Mondays 06:23 UTC) plus a manual "Run workflow" button. GitHub only runs scheduled workflows from the **default branch**, so it starts once this branch is merged. It is read-only, has no secrets, installs nothing, and opens or updates a single issue only when the exit code is 10. A CI run has nowhere to keep the ledger, so it always runs a fresh review; repeat alerts are avoided by updating the one issue in place.
- To run it on your own computer instead, schedule the manual command with Windows Task Scheduler or cron, for example `0 9 * * 1 cd /path/to/repo && python3 atlas/devtools/skills_review.py run`. The saved `next_run` makes an early run do nothing.
- Claude Code has its own scheduling feature that needs a claude.ai login; I have not verified that it is available to you, so it is not used.
