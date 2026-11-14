"""World Bank annual series: parsed from real responses (fetched 2026-11-08), change arithmetic, each indicator fails alone, demo invents nothing."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import worldbank as W
from atlas_api.app import create_app

FX = Path(__file__).parent / "fixtures"
RAW = {code: json.loads((FX / f"wb_{code}.json").read_text()) for code, *_ in W.INDICATORS}
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_the_real_response_parses_per_country_oldest_first_without_empty_years():
    s = W.parse(RAW["NY.GDP.MKTP.KD.ZG"], "growth")
    assert set(s) >= {"USA", "CHN", "EMU", "JPN", "GBR", "IND"} and s["USA"][0][0] < s["USA"][-1][0] and all(v is not None for _, v in s["USA"])
    assert s["USA"][-1] == (2025, pytest.approx(2.16, abs=0.01)) or s["USA"][-1][0] == 2025


def test_table_has_the_latest_year_the_previous_year_and_the_change_by_subtraction():
    rows = {r["iso"]: r for r in W.table(W.parse(RAW["NY.GDP.MKTP.KD.ZG"], "growth"), 2026)}
    usa = rows["USA"]
    assert usa["year"] == 2025 and usa["previous_year"] == 2024 and usa["change"] == pytest.approx(usa["value"] - usa["previous_value"], abs=0.011) and usa["years_old"] == 1
    assert [r["country"] for r in W.table(W.parse(RAW["NY.GDP.MKTP.KD.ZG"], "growth"), 2026)][:2] == ["United States", "Euro area"] and len(usa["history"]) <= 6


def test_each_country_keeps_its_own_newest_year():
    rows = {r["iso"]: r for r in W.table(W.parse(RAW["FP.CPI.TOTL.ZG"], "inflation"), 2026)}
    assert rows["USA"]["year"] <= 2025 and rows["CHN"]["year"] == 2025 and all(r["years_old"] >= 0 for r in rows.values() if r["available"])


def test_a_country_with_no_data_is_marked_unavailable_not_guessed():
    s = W.parse(RAW["SL.UEM.TOTL.ZS"], "unemployment")
    s.pop("JPN")
    rows = {r["iso"]: r for r in W.table(s, 2026)}
    assert rows["JPN"] == {"country": "Japan", "iso": "JPN", "available": False}


def test_garbage_is_refused():
    for bad in ([], [{"page": 1}, None], [{"page": 1}, [{"value": None, "date": "2025", "countryiso3code": "USA"}]], "nope"):
        with pytest.raises(ValueError):
            W.parse(bad, "x")


def handler_for(code_map):
    def h(req):
        code = req.url.path.rsplit("/", 1)[-1]
        return code_map(code)
    return h


def go(handler, demo=False):
    return asyncio.run(W.WorldBank(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_three_indicators_with_source_and_the_annual_caveat():
    r = go(handler_for(lambda c: httpx.Response(200, json=RAW[c])))
    assert r["available"] and [i["key"] for i in r["indicators"]] == ["gdp_growth", "inflation", "unemployment"] and "official" in r["source"] and "revised later" in r["note"]


def test_one_failing_indicator_leaves_the_others():
    r = go(handler_for(lambda c: httpx.Response(503) if c == "FP.CPI.TOTL.ZG" else httpx.Response(200, json=RAW[c])))
    inf = next(i for i in r["indicators"] if i["key"] == "inflation")
    assert r["available"] and inf["available"] is False and "World Bank inflation" in inf["reason"] and inf["rows"] == []
    assert next(i for i in r["indicators"] if i["key"] == "gdp_growth")["available"]


def test_everything_failing_says_so():
    r = go(lambda req: (_ for _ in ()).throw(httpx.ConnectError("x")))
    assert r["available"] is False and "could not be read" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(handler_for(lambda c: httpx.Response(200, json=RAW[c])), demo=True)["indicators"] == []
    with TestClient(create_app(db_path=str(tmp_path / "w.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/world").json()["data"]
        assert d["demo"] is True and d["available"] is False
