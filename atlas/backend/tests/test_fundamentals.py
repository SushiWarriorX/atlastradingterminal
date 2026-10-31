import math
from datetime import date, datetime, timezone

import pytest

from atlas_api.fundamentals.normalize import normalize, num, text

NOW = datetime(2026, 10, 30, tzinfo=timezone.utc)
EPOCH = lambda d: int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())      # noqa: E731

INFO = {"longName": "Acme Corp", "sector": "Technology", "industry": "Software", "quoteType": "EQUITY", "currency": "USD", "currentPrice": 200.0,
        "trailingEps": 6.0, "forwardEps": 8.0, "marketCap": 3.0e12, "enterpriseValue": 3.1e12, "totalRevenue": 4.0e11, "ebitda": 1.3e11, "bookValue": 4.0,
        "sharesOutstanding": 1.5e10, "totalCash": 6.0e10, "totalDebt": 1.0e11, "dividendRate": 1.0, "dividendYield": 0.5, "payoutRatio": 0.16,
        "revenueGrowth": 0.06, "earningsGrowth": 0.11, "grossMargins": 0.45, "operatingMargins": 0.30, "profitMargins": 0.25, "returnOnEquity": 1.5, "returnOnAssets": 0.22,
        "currentRatio": 0.9, "fiftyTwoWeekHigh": 220.0, "fiftyTwoWeekLow": 160.0, "mostRecentQuarter": EPOCH(date(2026, 9, 27))}


def v(r, k):
    return r["values"][k]


def test_ratios_are_computed_in_code_and_hand_checked():
    r = normalize(INFO, now=NOW)
    assert v(r, "pe") == pytest.approx(200 / 6) and v(r, "pe_forward") == pytest.approx(25.0)
    assert v(r, "ps") == pytest.approx(3.0e12 / 4.0e11) and v(r, "pb") == pytest.approx(50.0)
    assert v(r, "ev_ebitda") == pytest.approx(3.1e12 / 1.3e11)
    assert v(r, "net_debt") == pytest.approx(4.0e10) and v(r, "debt_to_equity") == pytest.approx(1.0e11 / (4.0 * 1.5e10))
    assert v(r, "range_pos_pct") == pytest.approx((200 - 160) / (220 - 160) * 100)
    assert v(r, "profit_margin_pct") == pytest.approx(25.0) and v(r, "roe_pct") == pytest.approx(150.0)         # fractions become percents


def test_dividend_yield_is_computed_not_taken_from_the_providers_ambiguous_field():
    r = normalize({**INFO, "dividendYield": 0.5}, now=NOW)            # 0.5 could mean 0.5% or 50%: the provider changed units between versions
    assert v(r, "dividend_yield_pct") == pytest.approx(0.5)             # 1.0 / 200 * 100, independent of that field
    r2 = normalize({**INFO, "dividendYield": 0.005}, now=NOW)
    assert v(r2, "dividend_yield_pct") == pytest.approx(0.5)
    zero = normalize({**INFO, "dividendRate": 0.0}, now=NOW)
    assert v(zero, "dividend_yield_pct") == 0.0                          # a non-payer really has a 0% yield
    assert v(normalize({**INFO, "dividendRate": None}, now=NOW), "dividend_yield_pct") is None


def test_non_positive_denominators_are_not_meaningful_with_a_reason_never_a_number():
    r = normalize({**INFO, "trailingEps": -2.0, "bookValue": -5.0, "ebitda": 0, "totalRevenue": 0}, now=NOW)
    for k in ("pe", "pb", "ev_ebitda", "ps", "debt_to_equity"):
        assert v(r, k) is None and "not meaningful" in r["not_meaningful"][k], k
    assert any("negative trailing earnings" in f for f in r["flags"])


