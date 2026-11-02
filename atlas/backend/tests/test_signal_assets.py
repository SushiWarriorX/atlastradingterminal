"""Signal: stable asset ids, same-ticker safety, search (with honest unsupported results), the saved watchlist, and watchlist/chart summaries."""
import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.db import DB
from atlas_api.models import DataStatus
from atlas_api.signal import assets as A
from atlas_api.signal import summary as S
from atlas_api.signal.service import SignalError, SignalService
from atlas_api.signal.watchlist import MAX_ITEMS, WatchlistError, WatchlistStore
from signal_helpers import FakeCoinGecko, FakeFedWatch, FakeFund, FakeMacro, FakeMempool, FakeNews, ScriptProvider, bars, make_svc


@pytest.fixture(autouse=True)
def regular_session(monkeypatch):
    monkeypatch.setattr("atlas_api.service.session_state", lambda now=None: {"state": "REGULAR"})


def run(c):
    return asyncio.run(c)


# --- directory and product-list fixtures ----------------------------------------------------------------------------------------------------
FILLER_NASDAQ = "".join(f"{a}{b}{c}|Filler {a}{b}{c} Inc. - Common Stock|Q|N|N|100|N|N\n" for a in "ABCDEFGHIJKLM" for b in "ABCDEFGHIJ" for c in "ABCDEFGH")
NASDAQ = ("Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares\n"
          "AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N\nQQQ|Invesco QQQ Trust, Series 1|G|N|N|100|Y|N\nIBIT|iShares Bitcoin Trust ETF|G|N|N|100|Y|N\nZZTEST|Test Issue Co|Q|Y|N|100|N|N\n" + FILLER_NASDAQ + "File Creation Time: 1101202612:00|||||||\n")
OTHER = ("ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
         "BTC|Grayscale Bitcoin Mini Trust ETF|P|BTC|Y|100|N|BTC\nSOL|Emeren Group Ltd - Common Stock|N|SOL|N|100|N|SOL\nBRK.B|Berkshire Hathaway Inc. Class B Common Stock|N|BRK.B|N|100|N|BRK B\n"
         "IBIT|iShares Bitcoin Trust ETF|Q|IBIT|Y|100|N|IBIT\nXYZ$|Bad Symbol|N|X|N|100|N|X\nFile Creation Time: 1101202612:00|||||||\n")
PRODUCTS = [{"id": f"{s}-USD", "quote_currency": "USD", "status": "online", "trading_disabled": False} for s, *_ in A.TOKENS if s != "PEPE"] + [{"id": "PEPE-USD", "quote_currency": "USD", "status": "delisted", "trading_disabled": True}]


def client_factory(directory=True, products=True, calls=None):
    def handler(req: httpx.Request) -> httpx.Response:
        u = str(req.url)
        if calls is not None:
            calls.append(u)
        if "nasdaqlisted" in u:
            return httpx.Response(200, text=NASDAQ) if directory else httpx.Response(503)
        if "otherlisted" in u:
            return httpx.Response(200, text=OTHER) if directory else httpx.Response(503)
        if "coinbase.com/products" in u:
            return httpx.Response(200, json=PRODUCTS) if products else httpx.Response(500)
        return httpx.Response(404)
    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def registry(tmp_path, **kw):
    return A.AssetRegistry(cache_dir=str(tmp_path), client_factory=client_factory(**kw))


# --- identity ------------------------------------------------------------------------------------------------------------------------------------
def test_ids_carry_type_and_venue_and_round_trip_without_any_lookup():
    for aid, cls, prov, psym in [("CRYPTO:COINBASE:ETH-USD:SPOT", "crypto", "coinbase", "ETH-USD"), ("EQUITY:NASDAQ:AAPL", "stock", "yahoo", "AAPL"),
                                 ("ETF:ARCA:SPY", "etf", "yahoo", "SPY"), ("EQUITY:NYSE:BRK.B", "stock", "yahoo", "BRK-B")]:
        a = A.describe(aid)
        assert a.id == aid and a.type == cls and a.inst.provider == prov and a.inst.provider_symbol == psym and a.inst.id == aid
    assert A.describe("CRYPTO:COINBASE:BTC-USD:SPOT").inst is A.I.get("CRYPTO:COINBASE:BTC-USD:SPOT")          # the same instrument the terminal uses


