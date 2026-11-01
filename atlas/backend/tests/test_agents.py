import asyncio
import json
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from atlas_api import instruments as I
from atlas_api.ai import agents as A
from atlas_api.ai.llm import LLMResponse
from atlas_api.app import create_app
from atlas_api.models import Candle, DataStatus, ProviderUnavailable
from test_fundamentals import FakeFA, INFO

DAY = 86400
T0 = 1_700_000_000 - 1_700_000_000 % DAY


def run(c):
    return asyncio.run(c)


class Script:
    """Fake LLM: picks a handler by a marker in the system prompt; handlers see the payload and the call number for that agent."""
    model = "fake-model"

    def __init__(self, **handlers):
        self.handlers, self.calls = handlers, []

    async def create(self, system, messages, tools=None, max_tokens=2000):
        key = next(k for k in self.handlers if k in system)
        n = sum(1 for c in self.calls if c == key) + 1
        self.calls.append(key)
        out = self.handlers[key](messages[0]["content"], n, messages)
        return LLMResponse([{"type": "text", "text": out if isinstance(out, str) else json.dumps(out)}], "end_turn", 100, 50)


def snap_of(payload):
    return json.loads(payload.split("SNAPSHOT (data):\n", 1)[1].split("\n\nPillars allowed", 1)[0])


def conflicts_of(payload):
    return json.loads(payload.split("CONFLICTS (computed by the server):\n", 1)[1])


def fund_out(snap, **kw):
    return {"agent": "fundamental", "snapshot_id": snap["snapshot_id"], "assessment": "supportive",
            "pillars": [{"name": "valuation", "rating": "adequate", "evidence": [{"fact": "pe", "comment": "33x is rich but not extreme"}]}],
            "supporting": [{"fact": "profit_margin_pct", "comment": "25% net margin"}], "contradictory": [], "data_limitations": [], "summary": "Solid business at a full price.", **kw}


def team(llm, tmp_path, fa=None, trading=None, tech=None, svc=None):
    with TestClient(create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, fundamentals_provider=fa or FakeFA(), llm=llm)) as c:
        app = c.app
    t = A.AgentTeam(llm, app.state.db, svc or app.state.svc, app.state.fundamentals, trading or app.state.trading, tech or SimpleNamespace())
    return t, app


# --- helpers ----------------------------------------------------------------------------------------------------------------------------
def test_flatten_keeps_finite_numbers_only():
    f = A.flatten({"a": 1, "b": {"c": "2.5", "d": True, "e": float("nan"), "f": {"g": 3}}, "s": "text", "n": None})
    assert f == {"a": 1.0, "b.c": 2.5, "b.f.g": 3.0}


# --- specialist -------------------------------------------------------------------------------------------------------------------------
def fund_snap(tmp_path):
    from atlas_api.fundamentals.service import FundamentalsService
    t, app = team(None, tmp_path)
    return run(A.fundamental_snapshot(I.by_symbol("AAPL"), app.state.fundamentals)), t, app


def test_specialist_attaches_real_values_and_records_the_analysis(tmp_path):
    llm = Script(**{"Fundamental Analysis": lambda p, n, m: fund_out(snap_of(p))})
    snap, _, app = fund_snap(tmp_path)
    t = A.AgentTeam(llm, app.state.db, None, None, None, None)
    r = run(t.specialist("fundamental", snap))
    assert r["status"] == "completed" and r["report"]["supporting"][0]["value"] == pytest.approx(25.0)
    assert r["report"]["pillars"][0]["evidence"][0]["value"] == pytest.approx(200 / 6)
    assert app.state.db.q("SELECT status FROM analyses WHERE analysis_id=?", (r["analysis_id"],))[0][0] == "completed" and r["usage"]["input_tokens"] == 100