def test_missing_and_hostile_values_never_raise_and_are_listed():
    r = normalize({"trailingEps": "N/A", "marketCap": float("nan"), "totalRevenue": "Infinity", "bookValue": True, "longName": "A\x00cme\x1b" + "x" * 300, "sector": 5}, price=None, now=NOW)
    assert all(x is None for k, x in r["values"].items())
    assert r["name"] == "Acme" + "x" * 76 and r["sector"] is None                      # control characters removed, capped at 80
    assert "pe" in r["missing"] and any("no price" in f for f in r["flags"])
    empty = normalize({}, now=NOW)
    assert empty["name"] is None and empty["groups"] and len(empty["missing"]) > 10


def test_num_and_text_helpers():
    assert num("3.5") == 3.5 and num(None) is None and num(True) is None and num(math.inf) is None and num("x") is None
    assert text("  hi\n") == "hi" and text(3) is None and text("") is None


def test_percent_fields_use_reported_fractions_exactly_once():
    r = normalize({**INFO, "grossMargins": 0.0, "operatingMargins": -0.1}, now=NOW)
    assert v(r, "gross_margin_pct") == 0.0 and v(r, "operating_margin_pct") == pytest.approx(-10.0)


def test_stale_financials_are_flagged_with_their_age():
    old = {**INFO, "mostRecentQuarter": EPOCH(date(2026, 3, 31))}
    r = normalize(old, now=NOW)
    assert r["financials_age_days"] == 213 and any("out of date" in f for f in r["flags"])
    fresh = normalize(INFO, now=NOW)
    assert fresh["financials_age_days"] == 33 and not any("out of date" in f for f in fresh["flags"])
    assert normalize({**INFO, "mostRecentQuarter": -5}, now=NOW)["financials_as_of"] is None


def test_next_earnings_is_the_first_future_date_only():
    cal = {"Earnings Date": [date(2026, 10, 20), date(2026, 11, 5), date(2026, 11, 3)]}
    assert normalize(INFO, calendar=cal, now=NOW)["next_earnings_date"] == "2026-11-03"
    assert normalize(INFO, calendar={"Earnings Date": [date(2026, 1, 1)]}, now=NOW)["next_earnings_date"] is None
    assert normalize(INFO, calendar={"Earnings Date": ["soon"]}, now=NOW)["next_earnings_date"] is None
    assert normalize(INFO, calendar={}, now=NOW)["next_earnings_date"] is None


def test_funds_get_one_clear_reason_not_a_wall_of_missing():
    r = normalize({"quoteType": "ETF", "currentPrice": 500.0, "fiftyTwoWeekHigh": 520.0, "fiftyTwoWeekLow": 400.0, "longName": "Index Fund"}, now=NOW)
    assert "not applicable to a ETF" in r["not_meaningful"]["pe"] and v(r, "range_pos_pct") == pytest.approx(100 / 120 * 100)
    assert "pe" not in r["missing"]


def test_every_row_carries_its_basis():
    r = normalize(INFO, now=NOW)
    rows = [row for g in r["groups"] for row in g["rows"]]
    assert len(rows) == len(r["values"]) and all(row["basis"] for row in rows)


# --- service / API / tool -------------------------------------------------------------------------------------------------------------
import asyncio  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402

from atlas_api import instruments as I  # noqa: E402
from atlas_api.ai.tools import Registry  # noqa: E402
from atlas_api.app import create_app  # noqa: E402
from atlas_api.fundamentals.service import FundamentalsService  # noqa: E402
from atlas_api.models import ProviderUnavailable  # noqa: E402


class FakeFA:
    name = "yahoo"

    def __init__(self, info=INFO, fail=False):
        self.info, self.fail, self.calls = info, fail, 0

    async def fetch(self, inst):
        self.calls += 1
        if self.fail:
            raise ProviderUnavailable("yahoo", "ConnectError: boom")
        return self.info, 200.0, {"Earnings Date": [date(2099, 1, 1)]}


AAPL, BTC = I.by_symbol("AAPL"), I.by_symbol("BTC")


