#!/usr/bin/env python3
"""Recurring development-skills review. DEVELOPMENT TOOLING ONLY: nothing in atlas_api, the web app or the phone app imports this, and it never touches trading or research execution.

What it does, in order:
 1. Inventory the skills that are installed (project, user, and account-synced; synced ones are managed by the account and are never modified).
 2. Collect DEMONSTRATED NEEDS from the project's own record: the improvement log, recent git commits, the last failing tests, the agent notes. Keyword-based, so counts show how often
    something came up, not how important it is.
 3. Take candidate skills from the sources you trust (a local folder, an inbox filled from a Claude Code session, or a GitHub repository), inspect each one STATICALLY (nothing is
    ever executed), compare it with what is installed, and score it against the demonstrated needs.
 4. Write a ledger (dates, findings, decisions, next run) and a short report. Alert only when there is a useful recommendation, a significant security/compatibility problem, or an action required.

What it never does by itself: install, update, overwrite, grant permissions, spend money, or call Claude. Installing needs your approval (`approve`) unless a source and scope are already
listed in `authorized_installs` in the config. A candidate is adopted only after an isolated evaluation shows the project's checks still pass AND a representative task was recorded as
improved. Every install keeps a backup, so `rollback` always works.

Frequency: weekly by default, a manual trigger always works (`run --force`), and the interval stretches (or the run defers) using the same pure rules as the production scheduler when the
shared Claude allowance is low or the scheduler is paused or stopped. This tool uses 0 Claude tokens unless `use_claude` is turned on, and it is NOT an AI loop.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
CONFIG = HERE / "skills_review.config.json"
LEDGER = HERE / "skills_ledger.json"
REPORT = HERE / "SKILLS_REVIEW.md"
BACKUPS = HERE / "skills_backup"
MAX_FILE_BYTES = 400_000
MAX_FILES = 300
TEXT_EXT = {".md", ".txt", ".py", ".sh", ".js", ".ts", ".json", ".yml", ".yaml", ".toml", ".cfg", ".ini", ".html", ".css", ".bat", ".ps1", ".rb", ".go", ".rs", ".sql", ""}

DEFAULT_CONFIG = {
    "interval_days": 7,
    "max_stretch": 4.0,
    "lookback_days": 14,
    "needs_priority": ["testing", "debugging", "security", "financial-data", "backtesting", "performance", "cloud-deployment", "mobile", "documentation"],
    "inventory_roots": {"project": ".claude/skills", "user": "~/.claude/skills", "synced": "~/.claude/skills/synced"},
    "trusted_sources": ["claude-plugin-catalog (searched inside a Claude Code session)", "anthropics/skills", "anthropics/claude-plugins-official"],
    "authorized_installs": [],                    # e.g. [{"source": "anthropics/skills", "scope": "project", "names": ["pdf"]}]. Empty means every install needs your approval.
    "default_install_scope": "project",
    "respect_shared_budget": True,
    "use_claude": False,
    "prod_db": "atlas/backend/atlas.db",
    "regression_commands": [["python3", "-m", "pytest", "-q", "atlas/devtools/tests"]],
    "redundancy_overlap": 0.6,
}

NEED_KEYWORDS = {
    "testing": ["test", "pytest", "e2e", "flaky", "regression", "coverage", "fixture"],
    "debugging": ["bug", "fix", "crash", "traceback", "caught", "wrong", "failed", "failure", "error", "broke"],
    "security": ["security", "secret", "token", "auth", "injection", "entity", "sanitiz", "csrf", "credential", "password", "untrusted"],
    "financial-data": ["price", "fee", "slippage", "bars per year", "split", "dividend", "adjusted", "stale", "freshness", "timezone", "utc", "sec ", "fred", "yield", "inflation"],
    "backtesting": ["backtest", "holdout", "walk-forward", "overfit", "sharpe", "drawdown", "look-ahead", "leakage", "strategy"],
    "performance": ["slow", "performance", "latency", "memory", "cache", "timeout", "rate limit", "bottleneck", "retry"],
    "cloud-deployment": ["docker", "compose", "deploy", "worker", "caddy", "vps", "backup", "rollback", "hosting"],
    "mobile": ["mobile", "phone", "expo", "react native", "responsive", "pwa", "ios", "android"],
    "documentation": ["docs", "readme", "documentation", "notes", "guide"],
}


# ---------------------------------------------------------------------------------------------------------------------------------- config
def load_config(path: Path | None = None) -> dict:
    path = path or CONFIG                      # resolved at call time, so tests and callers can point it elsewhere
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    if path.exists():
        cfg.update(json.loads(path.read_text()))
    return cfg


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------------------------------------------------------------- skills
def parse_frontmatter(text: str) -> dict:
    """The header of a SKILL.md: lines between the first two '---' markers, as simple 'key: value' pairs. Anything more elaborate is kept as a raw string."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", text, re.S)
    out: dict = {}
    if not m:
        return out
    for line in m.group(1).splitlines():
        kv = re.match(r"^([A-Za-z0-9_\-]+):\s*(.*)$", line)
        if kv:
            v = kv.group(2).strip()
            out[kv.group(1)] = v[1:-1] if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'" else v
    return out


def tree_hash(path: Path) -> str:
    h = hashlib.sha256()
    for f in sorted(p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts):
        h.update(str(f.relative_to(path)).encode())
        h.update(f.read_bytes())
    return h.hexdigest()[:16]


