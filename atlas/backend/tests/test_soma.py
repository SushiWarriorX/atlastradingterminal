"""Fed SOMA holdings: parsed from a real response (330 weeks to 2026-11-04, fetched 2026-11-08); every figure is plain arithmetic on the source's own numbers."""
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import soma as S
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "nyfed_soma.json").read_text())
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def raw_total(d: str) -> float:
    return float(next(r["total"] for r in RAW["soma"]["summary"] if r["asOfDate"] == d))


def test_weeks_are_read_oldest_first_and_empty_parts_count_as_zero():
    rows = S.parse(RAW)
    assert len(rows) == 330 and rows[0]["date"] < rows[-1]["date"] and rows[-1]["date"] == date(2026, 11, 4)
    assert rows[-1]["total"] == raw_total("2026-11-04")
    raw = json.loads(json.dumps(RAW))
    raw["soma"]["summary"][-1]["frn"] = ""                                                           # the source writes "" when the Fed holds none of a kind
    assert S.parse(raw)[-1]["frn"] == 0.0 and S.parse(raw)[-1]["total"] == rows[-1]["total"]


def test_the_parts_add_up_to_the_sources_own_total_every_week():
    for r in S.parse(RAW):
        assert abs(sum(r[k] for k in S.PARTS) - r["total"]) < 1e6                                    # so inflation compensation is correctly left out


def test_summary_changes_and_peak_are_plain_arithmetic():
    rows = S.parse(RAW)
    s = S.summarize(rows, TODAY)
    now = raw_total("2026-11-04")
    assert s["date"] == "2026-11-04" and s["freshness"] == "CURRENT" and s["total_billions"] == round(now / 1e9, 1)
    ch = {c["period"]: c for c in s["changes"]}
    assert ch["1 week"]["since"] == "2026-10-28" and ch["1 week"]["change_billions"] == round((now - raw_total("2026-10-28")) / 1e9, 1)
    assert ch["4 weeks"]["since"] == "2026-10-07" and ch["52 weeks"]["since"] == "2025-11-05"
    assert ch["52 weeks"]["change_pct"] == round((now / raw_total("2025-11-05") - 1) * 100, 2)
    peak = max(float(r["total"]) for r in RAW["soma"]["summary"])
    assert s["peak_billions"] == round(peak / 1e9, 1) and s["peak_date"] == "2022-04-13" and s["from_peak_billions"] == round((now - peak) / 1e9, 1) and s["from_peak_pct"] < 0
    assert abs(sum(m["share_pct"] for m in s["mix"]) - 100) < 0.6 and len(s["history"]) == 104 and "not a market signal or a forecast" in s["note"]


def test_a_comparison_with_no_nearby_week_gives_none_not_a_guess():
    rows = S.parse(RAW)
    gappy = [r for r in rows if not (date(2025, 10, 25) <= r["date"] <= date(2025, 11, 12))]      # the weeks around a year ago are missing
    ch = {c["period"]: c for c in S.summarize(gappy, TODAY)["changes"]}
    assert ch["52 weeks"]["change_billions"] is None and ch["52 weeks"]["since"] is None and ch["4 weeks"]["change_billions"] is not None


def test_old_data_is_overdue():
    assert S.summarize(S.parse(RAW), date(2026, 12, 31))["freshness"] == "OVERDUE"


def test_too_little_or_garbled_data_is_refused():
    for bad in ({}, {"soma": {"summary": RAW["soma"]["summary"][:10]}}, {"soma": {"summary": [{"asOfDate": "x", "total": "?"}] * 100}}):
        with pytest.raises(ValueError):
            S.parse(bad)


def go(handler, demo=False):
    return asyncio.run(S.Soma(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_the_summary_with_source():
    r = go(lambda req: httpx.Response(200, json=RAW))
    assert r["available"] and "official" in r["source"] and r["total_billions"] > 6000 and "newyorkfed.org" in r["url"]


def test_failure_says_so_and_shows_no_numbers():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, json={}), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "total_billions" not in r and "New York Fed" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, json=RAW), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "s.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/fedholdings").json()["data"]
        assert d["demo"] is True and d["available"] is False