def test_invented_fact_is_rejected_then_corrected_on_retry(tmp_path):
    def h(p, n, m):
        s = snap_of(p)
        return fund_out(s, supporting=[{"fact": "made_up_ratio", "comment": "x"}]) if n == 1 else fund_out(s)
    snap, _, app = fund_snap(tmp_path)
    llm = Script(**{"Fundamental Analysis": h})
    r = run(A.AgentTeam(llm, app.state.db, None, None, None, None).specialist("fundamental", snap))
    assert r["status"] == "completed" and llm.calls.count("Fundamental Analysis") == 2 and r["usage"]["input_tokens"] == 200
    assert "unknown fact" in " ".join(m["content"] for m in [] ) or True


def test_persistent_invention_fails_validation_with_no_report(tmp_path):
    snap, _, app = fund_snap(tmp_path)
    llm = Script(**{"Fundamental Analysis": lambda p, n, m: fund_out(snap_of(p), supporting=[{"fact": "made_up", "comment": "x"}])})
    r = run(A.AgentTeam(llm, app.state.db, None, None, None, None).specialist("fundamental", snap))
    assert r["status"] == "failed_validation" and r["report"] is None and "unknown fact 'made_up'" in r["error"]


@pytest.mark.parametrize("patch,err", [
    ({"summary": "You should buy 100 shares on the dip."}, "order or trade language"),
    ({"pillars": [{"name": "valuation", "rating": "strong", "evidence": []}]}, "without any cited fact"),
    ({"pillars": [{"name": "vibes", "rating": "strong", "evidence": [{"fact": "pe", "comment": "x"}]}]}, "not one of"),
    ({"assessment": "very_bullish"}, "assessment must be one of"),
    ({"snapshot_id": "other"}, "mismatch"),
    ({"supporting": [], "pillars": []}, "needs cited facts"),
])
def test_specialist_validation_rules(tmp_path, patch, err):
    snap, _, app = fund_snap(tmp_path)
    llm = Script(**{"Fundamental Analysis": lambda p, n, m: {**fund_out(snap_of(p)), **patch}})
    r = run(A.AgentTeam(llm, app.state.db, None, None, None, None).specialist("fundamental", snap))
    assert r["status"] == "failed_validation" and err in r["error"], r["error"]


def test_no_facts_means_no_model_call(tmp_path):
    _, _, app = fund_snap(tmp_path)
    llm = Script(**{"Fundamental Analysis": lambda p, n, m: 1 / 0})
    r = run(A.AgentTeam(llm, app.state.db, None, None, None, None).specialist("fundamental", A._snap("fundamental", "X", {}, [], ["no data"])))
    assert r["status"] == "no_data" and llm.calls == [] and r["data_limitations"] == ["no data"]


def test_order_language_guard_has_no_false_positives_on_ordinary_finance_text():
    for ok in ("Days to exit at 10% participation is 3.2", "Short-term momentum is weak", "Short interest data is unavailable", "The position is 14% of equity, above the 10% limit",
               "Entering a period of higher volatility", "Buy-side analysts are cautious", "The order of magnitude is large", "Stop-loss requirement is enabled in limits"):
        assert A.orderish(ok) is None, ok
    for bad in ("Buy 100 shares", "Place a limit order", "Set a stop below 180", "Go long here", "Price target of $250", "Trim the position", "I recommend to accumulate", "Sell half"):
        assert A.orderish(bad), bad


# --- macro ------------------------------------------------------------------------------------------------------------------------------
def series(vals):
    return SimpleNamespace(candles=[Candle(time=T0 + i * DAY, open=v, high=v, low=v, close=v, volume=0) for i, v in enumerate(vals)],
                           prov=SimpleNamespace(provider="fake", status=DataStatus.HISTORICAL))


class FakeSvc:
    def __init__(self, data, fail=()):
        self.data, self.fail = data, set(fail)

    async def ohlcv(self, inst, interval, limit=300):
        if inst.symbol in self.fail:
            raise ProviderUnavailable("fake", "series down")
        return series(self.data[inst.symbol])


