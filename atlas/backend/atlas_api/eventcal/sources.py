"""Pure parsers for the calendar's sources. No network here: each takes already-downloaded text or JSON and returns plain event dicts.

Event shape (all sources): {kind, date 'YYYY-MM-DD', at_utc (ISO or None), time_label (text or None), title, symbol, name, importance 'high'|'medium'|'low', details {...}, source, official (bool), link}
kind is one of: earnings, economy, rates, dividend, auction.
Anything a source does not say is None. Nothing is estimated here.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from ..fedwatch import parse_ics

# BLS release calendar entries worth showing: (text in the BLS title, id, label, importance)
BLS_WANT = (("Consumer Price Index", "cpi", "CPI (inflation)", "high"), ("Employment Situation", "jobs", "Jobs report (payrolls, unemployment)", "high"),
            ("Producer Price Index", "ppi", "PPI (producer prices)", "medium"), ("Job Openings and Labor Turnover", "jolts", "JOLTS (job openings)", "medium"),
            ("Employment Cost Index", "eci", "Employment Cost Index (wages)", "medium"))
BEA_WANT = (("GDP (", "gdp", "GDP", "high"), ("Gross Domestic Product", "gdp", "GDP", "high"), ("Personal Income and Outlays", "pce", "PCE inflation and personal income", "high"))
TIME_LABELS = {"time-pre-market": "Before the market opens", "time-after-hours": "After the market closes", "time-not-supplied": None}
LINKS = {"bls": "https://www.bls.gov/schedule/news_release/", "bea": "https://www.bea.gov/news/schedule", "fomc": "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
         "treasury": "https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding", "nasdaq_e": "https://www.nasdaq.com/market-activity/earnings", "nasdaq_d": "https://www.nasdaq.com/market-activity/dividends"}


def money(x) -> float | None:
    """'$1,234.5' -> 1234.5; '($0.12)' -> -0.12; '' / 'N/A' / None -> None."""
    if x is None:
        return None
    t = str(x).strip()
    if not t or t.upper() in ("N/A", "NA", "--"):
        return None
    neg = t.startswith("(") and t.endswith(")")
    t = re.sub(r"[^0-9.\-]", "", t)
    try:
        v = float(t)
    except ValueError:
        return None
    return -abs(v) if neg else v


def us_date(s) -> str | None:
    """'11/10/2026' -> '2026-11-10'."""
    try:
        return datetime.strptime(str(s).strip(), "%m/%d/%Y").date().isoformat()
    except ValueError:
        return None


def cap_importance(cap: float | None) -> str:
    return "high" if cap is not None and cap >= 200e9 else "medium" if cap is not None and cap >= 10e9 else "low"


def parse_nasdaq_earnings(payload: dict, day: str) -> list[dict]:
    out = []
    for r in ((payload or {}).get("data") or {}).get("rows") or []:
        sym = str(r.get("symbol") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-]{1,10}", sym):
            continue
        cap = money(r.get("marketCap"))
        out.append({"kind": "earnings", "date": day, "at_utc": None, "time_label": TIME_LABELS.get(r.get("time")), "title": f"{sym} earnings report", "symbol": sym, "name": str(r.get("name") or "")[:80] or None,
                    "importance": cap_importance(cap), "market_cap": cap,
                    "details": {"quarter_ending": r.get("fiscalQuarterEnding") or None, "eps_estimate": money(r.get("epsForecast")), "analysts": int(r["noOfEsts"]) if str(r.get("noOfEsts") or "").isdigit() else None,
                                "last_year_eps": money(r.get("lastYearEPS")), "last_year_report_date": us_date(r.get("lastYearRptDt"))},
                    "source": "Nasdaq earnings calendar (unofficial; estimates are analyst consensus as shown by Nasdaq)", "official": False, "link": LINKS["nasdaq_e"]})
    return out


def parse_nasdaq_dividends(payload: dict, day: str) -> list[dict]:
    out = []
    for r in (((payload or {}).get("data") or {}).get("calendar") or {}).get("rows") or []:
        sym = str(r.get("symbol") or "").strip().upper()
        if not re.fullmatch(r"[A-Z0-9.\-]{1,10}", sym):
            continue
        ex = us_date(r.get("dividend_Ex_Date")) or day
        out.append({"kind": "dividend", "date": ex, "at_utc": None, "time_label": "Ex-dividend date", "title": f"{sym} ex-dividend", "symbol": sym, "name": re.sub(r"\s+(Common Stock|Class [A-Z].*|Ordinary Shares.*)$", "", str(r.get("companyName") or ""))[:80] or None,
                    "importance": "low", "market_cap": None,
                    "details": {"amount": r.get("dividend_Rate") if isinstance(r.get("dividend_Rate"), (int, float)) else money(r.get("dividend_Rate")), "annual_amount": r.get("indicated_Annual_Dividend") if isinstance(r.get("indicated_Annual_Dividend"), (int, float)) else money(r.get("indicated_Annual_Dividend")),
                                "ex_date": ex, "pay_date": us_date(r.get("payment_Date")), "record_date": us_date(r.get("record_Date")), "announced": us_date(r.get("announcement_Date"))},
                    "source": "Nasdaq dividend calendar (unofficial)", "official": False, "link": LINKS["nasdaq_d"]})
    return out


def parse_bls(ics_text: str) -> list[dict]:
    out = []
    for e in parse_ics(ics_text, want=tuple((w[0], w[1], w[2]) for w in BLS_WANT)):
        imp = next(w[3] for w in BLS_WANT if w[1] == e["series"])
        out.append({"kind": "economy", "date": e["date"], "at_utc": e["at_utc"], "time_label": None, "title": e["label"], "symbol": None, "name": None, "importance": imp, "market_cap": None,
                    "details": {"release": e["name"], "series": e["series"]}, "source": "BLS release calendar (official)", "official": True, "link": LINKS["bls"]})
    return out


_BEA_ROW = re.compile(r'<div class="release-date">\s*([A-Za-z]+ \d{1,2})\s*</div>\s*<small class="text-muted">\s*([^<]*)</small>.*?release-title[^>]*>\s*([^<]+?)\s*</td>', re.S)


def parse_bea(html: str, today: date) -> list[dict]:
    """BEA's schedule page lists 'Month Day' without a year; the year is the nearest one that puts the date on or after (today minus 60 days)."""
    out = []
    for m in _BEA_ROW.finditer(html or ""):
        title = re.sub(r"\s+", " ", m.group(3)).strip()
        hit = next((w for w in BEA_WANT if w[0].lower() in title.lower()), None)
        if not hit:
            continue
        try:
            d = datetime.strptime(f"{m.group(1)} {today.year}", "%B %d %Y").date()
        except ValueError:
            continue
        if d < today - timedelta(days=60):
            d = d.replace(year=d.year + 1)
        out.append({"kind": "economy", "date": d.isoformat(), "at_utc": None, "time_label": m.group(2).strip() + " ET" if m.group(2).strip() else None, "title": f"{hit[2]}: {title}"[:140], "symbol": None, "name": None, "importance": hit[3],
                    "market_cap": None, "details": {"release": title, "series": hit[1]}, "source": "BEA release schedule (official)", "official": True, "link": LINKS["bea"]})
    return out