@pytest.mark.parametrize("bad", ["", "AAPL", "btc", "EQUITY:NASDAQ:", "EQUITY:NASDAQ:AAPL;DROP", "CRYPTO:COINBASE:BTC-EUR:SPOT", "CRYPTO:KRAKEN:BTC-USD:SPOT", "EQUITY:nasdaq:AAPL", "ETF:ARCA:A" + "B" * 20, "INDEX:SPGI:SPX", "MACRO:FRED:DGS10"])
def test_malformed_and_unsupported_ids_do_not_resolve(bad):
    assert A.describe(bad) is None


def test_a_crypto_token_and_an_etf_with_the_same_ticker_are_different_assets(tmp_path):
    reg = registry(tmp_path)
    out = run(reg.search("btc"))
    by_id = {r["id"]: r for r in out["results"]}
    assert "CRYPTO:COINBASE:BTC-USD:SPOT" in by_id and "ETF:ARCA:BTC" in by_id
    assert by_id["CRYPTO:COINBASE:BTC-USD:SPOT"]["type"] == "crypto" and by_id["ETF:ARCA:BTC"]["type"] == "etf" and by_id["ETF:ARCA:BTC"]["name"].startswith("Grayscale")
    assert [r["id"] for r in out["results"]][:2] == ["CRYPTO:COINBASE:BTC-USD:SPOT", "ETF:ARCA:BTC"]                 # exact ticker matches first, crypto before ETF
    crypto, etf = A.describe("CRYPTO:COINBASE:BTC-USD:SPOT"), A.describe("ETF:ARCA:BTC")
    assert crypto.inst.provider == "coinbase" and etf.inst.provider == "yahoo" and crypto.inst.provider_symbol != etf.inst.provider_symbol          # priced from different providers
    assert reg.same_symbol(crypto) == [reg._by_id["ETF:ARCA:BTC"]] and [x.id for x in reg.same_symbol(reg._by_id["EQUITY:NYSE:SOL"])] == ["CRYPTO:COINBASE:SOL-USD:SPOT"]


def test_search_ranks_exact_ticker_then_name_and_shows_type_and_venue(tmp_path):
    reg = registry(tmp_path)
    r = run(reg.search("sol"))["results"]
    assert [x["id"] for x in r[:2]] == ["CRYPTO:COINBASE:SOL-USD:SPOT", "EQUITY:NYSE:SOL"] and r[1]["venue"] == "NYSE" and r[0]["venue"] == "Coinbase spot (USD)"
    apple = run(reg.search("apple"))["results"]
    assert apple[0]["id"] == "EQUITY:NASDAQ:AAPL" and apple[0]["name"] == "Apple Inc." and apple[0]["type"] == "stock"
    assert run(reg.search("bitcoin"))["results"][0]["id"] == "CRYPTO:COINBASE:BTC-USD:SPOT"
    ib = [x for x in run(reg.search("bitcoin"))["results"] if x["id"] == "ETF:ARCA:BTC" or x["id"] == "ETF:NASDAQ:IBIT"]
    assert {x["id"] for x in ib} == {"ETF:ARCA:BTC", "ETF:NASDAQ:IBIT"}


def test_directory_parsing_drops_test_issues_odd_symbols_and_cleans_names():
    rows = A.parse_directory(NASDAQ, OTHER)
    d = {(e, s): (n, etf) for s, n, e, etf in rows}
    assert d[("NASDAQ", "AAPL")] == ("Apple Inc.", False) and d[("NASDAQ", "QQQ")][1] is True and d[("ARCA", "BTC")][1] is True and d[("NYSE", "BRK.B")][0].startswith("Berkshire")
    assert not any(s == "ZZTEST" or "$" in s for _, s in d) and ("NYSE", "SOL") in d


def test_no_match_is_reported_as_unsupported_not_silently_empty(tmp_path):
    reg = registry(tmp_path)
    out = run(reg.search("qwertyuiop"))
    assert out["results"] == [] and "No supported asset" in out["unsupported"]["message"] and "Coinbase" in out["unsupported"]["message"]
    nope = run(reg.search("ZZQ"))                                                        # ticker-shaped, and the directory IS loaded: it is not listed, so no guess is offered
    assert nope["results"] == [] and nope["unsupported"]


