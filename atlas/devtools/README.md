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

## Hand-off board chore (`board.py`)

The last step of every cycle is a row on the STATE BOARD in `atlas/HANDOFF.md` and the move of the oldest row to `atlas/HANDOFF_ARCHIVE.md`. `board.py` does both (standard library only):

```bash
python3 atlas/devtools/board.py add --job data --changed-file CHANGED.txt --next-file NEXT.txt --dry-run
python3 atlas/devtools/board.py add --job data --changed-file CHANGED.txt --next-file NEXT.txt
python3 atlas/devtools/board.py check
```

The texts of the "What changed" and "Next suggestion" cells are read from files (write them with an editor tool, not a shell heredoc); a cell may not hold a pipe or a line break. The time defaults to now (UTC), the archive label to "<hour> UTC <job> job" and the number of rows kept to 20. Nothing is written unless the result passes `check`, and a refusal says why (exit code 1). Tests: `cd atlas/devtools && python3 -m pytest tests -q`.

## Test runs under a fake clock (`clockrun.py`)

A test that reads the real clock passes on nearly every day and fails on one (found 2026-11-24: one CI run was red for five minutes after midnight in New York). `clockrun.py` runs pytest as if the clock stood somewhere else (standard library only; nothing is installed and nothing in the repository imports it):

```bash
cd atlas/backend
python3 ../devtools/clockrun.py --at 2026-11-25T05:07:00+00:00 -- -q -p no:cacheprovider          # five minutes after midnight in New York, in winter
python3 ../devtools/clockrun.py --at 2026-11-30T23:59:30+00:00 -- -q -p no:cacheprovider          # a month end: the clock crosses midnight during the run
python3 ../devtools/clockrun.py --at 2027-01-15T12:00:00+00:00 --no-tick -- -q tests/test_fedwatch.py   # frozen instead of running on
```

The instant needs an offset (`+00:00` or `Z`). The plugin replaces `datetime.datetime`, `datetime.date`, `time.time` and `time.time_ns` before any test or application module is imported; the clock starts at the instant and keeps ticking in real time (so timeouts and cache lifetimes behave) unless `--no-tick` freezes it; `time.monotonic` and `time.perf_counter` stay real. numpy, pandas and pydantic are imported first so that they keep the real classes (pandas ends the interpreter and pydantic v1 stops with a metaclass conflict otherwise).

Limits, so that a result is read and not trusted: a file's own times (`os.stat`) stay real, so a test that compares a cache file's age with `time.time()` fails at any instant more than a day from now (`test_directory_is_cached_on_disk_between_runs` does, and says nothing about the code); time zones are applied to the fake instant, not changed; code that asks the operating system for the time through a C library is not covered, and pandas does: `pd.Timestamp.now()`, `.today()`, `.utcnow()` and NumPy's `datetime64('now')` still return the real time (nothing in `atlas_api` or the tests calls them, searched 2026-11-25), but the exchange-calendars library calls the first when it builds the New York calendar, and that calendar ends one year after the REAL date (its last session is 2027-11-24 now), so at an instant more than a year ahead (the leap day of 2028 was tried) nine tests of `test_paper_trading.py` fail with `DateOutOfBounds` and say nothing about the code (the 620 tests of `test_btcquant_*.py` pass there). A failure under a fake clock is a place to look, not a bug in itself: read it first (a test that compares with a date written into it fails on every other day).

## Breakage runs (`breakage.py`)

A breakage run breaks a module one small change at a time and counts a failing test run as caught; a change nobody notices is a missing test or dead code. Until 2026-11-25 this was a script copied and edited for every module (40 of them). `breakage.py` (standard library only; nothing in the repository imports it) is the same thing as a tool, and you write only the table:

```bash
python3 atlas/devtools/breakage.py atlas_api/mod.py --cwd atlas/backend --table my_table.py --tests tests/test_mod.py tests/test_macro_notes.py
python3 atlas/devtools/breakage.py atlas_api/mod.py --cwd atlas/backend --table my_table.py --tests tests/test_mod.py --dry            # only check the table
python3 atlas/devtools/breakage.py atlas_api/mod.py --cwd atlas/backend --table my_table.py --tests tests/test_mod.py --equiv        # the EQUIVALENT list: every change should survive
python3 atlas/devtools/breakage.py atlas_api/mod.py --cwd atlas/backend --table my_table.py --tests tests/test_mod.py --only "limit lower"   # run survivors again after a test was added
```

The table is a Python file: `CHANGES = [(name, old, new), ...]` and, if there are any, `EQUIVALENT = [...]`. `old` and `new` are strings; two lists of equal length make one change out of several edits that are made one after the other (the second pattern is looked for in the text the first edit left), which is how a line is moved.

`--cwd` is the folder the tests import the module from (for the backend `atlas/backend`: pytest runs with the copy as its working directory, so the copy's own `atlas_api` is the one that is imported); the module and the test files are written relative to it.

What it does, so that a result can be trusted: the folder given by `--cwd` is COPIED to a temporary folder (not `__pycache__`, `.pytest_cache`, `node_modules`, `.git` or `*.pyc`) and every change is made in the copy, so the original is never written and nothing else can run a broken module; pytest runs in the copy with bytecode off (a compiled copy of the same size and second would hide a change) and `-x`; the clean copy is run first and must pass (a copy that fails before any change makes every change look caught); a run that takes longer than `--timeout` seconds (default 600) counts as caught, because the tests noticed a hang; the file is written back after every change and the run ends by checking that the original is byte for byte the same and the copy is restored; a stop request (SIGTERM or Ctrl-C) removes the copy, leaves the original alone, says so and exits with code 130. Before anything runs it REFUSES (exit code 2, with the name and the pattern) a pattern found other than once, a change that changes nothing, a name used twice and two lists of different lengths. Exit code 0 = no survivor (with `--equiv`: every equivalent change survived), 1 = survivors (with `--equiv`: one was caught, so it is not equivalent), 2 = the table or the clean copy could not be run.

Do not write changes that print the same text (a date with `str` instead of `isoformat()`, a number with `str` instead of `:g`): they survive and are listed as equivalent, with the reason, after they were run alone. Tests: `cd atlas && python3 -m pytest devtools/tests/test_breakage.py -q` breaks a toy module and checks that the break is caught, the survivor is named, the original is unchanged, a bad table is refused and a stop request cleans up.
