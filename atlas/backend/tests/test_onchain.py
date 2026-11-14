"""mempool.space network health: parsed from real responses (fetched 2026-11-08), arithmetic, each section fails on its own, demo invents nothing."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import onchain as O
from atlas_api.app import create_app

FX = Path(__file__).parent / "fixtures"
FEES, DIFF, MEMPOOL, HASH = (json.loads((FX / f).read_text()) for f in ("mp_fees.json", "mp_diff.json", "mp_mempool.json", "mp_hash.json"))
TIP = (FX / "mp_tip.txt").read_text().strip()
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_fees_are_read_with_a_typical_transaction_cost_by_arithmetic():
    f = O.parse_fees(FEES, MEMPOOL)
    assert f["sat_per_vbyte"]["fastest"] == FEES["fastestFee"] and f["typical_tx_sats_fastest"] == FEES["fastestFee"] * 140 and f["typical_tx_vbytes"] == 140
    assert f["mempool"]["transactions"] == MEMPOOL["count"] and f["mempool"]["megavbytes"] == round(MEMPOOL["vsize"] / 1e6, 1) and f["mempool"]["total_fees_btc"] == round(MEMPOOL["total_fee"] / 1e8, 4)
    assert "mempool" not in O.parse_fees(FEES, None)


def test_difficulty_cycle_fields_come_from_the_source():
    d = O.parse_difficulty(DIFF, int(TIP))
    assert d["remaining_blocks"] == DIFF["remainingBlocks"] and d["next_adjustment_height"] == DIFF["nextRetargetHeight"] and d["block_height"] == int(TIP)
    assert d["estimated_change_pct"] == round(DIFF["difficultyChange"], 2) and d["estimated_date"] > "2026-11-08" and "estimate" in d["note"]
    assert d["next_adjustment_height"] - d["block_height"] == d["remaining_blocks"]            # the two sources agree


def test_hashrate_headline_is_a_seven_day_average_in_exahashes():
    h = O.parse_hashrate(HASH)
    last7 = [r["avgHashrate"] for r in sorted(HASH["hashrates"], key=lambda r: r["timestamp"])[-7:]]
    assert h["seven_day_average_eh"] == round(sum(last7) / 7 / 1e18, 1) and 100 < h["seven_day_average_eh"] < 5000
    assert h["current_eh"] == round(HASH["currentHashrate"] / 1e18, 1) and len(h["history"]) == 90 and h["changes"]
    assert h["highest_day"]["eh"] >= h["latest_day_eh"] and h["highest_day"]["eh"] >= h["seven_day_average_eh"]
    assert [c["label"] for c in h["changes"]] == ["30 days", "90 days"] or [c["label"] for c in h["changes"]] == ["30 days"]


def test_too_little_hashrate_history_is_refused():
    with pytest.raises(ValueError):
        O.parse_hashrate({"hashrates": HASH["hashrates"][:5]})


def routes(req):
    path = req.url.path.replace("/api/", "")
    return {"v1/fees/recommended": httpx.Response(200, json=FEES), "mempool": httpx.Response(200, json=MEMPOOL), "v1/difficulty-adjustment": httpx.Response(200, json=DIFF),
            "blocks/tip/height": httpx.Response(200, text=TIP), "v1/mining/hashrate/3m": httpx.Response(200, json=HASH)}.get(path, httpx.Response(404))


def go(handler, demo=False):
    return asyncio.run(O.OnChain(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_all_three_sections_with_a_source():
    r = go(routes)
    assert all(r[k]["available"] for k in ("fees", "difficulty", "hashrate")) and "mempool.space" in r["source"]


def test_one_failing_section_does_not_hide_the_others():
    def h(req):
        return httpx.Response(503) if "hashrate" in req.url.path else routes(req)
    r = go(h)
    assert r["fees"]["available"] and r["difficulty"]["available"] and r["hashrate"]["available"] is False and "hashrate" in r["hashrate"]["reason"] and "history" not in r["hashrate"]


def test_a_missing_mempool_or_height_only_drops_the_extra():
    def h(req):
        return httpx.Response(500) if req.url.path.endswith(("/mempool", "/height")) else routes(req)
    r = go(h)
    assert r["fees"]["available"] and "mempool" not in r["fees"] and r["difficulty"]["available"] and r["difficulty"]["block_height"] is None


def test_everything_failing_says_so_three_times_and_shows_no_numbers():
    r = go(lambda req: (_ for _ in ()).throw(httpx.ConnectError("down")))
    assert not any(r[k]["available"] for k in ("fees", "difficulty", "hashrate"))


def test_demo_mode_invents_nothing(tmp_path):
    r = go(routes, demo=True)
    assert not any(r[k]["available"] for k in ("fees", "difficulty", "hashrate"))
    with TestClient(create_app(db_path=str(tmp_path / "o.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        assert c.get("/api/btc/network").json()["data"]["demo"] is True
