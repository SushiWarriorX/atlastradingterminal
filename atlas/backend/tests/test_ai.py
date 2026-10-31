import json

import pytest

from atlas_api import instruments as I
from atlas_api.ai.desk import Desk
from atlas_api.ai.llm import LLMResponse
from atlas_api.ai.tools import Registry, ToolError
from atlas_api.service import MarketService


class Script:
    """Scripted fake LLM; records every call so tests can inspect what the model was shown."""
    model = "fake-model"

    def __init__(self, *responses):
        self.responses, self.calls = list(responses), []

    async def create(self, system, messages, tools=None, max_tokens=2000):
        self.calls.append({"system": system, "messages": json.loads(json.dumps(messages, default=str)), "tools": tools})
        return self.responses.pop(0)


def text(t, **kw):
    return LLMResponse([{"type": "text", "text": t}], input_tokens=kw.get("i", 10), output_tokens=kw.get("o", 5))


def tool_use(name, args, id="tu1"):
    return LLMResponse([{"type": "tool_use", "id": id, "name": name, "input": args}], "tool_use", 10, 5)


@pytest.fixture
def desk_factory(db, demo_service):
    def make(llm, **kw):
        return Desk(llm, Registry(demo_service), db, **kw)
    return make


def test_no_execution_tools_exist(demo_service):
    names = set(Registry(demo_service).tools)
    assert not any(w in n for n in names for w in ("order", "trade", "buy", "sell", "execute", "broker"))


async def test_permissions_enforced(demo_service):
    reg = Registry(demo_service)
    with pytest.raises(ToolError):
        await reg.call("technical", "search_instruments", {"query": "x"})  # technical agent lacks this tool
    with pytest.raises(ToolError):
        await reg.call("desk", "place_order", {})
    assert {s["name"] for s in reg.specs("technical")} == {"get_quote", "get_technical_features", "get_multi_timeframe"}   # read-only tools only


async def test_chat_tool_loop_wraps_results_as_untrusted(desk_factory):
    llm = Script(tool_use("get_technical_features", {"symbol": "BTC", "interval": "1h"}), text("BTC is demo data [x]."))
    out = await desk_factory(llm).chat("How is BTC?", "CRYPTO:COINBASE:BTC-USD:SPOT")
    assert out["status"] == "completed" and out["tool_calls"][0]["ok"] and out["usage"]["input_tokens"] == 20
    result_msg = llm.calls[1]["messages"][-1]["content"][0]["content"]
    assert result_msg.startswith('<tool_data untrusted="true">') and '"data_status": "DEMO"' in result_msg
    assert "never state a price" in llm.calls[0]["system"].lower() or "Never state a price" in llm.calls[0]["system"]


async def test_chat_survives_tool_errors_and_bad_symbols(desk_factory):
    llm = Script(tool_use("get_quote", {"symbol": "??"}), tool_use("place_order", {}, "tu2"), text("could not fetch"))
    out = await desk_factory(llm).chat("buy BTC now")
    assert [c["ok"] for c in out["tool_calls"]] == [False, False] and out["answer"] == "could not fetch"


async def test_chat_budget_and_step_limits(desk_factory):
    big = LLMResponse([{"type": "tool_use", "id": "t", "name": "get_market_session", "input": {}}], "tool_use", 50000, 20000)
    out = await desk_factory(Script(big, big), max_tokens_budget=60000).chat("x")
    assert out["status"] == "budget_exceeded"
    loop = [tool_use("get_market_session", {}, f"t{i}") for i in range(3)]
    out = await desk_factory(Script(*loop), max_steps=3).chat("x")
    assert out["status"] == "step_limit"