def parse_treasury(payload: dict, today: date) -> list[dict]:
    out = []
    for r in (payload or {}).get("data") or []:
        d = str(r.get("auction_date") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) or d < today.isoformat():
            continue
        term = str(r.get("security_term") or "")
        big = term in ("10-Year", "30-Year", "20-Year")
        out.append({"kind": "auction", "date": d, "at_utc": None, "time_label": None, "title": f"Treasury {term} {str(r.get('security_type') or '').lower()} auction{' (reopening)' if r.get('reopening') == 'Yes' else ''}".strip(), "symbol": None, "name": None,
                    "importance": "medium" if big else "low", "market_cap": None, "details": {"term": term, "type": r.get("security_type"), "issue_date": r.get("issue_date"), "cusip": r.get("cusip")},
                    "source": "US Treasury auction schedule (official)", "official": True, "link": LINKS["treasury"]})
    return out


def parse_fomc(events: list[dict]) -> list[dict]:
    """fedwatch.scheduled_events() items -> calendar events (kind 'rates')."""
    out = []
    for e in events:
        at = e.get("at_utc")
        if not at:
            continue
        imp = "high" if e.get("type") in ("statement",) else "medium"
        d = datetime.fromisoformat(at).astimezone(timezone.utc).date().isoformat()
        out.append({"kind": "rates", "date": d, "at_utc": at, "time_label": None, "title": e["title"], "symbol": None, "name": None, "importance": imp, "market_cap": None,
                    "details": {"meeting": e.get("meeting"), "projections": bool(e.get("projections"))}, "source": "Fed FOMC calendar (entered by hand; confirm on the Fed site)", "official": True, "link": LINKS["fomc"]})
    return out
