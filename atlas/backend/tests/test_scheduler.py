"""Shared scheduler: interval adaptation, atomic budget reservation (including two processes), leases, retries, dead letters, recovery, emergency stop, honest 'usage unknown'."""
import asyncio
import random
import threading
from datetime import datetime, timedelta, timezone

import pytest

from atlas_api.db import DB
from atlas_api.sched import settings as ST
from atlas_api.sched.budget import Budget, window_end, window_key
from atlas_api.sched.engine import JobSpec, RetryAfter, Scheduler
from atlas_api.sched.intervals import IntervalInput, effective_interval

# Tuesday 2026-11-10, 15:00 UTC = 10:00 New York: market open
OPEN = datetime(2026, 11, 10, 15, 0, tzinfo=timezone.utc)
CLOSED = datetime(2026, 11, 10, 23, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self, t=OPEN):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, **kw):
        self.t += timedelta(**kw)


def make(tmp_path, clock=None, name="s.db", **kw):
    db = DB(str(tmp_path / name))
    clock = clock or Clock()
    return Scheduler(db, clock=clock, rng=random.Random(1), **kw), clock, db


def run(coro):
    return asyncio.run(coro)


async def ok_handler(ctx):
    ctx.call("rss", 2)
    return {"done": True}


def spec(id="news", handler=ok_handler, **kw):
    base = dict(title=id, kind="refresh", interval_market_s=300, interval_off_s=1800, priority=3, buckets={"rss": 2})
    base.update(kw)
    return JobSpec(id=id, handler=handler, **base)


# ---- interval adaptation ------------------------------------------------------------------------------------------------------------------
def test_interval_uses_market_or_off_hours_preference_and_says_so():
    s, why = effective_interval(IntervalInput(preferred_s=300, is_market_open=True))
    assert s == 300 and "market hours" in why[0]
    s, why = effective_interval(IntervalInput(preferred_s=1800, is_market_open=False))
    assert s == 1800 and "outside market hours" in why[0]


def test_interval_stretches_as_the_allowance_runs_down_and_explains_it():
    s, why = effective_interval(IntervalInput(preferred_s=600, is_market_open=True, budget_fractions={"ai_tokens": 0.25}))
    assert s == pytest.approx(1200) and any("x2.0 slower" in w and "25%" in w for w in why)
    s, why = effective_interval(IntervalInput(preferred_s=600, is_market_open=True, budget_fractions={"ai_tokens": 0.01}, reserve_pct=0))
    assert s == pytest.approx(600 * 8) and any("x8.0" in w for w in why)               # with no reserve kept back, never stretched more than 8x
    s, why = effective_interval(IntervalInput(preferred_s=600, is_market_open=True, budget_fractions={"ai_tokens": 0.21}))
    assert s == pytest.approx(600 * 0.5 / 0.21) and any("21%" in w for w in why)      # just above the 20% reserve: stretched about 2.4x, not yet deferred


def test_optional_work_is_deferred_when_only_the_reserve_is_left_but_essential_work_is_not():
    s, why = effective_interval(IntervalInput(preferred_s=600, is_market_open=True, priority=3, budget_fractions={"ai_tokens": 0.15}, reserve_pct=20))
    assert s is None and "usage reserve" in why[-1]
    s, why = effective_interval(IntervalInput(preferred_s=600, is_market_open=True, priority=5, budget_fractions={"ai_tokens": 0.15}, reserve_pct=20))
    assert s is not None


def test_a_job_that_would_overspend_its_share_is_slowed_to_fit():
    # 1000 tokens a run every 600 s = 144,000 a day against a 36,000 share: slowed 4x
    s, why = effective_interval(IntervalInput(preferred_s=600, is_market_open=True, avg_cost={"ai_tokens": 1000}, daily_allowance={"ai_tokens": 36000}))
    assert s == pytest.approx(2400, rel=0.01) and any("share" in w for w in why)


def test_stale_important_data_can_tighten_the_interval_but_never_below_half():
    s, why = effective_interval(IntervalInput(preferred_s=600, is_market_open=True, priority=5, age_s=7200))
    assert s == 300 and any("faster" in w for w in why)
    s2, _ = effective_interval(IntervalInput(preferred_s=600, is_market_open=True, priority=2, age_s=7200))
    assert s2 == 600                                                                    # low priority never tightens


