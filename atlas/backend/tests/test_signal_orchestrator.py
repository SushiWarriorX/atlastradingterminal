"""Signal orchestrator: concurrent agents, per-agent caching by cadence, partial results, preserved disagreements, and a briefing built only from usable findings."""
import asyncio
import json
from datetime import datetime, timezone

import pytest

from atlas_api.signal import fixtures
from atlas_api.signal import orchestrator as O
from atlas_api.signal.agents.fundamentals import FundamentalsAgent
from atlas_api.signal.agents.macro import MacroAgent
from atlas_api.signal.agents.news import NewsAgent
from atlas_api.signal.agents.technical import TechnicalAgent
from atlas_api.signal.models import AGENTS, Explanation, Fact, Finding, Point
from signal_helpers import FakeNews, ScriptProvider, ctx_for, make_svc, story, all_text, ORDER_WORDS

AAPL = "EQUITY:NASDAQ:AAPL"


@pytest.fixture(autouse=True)
def regular_session(monkeypatch):
    monkeypatch.setattr("atlas_api.service.session_state", lambda now=None: {"state": "REGULAR"})


def run(c):
    return asyncio.run(c)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def pt(kind, text, agent, prio=50, key=None):
    return Point(kind=kind, text=text, agent=agent, priority=prio, dedupe_key=key)


def finding(agent, status="ok", stance=None, points=(), error=None):
    return Finding(agent=agent, status=status, stance=stance, takeaway=f"{agent} takeaway", points=list(points), error=error)


class FakeAgent:
    def __init__(self, name, result=None, *, exc=None, delay=0.0):
        self.name, self.result, self.exc, self.delay, self.calls = name, result or finding(name), exc, delay, 0

    async def run(self, ctx):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.exc:
            raise self.exc
        return self.result.model_copy(deep=True)


def make(agents: dict, **kw):
    clock = kw.pop("clock", Clock())
    ctx = ctx_for(AAPL)
    o = O.Orchestrator(agents, lambda a: ctx_for(AAPL), clock=clock, **kw)
    return o, ctx.asset, clock


def four(**over):
    return {n: over.get(n) or FakeAgent(n) for n in AGENTS}


# --- partial results ------------------------------------------------------------------------------------------------------------------------------
def test_all_four_agents_run_and_the_briefing_summarises_their_stances():
    ag = four(technical=FakeAgent("technical", finding("technical", stance="supportive", points=[pt("supports", "Trend is up.", "technical", 80)])),
              macro=FakeAgent("macro", finding("macro", stance="mixed")))
    o, a, _ = make(ag)
    out = run(o.research(a))
    assert set(out["findings"]) == set(AGENTS) and out["pending"] == [] and out["asset"]["id"] == AAPL
    b = out["briefing"]
    assert b["headline"].startswith("Technicals supportive · Macro mixed") and b["supports"][0]["agent"] == "technical" and b["coverage"]["agents_ok"] == 4
    f = out["findings"]["technical"]
    assert f["analyzed_at"] and f["ttl_seconds"] == int(O.TTL["technical"]) and f["next_refresh_at"] > f["analyzed_at"]
    json.dumps(out)                                                                                         # the whole bundle is plain JSON


def test_a_crashing_agent_becomes_an_unavailable_finding_and_the_others_carry_on():
    ag = four(news=FakeAgent("news", exc=RuntimeError("secret internals: db password=hunter2")),
              technical=FakeAgent("technical", finding("technical", stance="supportive", points=[pt("supports", "Trend is up.", "technical")])))
    o, a, _ = make(ag)
    out = run(o.research(a))
    n = out["findings"]["news"]
    assert n["status"] == "unavailable" and n["error"] == "Internal error (RuntimeError)." and "hunter2" not in json.dumps(out)       # no internals leak to the client
    assert out["findings"]["technical"]["status"] == "ok" and out["briefing"]["supports"]
    cov = out["briefing"]["coverage"]
    assert cov["agents_ok"] == 3 and cov["unavailable"] == [{"agent": "news", "reason": "Internal error (RuntimeError)."}]