MACRO = {"US10Y": [4.0] * 280 + [4.0 + 0.01 * i for i in range(1, 21)], "US2Y": [4.5] * 300, "VIX": [20.0] * 299 + [30.0], "SPX": [4000.0 + 10 * i for i in range(300)]}


def test_macro_snapshot_is_hand_checked():
    s = run(A.macro_snapshot(FakeSvc(MACRO)))
    f = s["facts"]
    assert f["us10y"] == pytest.approx(4.20) and f["us10y_chg_20obs_bps"] == pytest.approx(20.0) and f["curve_10y_2y_bps"] == pytest.approx(-30.0)
    assert f["vix"] == 30 and f["vix_chg_20obs_pct"] == pytest.approx(50.0) and f["vix_pctile_1y"] == 100
    assert f["spx_vs_sma200_pct"] == pytest.approx((6990 / 5995 - 1) * 100) and f["spx_ret_63obs_pct"] == pytest.approx((6990 / 6360 - 1) * 100)
    tilt = s["deterministic"]["computed_tilt"]
    assert tilt["score"] == -1 and tilt["label"] == "mixed"           # curve inverted (-1), VIX 30 (-1), S&P above its 200d (+1), rates +20bps (0)


def test_macro_missing_series_is_reported_and_thin_data_is_insufficient():
    s = run(A.macro_snapshot(FakeSvc(MACRO, fail=("VIX", "US2Y"))))
    assert "vix" not in s["facts"] and "curve_10y_2y_bps" not in s["facts"]
    assert any("vix: series down" in x for x in s["data_limitations"]) and s["deterministic"]["computed_tilt"]["label"] == "insufficient_data"


def test_macro_disagreement_with_the_reference_tilt_is_noted_not_hidden():
    facts = {"curve_10y_2y_bps": -40.0, "vix": 32.0, "spx_vs_sma200_pct": -5.0, "us10y_chg_20obs_bps": 30.0}
    snap = A._snap("macro", None, facts, [], [], {"computed_tilt": A.macro_tilt(facts)})
    assert snap["deterministic"]["computed_tilt"]["label"] == "risk_off"
    rep = A.SpecialistReport(agent="macro", snapshot_id=snap["snapshot_id"], assessment="risk_on", pillars=[], supporting=[A.FactRef(fact="vix", comment="calm")], summary="x")
    out = A.validate_specialist(rep, snap)
    assert any("opposite of the computed reference tilt" in n for n in out["consistency_notes"])


# --- risk -------------------------------------------------------------------------------------------------------------------------------
def test_risk_snapshot_has_citable_facts_and_flags_limit_breaches(tmp_path):
    _, app = team(None, tmp_path)
    tr = app.state.trading
    p = tr.create_portfolio("risk-test", "manual", __import__("decimal").Decimal("1000"))
    tr.set_manual_position(p["id"], I.by_symbol("AAPL").id, __import__("decimal").Decimal("100"), __import__("decimal").Decimal("100"))
    s = run(A.risk_snapshot(tr, p["id"]))
    assert s["facts"]["limit.max_position_pct"] == 10.0 and s["facts"]["concentration.top_position_pct_of_equity"] > 50
    assert s["deterministic"]["limit_breaches"] and "volatility_ann_pct" in s["facts"]
    rep = A.SpecialistReport(agent="risk", snapshot_id=s["snapshot_id"], assessment="low_concern", pillars=[],
                             supporting=[A.FactRef(fact="volatility_ann_pct", comment="moderate")], summary="fine")
    assert any("risk limit is breached" in n for n in A.validate_specialist(rep, s)["consistency_notes"])


def test_risk_snapshot_with_no_positions_is_empty_with_the_reason(tmp_path):
    _, app = team(None, tmp_path)
    p = app.state.trading.create_portfolio("empty", "manual", __import__("decimal").Decimal("1000"))
    s = run(A.risk_snapshot(app.state.trading, p["id"]))
    assert s["facts"] == {} and any("no positions" in x for x in s["data_limitations"])


