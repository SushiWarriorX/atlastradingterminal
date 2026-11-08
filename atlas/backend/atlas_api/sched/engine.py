"""The shared scheduler. Durable (all state is in the database), safe across processes (leases and atomic budget reservations), and bounded (every run has a token, time and
experiment limit). It is not an AI conversation loop: handlers are ordinary deterministic code, and only some of them call Claude, within a reserved budget.

Life of a run: due -> decide (global gates, interval adaptation, cost estimate) -> lease + record the run -> reserve budget atomically -> execute with a timeout -> settle the real
cost -> schedule the next run. Failures back off exponentially with jitter (or wait the provider's Retry-After), and after repeated failures land in the dead-letter list.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from zoneinfo import ZoneInfo

from ..db import DB
from . import settings as ST
from .budget import Budget, window_end
from .intervals import IntervalInput, effective_interval

log = logging.getLogger("atlas.sched")
MAX_ATTEMPTS = 5                  # consecutive failures before a job lands in the dead-letter list
BACKOFF_BASE_S = 30.0
BACKOFF_CAP_S = 3600.0
RETRY_AFTER_CAP_S = 6 * 3600.0
DEFER_RECHECK_S = 900.0
EVENT_COOLDOWN_H = 24


class RetryAfter(Exception):
    """Raise from a handler when a provider says 'try again after N seconds' (HTTP 429/503 Retry-After). The scheduler waits at least that long."""

    def __init__(self, seconds: float, message: str = "provider asked us to wait"):
        super().__init__(message)
        self.seconds = float(seconds)


class JobCancelled(Exception):
    pass


class BudgetExceeded(Exception):
    pass


@dataclass
class JobSpec:
    id: str
    title: str
    kind: str                                   # refresh | discovery | experiment | scenario | health
    handler: Callable[["RunContext"], Awaitable[dict]]
    interval_market_s: int
    interval_off_s: int
    priority: int = 3
    max_tokens: int = 0                         # 0 = the job never calls Claude
    max_runtime_s: int = 300
    max_experiments: int = 0
    buckets: dict[str, float] = field(default_factory=dict)       # estimated provider calls per run, by quota bucket
    freshness_s: int | None = None              # how old its data may get before it is called stale (default 3x the preferred interval)
    description: str = ""
    enabled: bool = True


class RunContext:
    def __init__(self, sched: "Scheduler", job: dict, spec: JobSpec, run_id: int, trigger: str, attempt: int, started: datetime):
        self.sched, self.job, self.spec, self.run_id, self.trigger, self.attempt, self.started = sched, job, spec, run_id, trigger, attempt, started
        self.checkpoint: dict = json.loads(job["checkpoint"]) if job.get("checkpoint") else {}
        self.limits = {"max_tokens": int(job["max_tokens"]), "max_runtime_s": int(job["max_runtime_s"]), "max_experiments": int(job["max_experiments"])}
        self.tokens_in = self.tokens_out = self.experiments = 0
        self.calls: dict[str, float] = {}

    def check(self) -> None:
        """Handlers call this between steps: stops the run on an emergency stop or when its time is up."""
        if ST.get(self.sched.db)["emergency_stop"]:
            raise JobCancelled("emergency stop")
        if (self.sched.clock() - self.started).total_seconds() > self.limits["max_runtime_s"]:
            raise JobCancelled("runtime limit reached")

    def save_checkpoint(self) -> None:
        self.sched.db.x("UPDATE sched_jobs SET checkpoint=? WHERE id=?", (json.dumps(self.checkpoint), self.job["id"]))

    def use_tokens(self, tokens_in: int, tokens_out: int) -> None:
        """Record what a Claude call really used (the API returns these counts for every call). Refuses once the job's own limit is passed."""
        self.tokens_in += int(tokens_in)
        self.tokens_out += int(tokens_out)
        if self.tokens_in + self.tokens_out > self.limits["max_tokens"]:
            raise BudgetExceeded(f"this run used {self.tokens_in + self.tokens_out} tokens, over its limit of {self.limits['max_tokens']}")

    def call(self, bucket: str, n: float = 1) -> None:
        """Count provider calls against the quota. Calls beyond the estimate are still recorded, so the next reservation sees them."""
        self.calls[bucket] = self.calls.get(bucket, 0) + n

    def experiment(self) -> None:
        self.experiments += 1
        if self.experiments > self.limits["max_experiments"]:
            raise BudgetExceeded(f"experiment limit of {self.limits['max_experiments']} reached")