# ---- budget -------------------------------------------------------------------------------------------------------------------------------
def test_reservation_is_all_or_nothing_and_leaves_the_reserve_for_essential_jobs(tmp_path):
    sch, clock, db = make(tmp_path)
    b = sch.budget
    db.x("UPDATE sched_quotas SET limit_amount=1000 WHERE bucket='ai_tokens'")
    ok, why, _ = b.reserve(1, {"ai_tokens": 700, "rss": 5}, OPEN, 20, essential=False)
    assert ok and why is None
    ok, why, _ = b.reserve(2, {"ai_tokens": 200, "rss": 5}, OPEN, 20, essential=False)       # 700 + 200 > 800 usable by optional work
    assert not ok and "ai_tokens" in why and "usable by optional work" in why
    assert b.used("rss", window_key("hour", OPEN)) == 5                                        # the refused request charged nothing, not even rss
    ok, _, _ = b.reserve(3, {"ai_tokens": 250}, OPEN, 20, essential=True)                      # essential work may use the reserve: 950 <= 1000
    assert ok
    ok, why, _ = b.reserve(4, {"ai_tokens": 100}, OPEN, 20, essential=True)
    assert not ok and "full allowance" in why


def test_a_limit_of_zero_means_no_limit_is_set_and_never_blocks(tmp_path):
    sch, _, db = make(tmp_path)
    assert sch.budget.reserve(1, {"ai_usd": 1e9}, OPEN, 20, False)[0]
    assert sch.budget.snapshot(OPEN, 20)["ai_usd"]["limit"] is None


def test_settle_replaces_the_estimate_with_the_actual_and_release_frees_it(tmp_path):
    sch, _, db = make(tmp_path)
    db.x("UPDATE sched_quotas SET limit_amount=1000 WHERE bucket='ai_tokens'")
    sch.budget.reserve(1, {"ai_tokens": 500}, OPEN, 20, False)
    sch.budget.settle(1, {"ai_tokens": 120})
    assert sch.budget.used("ai_tokens", window_key("day", OPEN)) == 120
    sch.budget.reserve(2, {"ai_tokens": 300}, OPEN, 20, False)
    sch.budget.release(2)
    assert sch.budget.used("ai_tokens", window_key("day", OPEN)) == 120


def test_two_processes_cannot_both_spend_the_last_of_a_budget(tmp_path):
    path = str(tmp_path / "shared.db")
    a, b = DB(path), DB(path)                                                          # two connections to one file, like the web process and the worker
    Scheduler(a, clock=Clock())
    a.x("UPDATE sched_quotas SET limit_amount=1000 WHERE bucket='ai_tokens'")
    results, barrier = [], threading.Barrier(6)

    def worker(i):
        bud = Budget(a if i % 2 else b)
        barrier.wait()
        results.append(bud.reserve(100 + i, {"ai_tokens": 400}, OPEN, 0, essential=True)[0])
    ts = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(results) == 2                                                           # 1000 / 400: exactly two fit, however the six interleave
    assert Budget(a).used("ai_tokens", window_key("day", OPEN)) == 800


def test_windows_reset_at_the_right_time():
    assert window_end("day", OPEN) == datetime(2026, 11, 11, 0, 0, tzinfo=timezone.utc)
    assert window_end("month", datetime(2026, 12, 31, 12, tzinfo=timezone.utc)) == datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert window_key("hour", OPEN) == "2026-11-10T15"


# ---- running jobs -------------------------------------------------------------------------------------------------------------------------
def test_a_due_job_runs_once_records_its_cost_and_schedules_the_next_run(tmp_path):
    sch, clock, db = make(tmp_path)
    sch.register(spec())
    d = run(sch.tick())
    assert d[0]["action"] == "run"
    j = sch.job("news")
    assert j["last_status"] == "ok" and j["runs_total"] == 1 and j["consecutive_failures"] == 0
    assert datetime.fromisoformat(j["next_run_at"]) == OPEN + timedelta(seconds=300)          # market hours: the 5 minute preference
    assert run(sch.tick()) == []                                                               # not due again yet
    run_row = db.q("SELECT * FROM sched_runs WHERE job_id='news'")[0]
    assert run_row["status"] == "ok" and run_row["provider_calls"] == 2
    assert sch.budget.used("rss", window_key("hour", OPEN)) == 2


