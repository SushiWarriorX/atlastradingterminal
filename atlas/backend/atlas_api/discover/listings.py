"""Newly listed companies on NYSE and Nasdaq: upcoming deals and recent pricings, with an honest status for each.

SOURCE AND ITS LIMITS. The deal calendar is Nasdaq's own IPO calendar (a free public JSON feed behind its website; unofficial, undocumented, and Nasdaq attributes its data to EDGAR Online). It lists
IPOs: it does NOT list direct listings, completed SPAC mergers, exchange transfers or ticker changes. Those are therefore not shown (not invented), and the response says so. Where SEC filings are
reachable, a priced deal is checked against the company's final prospectus (Form 424B4) as independent evidence; otherwise it is marked unverified.

STATUS. upcoming = expected pricing date today or later; priced = pricing reported, first trade normally the next trading day, NOT yet confirmed as trading; trading = a first trading day confirmed from an
independent price history; withdrawn / filed = no listing. 'Upcoming' and 'confirmed trading' are never mixed. A company that traded before (a transfer or ticker change) is not 'new'; see is_genuinely_new.
If nothing is reported for a day the answer says so.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

import httpx

CAL_URL = "https://api.nasdaq.com/api/ipo/calendar?date={month}"
SOURCE = "Nasdaq IPO calendar (public website feed; unofficial; data attributed by Nasdaq to EDGAR Online)"
PAGE = "https://www.nasdaq.com/market-activity/ipos"
TTL = timedelta(hours=6)
VERIFY_FORMS = ("424B4", "424B1")
SPAC_NAME = re.compile(r"\bacquisition (corp|corporation|holdings|co|company)\b|\bblank check\b|\bmerger corp\b", re.I)
SPAC_NOTE = ("A blank-check company (SPAC): it raises cash to merge with an operating business later and has no business of its own yet, so there is no revenue to research. "
             "A completed merger is a different event and is not covered by this feed.")
COVERAGE_NOTE = ("This feed covers IPOs only. Direct listings, completed SPAC mergers, exchange transfers and ticker changes are not in it, so they are not shown here; "
                 "nothing is guessed. A priced deal is marked 'confirmed trading' only when an independent price history shows its first trading day.")


def exchange_of(text: str | None) -> tuple[str | None, str | None]:
    t = (text or "").strip()
    u = t.upper()
    if u.startswith("NASDAQ"):
        return "Nasdaq", t
    if u.startswith("NYSE AMERICAN") or u.startswith("NYSE MKT"):
        return "NYSE American", t
    if u.startswith("NYSE"):
        return "NYSE", t
    return None, t or None


def _date(s) -> str | None:
    if not s:
        return None
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(s).strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def _int(s) -> int | None:
    try:
        return int(str(s).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _money(s) -> float | None:
    try:
        return float(str(s).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def parse_calendar(payload: dict) -> list[dict]:
    """One month of the calendar -> rows (all four tables), with ISO dates. Rows without a usable name are dropped."""
    d = (payload or {}).get("data") or {}
    rows = []
    for table, stage in (("priced", "priced"), ("upcoming", "upcoming"), ("filed", "filed"), ("withdrawn", "withdrawn")):
        t = d.get(table) or {}
        if stage == "upcoming":
            t = t.get("upcomingTable") or t
        for r in t.get("rows") or []:
            name = r.get("companyName")
            if not isinstance(name, str) or not name.strip():
                continue
            ex, ex_text = exchange_of(r.get("proposedExchange"))
            price = r.get("proposedSharePrice")
            rows.append({"deal_id": str(r.get("dealID") or ""), "symbol": (r.get("proposedTickerSymbol") or None), "name": name.strip()[:120], "exchange": ex, "exchange_text": ex_text, "stage": stage,
                         "price": price if isinstance(price, str) else None, "shares_offered": _int(r.get("sharesOffered")), "offer_amount": _money(r.get("dollarValueOfSharesOffered")),
                         "priced_date": _date(r.get("pricedDate")), "expected_date": _date(r.get("expectedPriceDate")), "filed_date": _date(r.get("filedDate")), "withdraw_date": _date(r.get("withdrawDate"))})
    return rows


def next_trading_day(d: date) -> date:
    """The next weekday. US market holidays are not modelled, so this is an expectation, not a confirmation."""
    n = d + timedelta(days=1)
    while n.weekday() >= 5:
        n += timedelta(days=1)
    return n


def classify(row: dict, today: date, confirmed_first_trade: str | None = None) -> dict:
    """Status of one deal. A first trading day is accepted only when passed in from an independent price history."""
    st = row["stage"]
    out = {**row, "listing_type": "IPO", "listing_type_note": "From the IPO calendar; direct listings, SPAC mergers and transfers are not covered."}
    if SPAC_NAME.search(row.get("name") or ""):
        out.update(listing_type="SPAC IPO", listing_type_note=SPAC_NOTE)
    if st == "withdrawn":
        out.update(status="withdrawn", status_text="Withdrawn: the offering was pulled; no listing.")
    elif st == "filed":
        out.update(status="filed", status_text="Registration filed, no pricing date: not an upcoming listing yet.")
    elif st == "upcoming":
        exp = row.get("expected_date")
        if exp and date.fromisoformat(exp) >= today:
            out.update(status="upcoming", status_text=f"Expected to price on {exp}. Dates move; it is not trading yet.")
        else:
            out.update(status="upcoming_date_passed", status_text="The expected pricing date has passed with no pricing reported: it may have been postponed or may be missing from the feed.")
    else:                                                               # priced
        pd = date.fromisoformat(row["priced_date"]) if row.get("priced_date") else None
        if pd is None:
            out.update(status="priced", status_text="Pricing reported without a date.")
        else:
            exp_trade = next_trading_day(pd)
            out["expected_first_trade"] = exp_trade.isoformat()
            if confirmed_first_trade:
                out.update(status="trading", first_trade_date=confirmed_first_trade, status_text=f"Confirmed trading: first trading day {confirmed_first_trade} (from an independent price history).")
            elif exp_trade > today:
                out.update(status="priced", status_text=f"Priced on {row['priced_date']}; first trade expected {exp_trade.isoformat()}. Not yet trading.")
            else:
                out.update(status="priced", status_text=f"Priced on {row['priced_date']}; first trade was expected {exp_trade.isoformat()} but is not independently confirmed here.")
    return out


def is_genuinely_new(first_trade: str, earliest_price_date: str | None = None, earliest_filing_date: str | None = None, gap_days: int = 90) -> dict:
    """A company is new only if nothing shows it traded or filed as a public company well before its first trading day. None means 'cannot tell' (no independent history was available)."""
    ft = date.fromisoformat(first_trade)
    evidence = []
    if earliest_price_date:
        if (ft - date.fromisoformat(earliest_price_date)).days > gap_days:
            return {"new": False, "reason": f"Price history goes back to {earliest_price_date}, long before {first_trade}: this looks like a transfer, ticker change or relisting, not a new public company."}
        evidence.append(f"no price history before {earliest_price_date}")
    if earliest_filing_date:
        if (ft - date.fromisoformat(earliest_filing_date)).days > 400:
            return {"new": False, "reason": f"Periodic SEC reports go back to {earliest_filing_date}: the company was already public."}
        evidence.append(f"first periodic SEC report {earliest_filing_date}")
    if not evidence:
        return {"new": None, "reason": "No independent price or filing history was available to check whether this company was already public."}
    return {"new": True, "reason": "Genuinely new: " + "; ".join(evidence) + "."}


def verify_with_sec(filings: list[dict], priced_date: str | None) -> dict:
    """Independent evidence from the company's SEC filings: a final prospectus (424B4) filed within a few days of pricing."""
    if not priced_date:
        return {"verified": False, "evidence": None, "note": "No pricing date to check against."}
    pd = date.fromisoformat(priced_date)
    for f in filings or []:
        if f.get("form") in VERIFY_FORMS and f.get("filed"):
            try:
                gap = (date.fromisoformat(f["filed"]) - pd).days
            except ValueError:
                continue
            if -3 <= gap <= 10:
                return {"verified": True, "evidence": {"form": f["form"], "filed": f["filed"], "link": f.get("link")}, "note": f"Final prospectus ({f['form']}) filed {f['filed']}."}
    return {"verified": False, "evidence": None, "note": "No final prospectus (424B4) was found near the pricing date in the filings checked."}


