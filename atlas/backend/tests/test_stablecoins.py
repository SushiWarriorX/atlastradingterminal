"""Stablecoin supply (DefiLlama): parsed from real responses (fetched 2026-11-08), changes by arithmetic, non-USD coins excluded, staleness, failures labelled, demo invents nothing."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import stablecoins as S
from atlas_api.app import create_app

FX = Path(__file__).parent / "fixtures"
CHART = json.loads((FX / "stablecoin_chart.json").read_text())
LIST = json.loads((FX / "stablecoin_list.json").read_text())
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)
TODAY = date(2026, 11, 8)


def test_total_supply_and_changes_come_from_the_series():
    pts = S.parse_chart(CHART)
    f = S.chart_fact(pts, TODAY)
    assert f["date"] == "2026-11-08" and f["total_billions"] == 293.7 and f["freshness"] == "CURRENT" and len(f["history"]) == 90
    thirty = next(c for c in f["changes"] if c["label"] == "30 days")
    ref = dict(pts)[date.fromisoformat(thirty["ref_date"])]
    assert thirty["change_pct"] == pytest.approx((293661087870.85 / ref - 1) * 100, abs=0.01) and (date(2026, 11, 8) - date.fromisoformat(thirty["ref_date"])).days in range(30, 36)
    assert f["peak"]["total_billions"] >= f["total_billions"] and f["peak"]["below_peak_pct"] <= 0


def test_an_old_series_is_overdue_and_missing_comparisons_are_left_out():
    pts = S.parse_chart(CHART)
    assert S.chart_fact(pts, date(2026, 11, 30))["freshness"] == "OVERDUE"
    short = pts[-60:]
    labels = [c["label"] for c in S.chart_fact(short, TODAY)["changes"]]
    assert "7 days" in labels and "1 year" not in labels and "90 days" not in labels          # no comparison is invented without the data


def test_too_little_or_garbled_history_is_refused():
    with pytest.raises(ValueError):
        S.parse_chart(CHART[-10:])
    bad = [{"date": "x", "totalCirculating": {}}] * 50
    with pytest.raises(ValueError):
        S.parse_chart(bad)


def test_top_coins_are_usd_pegged_sorted_with_shares_and_changes():
    total = 293.66e9
    top = S.parse_top(LIST, total)
    assert len(top) == S.TOP and top[0]["symbol"] == "USDT" and top[0]["share_pct"] == pytest.approx(top[0]["billions"] * 1e9 / total * 100, abs=0.1)
    assert [t["billions"] for t in top] == sorted((t["billions"] for t in top), reverse=True) and top[0]["change_30d_pct"] is not None
    assert all(t["symbol"] != "" for t in top) and sum(t["share_pct"] for t in top) < 100.5


def test_non_usd_stablecoins_are_not_counted_in_the_usd_list():
    only_other = {"peggedAssets": [a for a in LIST["peggedAssets"] if a["pegType"] != "peggedUSD"]}
    assert only_other["peggedAssets"]
    with pytest.raises(ValueError):
        S.parse_top(only_other, 1e9)


def go(handler, demo=False):
    return asyncio.run(S.Stablecoins(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def ok_handler(req):
    return httpx.Response(200, json=CHART if "stablecoincharts" in req.url.path else LIST)


def test_service_returns_supply_top_coins_source_and_caveat():
    r = go(ok_handler)
    assert r["available"] and r["total_billions"] == 293.7 and r["top"][0]["symbol"] == "USDT" and "DefiLlama" in r["source"] and "not a price signal" in r["note"] and "not an official statistic" in r["source"]


def test_failure_of_either_request_says_so_and_shows_no_numbers():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json=[]), lambda req: httpx.Response(200, json=CHART) if "stablecoincharts" in req.url.path else httpx.Response(500),
              lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "total_billions" not in r and "DefiLlama" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(ok_handler, demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "s.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/btc/stablecoins").json()["data"]
        assert d["demo"] is True and d["available"] is False