def test_outside_market_hours_the_slower_preference_applies(tmp_path):
    sch, clock, _ = make(tmp_path, Clock(CLOSED))
    sch.register(spec())
    run(sch.tick())
    assert datetime.fromisoformat(sch.job("news")["next_run_at"]) == CLOSED + timedelta(seconds=1800)


def test_two_ticks_at_the_same_time_run_the_job_only_once(tmp_path):
    sch, _, db = make(tmp_path)
    calls = []

    async def slow(ctx):
        calls.append(1)
        await asyncio.sleep(0.2)
        return {}

    sch.register(spec(handler=slow))

    async def go():
        await asyncio.gather(sch.tick(), sch.tick())
    run(go())
    assert len(calls) == 1 and db.q("SELECT COUNT(*) FROM sched_runs WHERE status='ok'")[0][0] == 1


def test_a_second_scheduler_on_the_same_database_cannot_run_a_leased_job(tmp_path):
    path = str(tmp_path / "x.db")
    clock = Clock()
    s1, s2 = Scheduler(DB(path), clock=clock), Scheduler(DB(path), clock=clock)
    started = []

    async def slow(ctx):
        started.append(ctx.job["id"])
        await asyncio.sleep(0.25)
        return {}
    for s in (s1, s2):
        s.register(spec(handler=slow))

    async def go():
        await asyncio.gather(s1.tick(), s2.tick())
    run(go())
    assert started == ["news"]


def test_pause_stops_scheduled_runs_but_a_manual_run_still_works_and_emergency_stop_blocks_everything(tmp_path):
    sch, clock, _ = make(tmp_path)
    sch.register(spec())
    sch.set_global(paused=True)
    assert run(sch.tick()) == []
    assert sch.request_run("news")
    assert run(sch.tick())[0]["action"] == "run" and sch.job("news")["runs_total"] == 1
    sch.emergency_stop(True)
    assert run(sch.tick())[0]["action"] == "stopped"
    assert not sch.request_run("news")                                                         # no manual runs during an emergency stop either
    sch.emergency_stop(False)
    sch.set_global(paused=False)
    clock.advance(seconds=301)
    assert run(sch.tick())[0]["action"] == "run"


def test_emergency_stop_cancels_a_running_job_at_its_next_check(tmp_path):
    sch, _, _ = make(tmp_path)

    async def loop(ctx):
        for _ in range(100):
            ctx.check()
            await asyncio.sleep(0.01)
    sch.register(spec(handler=loop, max_runtime_s=30))

    async def go():
        t = asyncio.create_task(sch.tick())
        await asyncio.sleep(0.08)
        sch.emergency_stop(True)
        await t
    run(go())
    j = sch.job("news")
    assert j["last_status"] == "failed" and "emergency stop" in j["last_error"]


def test_ai_job_is_deferred_with_a_reason_when_the_budget_cannot_cover_it_and_nothing_is_spent(tmp_path):
    sch, clock, db = make(tmp_path)
    ran = []

    async def ai(ctx):
        ran.append(1)
        ctx.use_tokens(100, 50)
        return {}
    sch.register(spec(id="analyse", handler=ai, kind="discovery", max_tokens=5000, buckets={}))
    db.x("UPDATE sched_quotas SET limit_amount=6000 WHERE bucket='ai_tokens'")
    sch.budget.reserve(99, {"ai_tokens": 3000}, OPEN, 20, False)                               # 3000 used; optional work may use 4800 in total
    d = run(sch.tick())
    assert d[0]["action"] == "deferred" and "ai_tokens" in d[0]["reason"] and not ran
    j = sch.job("analyse")
    assert "ai_tokens" in j["deferred_reason"] and datetime.fromisoformat(j["next_run_at"]) > OPEN
    assert sch.budget.used("ai_tokens", window_key("day", OPEN)) == 3000
    clock.advance(minutes=16)
    run(sch.tick())
    assert db.q("SELECT COUNT(*) FROM sched_runs WHERE job_id='analyse' AND status='deferred'")[0][0] == 1       # one record per reason, not one per check
    assert sch.emit("budget", "x", "warn", "m") and not sch.emit("budget", "x", "warn", "m") and sch.emit("budget", "x", "warn", "changed")      # duplicate notices are suppressed


