"""Operations: the default jobs (with stand-in services), the health check, and the /api/ops routes."""
import asyncio
import random
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.db import DB
from atlas_api.sched.budget import window_key
from atlas_api.sched.engine import Scheduler
from atlas_api.sched.jobs import register_default_jobs

OPEN = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.t = OPEN

    def __call__(self):
        return self.t


class Svc:
    """A stand-in for a service with an async overview()."""

    def __init__(self, out=None, boom=False):
        self.out, self.boom = out or {"available": True}, boom

    async def overview(self):
        if self.boom:
            raise RuntimeError("down")
        return self.out


class News:
    def __init__(self, res):
        self.res = res

    async def refresh(self):
        return self.res


class Edgar:
    def __init__(self, enabled):
        self.enabled = enabled


class StockResearch:
    def __init__(self, enabled=True, needs_contact=False):
        self.edgar = Edgar(enabled)
        self.needs_contact = needs_contact
        self.calls = []

    async def filings_feed(self, insts, **kw):
        self.calls.append([i.symbol for i in insts])
        return {"items": [{"x": 1}] * 3, "errors": [], "needs_contact": self.needs_contact}


class Inst:
    def __init__(self, s):
        self.symbol, self.asset_class = s, "equity"


def setup(tmp_path, news=None, sr=None, extras=None):
    db = DB(str(tmp_path / "o.db"))
    clock = Clock()
    s = Scheduler(db, clock=clock, rng=random.Random(2))
    deps = {"db": db, "news": news or News([{"ok": True, "new": 2, "error": None}]), "stock_research": sr or StockResearch(), "resolve": lambda t: Inst(t), "btc_data": None, "demo": False, "extras": extras or {}}
    register_default_jobs(s, deps)
    s.set_global(max_concurrent=8)                                                                # these tests run every job in one tick; the slot limit itself is tested in test_scheduler
    return s, clock, db, deps


def tick(s):
    return asyncio.run(s.tick())


def test_default_jobs_are_registered_with_sensible_limits_and_none_uses_claude(tmp_path):
    s, _, _, _ = setup(tmp_path)
    jobs = {j["id"]: j for j in s.overview()["jobs"]}
    assert set(jobs) == {"news_refresh", "filings_refresh", "macro_refresh", "crypto_refresh", "health_check"}
    assert jobs["health_check"]["priority"] == 5 and not any(j["uses_ai"] for j in jobs.values())
    assert jobs["news_refresh"]["preferred_market_s"] < jobs["news_refresh"]["preferred_off_s"]


def test_filings_job_starts_disabled_when_the_sec_contact_is_missing_and_says_why(tmp_path):
    s, _, _, _ = setup(tmp_path, sr=StockResearch(enabled=False))
    j = next(x for x in s.overview()["jobs"] if x["id"] == "filings_refresh")
    assert j["enabled"] is False and "ATLAS_SEC_CONTACT" in j["description"]


def test_news_refresh_counts_provider_calls_and_fails_only_when_every_feed_fails(tmp_path):
    s, clock, db, _ = setup(tmp_path, news=News([{"ok": True, "new": 3, "error": None}, {"ok": False, "new": 0, "error": "HTTP 503"}]))
    tick(s)
    j = s.job("news_refresh")
    assert j["last_status"] == "ok" and s.budget.used("rss", window_key("hour", OPEN)) >= 2


def test_news_refresh_failing_everywhere_is_a_failure(tmp_path):
    (tmp_path / "b").mkdir()
    s, _, _, _ = setup(tmp_path / "b", news=News([{"ok": False, "new": 0, "error": "HTTP 503"}, {"ok": False, "new": 0, "error": "timeout"}]))
    tick(s)
    j = s.job("news_refresh")
    assert j["last_status"] == "failed" and "all 2 feeds failed" in j["last_error"] and j["consecutive_failures"] == 1


def test_macro_refresh_succeeds_when_some_sources_fail_and_fails_when_all_do(tmp_path):
    s, _, _, _ = setup(tmp_path, extras={"macro_brief": Svc(), "treasury": Svc({"available": False, "reason": "x"}), "ecb_fx": Svc(boom=True), "world_bank": Svc()})
    tick(s)
    row = s.db.q("SELECT summary,status FROM sched_runs WHERE job_id='macro_refresh'")[0]
    assert row["status"] == "ok" and "macro_brief" in row["summary"] and "ecb_fx: RuntimeError" in row["summary"]
    (tmp_path / "c").mkdir()
    s2, _, _, _ = setup(tmp_path / "c", extras={"macro_brief": Svc(boom=True), "treasury": Svc({"available": False})})
    tick(s2)
    assert s2.job("macro_refresh")["last_status"] == "failed" and "every macro source failed" in s2.job("macro_refresh")["last_error"]