def good_report(snap, **over):
    level = snap["timeframes"]["1d"]["levels"][0]["id"]
    r = {"agent": "technical", "instrument_id": snap["instrument_id"], "snapshot_id": snap["snapshot_id"],
         "analysis_timestamp": "2026-01-01T00:00:00Z", "status": "completed", "directional_assessment": "neutral",
         "time_horizon": "swing", "observations": ["demo data"],
         "supporting_evidence": [{"text": "RSI mid-range", "source_ids": [snap["source_ids"][0]]}], "contradictory_evidence": [],
         "key_levels": [{"role": "support", "level_id": level}],
         "scenarios": [{"name": "bullish", "conditions": "close above X", "invalidation": "close below Y"}],
         "invalidation_conditions": ["close below support"], "source_ids": snap["source_ids"],
         "data_limitations": ["synthetic"], "summary": "Neutral."}
    return {**r, **over}


class Capture(Script):
    """Builds its reply from the snapshot embedded in the prompt, like a real model would read it."""
    def __init__(self, mutate_first=None):
        super().__init__()
        self.mutate_first, self.n = mutate_first, 0

    async def create(self, system, messages, tools=None, max_tokens=2000):
        self.calls.append(list(messages))  # copy: the desk appends to this list afterwards
        prompt = messages[0]["content"]
        snap = json.loads(prompt.split("SNAPSHOT (data):\n")[1].split("\n\nanalysis_timestamp")[0])
        rep = good_report(snap)
        if self.n == 0 and self.mutate_first:
            rep = self.mutate_first(rep)
        self.n += 1
        return LLMResponse([{"type": "text", "text": json.dumps(rep)}], input_tokens=100, output_tokens=50)


async def test_technical_agent_valid_report_resolves_levels_server_side(desk_factory):
    out = await desk_factory(Capture()).technical("BTC")
    assert out["status"] == "completed"
    k = out["report"]["key_levels"][0]
    assert isinstance(k["price"], float) and k["derivation"]  # price comes from computed snapshot, not the model


async def test_technical_agent_rejects_invented_source_then_recovers(desk_factory):
    llm = Capture(mutate_first=lambda r: {**r, "source_ids": ["fabricated:source"]})
    out = await desk_factory(llm).technical("BTC")
    assert out["status"] == "completed" and len(llm.calls) == 2  # rejected once, corrected on retry
    assert "unknown source_ids" in llm.calls[1][-1]["content"]


async def test_technical_agent_fails_closed_on_persistent_invention(desk_factory):
    class Always(Capture):
        async def create(self, system, messages, tools=None, max_tokens=2000):
            r = await super().create(system, messages)
            rep = json.loads(r.content[0]["text"])
            rep["key_levels"] = [{"role": "support", "level_id": "made-up-99"}]
            return LLMResponse([{"type": "text", "text": json.dumps(rep)}])
    out = await desk_factory(Always()).technical("BTC")
    assert out["status"] == "failed_validation" and out["report"] is None and "level_id" in out["error"]


async def test_technical_agent_schema_failure_and_unknown_instrument(desk_factory):
    out = await desk_factory(Script(text("not json"), text("{}"))).technical("BTC")
    assert out["status"] == "failed_validation"
    with pytest.raises(ToolError):
        await desk_factory(Script()).technical("1234567890")


async def test_technical_agent_no_data_does_not_call_llm(db):
    desk = Desk(Script(), Registry(MarketService({}, demo=False)), db)
    out = await desk.technical("AAPL")
    assert out["status"] == "no_data" and out["data_limitations"] and desk.llm.calls == []


# --- multi-timeframe in the AI layer ---------------------------------------------------
from atlas_api.ai.desk import ReportRejected, TechnicalReport, validate_report


async def test_mtf_tool_is_permitted_for_both_agents_and_returns_source_id_and_levels(demo_service):
    reg = Registry(demo_service)
    assert "get_multi_timeframe" in {s["name"] for s in reg.specs("technical")} and "get_multi_timeframe" in {s["name"] for s in reg.specs("desk")}
    out = await reg.call("desk", "get_multi_timeframe", {"symbol": "AAPL"})
    assert out["source_id"] == "EQUITY:NASDAQ:AAPL:mtf" and out["score"]["benchmark"] == "SPY" and len(out["timeframes"]) == 5
    assert out["alignment"]["verdict"] and all(l["id"].startswith("mtf-") and l["price"] > 0 for l in out["levels"])
    btc = await reg.call("technical", "get_multi_timeframe", {"symbol": "BTC"})
    assert btc["score"]["benchmark"] is None and "relative_strength" in btc["score"]["unavailable"]
    with pytest.raises(ToolError):
        await reg.call("desk", "get_multi_timeframe", {"symbol": "AAPL", "benchmark": "NOPE123456"})