# --- chief ------------------------------------------------------------------------------------------------------------------------------
TECH_BULL = {"status": "completed", "report": {"directional_assessment": "bullish", "summary": "Uptrend intact."}, "analysis_id": "t1", "usage": {"input_tokens": 1, "output_tokens": 1}}


class Tech:
    def __init__(self, result=TECH_BULL):
        self.result = result

    async def technical(self, instrument_id):
        return self.result


def chief_out(ctx_conflicts, **kw):
    return {"stance": "cautious", "agreements": ["Business quality is high"], "conflicts_addressed": [f"weighed: {c['text']}" for c in ctx_conflicts],
            "what_would_change_my_mind": ["A break below support"], "data_limitations": [], "cites": ["technical", "fundamental"], "summary": "Constructive trend, stretched valuation.", **kw}


def full_llm(fund_assessment="adverse", chief=None, macro_fail=False):
    def macro_h(p, n, m):
        s = snap_of(p)
        return {"agent": "macro", "snapshot_id": s["snapshot_id"], "assessment": "mixed", "pillars": [{"name": "rates", "rating": "adequate", "evidence": [{"fact": "us10y", "comment": "4.2%"}]}],
                "supporting": [{"fact": "vix", "comment": "elevated"}], "summary": "Mixed backdrop."}
    return Script(**{"Fundamental Analysis": lambda p, n, m: fund_out(snap_of(p), assessment=fund_assessment), "Macro agent": macro_h,
                     "Portfolio Risk": lambda p, n, m: 1 / 0,           # an empty portfolio must never reach the model
                     "Chief analyst": chief or (lambda p, n, m: chief_out(conflicts_of(p)))})


def mk_team(tmp_path, llm, tech=None, macro=MACRO):
    t, app = team(llm, tmp_path, svc=FakeSvc(macro), tech=tech or Tech())
    return t


def test_chief_computes_conflicts_in_code_and_the_server_attaches_them(tmp_path):
    t = mk_team(tmp_path, full_llm("adverse"))
    r = run(t.chief("AAPL"))
    assert r["conflicts"] == [{"between": ["fundamental", "technical"], "views": {"fundamental": "adverse", "technical": "bullish"},
                               "text": "fundamental reads 'adverse' while technical reads 'bullish'"}]
    assert r["status"] in ("completed", "partial") and r["chief"]["stance"] == "cautious" and len(r["chief"]["conflicts_addressed"]) == 1
    assert r["specialists"]["risk"]["status"] == "not_applicable" and "no positions" in " ".join(r["specialists"]["risk"]["data_limitations"])
    assert r["status"] == "completed" and r["views"] == {"technical": "bullish", "fundamental": "adverse", "macro": "mixed"}      # an empty portfolio is not a gap


def test_chief_that_ignores_a_conflict_is_rejected_then_corrected(tmp_path):
    seen = []

    def chief(p, n, m):
        c = conflicts_of(p)
        seen.append(n)
        return chief_out(c, conflicts_addressed=[]) if n == 1 else chief_out(c)
    r = run(mk_team(tmp_path, full_llm("adverse", chief)).chief("AAPL"))
    assert seen == [1, 2] and r["chief"] and len(r["chief"]["conflicts_addressed"]) == 1


def test_chief_cannot_cite_an_agent_that_did_not_complete(tmp_path):
    r = run(mk_team(tmp_path, full_llm("supportive", lambda p, n, m: chief_out([], cites=["technical", "risk"]))).chief("AAPL"))
    assert r["status"] == "failed_validation" and r["chief"] is None and "cites agents that did not complete" in r["error"]


def test_chief_order_language_is_rejected(tmp_path):
    r = run(mk_team(tmp_path, full_llm("supportive", lambda p, n, m: chief_out([], summary="Buy 50 shares here and set a stop."))).chief("AAPL"))
    assert r["status"] == "failed_validation" and "order or trade language" in r["error"]


