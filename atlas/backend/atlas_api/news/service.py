"""News store and fetcher. RSS is polled (not real time), so every item is labelled DELAYED with its feed and publish time.

What is deliberately NOT here: sentiment, impact scores, "catalyst" flags or AI summaries. Those would be invented numbers over untrusted text;
this module stores headlines with provenance, groups near-duplicates deterministically, and tags symbols only when the headline is explicit.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import httpx

from ..db import DB, now as iso_now
from . import tagging
from .parse import FeedError, RawItem, parse

MAX_BYTES = 2_000_000
MAX_FEEDS = 30
RETENTION_DAYS = 14
SYMBOL_TTL = 600.0
SYMBOL_FEED = ("Yahoo Finance (per symbol)", "https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US")
# Public RSS endpoints, URLs from memory: the build sandbox had no internet, so NONE of these was fetched. Each shows its own health in the UI.
DEFAULT_FEEDS = [
    ("Federal Reserve: press releases", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("SEC: press releases", "https://www.sec.gov/news/pressreleases.rss"),
    ("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "https://cointelegraph.com/rss"),
    ("MarketWatch: top stories", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("CNBC: markets", "https://www.cnbc.com/id/10000664/device/rss/rss.html"),
    ("BBC: business", "https://feeds.bbci.co.uk/news/business/rss.xml"),
]
STOP = set("the a an and or of to in on for at by with from as is are was were be been it its this that after over into new says say will".split())


class NewsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def url_ok(url: str, allow_local: bool = False) -> str | None:
    """None if acceptable, else the reason. String-level SSRF hygiene for a single-user local app: http(s) only and no loopback/private/link-local
    literal hosts. (DNS names that resolve to private addresses are not checked; feed URLs are chosen by the one local user.)"""
    try:
        p = urlsplit(url.strip())
    except ValueError:
        return "not a valid URL"
    if p.scheme not in ("http", "https") or not p.hostname:
        return "must be an http(s) URL"
    if p.username or p.password:
        return "URLs with embedded credentials are refused"
    if len(url) > 500:
        return "URL too long"
    h = p.hostname.lower()
    if not allow_local:
        if h == "localhost" or h.endswith(".local") or h.endswith(".internal"):
            return "local hosts are refused"
        try:
            ip = ipaddress.ip_address(h)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_unspecified:
                return "private or loopback addresses are refused"
        except ValueError:
            pass
    return None


def masked(url: str) -> str:
    """Feed URLs may carry an API key in the query string: show the host and path only."""
    p = urlsplit(url)
    return f"{p.scheme}://{p.netloc}{p.path}" + ("?…" if p.query else "")


def _tokens(title: str) -> frozenset[str]:
    return frozenset(w for w in re.findall(r"[a-z0-9]+", title.lower()) if len(w) >= 3 and w not in STOP)


def cluster(items: list[dict], threshold: float = 0.7, window_h: float = 48) -> list[dict]:
    """Group near-duplicate headlines (token Jaccard >= threshold, within window_h hours) so one story from five outlets is one row.
    Items must be sorted newest first. The representative is the EARLIEST item in the group; the rest are listed in `also`."""
    groups: list[dict] = []
    toks: list[frozenset[str]] = []
    for it in items:
        t = _tokens(it["title"])
        placed = False
        for g, gt in zip(groups, toks):
            if not t or not gt:
                continue
            if abs(it["_ts"] - g["_ts_first"]) > window_h * 3600:
                continue
            small, big = (len(t), len(gt)) if len(t) <= len(gt) else (len(gt), len(t))
            if small / big < threshold:           # Jaccard can never exceed min/max of the sizes: skip the set operations
                continue
            inter = len(t & gt)
            if inter / (len(t) + len(gt) - inter) >= threshold:
                g["members"].append(it)
                g["_ts_first"] = min(g["_ts_first"], it["_ts"])
                placed = True
                break
        if not placed:
            groups.append({"members": [it], "_ts_first": it["_ts"]})
            toks.append(t)
    out = []
    for g in groups:
        ms = sorted(g["members"], key=lambda x: x["_ts"])
        head, rest = ms[0], ms[1:]
        syms = list(dict.fromkeys(s for m in ms for s in m["symbols"]))
        out.append({**head, "symbols": syms, "also": [{"feed": r["feed"], "title": r["title"], "link": r["link"], "published": r["published"]} for r in rest]})
    out.sort(key=lambda x: x["_ts"], reverse=True)
    return out


class NewsService:
    def __init__(self, db: DB, client: httpx.AsyncClient | None = None, allow_local: bool = False, user_agent: str = "ATLAS-Terminal/0.1 (personal research)",
                 symbol_url: str | None = None):
        self.db, self.allow_local, self.ua = db, allow_local, user_agent
        self.symbol_url = symbol_url or SYMBOL_FEED[1]
        self.client = client or httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=6.0), follow_redirects=True, max_redirects=3)
        self._sym_at: dict[str, float] = {}
        self._sem = asyncio.Semaphore(4)
        self._seed()

    def _seed(self) -> None:
        if not self.db.q("SELECT 1 FROM news_feeds WHERE kind='rss' LIMIT 1"):
            for n, u in DEFAULT_FEEDS:
                self.db.x("INSERT OR IGNORE INTO news_feeds(name,url,kind,enabled,builtin,created_at) VALUES(?,?,?,1,1,?)", (n, u, "rss", iso_now()))
        if not self.db.q("SELECT 1 FROM news_feeds WHERE kind='symbol'"):
            self.db.x("INSERT OR IGNORE INTO news_feeds(name,url,kind,enabled,builtin,created_at) VALUES(?,?,'symbol',1,1,?)", (SYMBOL_FEED[0], self.symbol_url, iso_now()))

    # --- feed management ---------------------------------------------------------------------------
    def feeds(self) -> list[dict]:
        out = []
        counts = {r["feed_id"]: r["n"] for r in self.db.q("SELECT feed_id, COUNT(*) AS n FROM news_items GROUP BY feed_id")}
        for r in self.db.q("SELECT * FROM news_feeds WHERE kind='rss' ORDER BY builtin DESC, name"):
            out.append({"id": r["id"], "name": r["name"], "url": masked(r["url"]), "enabled": bool(r["enabled"]), "builtin": bool(r["builtin"]), "items": counts.get(r["id"], 0),
                        "last_fetch": r["last_fetch"], "last_ok": r["last_ok"], "last_error": r["last_error"], "last_count": r["last_count"]})
        return out

    def add_feed(self, name: str, url: str) -> dict:
        bad = url_ok(url, self.allow_local)
        if bad:
            raise NewsError("INVALID_FEED_URL", bad, 422)
        if self.db.q("SELECT COUNT(*) FROM news_feeds WHERE kind='rss'")[0][0] >= MAX_FEEDS:
            raise NewsError("TOO_MANY_FEEDS", f"at most {MAX_FEEDS} feeds", 409)
        if self.db.q("SELECT 1 FROM news_feeds WHERE url=?", (url.strip(),)):
            raise NewsError("DUPLICATE_FEED", "that feed URL is already added", 409)
        fid = self.db.x("INSERT INTO news_feeds(name,url,kind,enabled,builtin,created_at) VALUES(?,?,'rss',1,0,?)", (name.strip()[:80], url.strip(), iso_now()))
        return next(f for f in self.feeds() if f["id"] == fid)

    def set_enabled(self, fid: int, enabled: bool) -> None:
        if not self.db.q("SELECT 1 FROM news_feeds WHERE id=? AND kind='rss'", (fid,)):
            raise NewsError("NOT_FOUND", "no such feed", 404)
        self.db.x("UPDATE news_feeds SET enabled=? WHERE id=?", (1 if enabled else 0, fid))

    def delete_feed(self, fid: int) -> None:
        if not self.db.q("SELECT 1 FROM news_feeds WHERE id=? AND kind='rss'", (fid,)):
            raise NewsError("NOT_FOUND", "no such feed", 404)
        with self.db.tx() as c:
            c.execute("DELETE FROM news_items WHERE feed_id=?", (fid,))
            c.execute("DELETE FROM news_feeds WHERE id=?", (fid,))

    # --- fetching ------------------------------------------------------------------------------------
    async def _get(self, url: str, etag: str | None, lm: str | None) -> tuple[int, bytes, dict]:
        headers = {"User-Agent": self.ua, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5"}
        if etag:
            headers["If-None-Match"] = etag
        if lm:
            headers["If-Modified-Since"] = lm
        async with self.client.stream("GET", url, headers=headers) as r:
            final = str(r.url)
            if final != url and url_ok(final, self.allow_local):
                raise FeedError("redirected to a refused address")
            if r.status_code == 304:
                return 304, b"", dict(r.headers)
            if r.status_code != 200:
                raise FeedError(f"HTTP {r.status_code}")
            buf = bytearray()
            async for chunk in r.aiter_bytes():
                buf += chunk
                if len(buf) > MAX_BYTES:
                    raise FeedError(f"response larger than {MAX_BYTES // 1_000_000} MB: refused")
            return 200, bytes(buf), dict(r.headers)

    def _store(self, feed_id: int, items: list[RawItem], force_symbol: str | None = None) -> int:
        fetched, new = iso_now(), 0
        with self.db.tx() as c:
            for it in items:
                syms = tagging.tag(it.title, it.summary)
                if force_symbol and force_symbol not in syms:
                    syms = [force_symbol, *syms][:6]
                cur = c.execute("INSERT OR IGNORE INTO news_items(feed_id,uid,title,link,summary,published,fetched_at,symbols) VALUES(?,?,?,?,?,?,?,?)",
                                (feed_id, it.uid, it.title, it.link, it.summary, it.published.isoformat() if it.published else None, fetched, json.dumps(syms)))
                new += cur.rowcount
        return new

    async def _refresh_row(self, row, url: str | None = None, force_symbol: str | None = None) -> dict:
        """Fetch one feed. A failure is recorded on that feed and never raised: one broken feed cannot affect the others."""
        url = url or row["url"]
        res = {"id": row["id"], "name": row["name"], "ok": False, "new": 0, "seen": 0, "error": None}
        sym = row["kind"] == "symbol"
        try:
            async with self._sem:
                status, body, hdr = await self._get(url, None if sym else row["etag"], None if sym else row["last_modified"])
            if status == 304:
                res.update(ok=True)
            else:
                items, dropped = await asyncio.to_thread(parse, body)       # XML parsing and the insert transaction stay off the event loop
                res.update(ok=True, seen=len(items), new=await asyncio.to_thread(self._store, row["id"], items, force_symbol), dropped=dropped)
                if not sym:
                    self.db.x("UPDATE news_feeds SET etag=?, last_modified=? WHERE id=?", (hdr.get("etag"), hdr.get("last-modified"), row["id"]))
        except FeedError as e:
            res["error"] = str(e)[:140]
        except httpx.HTTPError as e:
            res["error"] = f"{type(e).__name__} (feed unreachable)"           # never echo the URL: it may carry an API key
        except Exception as e:  # noqa: BLE001
            res["error"] = f"{type(e).__name__}"
        if not sym:
            self.db.x("UPDATE news_feeds SET last_fetch=?, last_ok=CASE WHEN ? THEN ? ELSE last_ok END, last_error=?, last_count=? WHERE id=?",
                      (iso_now(), 1 if res["ok"] else 0, iso_now(), res["error"], res["seen"] if res["ok"] else None, row["id"]))
        return res

    async def refresh(self, feed_id: int | None = None) -> list[dict]:
        rows = self.db.q("SELECT * FROM news_feeds WHERE kind='rss' AND enabled=1" + (" AND id=?" if feed_id else ""), (feed_id,) if feed_id else ())
        if feed_id and not rows:
            raise NewsError("NOT_FOUND", "no such enabled feed", 404)
        out = await asyncio.gather(*(self._refresh_row(r) for r in rows))
        self.prune()
        return list(out)

    async def refresh_symbol(self, yahoo_symbol: str, tag: str, force: bool = False) -> dict | None:
        """On-demand per-symbol headlines (cached 10 min). Returns the fetch result, or None when served from the cache window."""
        if not re.fullmatch(r"[A-Z0-9.\-^=]{1,15}", yahoo_symbol):
            return None
        last = self._sym_at.get(yahoo_symbol)
        if not force and last is not None and time.monotonic() - last < SYMBOL_TTL:      # None, not 0: monotonic() can be small right after boot
            return None
        self._sym_at[yahoo_symbol] = time.monotonic()
        row = self.db.q("SELECT * FROM news_feeds WHERE kind='symbol'")[0]
        return await self._refresh_row(row, row["url"].replace("{symbol}", quote(yahoo_symbol)), tag)

    def prune(self) -> int:
        cut = (datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)).isoformat()
        with self.db.tx() as c:
            return c.execute("DELETE FROM news_items WHERE COALESCE(published, fetched_at) < ?", (cut,)).rowcount

    async def run_loop(self, seconds: float) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:  # noqa: BLE001  the loop must survive anything
                pass
            await asyncio.sleep(seconds)

    # --- reading ---------------------------------------------------------------------------------------
    def items(self, symbol: str | None = None, q: str | None = None, hours: float = 72, limit: int = 60) -> dict:
        cut = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        sql = ("SELECT i.*, f.name AS feed FROM news_items i JOIN news_feeds f ON f.id=i.feed_id "
               "WHERE COALESCE(i.published, i.fetched_at) >= ? AND (f.enabled=1 OR f.kind='symbol')")
        args: list = [cut]
        if symbol:
            if not re.fullmatch(r"[A-Z0-9.\-]{1,12}", symbol):
                raise NewsError("INVALID_SYMBOL", "invalid symbol", 422)
            sql += " AND i.symbols LIKE ?"
            args.append(f'%"{symbol}"%')
        if q:
            esc = q.strip()[:80].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            sql += " AND i.title LIKE ? ESCAPE '\\'"
            args.append(f"%{esc}%")
        sql += " ORDER BY COALESCE(i.published, i.fetched_at) DESC LIMIT 400"
        rows = self.db.q(sql, tuple(args))
        items = []
        for r in rows:
            when = r["published"] or r["fetched_at"]
            items.append({"id": r["id"], "title": r["title"], "link": r["link"], "summary": r["summary"], "feed": r["feed"], "published": r["published"],
                          "fetched_at": r["fetched_at"], "symbols": json.loads(r["symbols"]), "status": "DELAYED",
                          "_ts": datetime.fromisoformat(when).timestamp()})
        grouped = cluster(items)
        for g in grouped:
            g.pop("_ts", None), g.pop("_ts_first", None)
        feeds = self.feeds()
        oks = [f["last_ok"] for f in feeds if f["last_ok"] and f["enabled"]]
        return {"items": grouped[:limit], "total_stories": len(grouped), "raw_items": len(items),
                "meta": {"feeds_enabled": sum(1 for f in feeds if f["enabled"]), "feeds_ok": sum(1 for f in feeds if f["enabled"] and f["last_ok"] and not f["last_error"]),
                         "feeds_failing": [{"name": f["name"], "error": f["last_error"]} for f in feeds if f["enabled"] and f["last_error"]],
                         "never_fetched": sum(1 for f in feeds if f["enabled"] and not f["last_fetch"]), "as_of": max(oks) if oks else None,
                         "note": "RSS is polled, not real time: every item is DELAYED. Tags only appear when a headline names a symbol explicitly ($TSLA, (NASDAQ: TSLA), Bitcoin)."}}