def test_when_the_directory_cannot_be_loaded_search_still_works_and_says_so(tmp_path):
    reg = registry(tmp_path, directory=False)
    out = run(reg.search("aapl"))
    assert out["results"][0]["id"] == "EQUITY:NASDAQ:AAPL" and out["notes"] and "directory unavailable" in out["notes"][0]
    guess = run(reg.search("ZZQ"))                                                       # unknown ticker + no directory: one clearly labelled UNVERIFIED candidate
    assert [r["id"] for r in guess["results"]] == ["EQUITY:US:ZZQ"] and guess["results"][0]["support"] == "unverified" and "could not be loaded" in " ".join(guess["notes"])
    assert reg.directory_loaded is False and reg.directory_error


def test_failed_directory_is_not_retried_on_every_keystroke(tmp_path):
    calls: list[str] = []
    reg = registry(tmp_path, directory=False, calls=calls)
    for q in ("a", "ap", "app", "appl"):
        run(reg.search(q))
    assert sum("nasdaqlisted" in c for c in calls) == 1


def test_coinbase_product_list_hides_tokens_it_does_not_trade(tmp_path):
    reg = registry(tmp_path)
    assert run(reg.search("pepe"))["results"] == [] or all(r["id"] != "CRYPTO:COINBASE:PEPE-USD:SPOT" for r in run(reg.search("pepe"))["results"])
    assert any(r["id"] == "CRYPTO:COINBASE:ETH-USD:SPOT" for r in run(reg.search("eth"))["results"])
    reg2 = registry(tmp_path, products=False)                                            # product list unreachable: nothing is hidden on a guess
    assert any(r["id"] == "CRYPTO:COINBASE:PEPE-USD:SPOT" for r in run(reg2.search("pepe"))["results"])


def test_directory_is_cached_on_disk_between_runs(tmp_path):
    run(registry(tmp_path).search("aapl"))
    calls: list[str] = []
    reg2 = registry(tmp_path, calls=calls)
    assert run(reg2.search("brk"))["results"][0]["id"] == "EQUITY:NYSE:BRK.B" and not any("nasdaqlisted" in c for c in calls)


def test_demo_registry_makes_no_network_calls_and_offers_only_the_built_in_list(tmp_path):
    calls: list[str] = []
    reg = A.AssetRegistry(demo=True, cache_dir=str(tmp_path), client_factory=client_factory(calls=calls))
    out = run(reg.search("aapl"))
    assert out["results"][0]["id"] == "EQUITY:NASDAQ:AAPL" and calls == [] and run(reg.search("ZZQ"))["results"] == []


# --- watchlist store --------------------------------------------------------------------------------------------------------------------------------
def test_watchlist_store_keeps_order_is_idempotent_and_renumbers(tmp_path):
    st = WatchlistStore(DB(str(tmp_path / "w.db")))
    a, b, c = (A.describe(i) for i in ("EQUITY:NASDAQ:AAPL", "CRYPTO:COINBASE:ETH-USD:SPOT", "ETF:ARCA:SPY"))
    assert st.add(a) and st.add(b) and st.add(c) and st.add(a) is False
    assert st.ids() == [a.id, b.id, c.id]
    st.reorder([c.id, a.id, b.id])
    assert st.ids() == [c.id, a.id, b.id]
    assert st.remove(a.id) and not st.remove(a.id)
    assert [r["position"] for r in st.list()] == [0, 1] and st.ids() == [c.id, b.id]
    assert st.list()[1]["symbol"] == "ETH" and st.list()[1]["asset_type"] == "crypto" and st.list()[1]["venue"] == "Coinbase spot (USD)"


def test_reorder_must_be_a_permutation_of_the_saved_assets(tmp_path):
    st = WatchlistStore(DB(str(tmp_path / "w.db")))
    for i in ("EQUITY:NASDAQ:AAPL", "ETF:ARCA:SPY"):
        st.add(A.describe(i))
    for bad in (["EQUITY:NASDAQ:AAPL"], ["EQUITY:NASDAQ:AAPL", "EQUITY:NASDAQ:AAPL"], ["EQUITY:NASDAQ:AAPL", "ETF:ARCA:SPY", "ETF:ARCA:QQQ"], ["ETF:ARCA:SPY", "EQUITY:NASDAQ:MSFT"]):
        with pytest.raises(WatchlistError) as e:
            st.reorder(bad)
        assert e.value.code == "ORDER_MISMATCH"
    assert st.ids() == ["EQUITY:NASDAQ:AAPL", "ETF:ARCA:SPY"]                       # a rejected change leaves the list untouched


