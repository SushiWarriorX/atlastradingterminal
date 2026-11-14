"""CFTC CME Bitcoin positioning: parsed from a real response (60 weeks, fetched 2026-11-08), arithmetic, rank, staleness, failures labelled, demo invents nothing."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import cftc as C
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "cftc_btc_tff.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_the_real_report_parses_oldest_first_with_nets_from_long_minus_short():
    weeks = C.parse(RAW)
    assert len(weeks) == 60 and weeks[0]["date"] < weeks[-1]["date"] and weeks[-1]["date"] == date(2026, 11, 3)
    lev = weeks[-1]["lev_money"]
    assert lev == {"long": 5114, "short": 7705, "net": 5114 - 7705} and weeks[-1]["open_interest"] == 17527


def test_summary_shares_changes_and_rank_follow_the_data():
    s = C.summarize(C.parse(RAW), TODAY)
    lev = next(g for g in s["groups"] if g["key"] == "lev_money")
    assert s["date"] == "2026-11-03" and s["freshness"] == "CURRENT" and s["open_interest"] == 17527 and s["open_interest_change"] == -3264
    assert lev["long_pct_oi"] == 29.2 and lev["short_pct_oi"] == 44.0 and lev["net"] == -2591
    weeks = C.parse(RAW)
    assert lev["net_change"] == lev["net"] - weeks[-2]["lev_money"]["net"] and 0 <= lev["net_rank_1y"] <= 100 and len(lev["net_history"]) == 26
    assert [g["key"] for g in s["groups"]] == ["lev_money", "asset_mgr", "dealer", "other_rept"] and "Net short is not the same as bearish" in s["note"]


def test_rank_is_none_without_enough_history_and_exact_otherwise():
    assert C.rank([1, 2, 3], 2) is None
    assert C.rank(list(range(1, 21)), 10) == 50 and C.rank(list(range(1, 21)), 20) == 100


def test_an_old_report_is_overdue_not_current():
    assert C.summarize(C.parse(RAW), date(2026, 12, 20))["freshness"] == "OVERDUE"


def test_unreadable_rows_are_dropped_and_no_rows_raises():
    rows = [{"report_date_as_yyyy_mm_dd": "bad", "open_interest_all": "5"}, {"open_interest_all": "5"}, {"report_date_as_yyyy_mm_dd": "2026-11-03T00:00:00.000", "open_interest_all": "0"}]
    with pytest.raises(ValueError):
        C.parse(rows)
    ok = C.parse([RAW[0], {**RAW[1], "lev_money_positions_long": "x"}])
    assert ok[-1]["lev_money"] is not None and ok[0]["lev_money"] is None          # a garbled group is left out, not guessed


def go(handler, demo=False):
    return asyncio.run(C.CftcBitcoin(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_asks_for_the_cme_bitcoin_contract_and_returns_the_report():
    seen = []

    def handler(req):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=RAW)
    r = go(handler)
    assert r["available"] and "official" in r["source"] and "133741" in seen[0]["$where"] and seen[0]["$order"].endswith("DESC")


def test_failure_says_so_and_shows_no_positions():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json=[]), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "groups" not in r and "CFTC" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, json=RAW), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "c.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/btc/positioning").json()["data"]
        assert d["demo"] is True and d["available"] is False