def test_actual_tokens_replace_the_estimate_and_dollars_stay_unknown_without_prices(tmp_path):
    sch, clock, db = make(tmp_path)

    async def ai(ctx):
        ctx.use_tokens(400, 100)
        return {"explained": 1}
    sch.register(spec(id="explain", handler=ai, kind="refresh", max_tokens=2000, buckets={}))
    run(sch.tick())
    r = db.q("SELECT * FROM sched_runs WHERE job_id='explain'")[0]
    assert (r["tokens_in"], r["tokens_out"]) == (400, 100)
    assert sch.budget.used("ai_tokens", window_key("day", OPEN)) == 500                          # 500 actually used, not the 2000 reserved
    assert sch.budget.used("ai_usd", window_key("day", OPEN)) == 0
    o = sch.overview()
    assert o["claude"]["usage_known"] is False and o["claude"]["dollar_cost_known"] is False and "not known" in o["claude"]["usage_note"]
    assert ST.dollars(ST.get(db), 1_000_000, 0) is None                                           # no price entered: no dollar figure invented
    sch.set_global(claude={"price_in_per_mtok": 2.0, "price_out_per_mtok": 10.0})
    assert ST.dollars(ST.get(db), 1_000_000, 100_000) == pytest.approx(3.0)


def test_a_run_that_exceeds_its_own_token_limit_is_stopped_and_counts_what_it_used(tmp_path):
    sch, _, db = make(tmp_path)

    async def greedy(ctx):
        ctx.use_tokens(900, 300)
        return {}
    sch.register(spec(id="greedy", handler=greedy, max_tokens=1000, buckets={}))
    run(sch.tick())
    j = sch.job("greedy")
    assert j["last_status"] == "failed" and "limit" in j["last_error"] and sch.budget.used("ai_tokens", window_key("day", OPEN)) == 1200


def test_failures_back_off_with_jitter_then_dead_letter_and_recover_on_success(tmp_path):
    sch, clock, db = make(tmp_path)
    state = {"fail": True}

    async def flaky(ctx):
        if state["fail"]:
            raise RuntimeError("provider down")
        return {}
    sch.register(spec(handler=flaky))
    delays = []
    for n in range(1, 6):
        run(sch.tick())
        j = sch.job("news")
        assert j["consecutive_failures"] == n and "provider down" in j["last_error"]
        delay = (datetime.fromisoformat(j["next_run_at"]) - clock()).total_seconds()
        delays.append(delay)
        clock.t = datetime.fromisoformat(j["next_run_at"]) + timedelta(seconds=1)
    for n, d in enumerate(delays[:4], start=1):
        ceiling = min(30 * 2 ** (n - 1), 3600)
        assert ceiling / 2 <= d <= ceiling                                                       # bounded exponential, jittered
    assert delays[4] == 1800                                                                     # dead-lettered: back to a normal (off-hours) interval, no hammering
    assert db.q("SELECT COUNT(*) FROM sched_dead_letters WHERE job_id='news' AND resolved=0")[0][0] == 1
    assert any("dead-letter" in e["message"] for e in sch.overview()["events"])
    state["fail"] = False
    dl = db.q("SELECT id FROM sched_dead_letters")[0]["id"]
    assert sch.resolve_dead_letter(dl, retry=True)
    run(sch.tick())
    j = sch.job("news")
    assert j["last_status"] == "ok" and j["consecutive_failures"] == 0 and sch.overview()["dead_letters"] == []


def test_retry_after_from_a_provider_is_respected(tmp_path):
    sch, clock, _ = make(tmp_path)

    async def limited(ctx):
        raise RetryAfter(1200)
    sch.register(spec(handler=limited))
    run(sch.tick())
    delay = (datetime.fromisoformat(sch.job("news")["next_run_at"]) - clock()).total_seconds()
    assert 1200 <= delay <= 1200 + 120                                                           # at least the Retry-After, plus a small jitter


