import asyncio
import json
import time
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api.app import create_app
from atlas_api.news import parse as P, tagging
from atlas_api.news.service import NewsService, cluster, url_ok

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def rss(items, extra=""):
    body = "".join(f"<item><title>{t}</title><link>{l}</link><guid>{g}</guid><pubDate>{d}</pubDate><description>{s}</description></item>" for t, l, g, d, s in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{extra}{body}</channel></rss>'.encode()


def _ago(hours: float) -> str:
    """An RSS date a little while ago. Sample stories must be recent: the news store drops anything older than its retention window, so fixed dates silently rot (they did on 2026-11-13)."""
    from email.utils import format_datetime
    return format_datetime(datetime.now(timezone.utc) - timedelta(hours=hours), usegmt=True)

ITEM = ("Fed holds rates steady", "https://ex.com/a", "g1", _ago(24), "The central bank <b>held</b> rates.")
ATOM = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Atom headline</title><link href="https://ex.com/atom"/>
<id>tag:ex,1</id><updated>2026-10-30T10:00:00Z</updated><summary>sum</summary></entry></feed>"""


# --- parsing ------------------------------------------------------------------------------------------------------------------------
def test_rss_fields_and_time_are_parsed():
    fixed = (ITEM[0], ITEM[1], ITEM[2], "Thu, 30 Oct 2026 11:00:00 GMT", ITEM[4])           # the parser is pure and gets a fixed NOW, so a fixed date is right here
    (it,), dropped = P.parse(rss([fixed]), NOW)
    assert it.title == "Fed holds rates steady" and it.link == "https://ex.com/a" and it.uid == "g1" and dropped == 0
    assert it.published == datetime(2026, 10, 30, 11, 0, tzinfo=timezone.utc) and it.summary == "The central bank held rates."


def test_atom_is_parsed():
    (it,), _ = P.parse(ATOM, NOW)
    assert it.title == "Atom headline" and it.link == "https://ex.com/atom" and it.uid == "tag:ex,1" and it.published.hour == 10


def test_doctype_and_entity_documents_are_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;&a;">]><rss version="2.0"><channel><item><title>&b;</title></item></channel></rss>'
    with pytest.raises(P.FeedError, match="DOCTYPE"):
        P.parse(bomb)
    with pytest.raises(P.FeedError, match="DOCTYPE"):
        P.parse(b'<?xml version="1.0"?>' + b" " * 10_000 + b"<!DOCTYPE x><rss/>")           # not just at the top of the document


def test_non_feeds_and_broken_xml_raise_clean_errors():
    with pytest.raises(P.FeedError, match="not an RSS"):
        P.parse(b"<html><body>hi</body></html>")
    with pytest.raises(P.FeedError, match="not valid XML"):
        P.parse(b"<rss><channel>")


def test_text_is_plain_and_links_are_safe():
    rows = [("<![CDATA[<script>alert(1)</script>Safe &amp;amp; sound]]>", "javascript:alert(1)", "a", "", "<![CDATA[<img src=x onerror=alert(1)> body &lt;b&gt;bold&lt;/b&gt;]]>"),
            ("Data link", "data:text/html;base64,AAAA", "b", "", ""), ("Fine", "https://ok.example/x", "c", "", "")]
    items, _ = P.parse(rss(rows), NOW)
    assert items[0].title == "alert(1) Safe & sound" and items[0].link is None            # tags gone, entities decoded once, text inert
    assert items[0].summary == "body bold" and "<" not in items[0].summary
    assert items[1].link is None and items[2].link == "https://ok.example/x"


def test_titleless_entries_are_counted_and_length_is_capped_and_future_dates_are_unknown():
    items, dropped = P.parse(rss([("", "https://e/1", "1", "", ""), ("T" * 500, "https://e/2", "2", "Thu, 30 Oct 2030 11:00:00 GMT", "S" * 900)]), NOW)
    assert dropped == 1 and len(items[0].title) <= 240 and len(items[0].summary) <= 320 and items[0].published is None
    assert P.parse_time("garbage", NOW) is None and P.parse_time("", NOW) is None
    assert P.parse_time("2026-10-30T10:00:00+02:00", NOW).hour == 8                       # offsets are converted to UTC


def test_uid_falls_back_to_link_then_hash():
    items, _ = P.parse(b'<rss version="2.0"><channel><item><title>A</title><link>https://e/x</link></item><item><title>B</title></item></channel></rss>', NOW)
    assert items[0].uid == "https://e/x" and len(items[1].uid) == 40


# --- tagging --------------------------------------------------------------------------------------------------------------------------
def test_tagging_is_conservative():
    assert tagging.tag("Why $TSLA fell today") == ["TSLA"]
    assert tagging.tag("Tesla (NASDAQ: TSLA) recalls cars") == ["TSLA"]
    assert tagging.tag("Berkshire (NYSE: BRK.B) earnings") == ["BRK.B"]
    assert tagging.tag("Bitcoin tops $70,000") == ["BTC"]
    for ordinary in ("ALL eyes on the Fed", "NOW is the time", "CAT and mouse", "A new era for IT firms", "Price rises $5 per share", "Mentions bitcoin only in text"):
        assert tagging.tag(ordinary) == [] or ordinary.startswith("Mentions") and tagging.tag(ordinary) == [], ordinary
    assert tagging.tag("Markets quiet", "summary mentions Bitcoin and $AAPL") == ["AAPL"]       # BTC only from the headline


# --- clustering -----------------------------------------------------------------------------------------------------------------------
def it(title, feed, ts, syms=()):
    return {"title": title, "feed": feed, "link": f"https://e/{feed}", "published": None, "symbols": list(syms), "_ts": ts}


def test_cluster_groups_the_same_story_and_keeps_distinct_ones():
    base = NOW.timestamp()
    items = [it("Fed holds interest rates steady on Wednesday", "CNBC", base), it("Fed holds interest rates steady Wednesday", "BBC", base - 600, ["X"]),
             it("Apple unveils new iPhone lineup", "BBC", base - 900), it("Fed holds interest rates steady on Wednesday, Powell says", "MW", base - 7200)]
    out = cluster(items)
    assert len(out) == 2
    fed = next(g for g in out if "Fed" in g["title"])
    assert fed["feed"] == "MW" and {a["feed"] for a in fed["also"]} == {"CNBC", "BBC"} and fed["symbols"] == ["X"]       # earliest is the representative


def test_cluster_does_not_merge_across_days():
    base = NOW.timestamp()
    out = cluster([it("Fed holds interest rates steady today", "A", base), it("Fed holds interest rates steady today", "B", base - 5 * 86400)])
    assert len(out) == 2


# --- url hygiene ------------------------------------------------------------------------------------------------------------------------
def test_url_ok():
    assert url_ok("https://feeds.example.com/rss.xml") is None
    for bad in ("ftp://x.com/a", "file:///etc/passwd", "javascript:alert(1)", "http://localhost/rss", "http://127.0.0.1:8000/x", "http://10.0.0.5/x",
                "http://192.168.1.1/x", "http://169.254.169.254/latest", "http://[::1]/x", "https://user:pw@x.com/rss", "http://printer.local/x", "https://" + "a" * 600):
        assert url_ok(bad) is not None, bad
    assert url_ok("http://127.0.0.1:9/x", allow_local=True) is None


# --- service ---------------------------------------------------------------------------------------------------------------------------
class Net:
    """httpx.MockTransport routing by URL -> (status, body, headers)."""

    def __init__(self, routes):
        self.routes, self.seen = routes, []

    def __call__(self, req: httpx.Request):
        self.seen.append((str(req.url), dict(req.headers)))
        r = self.routes.get(str(req.url))
        if r is None:
            raise httpx.ConnectError("boom: https://secret.example/?key=SECRET123")
        if callable(r):
            r = r(req)
        status, body, hdr = r
        return httpx.Response(status, content=body, headers=hdr)


def svc(db, routes, **kw):
    net = Net(routes)
    s = NewsService(db, httpx.AsyncClient(transport=httpx.MockTransport(net), follow_redirects=True), **kw)
    for f in s.feeds():
        s.delete_feed(f["id"])
    return s, net


A, B = "https://a.example/rss", "https://b.example/rss"


def run(c):
    return asyncio.run(c)


def test_refresh_stores_dedupes_and_is_idempotent(db):
    s, _ = svc(db, {A: (200, rss([ITEM, ("Second", "https://ex.com/b", "g2", _ago(25), "")]), {})})
    s.add_feed("A", A)
    r1 = run(s.refresh())
    assert r1[0]["ok"] and r1[0]["new"] == 2
    assert run(s.refresh())[0]["new"] == 0
    assert len(db.q("SELECT * FROM news_items")) == 2


def test_one_failing_feed_does_not_affect_others_and_error_never_leaks_the_url(db):
    s, _ = svc(db, {A: (200, rss([ITEM]), {}), B: (500, b"", {})})
    s.add_feed("A", A)
    s.add_feed("B", B)
    s.add_feed("Dead", "https://dead.example/rss?apikey=SECRET123")
    res = {r["name"]: r for r in run(s.refresh())}
    assert res["A"]["ok"] and res["A"]["new"] == 1
    assert not res["B"]["ok"] and res["B"]["error"] == "HTTP 500"
    assert not res["Dead"]["ok"] and "SECRET123" not in json.dumps(res) and "SECRET123" not in json.dumps(s.feeds())     # neither errors nor the listing show the key
    assert next(f for f in s.feeds() if f["name"] == "Dead")["url"] == "https://dead.example/rss?…"
    feeds = {f["name"]: f for f in s.feeds()}
    assert feeds["A"]["last_ok"] and feeds["A"]["last_error"] is None and feeds["B"]["last_error"] == "HTTP 500"


def test_conditional_get_is_sent_and_304_is_ok(db):
    calls = []

    def route(req):
        calls.append(dict(req.headers))
        return (304, b"", {}) if req.headers.get("if-none-match") == '"v1"' else (200, rss([ITEM]), {"ETag": '"v1"', "Last-Modified": "Thu, 30 Oct 2026 11:00:00 GMT"})
    s, _ = svc(db, {A: route})
    s.add_feed("A", A)
    run(s.refresh())
    r = run(s.refresh())[0]
    assert r["ok"] and r["new"] == 0 and calls[1]["if-none-match"] == '"v1"' and "if-modified-since" in calls[1]
    assert "ATLAS-Terminal" in calls[0]["user-agent"]


def test_oversize_and_hostile_bodies_are_rejected_and_recorded(db):
    s, _ = svc(db, {A: (200, b"x" * 2_100_000, {}), B: (200, b'<!DOCTYPE r [<!ENTITY a "b">]><rss version="2.0"><channel/></rss>', {})})
    s.add_feed("A", A)
    s.add_feed("B", B)
    res = {r["name"]: r["error"] for r in run(s.refresh())}
    assert "larger than" in res["A"] and "DOCTYPE" in res["B"]
    assert db.q("SELECT COUNT(*) FROM news_items")[0][0] == 0


def test_redirect_to_a_private_address_is_refused(db):
    s, _ = svc(db, {A: (302, b"", {"location": "http://169.254.169.254/latest/meta-data"}), "http://169.254.169.254/latest/meta-data": (200, rss([ITEM]), {})})
    s.add_feed("A", A)
    r = run(s.refresh())[0]
    assert not r["ok"] and "refused" in r["error"] and db.q("SELECT COUNT(*) FROM news_items")[0][0] == 0


def test_items_filter_by_symbol_and_query_with_provenance_and_clustering(db):
    now = datetime.now(timezone.utc)
    fmt = lambda m: (now - timedelta(minutes=m)).strftime("%a, %d %b %Y %H:%M:%S GMT")      # noqa: E731
    s, _ = svc(db, {A: (200, rss([("Why $TSLA fell sharply today", "https://e/1", "1", fmt(30), ""), ("Fed holds rates steady Wednesday", "https://e/2", "2", fmt(60), ""),
                                  ("Old story from long ago", "https://e/3", "3", fmt(60 * 24 * 10), "")]), {}),
                    B: (200, rss([("Fed holds rates steady on Wednesday", "https://f/2", "9", fmt(45), "")]), {})})
    s.add_feed("A", A)
    s.add_feed("B", B)
    run(s.refresh())
    all_ = s.items()
    assert all_["raw_items"] == 3 and all_["total_stories"] == 2                      # the old one is outside 72h; the two Fed items merge
    fed = next(i for i in all_["items"] if "Fed" in i["title"])
    assert fed["status"] == "DELAYED" and fed["feed"] == "A" and len(fed["also"]) == 1 and fed["also"][0]["feed"] == "B"
    assert [i["title"] for i in s.items(symbol="TSLA")["items"]] == ["Why $TSLA fell sharply today"]
    assert s.items(q="fed")["total_stories"] == 1 and s.items(q="%")["total_stories"] == 0           # LIKE wildcards are escaped
    assert s.items(hours=24 * 14)["raw_items"] == 4
    with pytest.raises(Exception):
        s.items(symbol="x'; DROP TABLE")


def test_prune_removes_old_items(db):
    s, _ = svc(db, {A: (200, rss([("Ancient", "https://e/1", "1", "Thu, 01 Jan 2026 11:00:00 GMT", ""), ITEM]), {})})
    s.add_feed("A", A)
    run(s.refresh())
    assert [r["title"] for r in db.q("SELECT title FROM news_items")] == ["Fed holds rates steady"]


def test_symbol_feed_tags_forced_symbol_and_is_cached(db):
    url = "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US"
    s, net = svc(db, {url: (200, rss([("Quarterly results beat estimates", "https://y/1", "y1", _ago(24), "")]), {})})
    s._seed()
    r = run(s.refresh_symbol("AAPL", "AAPL"))
    assert r["ok"] and r["new"] == 1 and run(s.refresh_symbol("AAPL", "AAPL")) is None        # second call inside the TTL does not hit the network
    assert len(net.seen) == 1
    assert json.loads(db.q("SELECT symbols FROM news_items")[0][0]) == ["AAPL"]
    assert run(s.refresh_symbol("AAPL; rm -rf", "X")) is None                                  # malformed symbol never reaches a URL


def test_a_story_carried_by_two_symbol_feeds_is_tagged_for_both_symbols(db):
    def feed(sym):
        return f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={sym}&region=US&lang=en-US"
    body = rss([("Chipmakers rally as demand grows", "https://y/shared", "shared-1", _ago(24), "")])
    s, _ = svc(db, {feed("AAPL"): (200, body, {}), feed("MSFT"): (200, body, {})})
    s._seed()
    run(s.refresh_symbol("AAPL", "AAPL"))
    r = run(s.refresh_symbol("MSFT", "MSFT"))
    assert r["ok"] and r["new"] == 0                                                           # the same story, stored once
    assert len(db.q("SELECT id FROM news_items")) == 1
    for sym in ("AAPL", "MSFT"):
        assert [i["title"] for i in s.items(sym, hours=24 * 3650)["items"]] == ["Chipmakers rally as demand grows"], sym
    run(s.refresh_symbol("MSFT", "MSFT", force=True))                                          # tagging again changes nothing
    assert json.loads(db.q("SELECT symbols FROM news_items")[0][0]) == ["AAPL", "MSFT"]


def test_feed_management_rules(db):
    s, _ = svc(db, {})
    f = s.add_feed("A", A)
    for bad in ("http://localhost/x", "file:///etc/passwd"):
        with pytest.raises(Exception):
            s.add_feed("bad", bad)
    with pytest.raises(Exception):
        s.add_feed("dup", A)
    s.set_enabled(f["id"], False)
    assert run(s.refresh()) == []
    s.delete_feed(f["id"])
    assert s.feeds() == []


# --- API --------------------------------------------------------------------------------------------------------------------------------
@pytest.fixture
def client(tmp_path):
    recent = (datetime.now(timezone.utc) - timedelta(minutes=20)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    net = Net({A: (200, rss([("Bitcoin rallies as traders eye the Fed", "https://e/btc", "b1", recent, "")]), {}),
               "https://feeds.finance.yahoo.com/rss/2.0/headline?s=AAPL&region=US&lang=en-US": (200, rss([("Apple supplier raises forecast", "https://y/a", "a1", recent, "")]), {})})
    with TestClient(create_app(db_path=str(tmp_path / "n.db"), demo=True, alert_loop=False, news_client=httpx.AsyncClient(transport=httpx.MockTransport(net)))) as c:
        for f in c.get("/api/news/feeds").json()["data"]["feeds"]:
            c.delete(f"/api/news/feeds/{f['id']}")
        c.news_net = net
        yield c


def test_api_demo_mode_has_no_fabricated_headlines_and_says_nothing_was_fetched(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=True, alert_loop=False)) as c:
        d = c.get("/api/news", params={"fetch": "false"}).json()["data"]
        assert d["items"] == [] and d["meta"]["never_fetched"] == 7 and d["meta"]["as_of"] is None
        assert len(c.get("/api/news/feeds").json()["data"]["feeds"]) == 7


def test_api_add_refresh_list_symbol_and_delete(client):
    f = client.post("/api/news/feeds", json={"name": "A", "url": A}).json()["data"]
    assert client.post("/api/news/refresh", json={}).json()["data"]["results"][0]["new"] == 1
    d = client.get("/api/news").json()["data"]
    assert d["items"][0]["title"].startswith("Bitcoin") and d["items"][0]["symbols"] == ["BTC"] and d["meta"]["feeds_ok"] == 1 and d["meta"]["as_of"]
    assert client.get("/api/news", params={"symbol": "BTC"}).json()["data"]["total_stories"] == 1
    aapl = client.get("/api/news", params={"symbol": "AAPL"}).json()["data"]                      # on-demand per-symbol fetch
    assert aapl["items"][0]["title"].startswith("Apple") and aapl["items"][0]["symbols"] == ["AAPL"] and aapl["meta"]["symbol_fetch"]["new"] == 1
    assert client.patch(f"/api/news/feeds/{f['id']}", json={"enabled": False}).json()["data"]["enabled"] is False
    assert client.get("/api/news").json()["data"]["total_stories"] == 1                          # only the AAPL (symbol-feed) item remains visible
    assert client.delete(f"/api/news/feeds/{f['id']}").json()["ok"]
    assert client.delete(f"/api/news/feeds/{f['id']}").status_code == 404


def test_api_rejects_bad_input(client):
    for body in ({"name": "x", "url": "http://localhost/rss"}, {"name": "x", "url": "ftp://a.example/x"}, {"name": "x", "url": A, "extra": 1}):
        assert client.post("/api/news/feeds", json=body).status_code == 422
    assert client.get("/api/news", params={"symbol": "a;b"}).status_code in (404, 422) or client.get("/api/news", params={"symbol": "a;b"}).json()["data"]["items"] == []
    assert client.patch("/api/news/feeds/999", json={"enabled": True}).status_code == 404
    assert client.post("/api/news/refresh", json={"feed_id": 999}).status_code == 404


def test_news_command_is_implemented(client):
    for text in ("AAPL NEWS", "NEWS"):
        d = client.post("/api/command", json={"text": text}).json()["data"]
        assert d["view"] == "news" and d["implemented"] is True and d["message"] is None
    assert client.post("/api/command", json={"text": "AAPL NEWS"}).json()["data"]["instrument_ids"] == ["EQUITY:NASDAQ:AAPL"]