async def test_snapshot_contains_mtf_and_report_gets_server_side_verdict_and_level_prices(desk_factory):
    class WithMtf(Capture):
        async def create(self, system, messages, tools=None, max_tokens=2000):
            prompt = messages[0]["content"]
            snap = json.loads(prompt.split("SNAPSHOT (data):\n")[1].split("\n\nanalysis_timestamp")[0])
            assert snap["mtf"] and f"{snap['instrument_id']}:mtf" in snap["source_ids"] and "snapshot.mtf" in system
            rep = good_report(snap)
            lvl = snap["mtf"]["levels"][0]
            rep["key_levels"] = [{"role": "support", "level_id": lvl["id"]}]
            rep["source_ids"] = snap["source_ids"]
            self.expected = (lvl["price"], snap["mtf"]["alignment"]["verdict"], snap["mtf"]["score"]["score"])
            self.calls.append(list(messages))
            return LLMResponse([{"type": "text", "text": json.dumps(rep)}], input_tokens=10, output_tokens=5)

    llm = WithMtf()
    out = await desk_factory(llm).technical("AAPL")
    assert out["status"] == "completed"
    r = out["report"]
    price, verdict, score = llm.expected
    assert r["key_levels"][0]["price"] == price and r["key_levels"][0]["kind"].startswith("mtf_")     # price resolved server-side
    assert r["mtf"]["verdict"] == verdict and r["mtf"]["score"] == score and r["mtf"]["source_id"].endswith(":mtf")


def snap_with(verdict="aligned bearish", label="bearish tilt"):
    return {"snapshot_id": "s1", "instrument_id": "X", "source_ids": ["X:mtf", "X:features:1d"],
            "timeframes": {"1d": {"levels": [{"id": "1d-L1", "price": 1.0, "kind": "swing_high", "derivation": "d"}]}},
            "mtf": {"alignment": {"verdict": verdict, "text": "t"}, "score": {"score": 20.0, "label": label, "benchmark": None},
                    "levels": [{"id": "mtf-1w-support", "kind": "mtf_support", "price": 9.5, "derivation": "d"}]}}


def report(direction, **kw):
    return TechnicalReport(instrument_id="X", snapshot_id="s1", analysis_timestamp="t", directional_assessment=direction, time_horizon="swing",
                           observations=[], supporting_evidence=[], contradictory_evidence=[], key_levels=kw.get("levels", []), scenarios=[],
                           invalidation_conditions=[], source_ids=kw.get("sources", ["X:mtf"]), data_limitations=[], summary="s")


def test_validation_flags_conflict_with_computed_mtf_and_rejects_unknown_mtf_levels():
    out = validate_report(report("bullish"), snap_with())
    assert len(out["consistency_notes"]) == 2 and "aligned bearish" in out["consistency_notes"][0] and "bearish tilt" in out["consistency_notes"][1]
    assert validate_report(report("bearish"), snap_with())["consistency_notes"] == []                        # agreement: nothing to flag
    assert validate_report(report("neutral"), snap_with())["consistency_notes"] == []                         # neutral is not a conflict
    assert validate_report(report("bullish"), snap_with(verdict="conflicting", label="neutral"))["consistency_notes"] == []
    ok_level = [{"role": "support", "level_id": "mtf-1w-support"}]
    assert validate_report(report("bearish", levels=ok_level), snap_with())["key_levels"][0]["price"] == 9.5
    with pytest.raises(ReportRejected):
        validate_report(report("bearish", levels=[{"role": "support", "level_id": "mtf-1w-resistance"}]), snap_with())   # not in the snapshot
    with pytest.raises(ReportRejected):
        validate_report(report("bearish", sources=["X:mtf", "made:up"]), snap_with())