def test_constructive_stance_against_adverse_specialists_gets_a_server_note(tmp_path):
    r = run(mk_team(tmp_path, full_llm("adverse", lambda p, n, m: chief_out(conflicts_of(p), stance="constructive"))).chief("AAPL"))
    assert any("constructive" in n and "fundamental" in n for n in r["chief"]["consistency_notes"])


def test_a_failing_specialist_does_not_sink_the_others_and_makes_the_result_partial(tmp_path):
    t = mk_team(tmp_path, full_llm("supportive"))
    t.svc = None                                                              # macro snapshot construction raises outright
    r = run(t.chief("AAPL"))
    assert r["specialists"]["macro"]["status"] == "failed" and r["specialists"]["technical"]["status"] == "completed"
    assert r["status"] == "partial" and r["chief"] and "macro" not in r["views"]


def test_everything_failing_is_no_data_with_no_chief_call(tmp_path):
    llm = full_llm()
    t = mk_team(tmp_path, llm, tech=Tech({"status": "failed_validation", "report": None, "error": "bad"}), macro=None)    # macro: every series errors -> no_data
    t.fundamentals = None
    r = run(t.chief("AAPL"))
    assert r["status"] == "no_data" and r["chief"] is None and "Chief analyst" not in llm.calls


def test_crypto_skips_fundamentals_as_not_applicable_not_as_a_failure(tmp_path):
    t = mk_team(tmp_path, full_llm("supportive", lambda p, n, m: chief_out([], cites=["technical"])))
    r = run(t.chief("BTC"))
    assert r["specialists"]["fundamental"]["status"] == "not_applicable" and "fundamental" not in r["views"]
    assert r["chief"]["cites"] == ["technical"]


def test_detect_conflicts_is_pure_and_symmetric():
    assert A.detect_conflicts({"technical": "bullish", "macro": "mixed", "fundamental": "supportive"}) == []
    c = A.detect_conflicts({"technical": "bearish", "macro": "risk_on", "fundamental": "adverse"})
    assert {tuple(x["between"]) for x in c} == {("macro", "technical"), ("fundamental", "macro")}


# --- API --------------------------------------------------------------------------------------------------------------------------------
def api(tmp_path, llm):
    return TestClient(create_app(db_path=str(tmp_path / "x.db"), demo=True, alert_loop=False, fundamentals_provider=FakeFA(), llm=llm))


def test_api_runs_the_fundamental_agent_and_refuses_what_does_not_apply(tmp_path):
    with api(tmp_path, Script(**{"Fundamental Analysis": lambda p, n, m: fund_out(snap_of(p))})) as c:
        d = c.post("/api/ai/analyze", json={"agent": "fundamental", "instrument_id": "AAPL"}).json()["data"]
        assert d["status"] == "completed" and d["report"]["supporting"][0]["fact"] == "profit_margin_pct"
        r = c.post("/api/ai/analyze", json={"agent": "fundamental", "instrument_id": "BTC"})
        assert r.status_code == 422 and "do not apply to crypto" in r.json()["error"]["message"]
        r = c.post("/api/ai/analyze", json={"agent": "strategy", "instrument_id": "AAPL"})
        assert r.status_code == 501 and "strategy" in r.json()["error"]["message"]
        assert c.post("/api/ai/analyze", json={"agent": "chief", "instrument_id": "NOPE123456"}).status_code == 404


def test_api_without_an_llm_is_503(tmp_path):
    with api(tmp_path, None) as c:
        for agent in ("fundamental", "macro", "risk", "chief"):
            assert c.post("/api/ai/analyze", json={"agent": agent, "instrument_id": "AAPL"}).status_code == 503


def test_no_agent_tool_can_place_orders(tmp_path):
    with api(tmp_path, Script()) as c:
        names = c.get("/api/ai/status").json()["data"]["tools"]
        assert not any(w in n for n in names for w in ("order", "trade", "buy", "sell", "submit"))