def inventory(cfg: dict, repo: Path = REPO, home: Path | None = None) -> list[dict]:
    """Installed skills with where they came from. Account-synced skills are managed elsewhere: listed, never modified."""
    home = home or Path.home()
    out = []
    for scope, root in cfg["inventory_roots"].items():
        base = Path(root.replace("~", str(home))) if root.startswith("~") else repo / root
        if not base.is_dir():
            continue
        skill_dirs = [d for d in base.iterdir() if d.is_dir() and (d / "SKILL.md").exists()]
        if scope == "user":
            skill_dirs = [d for d in skill_dirs if d.name != "synced"]
        if scope == "synced":       # one extra level: synced/<account id>/<skill>
            skill_dirs = [s for d in base.iterdir() if d.is_dir() for s in d.iterdir() if s.is_dir() and (s / "SKILL.md").exists()]
        for d in skill_dirs:
            fm = parse_frontmatter((d / "SKILL.md").read_text(errors="replace"))
            out.append({"name": fm.get("name") or d.name, "dir": d.name, "scope": scope, "path": str(d), "description": fm.get("description", ""), "version": fm.get("version") or tree_hash(d),
                        "managed": scope == "synced", "has_scripts": any(p.suffix in {".py", ".sh", ".js", ".ts", ".ps1", ".bat"} for p in d.rglob("*") if p.is_file())})
    return out


# ---------------------------------------------------------------------------------------------------------------------------------- needs
def has_kw(text: str, kw: str) -> bool:
    """Keyword match at the START of a word ('test' matches 'tests' but not 'backtest'), so one need is not mistaken for another."""
    return re.search(r"(?<![a-z0-9])" + re.escape(kw), text) is not None


