"""ECB reference rates: parsed from a real response (fetched 2026-11-08), pair maths, staleness, failures labelled, demo invents nothing."""
import asyncio
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import ecb as E
from atlas_api.app import create_app

CSV = (Path(__file__).parent / "fixtures" / "ecb_exr.csv").read_text()
TODAY = date(2026, 11, 8)
NOW = datetime(2026, 11, 8, 12, tzinfo=timezone.utc)


def test_the_real_file_parses_into_euro_based_series_for_every_currency():
    s = E.parse(CSV)
    assert set(s) >= {"USD", "JPY", "GBP", "CHF", "CNY", "CAD", "AUD"} and s["USD"][-1] == (date(2026, 11, 6), 1.1165) and s["USD"][0][0] < s["USD"][-1][0]


def test_pairs_are_calculated_from_the_euro_rates_with_the_right_direction():
    r = E.build(E.parse(CSV), TODAY)
    p = {x["pair"]: x for x in r["pairs"]}
    assert p["EUR/USD"]["rate"] == 1.1165                                         # dollars per euro, as published
    assert p["USD/JPY"]["rate"] == pytest.approx(176.77 / 1.1165, abs=0.01)         # yen per dollar = yen per euro / dollars per euro
    assert p["GBP/USD"]["rate"] == pytest.approx(1.1165 / 0.83415, abs=0.0001)      # dollars per pound
    assert p["USD/CHF"]["rate"] == pytest.approx(0.9143 / 1.1165, abs=0.0001)
    assert r["date"] == "2026-11-06" and r["freshness"] == "CURRENT" and "Reference rates" in r["note"] and "official" in r["source"]


def test_dollar_vs_change_is_positive_when_the_dollar_buys_more_of_the_other_currency():
    s = {"USD": [(date(2026, 10, 1) + __import__("datetime").timedelta(days=i), 1.10) for i in range(40)], "JPY": [(date(2026, 10, 1) + __import__("datetime").timedelta(days=i), 160.0) for i in range(40)]}
    s["USD"][-1] = (s["USD"][-1][0], 1.10)
    s["JPY"][-1] = (s["JPY"][-1][0], 176.0)            # yen per euro up 10% with dollars per euro flat: the dollar buys 10% more yen
    p = E.build(s, s["USD"][-1][0])["pairs"]
    jpy = next(x for x in p if x["pair"] == "USD/JPY")
    assert jpy["dollar_vs_1d_pct"] == pytest.approx(10.0, abs=0.01) and jpy["dollar_vs_30d_pct"] == pytest.approx(10.0, abs=0.01)
    s2 = {"USD": [(d, 1.20 if i == 39 else 1.10) for i, (d, _) in enumerate(s["USD"])], "GBP": [(d, 0.85) for d, _ in s["USD"]]}
    gbp = next(x for x in E.build(s2, s2["USD"][-1][0])["pairs"] if x["pair"] == "GBP/USD")
    assert gbp["rate"] == pytest.approx(1.20 / 0.85, abs=0.0001) and gbp["dollar_vs_1d_pct"] < 0         # pound worth more dollars = dollar weaker against it


def test_an_old_file_is_overdue_and_a_missing_currency_is_left_out():
    assert E.build(E.parse(CSV), date(2026, 11, 30))["freshness"] == "OVERDUE"
    no_cad = "\n".join(l for l in CSV.splitlines() if ",CAD," not in l)
    pairs = [x["pair"] for x in E.build(E.parse(no_cad), TODAY)["pairs"]]
    assert "USD/CAD" not in pairs and "EUR/USD" in pairs


def test_garbage_and_missing_dollar_rate_are_refused():
    for bad in ("", "a,b\n1,2", CSV.replace(",USD,", ",XXX,")):
        with pytest.raises(ValueError):
            E.parse(bad)


def go(handler, demo=False):
    return asyncio.run(E.EcbFx(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).overview(NOW))


def test_service_returns_pairs_and_asks_for_csv():
    seen = []

    def h(req):
        seen.append((req.headers["accept"], dict(req.url.params)))
        return httpx.Response(200, text=CSV)
    r = go(h)
    assert r["available"] and len(r["pairs"]) == 7 and seen[0][0] == "text/csv" and r["breadth"]["of"] == 7


def test_failure_says_so_and_shows_no_rates():
    for h in (lambda req: httpx.Response(503), lambda req: httpx.Response(200, text="nonsense"), lambda req: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        r = go(h)
        assert r["available"] is False and "pairs" not in r and "ECB" in r["reason"]


def test_demo_mode_invents_nothing(tmp_path):
    assert go(lambda req: httpx.Response(200, text=CSV), demo=True)["available"] is False
    with TestClient(create_app(db_path=str(tmp_path / "e.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        d = c.get("/api/macro/fx").json()["data"]
        assert d["demo"] is True and d["available"] is False
