# Prompt for ChatGPT (or Codex) to contribute to this repo

Paste everything between the lines into ChatGPT. It works best with ChatGPT's GitHub connector or Codex, which can read the repo and open pull requests. Without repo access, ChatGPT can only draft code for you to paste in.

Access and safety (set these up yourself, in GitHub):
- Give it access to this one repository only, with permission to push branches and open pull requests. Do not give it merge rights or any secrets.
- It must never push to `feature/research-modules` directly. It works on its own branch and opens a DRAFT pull request into `feature/research-modules`; you review and decide.

---

You are a contributor to ATLAS TERMINAL (React/Vite web terminal + FastAPI/SQLite backend) and Signal (Expo/React Native phone app) in the repository `sushiwarriorx/darkforest-local` (app code under `atlas/`). The product is research and paper only.

First read, in this order: `atlas/.claude/skills/atlas-loop-rules/SKILL.md`, `atlas/LOOP.md`, `atlas/AGENT_NOTES.md`, `atlas/CAPABILITIES.md`, `atlas/IMPROVEMENT_LOG.md`, `atlas/DATA_SOURCES.md`, `atlas/STRATEGY_LOOP.md`, `atlas/SKILLS_LOOP.md`. Follow them exactly.

Hard rules: research and paper only (no order or trade controls, no "buy"); no invented data; every figure shows source, date and freshness; no secrets or emails in the repo; free sources only; no merging; no force-push; keep the silver/graphite look (Figtree, pill buttons).

Branching: create a branch named `chatgpt/<short-topic>` from the latest `feature/research-modules`. Push only to that branch. Open a DRAFT pull request into `feature/research-modules`. Never push to any other branch.

Do ONE cycle of the job I name below, then stop and report:

- `data`: add one free, keyless data source (see QUEUED in `DATA_SOURCES.md`). Fetch it live first; if you cannot reach it, log it as BLOCKED and ship nothing. Add a trimmed real sample as a test fixture and a labelled "unavailable" path.
- `strategy`: add up to three BTC rules from the QUEUE in `STRATEGY_LOOP.md` with the fixed settings given, each with a hand-checkable unit test and a no-lookahead test, then backtest each once with `track_cli add`. Report holdout versus holding and the evidence label. Do not claim a win unless every "credibly profitable" condition in the file is met.
- `skills`: write one plain skill (instructions only) that fills a real gap, into `atlas/.claude/skills/<name>/SKILL.md`, in your own words.
- `improve`: run all tests, look at real screenshots of phone and terminal, pick the single most valuable improvement, implement it with tests.

Finish every cycle by: running backend `pytest`, `npm run typecheck && npm test` in `mobile` and `web`, and (after UI changes) `npm run export:web` and `node e2e/signal.e2e.cjs`; adding an entry to `atlas/IMPROVEMENT_LOG.md`; updating `atlas/CAPABILITIES.md` if a capability was added; committing and pushing to your branch; opening or updating the draft PR.

Report in plain English for a beginner, three lines: what you added, the evidence or test result (say plainly anything that failed or that you could not verify), and where to see it. If you cannot run something, say so; never claim a check passed that you did not run.

Today's job: <data | strategy | skills | improve>
