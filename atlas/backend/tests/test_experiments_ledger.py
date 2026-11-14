"""The experiments ledger shown in Signal: complete, honest, served without the network."""
import json
from pathlib import Path

from fastapi.testclient import TestClient

from atlas_api.app import create_app

LEDGER = json.loads((Path(__file__).parent.parent / "atlas_api" / "btclab" / "experiments_ledger.json").read_text())["entries"]


def test_every_entry_is_complete_and_states_what_was_not_verified():
    assert [e["id"] for e in LEDGER] == ["exp1_vol_target", "exp2_momentum", "exp3_gated_momentum", "exp4_funding_carry", "exp5_net_liquidity"]
    for e in LEDGER:
        for k in ("name", "date", "registered", "idea", "period", "verdict", "results", "conditions", "reading", "not_verified"):
            assert e.get(k), (e["id"], k)
        assert e["verdict"] in ("failed", "passed") and all(isinstance(c["met"], bool) for c in e["conditions"])
        assert all(r["k"] and r["v"] for r in e["results"])


def test_verdict_matches_the_conditions():
    for e in LEDGER:
        assert (e["verdict"] == "passed") == all(c["met"] for c in e["conditions"]), e["id"]


def test_route_serves_the_ledger_with_the_counts_and_no_profit_claim(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/btclab/experiments")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["tested"] == 5 and d["passed"] == 0 and len(d["entries"]) == 5
        assert "None has passed yet" in d["note"] and "profitable" in d["note"]