def test_watchlist_size_limit(tmp_path):
    st = WatchlistStore(DB(str(tmp_path / "w.db")))
    for i in range(MAX_ITEMS):
        st.add(A._stock("EQUITY", "NASDAQ", f"T{i}"[:5].replace("T", "TT") if False else f"A{chr(65 + i // 26)}{chr(65 + i % 26)}", None, "supported"))
    with pytest.raises(WatchlistError) as e:
        st.add(A.describe("EQUITY:NASDAQ:AAPL"))
    assert e.value.code == "WATCHLIST_FULL" and len(st.ids()) == MAX_ITEMS


# --- the service: add / list / persistence -----------------------------------------------------------------------------------------------------
def make_service(tmp_path, provider=None, name="s.db", demo=False, reg=None):
    svc, p = make_svc(provider)
    db = DB(str(tmp_path / name))
    sig = SignalService(db=db, svc=svc, news=FakeNews(), fundamentals=FakeFund(), macro=FakeMacro(), fedwatch=FakeFedWatch(), demo=demo, registry=reg or A.AssetRegistry(demo=True),
                        coingecko=FakeCoinGecko(), mempool=FakeMempool())
    return sig, p


def test_watchlist_rows_carry_price_provenance_sparkline_and_a_takeaway(tmp_path):
    sig, _ = make_service(tmp_path)
    run(sig.add("EQUITY:NASDAQ:AAPL"))
    row = run(sig.watchlist())["items"][0]
    q = row["quote"]
    assert row["asset"]["id"] == "EQUITY:NASDAQ:AAPL" and row["error"] is None and q["display"].startswith("$") and q["prov"]["provider"] == "yahoo" and q["prov"]["status"] == "DELAYED"
    assert q["prov"]["event_time"] and q["prov"]["delay_seconds"] == 900 and len(row["spark"]) == 30
    assert row["takeaway"]["timeframe"] == "1D" and "Uptrend" in row["takeaway"]["text"] and row["takeaway"]["source"].startswith("Technical")


def test_one_failing_asset_does_not_break_the_list_and_order_is_kept(tmp_path):
    sig, p = make_service(tmp_path)
    for i in ("EQUITY:NASDAQ:AAPL", "CRYPTO:COINBASE:ETH-USD:SPOT", "ETF:ARCA:SPY"):
        run(sig.add(i))
    real_quote = p.quote

    async def flaky(inst):
        if inst.symbol == "ETH-USD":
            raise S.ProviderUnavailable("coinbase", "exchange unreachable")
        return await real_quote(inst)
    p.quote = flaky
    rows = run(sig.watchlist())["items"]
    assert [r["asset"]["symbol"] for r in rows] == ["AAPL", "ETH", "SPY"]
    eth = rows[1]
    assert eth["quote"] is None and eth["error"]["code"] == "DATA_UNAVAILABLE" and "exchange unreachable" in eth["error"]["message"] and eth["spark"]            # bars still drawn, price missing
    assert rows[0]["quote"] and rows[2]["quote"]


def test_stale_and_historical_labels_from_the_market_service_are_passed_through(tmp_path):
    sig, _ = make_service(tmp_path, ScriptProvider(age=3 * 86400))
    run(sig.add("EQUITY:NASDAQ:AAPL"))
    row = run(sig.watchlist())["items"][0]
    assert row["quote"]["prov"]["status"] == "STALE"                           # three-day-old data is labelled STALE by the market service and shown as such
    ch = run(sig.chart("EQUITY:NASDAQ:AAPL", "1M"))
    assert ch["prov"]["status"] == "STALE" and ch["prov"]["provider"] == "yahoo"


def test_unknown_ids_are_rejected_and_saved_names_survive_a_missing_directory(tmp_path):
    sig, _ = make_service(tmp_path)
    with pytest.raises(SignalError) as e:
        run(sig.add("NOT-AN-ID"))
    assert e.value.code == "UNKNOWN_ASSET" and e.value.status == 404
    run(sig.add("EQUITY:NASDAQ:AAPL"))
    sig.store.db.x("UPDATE signal_watchlist SET name='Apple (saved name)' WHERE asset_id='EQUITY:NASDAQ:AAPL'")
    assert run(sig.watchlist())["items"][0]["asset"]["name"] == "Apple (saved name)"


