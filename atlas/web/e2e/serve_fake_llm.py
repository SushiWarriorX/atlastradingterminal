"""Starts the DEMO backend with a SCRIPTED LLM so the desk UI can be tested end to end without an API key. Test double only.
Usage (from atlas/backend): ATLAS_DEMO=1 ATLAS_DB=<throwaway.db> python ../web/e2e/serve_fake_llm.py 8000
The script never writes a number of its own: it cites fact keys it finds in the snapshot, exactly as a real model must."""
import json
import sys

import uvicorn

from atlas_api.ai.llm import LLMResponse
from atlas_api.app import create_app


def between(s, a, b):
    i = s.index(a) + len(a)
    return s[i: s.index(b, i)] if b else s[i:]


class Scripted:
    model = "scripted-e2e"

    async def create(self, system, messages, tools=None, max_tokens=2000):
        p = messages[0]["content"]
        if "Technical Analysis agent" in system:
            snap = json.loads(between(p, "SNAPSHOT (data):\n", "\n\nanalysis_timestamp"))
            ts = between(p, "analysis_timestamp must be ", None).rstrip(".")
            src = snap["source_ids"][0]
            out = {"agent": "technical", "instrument_id": snap["instrument_id"], "snapshot_id": snap["snapshot_id"], "analysis_timestamp": ts, "status": "completed",
                   "directional_assessment": "bullish", "time_horizon": "swing", "observations": ["Price holds above its moving averages."],
                   "supporting_evidence": [{"text": "Trend is up on the daily chart.", "source_ids": [src]}], "contradictory_evidence": [], "key_levels": [],
                   "scenarios": [{"name": "bullish", "conditions": "holds support", "invalidation": "closes below the 50-day"}, {"name": "bearish", "conditions": "loses support", "invalidation": "reclaims the 20-day"}],
                   "invalidation_conditions": ["close below the 50-day average"], "source_ids": [src], "data_limitations": [], "summary": "Uptrend intact on the computed features."}
        elif "Fundamental Analysis agent" in system or "Macro agent" in system or "Portfolio Risk agent" in system:
            snap = json.loads(between(p, "SNAPSHOT (data):\n", "\n\nPillars allowed"))
            keys = list(snap["facts"])
            fact = "pe" if "pe" in snap["facts"] else "us10y" if "us10y" in snap["facts"] else keys[0]
            fund, macro = "Fundamental Analysis agent" in system, "Macro agent" in system
            agent = "fundamental" if fund else "macro" if macro else "risk"
            pillar = "valuation" if fund else "rates" if macro else "concentration"
            out = {"agent": agent, "snapshot_id": snap["snapshot_id"], "assessment": "adverse" if fund else "mixed" if macro else "moderate_concern",
                   "pillars": [{"name": pillar, "rating": "weak" if fund else "adequate", "evidence": [{"fact": fact, "comment": "the headline figure for this pillar"}]}],
                   "supporting": [{"fact": keys[-1], "comment": "supporting context"}], "contradictory": [], "data_limitations": [], "summary": f"Scripted {agent} view built from the computed facts."}
        else:
            conflicts = json.loads(between(p, "CONFLICTS (computed by the server):\n", None))
            cites = [n for n in ("technical", "fundamental", "macro") if f'"{n}": {{"status": "completed"' in p]
            out = {"stance": "cautious", "agreements": ["Specialists agree the data is thin in places."], "conflicts_addressed": [f"Weighing: {c['text']}; the computed evidence is kept side by side." for c in conflicts],
                   "what_would_change_my_mind": ["A change in the computed trend or in reported earnings."], "data_limitations": [], "cites": cites, "summary": "Mixed picture: the trend and the fundamentals disagree."}
        return LLMResponse([{"type": "text", "text": json.dumps(out)}], "end_turn", 120, 60)


uvicorn.run(create_app(llm=Scripted()), host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
