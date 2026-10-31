import json

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.journal import hyperliquid as hl

ADDR = "0x" + "ab" * 20
OTHER = "0x" + "cd" * 20
T = 1_767_225_600_000            # 2026-01-01 00:00:00 UTC in ms
H = 3_600_000


def fill(tid, coin, side, px, sz, t, d="Open Long", fee="0", pnl="0", start="0", **kw):
    return {"coin": coin, "px": str(px), "sz": str(sz), "side": side, "time": t, "startPosition": start, "dir": d, "closedPnl": pnl,
            "hash": f"0xh{tid}", "oid": tid, "crossed": True, "fee": fee, "tid": tid, "feeToken": "USDC", **kw}


ROUND_TRIP = [
    fill(1, "BTC", "B", "60000.0", "0.1", T, "Open Long", fee="0.60"),
    fill(2, "BTC", "A", "61000.0", "0.1", T + 2 * H, "Close Long", fee="0.61", pnl="100.0", start="0.1"),
]
FUNDING = [{"time": T + H, "hash": "0xf1", "delta": {"type": "funding", "coin": "BTC", "usdc": "-0.25", "szi": "0.1", "fundingRate": "0.0000125", "nSamples": None}}]


class FakeHL:
    def __init__(self, fills, funding=(), fail=False):
        self.f, self.g, self.fail, self.calls = list(fills), list(funding), fail, []

    async def fills(self, address):
        self.calls.append(("fills", address))
        if self.fail:
            raise hl.HyperliquidError("Hyperliquid API unavailable: ConnectError")
        return self.f

    async def funding(self, address):
        self.calls.append(("funding", address))
        return self.g


@pytest.fixture
def make(tmp_path):
    clients = []

    def build(fake):
        c = TestClient(create_app(db_path=str(tmp_path / "h.db"), demo=True, alert_loop=False, hyperliquid=fake))
        c.__enter__()
        clients.append(c)
        return c
    yield build
    for c in clients:
        c.__exit__(None, None, None)


def sync(c, address=ADDR):
    return c.post("/api/journal/hyperliquid/sync", json={"address": address})


# --- parsing --------------------------------------------------------------------------------------------------------------------------
def test_fill_parsing_is_hand_checked():
    r = hl.parse_fills(ROUND_TRIP, ADDR)
    a, b = r.executions
    assert (a.symbol, a.side, str(a.qty), str(a.price), str(a.fee), a.ext_id) == ("BTC-PERP", "buy", "0.1", "60000.0", "0.60", "1")
    assert b.side == "sell" and b.ts.isoformat() == "2026-01-01T02:00:00+00:00" and a.source.startswith("hyperliquid:0xabab")
    assert r.options["reported_closed_pnl"] == "100.0" and not r.skipped


def test_unusable_rows_are_counted_not_dropped_and_duplicates_collapse():
    rows = ROUND_TRIP + [dict(ROUND_TRIP[0]), {"coin": "BTC"}, fill(9, "BTC", "B", "0", "1", T), fill(10, "BTC", "X", "1", "1", T)]
    r = hl.parse_fills(rows, ADDR)
    assert len(r.executions) == 2 and sum(r.skipped.values()) == 4
    assert r.skipped["duplicate in response"] == 1


def test_rebate_fee_is_negative_and_spot_and_foreign_fee_tokens_are_handled_honestly():
    rows = [fill(1, "ETH", "B", "3000", "1", T, fee="-0.30"),
            fill(2, "PURR", "B", "0.5", "100", T, d="Buy", fee="0.1", feeToken="PURR"),
            fill(3, "HYPE", "B", "20", "1", T, d="Buy", fee="0.01", feeToken="WEIRD")]
    r = hl.parse_fills(rows, ADDR)
    eth, purr, hype = r.executions
    assert str(eth.fee) == "-0.30"
    assert purr.symbol == "PURR" and float(purr.fee) == pytest.approx(0.05)       # base-token fee converted at the fill price
    assert float(hype.fee) == 0 and any("WEIRD" in w for w in r.warnings)          # not converted, and said so


def test_liquidation_only_when_the_account_was_the_liquidated_user():
    liq = {"liquidatedUser": ADDR, "markPx": "1", "method": "market"}
    other = {"liquidatedUser": OTHER, "markPx": "1", "method": "market"}
    r = hl.parse_fills([fill(1, "BTC", "A", "1", "1", T, "Close Long", liquidation=liq), fill(2, "BTC", "A", "1", "1", T + 1, "Close Long", liquidation=other)], ADDR)
    assert [e.kind for e in r.executions] == ["liquidation", "trade"]


def test_truncated_history_is_flagged():
    r = hl.parse_fills([fill(1, "BTC", "A", "61000", "0.1", T, "Close Long", start="0.1")], ADDR)
    assert any("earlier opening fills are missing" in w for w in r.warnings)
    assert not hl.parse_fills(ROUND_TRIP, ADDR).warnings


def test_funding_sign_is_preserved_and_non_funding_rows_ignored():
    fl = hl.parse_funding(FUNDING + [{"time": T, "hash": "0x", "delta": {"type": "deposit", "usdc": "5"}}, {"junk": 1}], ADDR)
    assert len(fl) == 1 and str(fl[0].amount) == "-0.25" and fl[0].symbol == "BTC-PERP" and fl[0].kind == "funding"


# --- address handling ----------------------------------------------------------------------------------------------------------------
def test_address_validation_and_private_key_rejection():
    assert hl.valid_address(" " + ADDR.upper().replace("0X", "0x") + " ") == ADDR
    for bad in ("", "0x123", "not an address", ADDR + "00"):
        with pytest.raises(ValueError):
            hl.valid_address(bad)
    with pytest.raises(ValueError, match="PRIVATE KEY"):
        hl.valid_address("0x" + "1f" * 32)