def test_health_check_reports_stale_jobs_dead_letters_and_exhausted_budgets_without_repeating_itself(tmp_path):
    s, clock, db, _ = setup(tmp_path)
    tick(s)                                                                                       # everything runs once
    clock.t = OPEN + timedelta(hours=5)                                                          # the news job is now far past 3x its interval
    db.x("UPDATE sched_quotas SET limit_amount=100 WHERE bucket='ai_tokens'")
    s.budget.charge(1, "ai_tokens", 100, clock.t)                                               # exhausted
    db.x("INSERT INTO sched_dead_letters(job_id,failed_at,attempts,error) VALUES('macro_refresh',?,5,'boom')", (clock.t.isoformat(),))
    db.x("UPDATE sched_jobs SET next_run_at=? WHERE id='health_check'", (clock.t.isoformat(),))
    tick(s)
    summary = db.q("SELECT summary FROM sched_runs WHERE job_id='health_check' ORDER BY id DESC LIMIT 1")[0]["summary"]
    assert "freshness: news_refresh" in summary and "dead letters" in summary and "budget: ai_tokens" in summary and '"database integrity"' in summary
    n_events = db.q("SELECT COUNT(*) FROM sched_events")[0][0]
    assert n_events >= 3
    clock.t += timedelta(minutes=11)
    db.x("UPDATE sched_jobs SET next_run_at=? WHERE id='health_check'", (clock.t.isoformat(),))
    tick(s)
    assert db.q("SELECT COUNT(*) FROM sched_events WHERE kind IN ('stale','budget')")[0][0] <= n_events        # unchanged problems are not re-announced


def test_healthy_system_reports_all_ok(tmp_path):
    s, _, db, _ = setup(tmp_path)
    tick(s)
    out = db.q("SELECT summary FROM sched_runs WHERE job_id='health_check'")[0]["summary"]
    assert '"problems": 0' in out and "all checks" in out


# ---- API ----------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "api.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        yield c


def data(r):
    assert r.status_code == 200, r.text
    return r.json()["data"]


def test_overview_has_jobs_budgets_and_honest_claude_status(client):
    o = data(client.get("/api/ops/overview"))
    assert {j["id"] for j in o["jobs"]} >= {"news_refresh", "health_check"} and o["claude"]["access"] == "unknown" and o["claude"]["usage_known"] is False
    assert o["reserve_pct"] == 20 and not o["paused"] and not o["emergency_stop"] and any(b["bucket"] == "ai_tokens" for b in o["budgets"])


def test_job_settings_are_validated_and_persist(client):
    o = data(client.post("/api/ops/jobs/news_refresh", json={"interval_market_s": 600, "priority": 2, "enabled": False}))
    j = next(x for x in o["jobs"] if x["id"] == "news_refresh")
    assert j["preferred_market_s"] == 600 and j["priority"] == 2 and j["enabled"] is False
    assert client.post("/api/ops/jobs/news_refresh", json={"interval_market_s": 1}).status_code == 422          # too small
    assert client.post("/api/ops/jobs/news_refresh", json={"priority": 9}).status_code == 422
    assert client.post("/api/ops/jobs/news_refresh", json={"lease_until": "x"}).status_code == 422               # unknown fields are refused
    assert client.post("/api/ops/jobs/nope", json={"priority": 3}).status_code == 404


def test_manual_run_pause_resume_and_emergency_stop(client):
    o = data(client.post("/api/ops/jobs/health_check/run"))
    assert next(j for j in o["jobs"] if j["id"] == "health_check")["last_status"] == "ok"
    assert data(client.post("/api/ops/pause"))["paused"] is True and data(client.post("/api/ops/resume"))["paused"] is False
    assert data(client.post("/api/ops/emergency-stop"))["emergency_stop"] is True
    r = client.post("/api/ops/jobs/health_check/run")
    assert r.status_code == 409 and "emergency stop" in r.json()["error"]["message"].lower()
    assert data(client.post("/api/ops/emergency-clear"))["emergency_stop"] is False
    assert any("Emergency stop" in e["message"] for e in data(client.get("/api/ops/overview"))["events"])


def test_claude_settings_never_invent_usage_or_prices(client):
    o = data(client.post("/api/ops/settings", json={"reserve_pct": 30, "claude": {"access": "api", "daily_token_limit": 50000, "usage_telemetry": "per_request"}}))
    assert o["reserve_pct"] == 30 and o["claude"]["access"] == "api" and o["claude"]["telemetry"] == "per_request"
    assert o["claude"]["usage_known"] is False and o["claude"]["dollar_cost_known"] is False                       # still no provider-side remaining quota and no price entered
    assert next(b for b in o["budgets"] if b["bucket"] == "ai_tokens")["limit"] == 50000
    o = data(client.post("/api/ops/settings", json={"claude": {"price_in_per_mtok": 2.0, "price_out_per_mtok": 10.0}}))
    assert o["claude"]["dollar_cost_known"] is True
    assert client.post("/api/ops/settings", json={"claude": {"access": "magic"}}).status_code == 422
    assert client.post("/api/ops/settings", json={"reserve_pct": 99}).status_code == 422


def test_dead_letter_endpoints(client):
    assert client.post("/api/ops/dead-letters/999/retry").status_code == 404
    assert client.post("/api/ops/dead-letters/1/explode").status_code == 422