def test_a_hung_agent_is_stopped_at_its_own_timeout(monkeypatch):
    monkeypatch.setitem(O.AGENT_TIMEOUT, "macro", 0.05)
    o, a, _ = make(four(macro=FakeAgent("macro", delay=5)))
    out = run(o.research(a, wait=None))
    assert out["findings"]["macro"]["status"] == "unavailable" and "took too long" in out["findings"]["macro"]["error"] and out["findings"]["technical"]["status"] == "ok"


def test_slow_agents_show_as_pending_and_finish_in_the_background():
    slow = FakeAgent("fundamentals", finding("fundamentals", stance="cautious"), delay=0.3)
    o, a, _ = make(four(fundamentals=slow))

    async def scenario():
        first = await o.research(a, wait=0.05)
        assert first["pending"] == ["fundamentals"] and first["findings"]["fundamentals"]["status"] == "pending" and first["findings"]["technical"]["status"] == "ok"
        assert "fundamentals" not in first["briefing"]["headline"]
        await asyncio.sleep(0.4)
        second = await o.research(a, wait=0.05)
        assert second["pending"] == [] and second["findings"]["fundamentals"]["stance"] == "cautious"
        assert slow.calls == 1                                                                              # the same computation finished; it was not started twice
        assert "Fundamentals cautious" in second["briefing"]["headline"]
    run(scenario())


# --- cadence-based caching ----------------------------------------------------------------------------------------------------------------------------
def test_each_agent_is_cached_for_its_own_ttl():
    ag = four()
    o, a, clock = make(ag)
    run(o.research(a))
    run(o.research(a))
    assert all(x.calls == 1 for x in ag.values())
    clock.t += O.TTL["technical"] + 1                                                                       # technical data goes stale first
    run(o.research(a))
    assert ag["technical"].calls == 2 and ag["news"].calls == 1 and ag["macro"].calls == 1 and ag["fundamentals"].calls == 1
    clock.t += O.TTL["news"]
    run(o.research(a))
    assert ag["news"].calls == 2 and ag["macro"].calls == 1


def test_failures_and_partial_results_are_cached_only_briefly():
    ag = four(news=FakeAgent("news", finding("news", status="unavailable", error="feeds down")), macro=FakeAgent("macro", finding("macro", status="partial")))
    o, a, clock = make(ag)
    run(o.research(a))
    assert ag["news"].calls == 1
    clock.t += O.FAIL_TTL + 1
    run(o.research(a))
    assert ag["news"].calls == 2 and ag["macro"].calls == 1 and ag["technical"].calls == 1                  # unavailable is retried soon; partial lasts longer; ok stays cached
    clock.t += O.PARTIAL_TTL + 1
    run(o.research(a))
    assert ag["macro"].calls == 2


def test_simultaneous_requests_share_one_computation_per_agent():
    ag = four(technical=FakeAgent("technical", delay=0.1))
    o, a, _ = make(ag)

    async def many():
        return await asyncio.gather(*(o.research(a, wait=None) for _ in range(6)))
    outs = run(many())
    assert all(x.calls == 1 for x in ag.values()) and len({json.dumps(r["findings"]["technical"]) for r in outs}) == 1


def test_refresh_recomputes_one_agent_and_has_a_cooldown():
    ag = four()
    o, a, clock = make(ag)
    run(o.research(a))
    out = run(o.refresh(a, "news"))
    assert ag["news"].calls == 2 and ag["technical"].calls == 1 and out["findings"]["news"]["status"] == "ok"
    with pytest.raises(O.OrchestratorError) as e:
        run(o.refresh(a, "news"))
    assert e.value.code == "COOLDOWN" and e.value.status == 429
    clock.t += O.REFRESH_COOLDOWN + 1
    run(o.refresh(a, "news"))
    assert ag["news"].calls == 3
    with pytest.raises(O.OrchestratorError) as e2:
        run(o.refresh(a, "weather"))
    assert e2.value.code == "UNKNOWN_AGENT"