def build_feed(rows: list[dict], today: date, days: int = 30, confirmations: dict | None = None, verifications: dict | None = None, errors: list[str] | None = None) -> dict:
    """Two separate lists (upcoming and recent), a summary for today and the rolling window. `confirmations` maps symbol -> first trading day from an independent history."""
    confirmations, verifications = confirmations or {}, verifications or {}
    seen, upcoming, recent = set(), [], []
    cutoff = today - timedelta(days=days)
    for r in rows:
        if r["exchange"] is None:                                          # OTC and other venues are not NYSE or Nasdaq
            continue
        if r["deal_id"] in seen:
            continue
        seen.add(r["deal_id"])
        c = classify(r, today, confirmations.get((r["symbol"] or "").upper()))
        if r["symbol"] and r["symbol"].upper() in verifications:
            c["verification"] = verifications[r["symbol"].upper()]
        if c["status"] in ("upcoming", "upcoming_date_passed"):
            upcoming.append(c)
        elif c["status"] in ("priced", "trading") and r.get("priced_date") and date.fromisoformat(r["priced_date"]) >= cutoff:
            recent.append(c)
    upcoming.sort(key=lambda x: (x.get("expected_date") or "9999", x["name"]))
    recent.sort(key=lambda x: (x.get("priced_date") or "", x["name"]), reverse=True)
    pricing_today = [x for x in recent if x.get("priced_date") == today.isoformat()]
    trading_today = [x for x in recent if x.get("expected_first_trade") == today.isoformat() or x.get("first_trade_date") == today.isoformat()]
    if pricing_today or trading_today:
        text = f"{len(pricing_today)} priced today; {len(trading_today)} expected to begin trading today (confirmed: {sum(1 for x in trading_today if x['status'] == 'trading')})."
    else:
        text = "No new listings are reported for today."
    return {"as_of": today.isoformat(), "window_days": days, "today": {"priced": len(pricing_today), "expected_first_trade": len(trading_today), "text": text}, "upcoming": upcoming, "recent": recent,
            "counts": {"upcoming": len(upcoming), "recent": len(recent), "confirmed_trading": sum(1 for x in recent if x["status"] == "trading"), "verified_by_sec": sum(1 for x in recent if (x.get("verification") or {}).get("verified"))},
            "source": SOURCE, "url": PAGE, "coverage": COVERAGE_NOTE, "errors": errors or []}