def test_private_key_is_rejected_before_any_fetch_and_never_echoed(make):
    fake = FakeHL(ROUND_TRIP)
    c = make(fake)
    key = "0x" + "1f" * 32
    r = sync(c, key)
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_ADDRESS" and "PRIVATE KEY" in r.json()["error"]["message"]
    assert key not in r.text and key[2:] not in r.text and fake.calls == []
    assert not any(key[2:] in str(dict(row)) for row in c.app.state.db.q("SELECT * FROM audit_log"))


def test_unknown_request_fields_are_rejected(make):
    c = make(FakeHL([]))
    assert c.post("/api/journal/hyperliquid/sync", json={"address": ADDR, "private_key": "x"}).status_code == 422


# --- end to end ----------------------------------------------------------------------------------------------------------------------
def test_sync_builds_a_closed_trade_with_fees_and_funding_and_is_idempotent(make):
    c = make(FakeHL(ROUND_TRIP, FUNDING))
    d = sync(c).json()["data"]
    assert d["executions"] == {"inserted": 2, "duplicates": 0} and d["funding"]["inserted"] == 1 and d["reported"]["closed_pnl"] == "100.0"
    (t,) = c.get("/api/journal/trades", params={"source": d["source"]}).json()["data"]["trades"]
    assert t["symbol"] == "BTC-PERP" and t["status"] == "closed"
    assert float(t["gross_pnl"]) == pytest.approx(100.0)          # (61000-60000) * 0.1
    assert float(t["fees"]) == pytest.approx(1.21) and float(t["funding"]) == pytest.approx(-0.25)
    assert float(t["net_pnl"]) == pytest.approx(100 - 1.21 - 0.25)
    d2 = sync(c).json()["data"]
    assert d2["executions"] == {"inserted": 0, "duplicates": 2} and d2["funding"]["inserted"] == 0
    assert len(c.get("/api/journal/trades", params={"source": d["source"]}).json()["data"]["trades"]) == 1


def test_short_and_flip_through_zero_match_correctly(make):
    rows = [fill(1, "ETH", "A", "3000", "2", T, "Open Short"),
            fill(2, "ETH", "B", "2900", "3", T + H, "Short > Long", start="-2"),          # closes the 2 short (+200) and opens 1 long
            fill(3, "ETH", "A", "2950", "1", T + 2 * H, "Close Long", start="1")]            # closes the long (+50 loss -> 2950 vs 2900 = +50)
    c = make(FakeHL(rows))
    src = sync(c).json()["data"]["source"]
    trades = c.get("/api/journal/trades", params={"source": src}).json()["data"]["trades"]
    assert len(trades) == 2 and sorted(float(t["gross_pnl"]) for t in trades) == [pytest.approx(50.0), pytest.approx(200.0)]


def test_api_failure_imports_nothing_and_says_so(make):
    c = make(FakeHL(ROUND_TRIP, fail=True))
    r = sync(c)
    assert r.status_code == 502 and r.json()["error"]["code"] == "HYPERLIQUID_UNAVAILABLE" and "Nothing was imported" in r.json()["error"]["message"]
    assert c.get("/api/journal/sources").json()["data"]["sources"] == []


def test_two_wallets_are_separate_sources_never_netted_together(make):
    c = make(FakeHL(ROUND_TRIP))
    a = sync(c, ADDR).json()["data"]["source"]
    b = sync(c, OTHER).json()["data"]["source"]
    assert a != b and {s["source"] for s in c.get("/api/journal/sources").json()["data"]["sources"]} == {a, b}


# --- client paging --------------------------------------------------------------------------------------------------------------------
def mock_client(pages):
    calls = []

    def handler(req):
        body = json.loads(req.content)
        calls.append(body)
        return httpx.Response(200, json=pages(body))
    return hl.HyperliquidClient("https://hl.test", httpx.AsyncClient(transport=httpx.MockTransport(handler))), calls


@pytest.mark.asyncio
async def test_paging_starts_at_the_last_timestamp_so_same_millisecond_fills_are_not_lost():
    first = [fill(i, "BTC", "B", "1", "1", T + (i if i < 1999 else 1999)) for i in range(2000)]          # full page, the last two share a ms
    second = [fill(1999, "BTC", "B", "1", "1", T + 1999), fill(2000, "BTC", "B", "1", "1", T + 1999), fill(2001, "BTC", "B", "1", "1", T + 2000)]
    cl, calls = mock_client(lambda b: first if b["startTime"] == 0 else second)
    got = await cl.fills(ADDR)
    assert calls[1]["startTime"] == T + 1999                                   # not +1
    assert {e.ext_id for e in hl.parse_fills(got, ADDR).executions} >= {"2000", "2001"}          # the overlap is deduped, nothing is lost


@pytest.mark.asyncio
async def test_a_page_that_cannot_advance_does_not_loop_forever():
    stuck = [fill(i, "BTC", "B", "1", "1", T) for i in range(2000)]
    cl, calls = mock_client(lambda b: stuck)
    await cl.fills(ADDR)
    assert len(calls) <= 2


@pytest.mark.asyncio
async def test_http_and_shape_errors_become_hyperliquid_errors():
    cl = hl.HyperliquidClient("https://hl.test", httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
    with pytest.raises(hl.HyperliquidError):
        await cl.fills(ADDR)
    cl2 = hl.HyperliquidClient("https://hl.test", httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"oops": 1}))))
    with pytest.raises(hl.HyperliquidError, match="unexpected response"):
        await cl2.fills(ADDR)
