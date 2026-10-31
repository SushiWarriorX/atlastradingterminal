"""RSS 2.0 / Atom parsing and text hygiene (pure). Feeds are UNTRUSTED input.

- Documents containing a DOCTYPE or ENTITY declaration are refused outright (blocks entity-expansion and external-entity tricks without
  needing a hardened parser), and documents are size-capped by the fetcher.
- Titles and summaries become PLAIN TEXT: tags stripped, entities decoded, control characters removed, length capped. The UI renders them as
  text, never as HTML.
- Only http(s) links survive; `javascript:`, `data:` and the like are dropped.
- Headlines are kept with a short summary and a link back; full article text is never stored.
"""
from __future__ import annotations

import hashlib
import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

MAX_TITLE, MAX_SUMMARY = 240, 320
_TAG = re.compile(r"<[^>]*>")
_WS = re.compile(r"\s+")
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DANGER = re.compile(rb"<!\s*(DOCTYPE|ENTITY)", re.I)


class FeedError(Exception):
    pass


@dataclass
class RawItem:
    uid: str
    title: str
    link: str | None
    summary: str
    published: datetime | None


def clean_text(s: str | None, limit: int) -> str:
    if not s:
        return ""
    t = _TAG.sub(" ", s)
    t = html.unescape(html.unescape(t))          # feeds often double-encode
    t = _TAG.sub(" ", t)                         # entities may have decoded into tags
    t = _CTRL.sub("", t)
    t = _WS.sub(" ", t).strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def safe_link(u: str | None) -> str | None:
    if not u:
        return None
    u = u.strip()
    p = urlsplit(u)
    return u if p.scheme in ("http", "https") and p.netloc and len(u) <= 2000 else None


def parse_time(s: str | None, now: datetime | None = None) -> datetime | None:
    """RFC 822 or ISO 8601 -> aware UTC. Unparseable or implausibly far-future values give None (never a guess)."""
    if not s or not s.strip():
        return None
    s = s.strip()
    d = None
    try:
        d = parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d is None:
        return None
    d = d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    if d > (now or datetime.now(timezone.utc)) + timedelta(minutes=10):
        return None
    return d


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(el: ET.Element, *names: str) -> ET.Element | None:
    for c in el:
        if _local(c.tag) in names:
            return c
    return None


def _text(el: ET.Element | None) -> str:
    return "".join(el.itertext()) if el is not None else ""


def parse(data: bytes, now: datetime | None = None) -> tuple[list[RawItem], int]:
    """Returns (items, dropped). `dropped` counts entries without a usable title."""
    if _DANGER.search(data[:4096]) or _DANGER.search(data):
        raise FeedError("document declares a DOCTYPE/ENTITY: refused")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise FeedError(f"not valid XML ({str(e)[:60]})") from None
    kind = _local(root.tag)
    if kind == "rss":
        ch = _child(root, "channel")
        entries = [c for c in (ch if ch is not None else []) if _local(c.tag) == "item"]
    elif kind == "feed":
        entries = [c for c in root if _local(c.tag) == "entry"]
    elif kind == "RDF":
        entries = [c for c in root if _local(c.tag) == "item"]
    else:
        raise FeedError(f"not an RSS or Atom feed (root element '{kind[:30]}')")
    out: list[RawItem] = []
    dropped = 0
    for e in entries:
        title = clean_text(_text(_child(e, "title")), MAX_TITLE)
        if not title:
            dropped += 1
            continue
        link_el = _child(e, "link")
        link = None
        if link_el is not None:
            link = safe_link(link_el.get("href") or _text(link_el))
        summ = clean_text(_text(_child(e, "description", "summary", "encoded", "content")), MAX_SUMMARY)
        pub = parse_time(_text(_child(e, "pubDate", "published", "updated", "date")), now)
        guid = _text(_child(e, "guid", "id")).strip()
        uid = guid[:300] if guid else (link or hashlib.sha1(f"{title}|{pub}".encode()).hexdigest())
        out.append(RawItem(uid, title, link, summ, pub))
    return out, dropped