# --- the briefing -----------------------------------------------------------------------------------------------------------------------------------
def test_disagreement_between_agents_is_kept_not_averaged_away():
    ag = four(technical=FakeAgent("technical", finding("technical", stance="supportive", points=[pt("supports", "Daily trend is up.", "technical", 80)])),
              macro=FakeAgent("macro", finding("macro", stance="cautious", points=[pt("risk", "Rising yields weigh on growth assets.", "macro", 70)])),
              fundamentals=FakeAgent("fundamentals", finding("fundamentals", stance="supportive")))
    b = run(make(ag)[0].research(make(ag)[1]))["briefing"]
    pairs = [sorted(d["agents"]) for d in b["disagreements"]]
    assert pairs == [["macro", "technical"], ["fundamentals", "macro"]] or sorted(pairs) == sorted([["macro", "technical"], ["fundamentals", "macro"]])
    assert "Technicals supportive · Macro cautious · Fundamentals supportive" in b["headline"]
    assert "both views are shown" in b["disagreements"][0]["text"] and b["supports"][0]["text"] == "Daily trend is up." and b["risks"][0]["text"].startswith("Rising yields")
    agree = four(technical=FakeAgent("technical", finding("technical", stance="supportive")), macro=FakeAgent("macro", finding("macro", stance="mixed")))
    assert run(make(agree)[0].research(make(agree)[1]))["briefing"]["disagreements"] == []                 # supportive vs mixed is not a conflict


def test_briefing_is_short_diverse_deduplicated_and_ordered_by_priority():
    tech = [pt("risk", f"Technical risk {i}", "technical", 90 - i) for i in range(5)] + [pt("risk", "Shared note about volatility", "technical", 95, "vol")]
    mac = [pt("risk", "Shared note about volatility", "macro", 96, "vol"), pt("risk", "Macro risk A", "macro", 40), pt("risk", "Shared note about volatility today", "macro", 30)]
    ag = four(technical=FakeAgent("technical", finding("technical", points=tech)), macro=FakeAgent("macro", finding("macro", points=mac)))
    risks = run(make(ag)[0].research(make(ag)[1]))["briefing"]["risks"]
    assert [r["text"] for r in risks] == ["Shared note about volatility", "Technical risk 0", "Technical risk 1"]       # priority order; the duplicate and the near-duplicate are dropped
    assert {r["agent"] for r in risks} == {"technical", "macro"}                                                   # the highest-priority line came from macro, not only technical


def test_only_usable_findings_feed_the_briefing_and_coverage_says_what_is_missing():
    ag = four(technical=FakeAgent("technical", finding("technical", status="unavailable", error="no bars", points=[pt("supports", "should not appear", "technical", 99)])),
              macro=FakeAgent("macro", finding("macro", status="not_applicable")), news=FakeAgent("news", finding("news", status="partial", points=[pt("changed", "A headline.", "news", 50)])))
    b = run(make(ag)[0].research(make(ag)[1]))["briefing"]
    assert b["supports"] == [] and b["changed"][0]["text"] == "A headline." and b["coverage"]["partial"] == ["news"] and b["coverage"]["not_applicable"] == ["macro"]
    assert b["coverage"]["unavailable"][0]["agent"] == "technical" and b["headline"] == "Not enough analysis is available yet."


def test_scheduled_moments_keep_their_utc_time_for_the_client():
    ag = four(macro=FakeAgent("macro", finding("macro", points=[Point(kind="watch", text="Next FOMC decision.", agent="macro", priority=80, at_utc="2026-12-09T19:00:00+00:00")])))
    w = run(make(ag)[0].research(make(ag)[1]))["briefing"]["watch"]
    assert w[0]["at_utc"] == "2026-12-09T19:00:00+00:00"