class NasdaqIpoFeed:
    def __init__(self, db=None, client: httpx.AsyncClient | None = None):
        self.db, self._client = db, client

    def _cached(self, key: str):
        if self.db is None:
            return None, None
        r = self.db.q("SELECT fetched_at, payload FROM listing_cache WHERE key=?", (key,))
        if not r:
            return None, None
        at = datetime.fromisoformat(r[0]["fetched_at"])
        return json.loads(r[0]["payload"]), at

    def _save(self, key: str, payload: dict, now: datetime) -> None:
        if self.db is not None:
            self.db.x("INSERT INTO listing_cache(key,fetched_at,payload) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET fetched_at=excluded.fetched_at, payload=excluded.payload", (key, now.isoformat(), json.dumps(payload)))

    async def rows(self, today: date, now: datetime | None = None, back_months: int = 2) -> tuple[list[dict], list[str]]:
        """All calendar rows for the current month, the months before it and the next one. A month that cannot be fetched uses its last saved copy (said in the errors) or is skipped."""
        now = now or datetime.now(timezone.utc)
        months = []
        for k in range(-back_months, 2):
            i = today.year * 12 + today.month - 1 + k
            months.append(f"{i // 12}-{i % 12 + 1:02d}")
        out, errors = [], []
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            for m in months:
                payload, at = self._cached(f"ipo:{m}")
                if payload is not None and now - at < TTL:
                    out += parse_calendar(payload)
                    continue
                try:
                    r = await c.get(CAL_URL.format(month=m), headers={"User-Agent": "ATLAS research terminal", "Accept": "application/json"})
                    if r.status_code != 200:
                        raise ValueError(f"HTTP {r.status_code}")
                    p = r.json()
                    if (p.get("status") or {}).get("rCode") != 200:
                        raise ValueError("the feed reported an error")
                    rows = parse_calendar(p)
                    self._save(f"ipo:{m}", p, now)
                    out += rows
                except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
                    if payload is not None:
                        errors.append(f"{m}: could not refresh ({type(e).__name__}); showing the copy saved {at.date().isoformat()}")
                        out += parse_calendar(payload)
                    else:
                        errors.append(f"{m}: could not be read ({type(e).__name__}: {str(e)[:60]})")
        finally:
            if self._client is None:
                await c.aclose()
        return out, errors