class Scheduler:
    def __init__(self, db: DB, clock: Callable[[], datetime] | None = None, rng: random.Random | None = None, notify: Callable[[str, str], None] | None = None):
        self.db = db
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.rng = rng or random.Random()
        self.notify = notify
        self.budget = Budget(db)
        self.specs: dict[str, JobSpec] = {}
        ST.seed_quotas(db)
        self._stop = asyncio.Event()

    # ---- registration -------------------------------------------------------------------------------------------------------------------
    def register(self, spec: JobSpec) -> None:
        """Adds the job if it is new. An existing job keeps every setting the user changed."""
        self.specs[spec.id] = spec
        now = self.clock().isoformat()
        self.db.x("INSERT OR IGNORE INTO sched_jobs(id,enabled,priority,interval_market_s,interval_off_s,max_tokens,max_runtime_s,max_experiments,next_run_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (spec.id, int(spec.enabled), spec.priority, spec.interval_market_s, spec.interval_off_s, spec.max_tokens, spec.max_runtime_s, spec.max_experiments, now, now))

    def job(self, job_id: str) -> dict | None:
        r = self.db.q("SELECT * FROM sched_jobs WHERE id=?", (job_id,))
        return dict(r[0]) if r else None

    # ---- time ---------------------------------------------------------------------------------------------------------------------------
    def is_market_open(self, at: datetime) -> bool:
        m = ST.get(self.db)["market"]
        local = at.astimezone(ZoneInfo(m["tz"]))
        if local.weekday() not in m["weekdays"]:
            return False
        oh, om = map(int, m["open"].split(":"))
        ch, cm = map(int, m["close"].split(":"))
        return (oh, om) <= (local.hour, local.minute) < (ch, cm)       # US market holidays are not modelled: the market-hours schedule also applies on a holiday

    # ---- events -------------------------------------------------------------------------------------------------------------------------
    def emit(self, kind: str, key: str, severity: str, message: str) -> bool:
        """Record an operator event. The same message for the same key is suppressed for 24 hours; a changed message goes through at once."""
        now = self.clock()
        last = self.db.q("SELECT ts,message FROM sched_events WHERE dedupe_key=? ORDER BY id DESC LIMIT 1", (key,))
        if last and last[0]["message"] == message and (now - datetime.fromisoformat(last[0]["ts"])) < timedelta(hours=EVENT_COOLDOWN_H):
            return False
        self.db.x("INSERT INTO sched_events(ts,kind,dedupe_key,severity,message,notified) VALUES(?,?,?,?,?,?)", (now.isoformat(), kind, key, severity, message, 0))
        if self.notify and severity in ("warn", "critical"):
            try:
                self.notify(severity, message)
                self.db.x("UPDATE sched_events SET notified=1 WHERE id=(SELECT MAX(id) FROM sched_events WHERE dedupe_key=?)", (key,))
            except Exception:  # noqa: BLE001  a failed notification must never stop the scheduler
                log.exception("notification failed")
        return True

    # ---- operator controls --------------------------------------------------------------------------------------------------------------
    def set_global(self, **patch) -> dict:
        s = ST.save(self.db, patch)
        self.db.audit("user", "sched_settings", {k: v for k, v in patch.items() if k != "claude"} | ({"claude": "changed"} if "claude" in patch else {}))
        return s

    def emergency_stop(self, on: bool = True) -> None:
        ST.save(self.db, {"emergency_stop": on})
        self.db.audit("user", "sched_emergency_stop", {"on": on})
        self.emit("action", "emergency_stop", "critical" if on else "info", "Emergency stop is ON: no job will run until it is cleared." if on else "Emergency stop was cleared.")

    def update_job(self, job_id: str, **patch) -> dict:
        allowed = {"enabled": int, "paused": int, "priority": int, "interval_market_s": int, "interval_off_s": int, "max_tokens": int, "max_runtime_s": int, "max_experiments": int}
        sets, args = [], []
        for k, v in patch.items():
            if k not in allowed:
                raise KeyError(k)
            sets.append(f"{k}=?")
            args.append(allowed[k](v))
        if sets:
            self.db.x(f"UPDATE sched_jobs SET {','.join(sets)}, updated_at=? WHERE id=?", (*args, self.clock().isoformat(), job_id))
            self.db.audit("user", "sched_job", {"job": job_id, **patch})
        return self.job(job_id)

    def request_run(self, job_id: str) -> bool:
        if ST.get(self.db)["emergency_stop"] or not self.job(job_id):
            return False
        self.db.x("UPDATE sched_jobs SET run_requested=1, next_run_at=? WHERE id=?", (self.clock().isoformat(), job_id))
        self.db.audit("user", "sched_run_now", {"job": job_id})
        return True

    # ---- recovery -----------------------------------------------------------------------------------------------------------------------
    def recover(self) -> int:
        """Runs whose lease has expired belong to a crashed or killed worker. They are marked interrupted, their reserved budget is counted as spent (we cannot know it was not),
        and the job keeps its checkpoint and is retried soon."""
        now = self.clock()
        n = 0
        for r in self.db.q("SELECT id, lease_run_id FROM sched_jobs WHERE lease_until IS NOT NULL AND lease_until < ?", (now.isoformat(),)):
            rid = r["lease_run_id"]
            self.db.x("UPDATE sched_runs SET status='interrupted', finished_at=?, error='worker stopped before this run finished' WHERE id=? AND status='running'", (now.isoformat(), rid))
            self.db.x("UPDATE sched_reservations SET state='committed' WHERE run_id=? AND state='reserved'", (rid,))
            self.db.x("UPDATE sched_jobs SET lease_until=NULL, lease_run_id=NULL, last_status='interrupted', next_run_at=? WHERE id=?", ((now + timedelta(seconds=30)).isoformat(), r["id"]))
            self.emit("failure", f"interrupted:{r['id']}", "warn", f"Job '{r['id']}' was interrupted (the worker stopped); it will resume from its checkpoint.")
            n += 1
        return n

    # ---- the tick -----------------------------------------------------------------------------------------------------------------------
    async def tick(self) -> list[dict]:
        now = self.clock()
        s = ST.get(self.db)
        self.db.x("INSERT INTO sched_settings(key,value) VALUES('heartbeat',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (now.isoformat(),))      # proof the scheduler process is alive
        self.recover()
        if s["emergency_stop"]:
            return [{"job": None, "action": "stopped", "reason": "emergency stop is on"}]
        running = self.db.q("SELECT COUNT(*) FROM sched_jobs WHERE lease_until IS NOT NULL AND lease_until >= ?", (now.isoformat(),))[0][0]
        slots = max(int(s["max_concurrent"]) - running, 0)
        rows = self.db.q("SELECT * FROM sched_jobs WHERE enabled=1 AND next_run_at<=? AND (lease_until IS NULL OR lease_until<?) ORDER BY priority DESC, next_run_at ASC", (now.isoformat(), now.isoformat()))
        decisions, todo = [], []
        for r in rows:
            j = dict(r)
            manual = bool(j["run_requested"])
            if (s["paused"] or j["paused"]) and not manual:
                continue
            if j["id"] not in self.specs:
                continue
            if len(todo) >= slots:
                decisions.append({"job": j["id"], "action": "waiting", "reason": f"all {s['max_concurrent']} worker slots are busy"})
                continue
            d = self._decide(j, self.specs[j["id"]], now, s, manual)
            decisions.append({"job": j["id"], "action": d["action"], "reason": d.get("reason")})
            if d["action"] == "run":
                todo.append((j["id"], "manual" if manual else ("retry" if j["consecutive_failures"] else "schedule"), d))
        await asyncio.gather(*(self._execute(jid, trig, d) for jid, trig, d in todo))
        return decisions

    def _bucket_fractions(self, j: dict, spec: JobSpec, snap: dict) -> dict[str, float]:
        used = set(spec.buckets) | ({"ai_tokens", "ai_usd", "ai_usd_month"} if j["max_tokens"] > 0 else set())
        return {b: snap[b]["remaining_fraction"] for b in used if b in snap and snap[b]["remaining_fraction"] is not None}

    def _decide(self, j: dict, spec: JobSpec, now: datetime, s: dict, manual: bool) -> dict:
        snap = self.budget.snapshot(now, s["reserve_pct"])
        market = self.is_market_open(now)
        pref = j["interval_market_s"] if market else j["interval_off_s"]
        age = (now - datetime.fromisoformat(j["last_success_at"])).total_seconds() if j["last_success_at"] else None
        avg = {}
        if j["avg_cost_tokens"]:
            avg["ai_tokens"] = float(j["avg_cost_tokens"])
        share = {}
        if "ai_tokens" in snap and snap["ai_tokens"]["limit"]:
            share["ai_tokens"] = snap["ai_tokens"]["limit"] * (1 - s["reserve_pct"] / 100.0) * (j["priority"] / 15.0)
        eff, reasons = effective_interval(IntervalInput(preferred_s=pref, is_market_open=market, priority=j["priority"], budget_fractions=self._bucket_fractions(j, spec, snap),
                                                        reserve_pct=s["reserve_pct"], avg_cost=avg if j["max_tokens"] > 0 else {}, daily_allowance=share, age_s=age))
        self.db.x("UPDATE sched_jobs SET effective_interval_s=?, effective_reason=? WHERE id=?", (int(eff) if eff else None, json.dumps(reasons), j["id"]))
        need = self._estimate(j, spec, s)
        if eff is None and not manual:
            return self._defer(j, now, reasons[-1], snap)
        essential = j["priority"] >= 5 or manual
        for b, amount in need.items():                                   # cheap pre-check so a deferral does not create a run record
            q = snap.get(b)
            if q and q["limit"] and q["used"] + amount > (q["limit"] if essential else q["limit"] * (1 - s["reserve_pct"] / 100.0)) + 1e-9:
                return self._defer(j, now, f"{b}: needs {amount:g} {q['unit']}, not enough left before {q['resets_at'][11:16]} UTC", snap, bucket=b)
        return {"action": "run", "need": need, "interval": eff or pref, "reasons": reasons}

    def _estimate(self, j: dict, spec: JobSpec, s: dict) -> dict[str, float]:
        """What the run is expected to use, worked out BEFORE it starts. AI: the average of past runs plus 25%, never above the job's own cap (the cap itself for a new job)."""
        need = dict(spec.buckets)
        need["runtime"] = float(j["max_runtime_s"])
        if j["max_tokens"] > 0:
            est = min(j["max_tokens"], (j["avg_cost_tokens"] * 1.25) if j["avg_cost_tokens"] else j["max_tokens"])
            need["ai_tokens"] = float(est)
            usd = ST.dollars(s, int(est * 0.7), int(est * 0.3))
            if usd is not None:
                need["ai_usd"] = usd
                need["ai_usd_month"] = usd
        return need

    def _defer(self, j: dict, now: datetime, reason: str, snap: dict, bucket: str | None = None) -> dict:
        retry = now + timedelta(seconds=DEFER_RECHECK_S)
        if bucket and bucket in snap:
            reset = datetime.fromisoformat(snap[bucket]["resets_at"])
            retry = min(reset, now + timedelta(hours=1)) if reset > now else retry
        if j["deferred_reason"] != reason:                                # one record per distinct reason, not one per check
            self.db.x("INSERT INTO sched_runs(job_id,trigger,started_at,finished_at,status,reason) VALUES(?,?,?,?, 'deferred', ?)", (j["id"], "schedule", now.isoformat(), now.isoformat(), reason))
            if j["priority"] >= 4:
                self.emit("budget", f"deferred:{j['id']}", "warn", f"Job '{j['id']}' is deferred: {reason}")
        self.db.x("UPDATE sched_jobs SET deferred_reason=?, last_status='deferred', next_run_at=?, run_requested=0 WHERE id=?", (reason, retry.isoformat(), j["id"]))
        return {"action": "deferred", "reason": reason}

    # ---- one run ------------------------------------------------------------------------------------------------------------------------
    async def _execute(self, job_id: str, trigger: str, d: dict) -> None:
        now = self.clock()
        s = ST.get(self.db)
        spec = self.specs[job_id]
        lease_s = int(self.job(job_id)["max_runtime_s"]) + 60
        with self.db.tx(immediate=True) as conn:                          # lease + run record in one step: a second process cannot start the same job
            j = dict(conn.execute("SELECT * FROM sched_jobs WHERE id=?", (job_id,)).fetchone())
            if j["lease_until"] and j["lease_until"] >= now.isoformat():
                return
            attempt = j["consecutive_failures"] + 1
            cur = conn.execute("INSERT INTO sched_runs(job_id,trigger,started_at,status,attempt) VALUES(?,?,?, 'running', ?)", (job_id, trigger, now.isoformat(), attempt))
            run_id = cur.lastrowid
            conn.execute("UPDATE sched_jobs SET lease_until=?, lease_run_id=?, last_started_at=?, last_status='running', run_requested=0 WHERE id=?", ((now + timedelta(seconds=lease_s)).isoformat(), run_id, now.isoformat(), job_id))
        essential = j["priority"] >= 5 or trigger == "manual"
        ok, why, _ = self.budget.reserve(run_id, d["need"], now, s["reserve_pct"], essential)
        if not ok:
            self.db.x("UPDATE sched_runs SET status='deferred', finished_at=?, reason=? WHERE id=?", (now.isoformat(), why, run_id))
            self.db.x("UPDATE sched_jobs SET lease_until=NULL, lease_run_id=NULL, last_status='deferred', deferred_reason=?, next_run_at=? WHERE id=?", (why, (now + timedelta(seconds=DEFER_RECHECK_S)).isoformat(), job_id))
            return
        ctx = RunContext(self, j, spec, run_id, trigger, attempt, now)
        err, status, summary, retry_after = None, "ok", {}, None
        try:
            summary = await asyncio.wait_for(spec.handler(ctx), timeout=max(float(j["max_runtime_s"]), 1.0)) or {}
        except asyncio.TimeoutError:
            status, err = "timeout", f"exceeded its {j['max_runtime_s']}s runtime limit"
        except JobCancelled as e:
            status, err = "failed", f"cancelled: {e}"
        except RetryAfter as e:
            status, err, retry_after = "failed", f"provider asked to retry after {e.seconds:.0f}s", e.seconds
        except BudgetExceeded as e:
            status, err = "failed", f"stopped by its own limit: {e}"
        except Exception as e:  # noqa: BLE001  one failing job must never stop the others
            status, err = "failed", f"{type(e).__name__}: {str(e)[:300]}"
            log.exception("job %s failed", job_id)
        self._finish(j, spec, ctx, run_id, status, err, summary, retry_after, s)

    def _finish(self, j: dict, spec: JobSpec, ctx: RunContext, run_id: int, status: str, err: str | None, summary: dict, retry_after: float | None, s: dict) -> None:
        end = self.clock()
        dur = (end - ctx.started).total_seconds()
        tokens = ctx.tokens_in + ctx.tokens_out
        actual = {"runtime": dur, "ai_tokens": float(tokens), **{b: float(n) for b, n in ctx.calls.items()}}
        usd = ST.dollars(s, ctx.tokens_in, ctx.tokens_out)
        if usd is not None:
            actual["ai_usd"] = usd
            actual["ai_usd_month"] = usd
        for b in (set(spec.buckets) | set(ctx.calls)):                      # provider calls the handler did not count are assumed to match the estimate (conservative)
            actual.setdefault(b, float(spec.buckets.get(b, 0)))
        self.budget.settle(run_id, actual)
        for b, n in ctx.calls.items():
            if n > spec.buckets.get(b, 0):
                self.budget.charge(run_id, b, n - spec.buckets.get(b, 0), end)
        avg_tok = tokens if not j["avg_cost_tokens"] else 0.7 * j["avg_cost_tokens"] + 0.3 * tokens
        avg_rt = dur if not j["avg_runtime_s"] else 0.7 * j["avg_runtime_s"] + 0.3 * dur
        self.db.x("UPDATE sched_runs SET status=?, finished_at=?, tokens_in=?, tokens_out=?, provider_calls=?, duration_s=?, summary=?, error=? WHERE id=?",
                  (status, end.isoformat(), ctx.tokens_in, ctx.tokens_out, int(sum(ctx.calls.values())), dur, json.dumps(summary)[:4000], err, run_id))
        if status == "ok":
            eff = j["effective_interval_s"] or (j["interval_market_s"] if self.is_market_open(end) else j["interval_off_s"])
            self.db.x("UPDATE sched_jobs SET lease_until=NULL, lease_run_id=NULL, last_status='ok', last_success_at=?, last_error=NULL, deferred_reason=NULL, consecutive_failures=0, next_run_at=?, runs_total=runs_total+1, "
                      "avg_cost_tokens=?, avg_runtime_s=?, checkpoint=? WHERE id=?", (end.isoformat(), (end + timedelta(seconds=eff)).isoformat(), avg_tok, avg_rt, json.dumps(ctx.checkpoint), j["id"]))
            return
        fails = j["consecutive_failures"] + 1
        if retry_after is not None:
            delay = min(max(retry_after, 1.0), RETRY_AFTER_CAP_S) + self.rng.uniform(0, min(retry_after * 0.1, 30))
        else:
            ceiling = min(BACKOFF_BASE_S * (2 ** (fails - 1)), BACKOFF_CAP_S)
            delay = self.rng.uniform(ceiling / 2, ceiling)                  # jittered, so many failing jobs do not retry in step
        nxt = end + timedelta(seconds=delay)
        if fails >= MAX_ATTEMPTS:
            self.db.x("INSERT INTO sched_dead_letters(job_id,run_id,failed_at,attempts,error,checkpoint) VALUES(?,?,?,?,?,?)", (j["id"], run_id, end.isoformat(), fails, err, json.dumps(ctx.checkpoint)))
            self.emit("failure", f"dead:{j['id']}", "critical", f"Job '{j['id']}' failed {fails} times in a row and was moved to the dead-letter list: {err}")
            nxt = end + timedelta(seconds=j["interval_off_s"])               # stop hammering: wait a normal interval
        elif fails >= 3:
            self.emit("failure", f"fail:{j['id']}", "warn", f"Job '{j['id']}' has failed {fails} times in a row: {err}")
        self.db.x("UPDATE sched_jobs SET lease_until=NULL, lease_run_id=NULL, last_status=?, last_error=?, consecutive_failures=?, next_run_at=?, checkpoint=? WHERE id=?",
                  (status, err, fails, nxt.isoformat(), json.dumps(ctx.checkpoint), j["id"]))

    # ---- dead letters -------------------------------------------------------------------------------------------------------------------
    def resolve_dead_letter(self, dl_id: int, retry: bool) -> bool:
        r = self.db.q("SELECT job_id FROM sched_dead_letters WHERE id=? AND resolved=0", (dl_id,))
        if not r:
            return False
        self.db.x("UPDATE sched_dead_letters SET resolved=1, resolved_at=? WHERE id=?", (self.clock().isoformat(), dl_id))
        if retry:
            self.db.x("UPDATE sched_jobs SET consecutive_failures=0 WHERE id=?", (r[0]["job_id"],))
            self.request_run(r[0]["job_id"])
        return True

    # ---- the long-running loop ----------------------------------------------------------------------------------------------------------
    async def run_forever(self, poll_s: float = 10.0) -> None:
        log.info("scheduler started with %d jobs", len(self.specs))
        while not self._stop.is_set():
            try:
                await self.tick()
            except Exception:  # noqa: BLE001
                log.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=poll_s)
            except asyncio.TimeoutError:
                pass

    def stop(self) -> None:
        self._stop.set()

    # ---- what the dashboard shows -------------------------------------------------------------------------------------------------------
    def overview(self) -> dict:
        now = self.clock()
        s = ST.get(self.db)
        snap = self.budget.snapshot(now, s["reserve_pct"])
        jobs = []
        for r in self.db.q("SELECT * FROM sched_jobs ORDER BY priority DESC, id"):
            j = dict(r)
            spec = self.specs.get(j["id"])
            market = self.is_market_open(now)
            pref = j["interval_market_s"] if market else j["interval_off_s"]
            age = (now - datetime.fromisoformat(j["last_success_at"])).total_seconds() if j["last_success_at"] else None
            limit_age = (spec.freshness_s if spec and spec.freshness_s else pref * 3)
            jobs.append({"id": j["id"], "title": spec.title if spec else j["id"], "kind": spec.kind if spec else None, "description": spec.description if spec else "", "registered": spec is not None,
                         "enabled": bool(j["enabled"]), "paused": bool(j["paused"]), "priority": j["priority"], "uses_ai": j["max_tokens"] > 0,
                         "preferred_market_s": j["interval_market_s"], "preferred_off_s": j["interval_off_s"], "preferred_now_s": pref, "effective_interval_s": j["effective_interval_s"] or pref,
                         "why_effective": json.loads(j["effective_reason"]) if j["effective_reason"] else [f"preferred {pref}s"], "differs": bool(j["effective_interval_s"] and abs(j["effective_interval_s"] - pref) > 1),
                         "next_run_at": j["next_run_at"], "last_success_at": j["last_success_at"], "age_s": age, "stale": age is None or age > limit_age, "last_status": j["last_status"], "last_error": j["last_error"],
                         "deferred_reason": j["deferred_reason"], "failures": j["consecutive_failures"], "avg_tokens": j["avg_cost_tokens"], "avg_runtime_s": j["avg_runtime_s"], "runs_total": j["runs_total"],
                         "max_tokens": j["max_tokens"], "max_runtime_s": j["max_runtime_s"], "max_experiments": j["max_experiments"], "running": bool(j["lease_until"] and j["lease_until"] >= now.isoformat())})
        c = s["claude"]
        hb = self.db.q("SELECT value FROM sched_settings WHERE key='heartbeat'")
        hb_age = (now - datetime.fromisoformat(hb[0]["value"])).total_seconds() if hb else None
        return {"as_of": now.isoformat(), "scheduler_heartbeat_age_s": hb_age, "scheduler_alive": hb_age is not None and hb_age < 120, "market_open": self.is_market_open(now), "paused": s["paused"], "emergency_stop": s["emergency_stop"], "reserve_pct": s["reserve_pct"], "max_concurrent": s["max_concurrent"],
                "market": s["market"], "market_note": "US market holidays are not modelled; the market-hours schedule also applies on a holiday.",
                "claude": {"access": c["access"], "model": c["model"], "telemetry": c["usage_telemetry"],
                           "usage_known": False, "usage_note": "Remaining Claude allowance is not known to this app: per-call token counts are recorded for what this app spends, but the provider's own remaining quota is not read. Budgets here are the limits you set.",
                           "dollar_cost_known": c["price_in_per_mtok"] is not None and c["price_out_per_mtok"] is not None},
                "budgets": list(snap.values()), "jobs": jobs,
                "runs": [dict(r) for r in self.db.q("SELECT id,job_id,trigger,started_at,finished_at,status,attempt,reason,tokens_in,tokens_out,provider_calls,duration_s,error FROM sched_runs ORDER BY id DESC LIMIT 40")],
                "dead_letters": [dict(r) for r in self.db.q("SELECT id,job_id,failed_at,attempts,error FROM sched_dead_letters WHERE resolved=0 ORDER BY id DESC LIMIT 20")],
                "events": [dict(r) for r in self.db.q("SELECT ts,kind,severity,message FROM sched_events ORDER BY id DESC LIMIT 20")]}