def test_a_run_that_takes_too_long_times_out_and_keeps_its_checkpoint(tmp_path):
    sch, _, _ = make(tmp_path)

    async def hang(ctx):
        ctx.checkpoint["done"] = 3
        ctx.save_checkpoint()
        await asyncio.sleep(5)
    sch.register(spec(handler=hang, max_runtime_s=1))
    run(sch.tick())
    j = sch.job("news")
    assert j["last_status"] == "timeout" and "runtime limit" in j["last_error"] and '"done": 3' in j["checkpoint"]


def test_a_crashed_worker_is_recovered_from_its_checkpoint_and_its_budget_counts_as_spent(tmp_path):
    sch, clock, db = make(tmp_path)
    db.x("UPDATE sched_quotas SET limit_amount=10000 WHERE bucket='ai_tokens'")

    async def work(ctx):
        return {"resumed_from": ctx.checkpoint.get("page")}
    sch.register(spec(id="crawl", handler=work, max_tokens=800, buckets={}))
    # simulate a worker that died mid-run: a running record, a lease, a reservation and a checkpoint
    rid = db.x("INSERT INTO sched_runs(job_id,trigger,started_at,status,attempt) VALUES('crawl','schedule',?, 'running', 1)", (OPEN.isoformat(),))
    db.x("UPDATE sched_jobs SET lease_until=?, lease_run_id=?, checkpoint='{\"page\": 7}' WHERE id='crawl'", ((OPEN + timedelta(seconds=60)).isoformat(), rid))
    sch.budget.reserve(rid, {"ai_tokens": 800}, OPEN, 20, False)
    clock.advance(minutes=5)
    assert sch.recover() == 1
    assert db.q("SELECT status FROM sched_runs WHERE id=?", (rid,))[0]["status"] == "interrupted"
    assert sch.budget.used("ai_tokens", window_key("day", OPEN)) == 800                          # counted as spent: we cannot know it was not
    clock.advance(minutes=1)
    run(sch.tick())
    assert db.q("SELECT summary FROM sched_runs WHERE job_id='crawl' AND status='ok'")[0]["summary"] == '{"resumed_from": 7}'


def test_a_user_changed_setting_survives_registration_on_the_next_start(tmp_path):
    sch, _, db = make(tmp_path)
    sch.register(spec())
    sch.update_job("news", interval_market_s=900, enabled=0)
    sch2 = Scheduler(db, clock=Clock())
    sch2.register(spec())
    j = sch2.job("news")
    assert j["interval_market_s"] == 900 and j["enabled"] == 0
    assert run(sch2.tick()) == []                                                                # disabled jobs do not run
    with pytest.raises(KeyError):
        sch2.update_job("news", lease_until="x")                                                 # only real settings can be changed


def test_overview_shows_effective_interval_reasons_freshness_and_budgets(tmp_path):
    sch, clock, db = make(tmp_path)
    sch.register(spec())
    run(sch.tick())
    o = sch.overview()
    j = next(x for x in o["jobs"] if x["id"] == "news")
    assert o["market_open"] and j["preferred_now_s"] == 300 and j["effective_interval_s"] == 300 and j["why_effective"][0].startswith("preferred") and not j["stale"] and j["differs"] is False
    clock.advance(hours=3)
    assert next(x for x in sch.overview()["jobs"] if x["id"] == "news")["stale"] is True
    assert {b["bucket"] for b in o["budgets"]} >= {"ai_tokens", "sec", "rss", "yahoo", "runtime"} and "market holidays are not modelled" in o["market_note"]


def test_heartbeat_shows_the_scheduler_is_alive_and_goes_stale_when_it_stops(tmp_path):
    sch, clock, _ = make(tmp_path)
    assert sch.overview()["scheduler_alive"] is False                       # never ticked: not alive
    run(sch.tick())
    o = sch.overview()
    assert o["scheduler_alive"] is True and o["scheduler_heartbeat_age_s"] == 0
    clock.advance(minutes=5)
    assert sch.overview()["scheduler_alive"] is False                       # the worker stopped writing it