def gather_evidence(repo: Path = REPO, lookback_days: int = 14, now: datetime | None = None) -> dict[str, list[str]]:
    """Raw lines from the project's own record. Pure reading; no network."""
    now = now or now_utc()
    ev: dict[str, list[str]] = {"improvement log": [], "git commits": [], "failing tests": [], "agent notes": []}
    log = repo / "atlas" / "IMPROVEMENT_LOG.md"
    if log.exists():
        cutoff = (now - timedelta(days=lookback_days)).date().isoformat()
        keep = False
        for line in log.read_text(errors="replace").splitlines():
            m = re.match(r"^## (\d{4}-\d{2}-\d{2})", line)
            if m:
                keep = m.group(1) >= cutoff
            if keep and line.strip():
                ev["improvement log"].append(line.strip())
    try:
        r = subprocess.run(["git", "log", f"--since={lookback_days} days ago", "--pretty=%s"], cwd=repo, capture_output=True, text=True, timeout=30)
        ev["git commits"] = [x for x in r.stdout.splitlines() if x.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    for p in repo.glob("**/.pytest_cache/v/cache/lastfailed"):
        if "node_modules" in p.parts:
            continue
        try:
            ev["failing tests"] += [f"failing test: {k}" for k in json.loads(p.read_text())]
        except (OSError, ValueError):
            pass
    notes = repo / "atlas" / "AGENT_NOTES.md"
    if notes.exists():
        ev["agent notes"] = [l.strip() for l in notes.read_text(errors="replace").splitlines() if l.strip().startswith("- ")]
    return ev


def collect_needs(evidence: dict[str, list[str]]) -> dict:
    """Count how often each development need shows up and keep a few example lines. Keyword-based and labelled as such."""
    needs = {c: {"count": 0, "examples": []} for c in NEED_KEYWORDS}
    for source, lines in evidence.items():
        for line in lines:
            low = line.lower()
            for cat, kws in NEED_KEYWORDS.items():
                if any(has_kw(low, k) for k in kws):
                    needs[cat]["count"] += 1
                    if len(needs[cat]["examples"]) < 4:
                        needs[cat]["examples"].append(f"[{source}] {line[:160]}")
    subjects = [l for l in evidence.get("git commits", [])]
    prefixes: dict[str, int] = {}
    for s in subjects:
        p = " ".join(s.split()[:3]).lower()
        prefixes[p] = prefixes.get(p, 0) + 1
    repetitive = [{"pattern": p, "times": n} for p, n in sorted(prefixes.items(), key=lambda kv: -kv[1]) if n >= 3]
    return {"categories": needs, "repetitive_manual_work": repetitive, "method": "keyword matching on the improvement log, recent commit subjects, failing-test cache and agent notes; counts show frequency, not importance"}


# ---------------------------------------------------------------------------------------------------------------------------------- static inspection
CRITICAL = [
    (r"ignore (all |any )?(the )?(previous|prior|above) (instructions|rules)", "tries to override earlier instructions"),
    (r"(disable|skip|bypass|turn off|suppress)\s+(the\s+)?(tests?|safeguards?|safety|verification|hooks?|permission|confirmation|checks?)", "weakens a safeguard"),
    (r"--no-verify|--dangerously|dangerously-skip|bypassPermissions", "bypasses permission or verification checks"),
    (r"(never|don'?t|do not)\s+(ask|confirm|check with)\b.{0,40}\b(user|me)\b|without (asking|confirmation|approval)", "acts without asking the user"),
    (r"(ask|prompt|request|require|provide|paste|enter|send)\b.{0,60}\b(api[ _-]?key|password|secret|access[ _-]?token|private key|credentials?|seed phrase)", "asks for secrets or credentials"),
    (r"(curl|wget)\b[^\n|]*\|\s*(sudo\s+)?(ba|z)?sh\b", "pipes a download straight into a shell"),
    (r"\b(live[- ]trading|place (real |live )?orders?|execute (real )?trades?|enable live)\b", "touches live trading, which this project keeps disabled"),
    (r"force[- ]push|git push --force|push (directly )?to (main|master)", "force-pushes or pushes to the main branch"),
    (r"~/\.ssh|id_rsa|\.aws/credentials|\.env\b.{0,40}(upload|send|post|curl)", "reads or sends credential files"),
    (r"allowed-tools:\s*(\*|Bash\(\*\))", "requests unrestricted tool access"),
]
WARN = [
    (r"\b(requests\.(get|post)|urllib\.request|httpx\.|fetch\(|curl\s|wget\s|http\.client)", "makes network requests"),
    (r"\b(subprocess|os\.system|shell\s*=\s*True|child_process|exec\()", "runs other programs"),
    (r"\b(os\.environ|process\.env|getenv)\b", "reads environment variables"),
    (r"\b(eval|exec)\s*\(|base64\.b64decode|atob\(|\\x[0-9a-f]{2}(\\x[0-9a-f]{2}){8,}", "obfuscated or dynamically evaluated code"),
    (r"\bhooks?\s*:|\"hooks\"\s*:", "declares hooks that run automatically"),
    (r"\b(rm\s+-rf|shutil\.rmtree|os\.remove|unlink)\b", "deletes files"),
    (r"\b(sudo|chmod\s+[0-7]*7|chown)\b", "changes permissions or runs as root"),
]
BOUNDARY = "this is a static check of text; it cannot prove a skill is safe"


def inspect_skill(path: Path) -> dict:
    """Read every text file in a candidate and flag risky instructions and code. NOTHING is executed and no network is used."""
    findings, files, size = [], 0, 0
    fm: dict = {}
    skill_md = path / "SKILL.md"
    if skill_md.exists():
        fm = parse_frontmatter(skill_md.read_text(errors="replace"))
    problems = []
    if not skill_md.exists():
        problems.append("no SKILL.md")
    elif not fm.get("name") or not fm.get("description"):
        problems.append("SKILL.md header lacks a name or description (incompatible format)")
    for f in sorted(p for p in path.rglob("*") if p.is_file() and ".git" not in p.parts):
        files += 1
        if files > MAX_FILES:
            findings.append({"severity": "warn", "what": f"more than {MAX_FILES} files; the rest were not read", "file": "", "line": 0, "excerpt": ""})
            break
        b = f.stat().st_size
        size += b
        rel = str(f.relative_to(path))
        if f.suffix.lower() not in TEXT_EXT:
            findings.append({"severity": "warn", "what": "binary or unknown file type that cannot be read here", "file": rel, "line": 0, "excerpt": ""})
            continue
        if b > MAX_FILE_BYTES:
            findings.append({"severity": "warn", "what": "very large text file; not scanned", "file": rel, "line": 0, "excerpt": ""})
            continue
        text = f.read_text(errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for rx, what in CRITICAL:
                if re.search(rx, line, re.I):
                    findings.append({"severity": "critical", "what": what, "file": rel, "line": n, "excerpt": line.strip()[:140]})
            for rx, what in WARN:
                if re.search(rx, line, re.I):
                    findings.append({"severity": "warn", "what": what, "file": rel, "line": n, "excerpt": line.strip()[:140]})
    perms = []
    for k in ("allowed-tools", "tools", "hooks"):
        if fm.get(k):
            perms.append(f"{k}: {fm[k][:80]}")
    crit = [x for x in findings if x["severity"] == "critical"]
    verdict = "reject" if crit or problems else "review" if findings else "ok"
    uniq, seen = [], set()
    for x in findings:
        key = (x["severity"], x["what"], x["file"])
        if key not in seen:
            seen.add(key)
            uniq.append(x)
    return {"verdict": verdict, "problems": problems, "findings": uniq[:30], "files": files, "bytes": size, "permissions_requested": perms, "content_hash": tree_hash(path), "boundary": BOUNDARY}


# ---------------------------------------------------------------------------------------------------------------------------------- comparison
def tokens(s: str) -> set[str]:
    return {w for w in re.findall(r"[a-z][a-z0-9\-]{2,}", s.lower()) if w not in {"the", "and", "for", "with", "use", "when", "that", "this", "from", "into", "your", "are", "skill", "skills", "claude", "code"}}


def overlap(cand: dict, installed: list[dict]) -> list[dict]:
    ct = tokens(f"{cand['name']} {cand.get('description', '')}")
    out = []
    for s in installed:
        st = tokens(f"{s['name']} {s['description']}")
        if not ct or not st:
            continue
        j = len(ct & st) / len(ct | st)
        if j > 0.12 or s["name"].lower() == cand["name"].lower():
            out.append({"name": s["name"], "scope": s["scope"], "overlap": round(j, 2)})
    return sorted(out, key=lambda x: -x["overlap"])[:3]


def relevance(cand: dict, needs: dict, priority: list[str]) -> dict:
    """Which demonstrated needs the candidate speaks to, weighted by how often the need came up and by your priority order."""
    text = f"{cand['name']} {cand.get('description', '')}".lower()
    hits, score = [], 0.0
    for rank, cat in enumerate(priority):
        n = needs["categories"].get(cat, {}).get("count", 0)
        if n and any(has_kw(text, k) for k in NEED_KEYWORDS.get(cat, [])):
            w = (len(priority) - rank) / len(priority)
            score += w * min(n, 10) / 10
            hits.append({"need": cat, "times_seen": n, "example": needs["categories"][cat]["examples"][:1]})
    return {"score": round(score, 3), "needs": hits}


def version_tuple(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.findall(r"\d+", v or "")) or (0,)


# ---------------------------------------------------------------------------------------------------------------------------------- ledger
def empty_ledger() -> dict:
    return {"version": 1, "reviews": [], "candidates": {}, "installed": {}, "next_run": None, "last_run": None, "pending_actions": []}


def load_ledger(path: Path | None = None) -> dict:
    path = path or LEDGER
    return json.loads(path.read_text()) if path.exists() else empty_ledger()


def save_ledger(led: dict, path: Path | None = None) -> None:
    path = path or LEDGER
    path.write_text(json.dumps(led, indent=1) + "\n")


# ---------------------------------------------------------------------------------------------------------------------------------- shared budget (read only)
def read_shared_budget(db_path: Path) -> dict:
    """Reads the production scheduler's settings and Claude allowance from its database, READ ONLY (this tool never writes to it). Returns what is known; unknown stays unknown."""
    info = {"known": False, "paused": False, "emergency_stop": False, "ai_fraction": None, "optional_allowed": True, "reserve_pct": 20.0}
    if not db_path.exists():
        return info
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=5)
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT value FROM sched_settings WHERE key='settings'").fetchone()
        s = json.loads(row["value"]) if row else {}
        info.update(known=True, paused=bool(s.get("paused")), emergency_stop=bool(s.get("emergency_stop")), reserve_pct=float(s.get("reserve_pct", 20.0)))
        q = con.execute("SELECT limit_amount FROM sched_quotas WHERE bucket='ai_tokens'").fetchone()
        if q and q["limit_amount"] > 0:
            key = now_utc().strftime("%Y-%m-%d")
            used = con.execute("SELECT COALESCE(SUM(amount),0) FROM sched_reservations WHERE bucket='ai_tokens' AND window_key=? AND state IN ('reserved','committed')", (key,)).fetchone()[0]
            frac = max(q["limit_amount"] - used, 0) / q["limit_amount"]
            info.update(ai_fraction=frac, optional_allowed=frac > info["reserve_pct"] / 100.0)
        con.close()
    except (sqlite3.Error, ValueError, KeyError):
        pass
    return info


def next_interval_days(cfg: dict, budget: dict) -> tuple[float | None, list[str]]:
    """The review's frequency, adapted to the shared allowance by the same pure rules the production scheduler uses (priority 1 = first to give way)."""
    pref = cfg["interval_days"] * 86400.0
    reasons = [f"preferred every {cfg['interval_days']} days"]
    if not cfg["respect_shared_budget"] or not budget["known"]:
        if cfg["respect_shared_budget"]:
            reasons.append("shared budget not readable here, so the preferred interval applies")
        return cfg["interval_days"], reasons
    if budget["emergency_stop"] or budget["paused"]:
        return None, reasons + ["deferred: the scheduler is " + ("on emergency stop" if budget["emergency_stop"] else "paused")]
    if budget["ai_fraction"] is None:
        return cfg["interval_days"], reasons
    sys.path.insert(0, str(REPO / "atlas" / "backend"))
    try:
        from atlas_api.sched.intervals import IntervalInput, effective_interval
    finally:
        sys.path.pop(0)
    eff, why = effective_interval(IntervalInput(preferred_s=pref, is_market_open=False, priority=1, budget_fractions={"ai_tokens": budget["ai_fraction"]}, reserve_pct=budget["reserve_pct"]))
    if eff is None:
        return None, reasons + ["deferred: " + why[-1]]
    days = min(eff / 86400.0, cfg["interval_days"] * cfg["max_stretch"])
    return days, reasons + [w for w in why[1:]]


# ---------------------------------------------------------------------------------------------------------------------------------- discovery adapters
def discover_local(folder: Path, source: str = "local folder") -> list[dict]:
    """Candidate skills in a folder (for example a clone you made of a skills repository). Each sub-folder with a SKILL.md is one candidate."""
    out = []
    if not folder.is_dir():
        return out
    for d in sorted(folder.iterdir()):
        if d.is_dir() and (d / "SKILL.md").exists():
            fm = parse_frontmatter((d / "SKILL.md").read_text(errors="replace"))
            out.append({"name": fm.get("name") or d.name, "description": fm.get("description", ""), "version": fm.get("version") or tree_hash(d), "source": source, "link": str(d), "path": str(d)})
    return out


def discover_github(repo: str, client=None, subdir: str = "skills", fetch_files: bool = True) -> list[dict]:
    """Candidate skills in a public GitHub repository, downloaded to a temp folder for static inspection only. Not verified live from the build machine (it cannot reach GitHub)."""
    import httpx
    c = client or httpx.Client(timeout=30, headers={"User-Agent": "atlas-skills-review", "Accept": "application/vnd.github+json"})
    out = []
    r = c.get(f"https://api.github.com/repos/{repo}/contents/{subdir}")
    r.raise_for_status()
    tmp = Path(tempfile.mkdtemp(prefix="skills-candidates-"))
    for item in r.json():
        if item.get("type") != "dir":
            continue
        dest = tmp / item["name"]
        dest.mkdir()
        listing = c.get(item["url"])
        if listing.status_code != 200:
            continue
        for f in listing.json():
            if f.get("type") == "file" and f.get("download_url") and f.get("size", 0) < MAX_FILE_BYTES and fetch_files:
                (dest / f["name"]).write_bytes(c.get(f["download_url"]).content)
        if (dest / "SKILL.md").exists():
            fm = parse_frontmatter((dest / "SKILL.md").read_text(errors="replace"))
            out.append({"name": fm.get("name") or item["name"], "description": fm.get("description", ""), "version": fm.get("version") or tree_hash(dest), "source": repo,
                        "link": item.get("html_url") or f"https://github.com/{repo}/tree/HEAD/{subdir}/{item['name']}", "path": str(dest)})
    return out


# ---------------------------------------------------------------------------------------------------------------------------------- the review
META_WARN = [(r"\b(remote (mcp )?server|outside server|external server|connects to)\b", "its description says it connects to an outside server"),
             (r"\bhooks?\b", "its description mentions hooks that run automatically"),
             (r"\b(account|login|sign[- ]?in)\b", "its description mentions an outside account"),
             (r"\b(api[ _-]?key|credentials?|token)\b", "its description mentions keys or credentials")]


def metadata_only(cand: dict) -> dict:
    """A candidate whose files we do not have (for example one found in the plugin catalog). Only its description can be read, so it is never called safe and cannot be installed."""
    findings = []
    for rx, what in META_WARN:
        if re.search(rx, cand.get("description", ""), re.I):
            findings.append({"severity": "warn", "what": what, "file": "(catalog description)", "line": 0, "excerpt": cand.get("description", "")[:140]})
    return {"verdict": "review", "problems": ["metadata only: no files were available, so nothing could be inspected"], "findings": findings, "files": 0, "bytes": 0, "permissions_requested": [], "content_hash": None, "boundary": BOUNDARY}


def evaluate_candidate(cand: dict, inst: list[dict], needs: dict, cfg: dict, led: dict) -> dict:
    """Everything recorded for one candidate and the decision this review reaches. A recommendation is only a proposal."""
    path = Path(cand["path"]) if cand.get("path") else None
    insp = inspect_skill(path) if path and path.is_dir() else metadata_only(cand)
    ov = overlap(cand, inst)
    rel = relevance(cand, needs, cfg["needs_priority"])
    reasons = []
    status = "proposed"
    if insp["verdict"] == "reject":
        status = "rejected"
        reasons += [f"security/compatibility: {x['what']} ({x['file']}:{x['line']})" for x in insp["findings"] if x["severity"] == "critical"][:3] + insp["problems"]
    same = next((s for s in inst if s["name"].lower() == cand["name"].lower()), None)
    if status != "rejected" and same:
        if same["managed"]:
            status, reasons = "skipped", reasons + [f"an account-managed skill named '{same['name']}' already exists and is updated by the account, not here"]
        elif version_tuple(cand["version"]) <= version_tuple(same["version"]):
            status, reasons = "skipped", reasons + [f"already installed at version {same['version']} (candidate {cand['version']} is not newer)"]
        else:
            recorded = led["installed"].get(cand["name"], {})
            if recorded.get("content_hash") and tree_hash(Path(same["path"])) != recorded["content_hash"]:
                status, reasons = "skipped", reasons + ["the installed copy has been customized; it will not be overwritten. Merge by hand if you want the update."]
            else:
                reasons.append(f"update from {same['version']} to {cand['version']}")
    others = [o for o in ov if o["name"].lower() != cand["name"].lower()]          # a same-named installed skill is the thing being updated, not a redundant one
    if status == "proposed" and others and others[0]["overlap"] >= cfg["redundancy_overlap"]:
        status, reasons = "skipped", reasons + [f"mostly redundant with installed '{others[0]['name']}' (overlap {others[0]['overlap']})"]
    if status == "proposed" and rel["score"] <= 0:
        status, reasons = "skipped", reasons + ["no demonstrated need in the project record this period"]
    if status == "proposed" and insp["verdict"] == "review":
        reasons.append("needs a human look at the flagged items before any install")
    prior = led["candidates"].get(cand["name"], {})
    if prior.get("status") in ("approved", "evaluating", "adopted", "rejected_by_user") and prior.get("version") == cand["version"]:
        status = prior["status"]                      # a decision you already made is never reset by a later review
    return {"name": cand["name"], "source": cand["source"], "source_link": cand["link"], "version": cand["version"], "description": cand.get("description", ""),
            "problem_addressed": rel["needs"], "expected_benefit": ("Addresses " + ", ".join(n["need"] for n in rel["needs"]) + ".") if rel["needs"] else "None demonstrated.",
            "overlap_with_installed": ov, "compatibility": ("SKILL.md header present with name and description" if not insp["problems"] else "; ".join(insp["problems"])),
            "dependencies": "none declared" if not insp["files"] or not any(x["what"] == "runs other programs" for x in insp["findings"]) else "runs other programs: review scripts",
            "permissions": insp["permissions_requested"] or ["none declared in the header"], "potential_cost": "no direct cost known; installing changes what Claude reads, so token use may rise slightly",
            "security": {k: insp[k] for k in ("verdict", "findings", "files", "bytes", "content_hash", "boundary")},
            "evaluation_plan": ["install in an isolated copy of the repo (never your working tree)", "run the project's regression checks", "give Claude one representative task with and without the skill and record the outcome", "adopt only if the outcome is 'improved' and checks still pass"],
            "relevance_score": rel["score"], "status": status, "reasons": reasons, "path": cand.get("path")}


def run_review(cfg: dict, led: dict, candidates: list[dict], *, repo: Path = REPO, home: Path | None = None, now: datetime | None = None, trigger: str = "schedule", force: bool = False,
               evidence: dict | None = None, budget: dict | None = None) -> dict:
    now = now or now_utc()
    if not force and led["next_run"] and now < datetime.fromisoformat(led["next_run"]):
        return {"ran": False, "reason": f"not due until {led['next_run']}"}
    budget = budget if budget is not None else read_shared_budget(repo / cfg["prod_db"])
    days, why = next_interval_days(cfg, budget)
    if days is None and not force:
        retry = now + timedelta(days=1)
        led["next_run"] = retry.isoformat()
        led["reviews"].append({"id": len(led["reviews"]) + 1, "date": now.isoformat(), "trigger": trigger, "status": "deferred", "reason": why[-1], "recommendations": [], "alerted": False})
        return {"ran": False, "deferred": True, "reason": why[-1], "next_run": led["next_run"]}
    inst = inventory(cfg, repo, home)
    needs = collect_needs(evidence if evidence is not None else gather_evidence(repo, cfg["lookback_days"], now))
    results = [evaluate_candidate(c, inst, needs, cfg, led) for c in candidates]
    for r in results:
        old = led["candidates"].get(r["name"], {})
        r["decisions"] = old.get("decisions", [])
        r["first_seen"] = old.get("first_seen", now.isoformat())
        r["last_seen"] = now.isoformat()
        led["candidates"][r["name"]] = r
    recs = sorted([r["name"] for r in results if r["status"] == "proposed" and r["security"]["verdict"] != "reject"], key=lambda n: -led["candidates"][n]["relevance_score"])
    serious = [r["name"] for r in results if r["status"] == "rejected" and any(f["severity"] == "critical" for f in r["security"]["findings"]) and r["relevance_score"] > 0]
    prev = next((x for x in reversed(led["reviews"]) if x["status"] == "done"), None)
    changed = prev is None or sorted(prev["recommendations"]) != sorted(recs)
    alert = bool(recs and changed) or bool(serious and (prev is None or sorted(prev.get("serious", [])) != sorted(serious))) or bool(led["pending_actions"] and changed)
    review = {"id": len(led["reviews"]) + 1, "date": now.isoformat(), "trigger": trigger, "status": "done", "installed_skills": len(inst), "candidates_considered": len(results),
              "needs": {c: v["count"] for c, v in needs["categories"].items() if v["count"]}, "recommendations": recs, "serious": serious, "alerted": alert,
              "outcome": "recommendations" if recs else "nothing worthwhile found", "interval": why}
    led["reviews"].append(review)
    led["last_run"] = now.isoformat()
    led["next_run"] = (now + timedelta(days=days or cfg["interval_days"])).isoformat()
    led["pending_actions"] = [f"approve or reject '{n}'" for n in recs] + [f"read the security findings for '{n}'" for n in serious]
    return {"ran": True, "review": review, "needs": needs, "results": results, "alert": alert, "next_run": led["next_run"], "interval": why}


def render_report(out: dict, led: dict) -> str:
    r = out["review"]
    lines = [f"# Development skills review ({r['date'][:10]})", "", f"Trigger: {r['trigger']}. Installed skills seen: {r['installed_skills']}. Candidates considered: {r['candidates_considered']}. Next review: {led['next_run'][:10]}.",
             f"Frequency: {'; '.join(r['interval'])}.", ""]
    if r["needs"]:
        lines += ["## Demonstrated needs this period (keyword counts, not importance)", ""] + [f"- {c}: {n}" for c, n in sorted(r["needs"].items(), key=lambda kv: -kv[1])] + [""]
    else:
        lines += ["No development needs were detected in the project record this period.", ""]
    if out["needs"]["repetitive_manual_work"]:
        lines += ["## Repetitive work", ""] + [f"- \"{x['pattern']}\" appeared {x['times']} times in recent commits" for x in out["needs"]["repetitive_manual_work"]] + [""]
    if r["recommendations"]:
        lines += ["## Recommendations (nothing is installed until you approve)", ""]
        for n in r["recommendations"]:
            c = led["candidates"][n]
            lines += [f"### {c['name']} {c['version']}", f"- Source: {c['source_link']}", f"- Addresses: {', '.join(x['need'] for x in c['problem_addressed'])}", f"- Overlap with installed: {c['overlap_with_installed'] or 'none found'}",
                      f"- Permissions: {', '.join(c['permissions'])}",
                      (f"- Security check: NOT INSPECTED (metadata only). {len(c['security']['findings'])} concern(s) in the description: {'; '.join(x['what'] for x in c['security']['findings']) or 'none'}. It cannot be installed until its files are downloaded and inspected."
                       if c['security']['files'] == 0 else f"- Security check ({c['security']['verdict']}): {len(c['security']['findings'])} flagged items. {c['security']['boundary']}"),
                      f"- Decide: `python3 atlas/devtools/skills_review.py approve {c['name']}` or `reject {c['name']} --reason ...`", ""]
    else:
        lines += ["## Result", "", "Nothing worthwhile found this period. No alert was generated.", ""]
    skipped = [(c["name"], c["reasons"]) for c in out["results"] if c["status"] in ("skipped", "rejected")]
    if skipped:
        lines += ["## Considered and not recommended", ""] + [f"- {n}: {'; '.join(rs) or 'no reason recorded'}" for n, rs in skipped] + [""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------------------------- decisions, install, evaluate, adopt, rollback
class Refused(Exception):
    pass


def _record(led: dict, name: str, what: str, now: datetime, **kw) -> None:
    led["candidates"][name].setdefault("decisions", []).append({"at": now.isoformat(), "what": what, **kw})


def approve(led: dict, name: str, scope: str, now: datetime | None = None) -> None:
    c = led["candidates"].get(name)
    if not c:
        raise Refused(f"no candidate named '{name}' in the ledger")
    if c["security"]["verdict"] == "reject":
        raise Refused("this candidate was rejected by the security check; it cannot be approved")
    c["status"], c["approved_scope"] = "approved", scope
    _record(led, name, "approved", now or now_utc(), scope=scope)


def reject(led: dict, name: str, reason: str, now: datetime | None = None) -> None:
    if name not in led["candidates"]:
        raise Refused(f"no candidate named '{name}' in the ledger")
    led["candidates"][name]["status"] = "rejected_by_user"
    _record(led, name, "rejected", now or now_utc(), reason=reason)


def is_authorized(cfg: dict, c: dict, scope: str) -> bool:
    return any(a.get("source") == c["source"] and a.get("scope") == scope and (not a.get("names") or c["name"] in a["names"]) for a in cfg["authorized_installs"])


def target_dir(scope: str, name: str, repo: Path, home: Path) -> Path:
    return (repo / ".claude" / "skills" / name) if scope == "project" else (home / ".claude" / "skills" / name)


def apply(cfg: dict, led: dict, name: str, repo: Path = REPO, home: Path | None = None, now: datetime | None = None) -> Path:
    """Copy an approved (or explicitly pre-authorized) candidate into place, keeping a backup. Refuses on any mismatch; never grants permissions."""
    now, home = now or now_utc(), home or Path.home()
    c = led["candidates"].get(name)
    if not c:
        raise Refused(f"no candidate named '{name}'")
    scope = c.get("approved_scope") or cfg["default_install_scope"]
    if c["status"] != "approved" and not is_authorized(cfg, c, scope):
        raise Refused(f"'{name}' is not approved for installation (run `approve {name}`), and its source and scope are not in authorized_installs")
    if c["security"]["verdict"] == "reject":
        raise Refused("rejected by the security check")
    src = Path(c["path"]) if c.get("path") else None
    if not src or not src.is_dir():
        raise Refused("the candidate files are no longer available; run the review again")
    if tree_hash(src) != c["security"]["content_hash"]:
        raise Refused("the files changed since they were inspected; run the review again so they are re-inspected")
    dest = target_dir(scope, name, repo, home)
    if dest.exists():
        rec = led["installed"].get(name)
        if not rec or tree_hash(dest) != rec.get("content_hash"):
            raise Refused(f"{dest} already exists and is not an unmodified copy installed by this tool; it will not be overwritten")
        backup = BACKUPS / name / now.strftime("%Y%m%dT%H%M%S")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(dest, backup)
        shutil.rmtree(dest)
    else:
        backup = None
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dest)
    led["installed"][name] = {"version": c["version"], "scope": scope, "path": str(dest), "source": c["source"], "content_hash": tree_hash(dest), "backup": str(backup) if backup else None,
                               "previous_version": led["installed"].get(name, {}).get("version"), "installed_at": now.isoformat(), "adopted": False}
    c["status"] = "evaluating"
    _record(led, name, "installed for evaluation", now, scope=scope, backup=str(backup) if backup else None)
    return dest


def evaluate(cfg: dict, led: dict, name: str, repo: Path = REPO, now: datetime | None = None, runner=subprocess.run) -> dict:
    """Try the skill in an ISOLATED copy of the repository (a temporary git worktree), run the project's regression commands there, and record the result. Your working tree is untouched."""
    now = now or now_utc()
    c = led["candidates"].get(name)
    if not c or c["status"] not in ("evaluating", "approved"):
        raise Refused("only an approved or installed candidate can be evaluated")
    src = Path(c["path"])
    if not src.is_dir() or tree_hash(src) != c["security"]["content_hash"]:
        raise Refused("candidate files missing or changed since inspection")
    tmp = Path(tempfile.mkdtemp(prefix="skill-eval-"))
    wt = tmp / "repo"
    try:
        runner(["git", "worktree", "add", "--detach", str(wt), "HEAD"], cwd=repo, check=True, capture_output=True, timeout=120)
        shutil.copytree(src, wt / ".claude" / "skills" / name)
        results = []
        for cmd in cfg["regression_commands"]:
            p = runner(cmd, cwd=wt, capture_output=True, text=True, timeout=1800)
            results.append({"command": " ".join(cmd), "returncode": p.returncode, "tail": (p.stdout or "")[-400:] + (p.stderr or "")[-200:]})
        ok = all(r["returncode"] == 0 for r in results)
    finally:
        runner(["git", "worktree", "remove", "--force", str(wt)], cwd=repo, capture_output=True, timeout=120)
        shutil.rmtree(tmp, ignore_errors=True)
    ev = {"at": now.isoformat(), "regression_pass": ok, "commands": results, "representative_task": None}
    c["evaluation"] = ev
    _record(led, name, "isolated evaluation", now, regression_pass=ok)
    return ev


def record_task(led: dict, name: str, task: str, result: str, notes: str, now: datetime | None = None) -> None:
    if result not in ("improved", "neutral", "regressed"):
        raise Refused("result must be improved, neutral or regressed")
    c = led["candidates"].get(name)
    if not c or "evaluation" not in c:
        raise Refused("run `evaluate` first")
    c["evaluation"]["representative_task"] = {"task": task, "result": result, "notes": notes, "at": (now or now_utc()).isoformat()}
    _record(led, name, "representative task recorded", now or now_utc(), result=result)


def adopt(led: dict, name: str, now: datetime | None = None) -> None:
    c = led["candidates"].get(name)
    ev = (c or {}).get("evaluation")
    if not ev or not ev["regression_pass"]:
        raise Refused("adoption needs a passing isolated evaluation")
    t = ev.get("representative_task")
    if not t or t["result"] != "improved":
        raise Refused("adoption needs a recorded representative task with the result 'improved'")
    c["status"] = "adopted"
    led["installed"][name]["adopted"] = True
    _record(led, name, "adopted", now or now_utc(), version=c["version"])


def rollback(led: dict, name: str, repo: Path = REPO, now: datetime | None = None) -> str:
    rec = led["installed"].get(name)
    if not rec:
        raise Refused(f"'{name}' was not installed by this tool")
    dest = Path(rec["path"])
    if dest.exists():
        shutil.rmtree(dest)
    restored = "removed (no earlier version existed)"
    if rec.get("backup") and Path(rec["backup"]).is_dir():
        shutil.copytree(rec["backup"], dest)
        restored = f"restored version {rec.get('previous_version')} from {rec['backup']}"
        rec["version"], rec["content_hash"], rec["backup"] = rec.get("previous_version"), tree_hash(dest), None
    else:
        del led["installed"][name]
    if name in led["candidates"]:
        led["candidates"][name]["status"] = "rolled_back"
        _record(led, name, "rolled back", now or now_utc(), result=restored)
    return restored


# ---------------------------------------------------------------------------------------------------------------------------------- command line
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the review now (the schedule is respected unless --force)")
    r.add_argument("--force", action="store_true")
    r.add_argument("--local", action="append", default=[], help="folder of candidate skills")
    r.add_argument("--github", action="append", default=[], help="owner/repo to read candidate skills from")
    r.add_argument("--github-subdir", default="skills")
    r.add_argument("--ci", action="store_true", help="do not save the ledger (a CI run has no place to keep it)")
    r.add_argument("--trigger", default="manual")
    ac = sub.add_parser("add-candidate", help="record a candidate found in a Claude Code session (catalog search cannot run unattended)")
    ac.add_argument("name"); ac.add_argument("--source", required=True); ac.add_argument("--link", required=True); ac.add_argument("--version", default="unknown"); ac.add_argument("--description", required=True)
    ac.add_argument("--path", default=None, help="folder with the downloaded files, if you have them (needed for the security inspection)")
    nt = sub.add_parser("note", help="record a decision or fact about a candidate that happened outside this tool")
    nt.add_argument("name"); nt.add_argument("text")
    sub.add_parser("status")
    sub.add_parser("inventory")
    sub.add_parser("needs")
    i = sub.add_parser("inspect")
    i.add_argument("path")
    a = sub.add_parser("approve"); a.add_argument("name"); a.add_argument("--scope", default=None)
    d = sub.add_parser("reject"); d.add_argument("name"); d.add_argument("--reason", required=True)
    ap_ = sub.add_parser("apply"); ap_.add_argument("name")
    e = sub.add_parser("evaluate"); e.add_argument("name")
    t = sub.add_parser("record-eval"); t.add_argument("name"); t.add_argument("--task", required=True); t.add_argument("--result", required=True); t.add_argument("--notes", default="")
    ad = sub.add_parser("adopt"); ad.add_argument("name")
    rb = sub.add_parser("rollback"); rb.add_argument("name")
    args = ap.parse_args(argv)
    cfg, led = load_config(), load_ledger()
    try:
        if args.cmd == "inventory":
            for s in inventory(cfg):
                print(f"{s['scope']:8} {s['name']:28} v{s['version']:18} {'(managed by the account) ' if s['managed'] else ''}{s['description'][:70]}")
            return 0
        if args.cmd == "needs":
            n = collect_needs(gather_evidence(REPO, cfg["lookback_days"]))
            for c, v in sorted(n["categories"].items(), key=lambda kv: -kv[1]["count"]):
                print(f"{c:18} {v['count']:4}  {v['examples'][0] if v['examples'] else ''}")
            return 0
        if args.cmd == "inspect":
            print(json.dumps(inspect_skill(Path(args.path)), indent=1))
            return 0
        if args.cmd == "add-candidate":
            inbox = HERE / "skills_inbox.json"
            items = json.loads(inbox.read_text()) if inbox.exists() else []
            items = [x for x in items if not (x["name"] == args.name and x["version"] == args.version)]
            items.append({"name": args.name, "description": args.description, "version": args.version, "source": args.source, "link": args.link, "path": args.path})
            inbox.write_text(json.dumps(items, indent=1) + "\n")
            print(f"recorded '{args.name}' in the inbox; the next review will consider it" + ("" if args.path else " (metadata only: it cannot be installed until its files are downloaded and inspected)"))
            return 0
        if args.cmd == "note":
            if args.name not in led["candidates"]:
                raise Refused(f"no candidate named '{args.name}' in the ledger; run a review first")
            _record(led, args.name, "note", now_utc(), text=args.text)
            save_ledger(led)
            return 0
        if args.cmd == "status":
            print(json.dumps({"last_run": led["last_run"], "next_run": led["next_run"], "pending_actions": led["pending_actions"], "candidates": {k: v["status"] for k, v in led["candidates"].items()}, "installed": {k: v["version"] for k, v in led["installed"].items()}}, indent=1))
            return 0
        if args.cmd == "run":
            cands = []
            for f in args.local:
                cands += discover_local(Path(f), f"local:{f}")
            for g in args.github:
                try:
                    cands += discover_github(g, subdir=args.github_subdir)
                except Exception as ex:  # noqa: BLE001  one unreachable source must not stop the review
                    print(f"source {g} could not be read: {type(ex).__name__}: {str(ex)[:100]}", file=sys.stderr)
            inbox = HERE / "skills_inbox.json"
            if inbox.exists():
                cands += json.loads(inbox.read_text())
            out = run_review(cfg, led, cands, trigger=args.trigger, force=args.force)
            if not out["ran"]:
                print(f"review did not run: {out['reason']}")
                if not args.ci:
                    save_ledger(led)
                return 0
            report = render_report(out, led)
            REPORT.write_text(report + "\n")
            if not args.ci:
                save_ledger(led)
            print(report)
            return 10 if out["alert"] else 0               # exit code 10 = there is something worth telling you
        if args.cmd == "approve":
            approve(led, args.name, args.scope or cfg["default_install_scope"])
        elif args.cmd == "reject":
            reject(led, args.name, args.reason)
        elif args.cmd == "apply":
            print("installed to", apply(cfg, led, args.name))
        elif args.cmd == "evaluate":
            print(json.dumps(evaluate(cfg, led, args.name), indent=1))
        elif args.cmd == "record-eval":
            record_task(led, args.name, args.task, args.result, args.notes)
        elif args.cmd == "adopt":
            adopt(led, args.name)
        elif args.cmd == "rollback":
            print(rollback(led, args.name))
        save_ledger(led)
        return 0
    except Refused as ex:
        print(f"REFUSED: {ex}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