def test_an_unverified_ticker_is_added_only_if_it_has_a_price(tmp_path):
    sig, p = make_service(tmp_path)
    assert run(sig.add("EQUITY:US:ZZQ"))["added"] is True
    p.fail_quote = True
    with pytest.raises(SignalError) as e:
        run(sig.add("EQUITY:US:YYQ"))
    assert e.value.code == "NO_DATA" and "YYQ" not in sig.store.ids()
    demo, _ = make_service(tmp_path, name="d.db", demo=True)
    with pytest.raises(SignalError) as e2:
        run(demo.add("EQUITY:US:ZZQ"))
    assert e2.value.code == "UNSUPPORTED_IN_DEMO"


def test_watchlist_survives_a_restart_and_keeps_its_order(tmp_path):
    path = str(tmp_path / "persist.db")
    with TestClient(create_app(db_path=path, demo=True, alert_loop=False)) as c:
        for i in ("CRYPTO:COINBASE:ETH-USD:SPOT", "EQUITY:NASDAQ:AAPL", "ETF:ARCA:SPY"):
            assert c.post("/api/signal/watchlist", json={"id": i}).status_code == 200
        assert c.put("/api/signal/watchlist/positions", json={"ids": ["ETF:ARCA:SPY", "CRYPTO:COINBASE:ETH-USD:SPOT", "EQUITY:NASDAQ:AAPL"]}).status_code == 200
        assert c.delete("/api/signal/watchlist/EQUITY:NASDAQ:AAPL").json()["data"]["removed"] is True
    with TestClient(create_app(db_path=path, demo=True, alert_loop=False)) as c2:          # a brand-new app on the same database file
        rows = c2.get("/api/signal/watchlist").json()["data"]["items"]
        assert [r["asset"]["id"] for r in rows] == ["ETF:ARCA:SPY", "CRYPTO:COINBASE:ETH-USD:SPOT"]


# --- chart ----------------------------------------------------------------------------------------------------------------------------------------
def test_chart_ranges_and_change(tmp_path):
    sig, _ = make_service(tmp_path)
    for rng, n_max in (("1W", 240), ("1M", 33), ("3M", 100), ("1Y", 240), ("5Y", 240)):
        ch = run(sig.chart("EQUITY:NASDAQ:AAPL", rng))
        pts = ch["points"]
        assert 2 <= len(pts) <= n_max and pts == sorted(pts, key=lambda x: x[0]) and ch["range"] == rng
        assert ch["first"] == pts[0][1] and ch["last"] == pts[-1][1] and ch["change"] == pytest.approx(ch["last"] - ch["first"]) and ch["prov"]["provider"] == "yahoo"
    with pytest.raises(S.SummaryError) as e:
        run(sig.chart("EQUITY:NASDAQ:AAPL", "10Y"))
    assert e.value.code == "INVALID_RANGE"


def test_one_day_chart_is_the_latest_session_for_stocks_and_24_hours_for_crypto(tmp_path):
    sig, _ = make_service(tmp_path)
    eq = run(sig.chart("EQUITY:NASDAQ:AAPL", "1D"))["points"]
    ny = lambda t: datetime.fromtimestamp(t, timezone.utc).astimezone(S.NY).date()
    assert len({ny(t) for t, _ in eq}) == 1
    cr = run(sig.chart("CRYPTO:COINBASE:ETH-USD:SPOT", "1D"))["points"]
    assert cr[-1][0] - cr[0][0] <= 86400 and len(cr) > 100


def test_chart_for_a_provider_failure_is_a_clean_error(tmp_path):
    sig, _ = make_service(tmp_path, ScriptProvider(fail_intervals={"1d"}))
    with pytest.raises(S.ProviderUnavailable):
        run(sig.chart("EQUITY:NASDAQ:AAPL", "1M"))


def test_thinning_keeps_first_and_last_and_order():
    pts = [[i, float(i)] for i in range(1000)]
    t = S.thin(pts, 100)
    assert len(t) == 100 and t[0] == pts[0] and t[-1] == pts[-1] and [x[0] for x in t] == sorted(x[0] for x in t)


def test_quick_take_wording():
    up = bars("1d", 120, drift=0.004)
    assert S.quick_take(up)["text"].startswith("Uptrend") and "in 1M" in S.quick_take(up)["text"]
    assert S.quick_take(bars("1d", 120, drift=-0.004))["text"].startswith("Downtrend")
    assert "short history" in S.quick_take(bars("1d", 30))["text"] and S.quick_take(bars("1d", 10)) is None