# --- demo vs live -----------------------------------------------------------------------------------------------------------------------------------
def test_demo_flag_marks_every_finding_and_the_briefing_and_live_mode_never_does():
    demo, a, _ = make(four(), demo=True)
    d = run(demo.research(a))
    assert d["demo"] is True and d["briefing"]["demo"] is True and all(f["demo"] for f in d["findings"].values())
    live, a2, _ = make(four(), demo=False)
    l = run(live.research(a2))
    assert l["demo"] is False and l["briefing"]["demo"] is False and not any(f["demo"] for f in l["findings"].values())


def real_agents():
    return {"news": NewsAgent(), "technical": TechnicalAgent(), "macro": MacroAgent(), "fundamentals": FundamentalsAgent()}


def test_live_mode_never_touches_the_demo_fixtures(monkeypatch):
    for name in ("news", "macro_overview", "fedwatch", "etf_raw", "coin_raw", "btc_snapshot"):
        monkeypatch.setattr(fixtures, name, lambda *a, **k: (_ for _ in ()).throw(AssertionError("demo fixture used in live mode")))
    svc = make_svc(ScriptProvider(drift=0.004))[0]
    news = FakeNews([story(1, "Apple posts record revenue", hours_ago=3)])
    o = O.Orchestrator(real_agents(), lambda a: ctx_for(AAPL, svc=svc, news=news))
    out = run(o.research(ctx_for(AAPL).asset, wait=None))
    assert all(f["status"] in ("ok", "partial") and f["demo"] is False for f in out["findings"].values())
    assert "DEMO" not in json.dumps(out) and "Demo fixture" not in json.dumps(out)


def test_full_live_style_bundle_is_attributed_dated_and_free_of_order_language():
    svc = make_svc(ScriptProvider(drift=0.004))[0]
    news = FakeNews([story(1, "Apple posts record revenue", hours_ago=3), story(2, "Regulators open a probe into app store fees", hours_ago=10)])
    o = O.Orchestrator(real_agents(), lambda a: ctx_for(AAPL, svc=svc, news=news))
    out = run(o.research(ctx_for(AAPL).asset, wait=None))
    for name, f in out["findings"].items():
        assert f["takeaway"] and f["sources"] and f["analyzed_at"] and f["data_as_of"], name
        assert all(x["source"] and x["display"] for x in f["facts"]), name
        for t in [f["takeaway"], *(i["text"] for i in f["interpretations"]), *(p["text"] for p in f["points"])]:
            assert not ORDER_WORDS.search(t.replace("“", "").replace("”", "")), t
    b = out["briefing"]
    assert b["headline"] and all(len(b[k]) <= O.MAX_LINES for k in ("changed", "supports", "risks", "watch")) and b["watch"]
    assert {l["agent"] for k in ("changed", "supports", "risks", "watch") for l in b[k]} >= {"technical", "news"}


# --- optional AI wording --------------------------------------------------------------------------------------------------------------------------------
class FakeExplainer:
    llm = type("L", (), {"model": "m"})()

    def __init__(self, fail=False):
        self.fail, self.calls = fail, []

    async def explain(self, f, asset):
        self.calls.append(f.agent)
        if self.fail:
            raise RuntimeError("model down")
        return Explanation(text="Plain words.", model="m")


def test_ai_wording_is_attached_only_to_usable_findings_and_never_breaks_a_finding():
    ag = four(news=FakeAgent("news", finding("news", status="unavailable", error="x")))
    ex = FakeExplainer()
    out = run(make(ag, explainer=ex)[0].research(make(ag)[1]))
    assert out["findings"]["technical"]["explanation"]["text"] == "Plain words." and out["findings"]["news"]["explanation"] is None and "news" not in ex.calls
    bad = run(make(four(), explainer=FakeExplainer(fail=True))[0].research(make(four())[1]))
    assert all(f["explanation"] is None and f["status"] == "ok" for f in bad["findings"].values())