def test_service_caches_labels_provenance_and_refuses_unsupported_classes(db):
    fa = FakeFA()
    s = FundamentalsService(db, fa)
    a = asyncio.run(s.get(AAPL))
    assert a["prov"]["status"] == "DELAYED" and a["prov"]["origin"] == "live" and a["values"]["pe"] == pytest.approx(200 / 6) and a["next_earnings_date"] == "2099-01-01"
    assert asyncio.run(s.get(AAPL))["prov"]["origin"] == "cache" and fa.calls == 1                 # second read inside the TTL is served from the cache
    assert asyncio.run(s.get(AAPL, force=True))["prov"]["origin"] == "live" and fa.calls == 2
    with pytest.raises(ProviderUnavailable, match="not available for crypto"):
        asyncio.run(s.get(BTC))


def test_failed_refresh_serves_the_last_snapshot_as_stale_and_no_snapshot_is_unavailable(db):
    s = FundamentalsService(db, FakeFA())
    asyncio.run(s.get(AAPL))
    s.provider = FakeFA(fail=True)
    stale = asyncio.run(s.get(AAPL, force=True))
    assert stale["prov"]["status"] == "STALE" and any("refresh failed" in q for q in stale["prov"]["quality"]) and stale["values"]["pe"] is not None
    fresh = FundamentalsService(db, FakeFA(fail=True))
    with pytest.raises(ProviderUnavailable):
        asyncio.run(fresh.get(I.by_symbol("MSFT")))


def test_concurrent_requests_share_one_fetch(db):
    fa = FakeFA()
    s = FundamentalsService(db, fa)

    async def go():
        return await asyncio.gather(*(s.get(AAPL) for _ in range(5)))
    asyncio.run(go())
    assert fa.calls == 1


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "f.db"), demo=False, providers={}, alert_loop=False, fundamentals_provider=FakeFA())) as c:
        yield c


def test_api_returns_groups_with_provenance_and_clean_errors(client):
    d = client.get("/api/fundamentals/AAPL").json()["data"]
    assert d["symbol"] == "AAPL" and d["prov"]["provider"] == "yahoo" and [g["name"] for g in d["groups"]][0] == "Valuation"
    assert client.get("/api/fundamentals/EQUITY:NASDAQ:AAPL").status_code == 200
    r = client.get("/api/fundamentals/BTC")
    assert r.status_code == 503 and "not available for crypto" in r.json()["error"]["message"]
    assert client.get("/api/fundamentals/NOPE123456").status_code == 404


def test_demo_mode_is_labelled_demo_and_is_deterministic(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=True, alert_loop=False)) as c:
        a, b = (c.get("/api/fundamentals/NVDA", params={"refresh": True}).json()["data"] for _ in range(2))
        assert a["prov"]["status"] == "DEMO" and "synthetic" in a["name"] and a["values"]["pe"] == b["values"]["pe"]


def test_ai_tool_returns_computed_values_and_is_desk_only(db, demo_service):
    reg = Registry(demo_service, None, FundamentalsService(db, FakeFA()))
    out = asyncio.run(reg.call("desk", "get_fundamentals", {"symbol": "AAPL"}))
    assert out["source_id"].endswith(":fundamentals") and out["values"]["pe"] == pytest.approx(200 / 6) and "missing" in out and out["data_status"] == "DELAYED"
    assert "get_fundamentals" not in [s["name"] for s in reg.specs("technical")]
    none = asyncio.run(Registry(demo_service, None, None).call("desk", "get_fundamentals", {"symbol": "AAPL"}))
    assert none["error"] == "DATA_UNAVAILABLE"
    unavailable = asyncio.run(Registry(demo_service, None, FundamentalsService(db, FakeFA(fail=True))).call("desk", "get_fundamentals", {"symbol": "MSFT"}))      # not cached
    assert unavailable["error"] == "DATA_UNAVAILABLE"
