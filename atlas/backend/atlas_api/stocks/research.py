"""Stock research: facts from SEC filings, valuation and next earnings from the fundamentals service, rule-based bull/bear points, catalysts, news.

Every block says where it came from and how old it is. Three kinds of statement are kept apart:
  fact           - a number from a filing or a provider, with its period end / fetch time
  calculated     - a ratio computed here from those facts (the formula is stated)
  interpretation - bull/bear points from fixed rules over the calculated facts; never a prediction, rating or advice
Missing inputs give a missing figure and a reason, never an estimate. Guidance and consensus are not available from free sources and are said to be so.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from ..models import ProviderUnavailable

RULES = {"growth_good_pct": 10.0, "margin_gain_pp": 1.0, "de_high": 2.0, "pe_high": 40.0, "ps_high": 15.0, "net_cash_note": True}
GAPS = ["Management guidance and analyst consensus ('beat or miss') are not available from free sources and are not shown.",
        "Financial statements come from annual 10-K filings, so they can be up to a year old; the latest quarter is not included.",
        "Valuation ratios and the next earnings date come from Yahoo Finance (unofficial, delayed)."]


def _pct(a, b):
    return None if a is None or not b or b <= 0 else (a / b - 1) * 100


def _ratio(a, b):
    return None if a is None or b is None or b <= 0 else a / b * 100


def _gap_days(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def compute(years: list[dict]) -> list[dict]:
    """Per fiscal year: the raw figures plus growth and margins. Growth needs the previous year to be a real one-year step apart."""
    out = []
    for i, y in enumerate(years):
        prev = years[i - 1] if i else None
        step = prev and 350 <= _gap_days(y["end"], prev["end"]) <= 380
        fcf = None if y.get("operating_cash_flow") is None or y.get("capex") is None else y["operating_cash_flow"] - abs(y["capex"])
        debt = y.get("debt")
        out.append({**y, "free_cash_flow": fcf,
                    "revenue_growth_pct": _pct(y.get("revenue"), prev.get("revenue")) if step else None,
                    "net_income_growth_pct": _pct(y.get("net_income"), prev.get("net_income")) if step and (prev.get("net_income") or 0) > 0 and (y.get("net_income") or 0) > 0 else None,
                    "gross_margin_pct": _ratio(y.get("gross_profit"), y.get("revenue")), "operating_margin_pct": _ratio(y.get("operating_income"), y.get("revenue")),
                    "net_margin_pct": _ratio(y.get("net_income"), y.get("revenue")), "fcf_margin_pct": _ratio(fcf, y.get("revenue")),
                    "net_cash": None if y.get("cash") is None or debt is None else y["cash"] - debt,
                    "debt_to_equity": None if debt is None or (y.get("equity") or 0) <= 0 else debt / y["equity"]})
    return out


def cagr(years: list[dict], metric: str = "revenue") -> dict | None:
    pts = [(y["end"], y.get(metric)) for y in years if y.get(metric) is not None]
    if len(pts) < 3 or pts[0][1] <= 0 or pts[-1][1] <= 0:
        return None
    n = _gap_days(pts[-1][0], pts[0][0]) / 365.25
    if n < 1.5:
        return None
    return {"metric": metric, "from": pts[0][0], "to": pts[-1][0], "years": round(n, 1), "value_pct": ((pts[-1][1] / pts[0][1]) ** (1 / n) - 1) * 100,
            "formula": "(last / first) ^ (1 / years) - 1, over the fiscal years shown"}


def cases(calc: list[dict], valuation: dict | None) -> tuple[list[dict], list[dict]]:
    """Bull and bear points from fixed rules. Each cites the figures behind it. Interpretation only."""
    bull, bear = [], []
    if not calc:
        return bull, bear
    last, prev = calc[-1], calc[-2] if len(calc) > 1 else None

    def add(side, rid, text, based):
        side.append({"id": rid, "text": text, "based_on": based, "kind": "Interpretation (rule-based)"})
    g = last.get("revenue_growth_pct")
    if g is not None:
        if g >= RULES["growth_good_pct"]:
            add(bull, "growth", f"Revenue grew {g:.1f}% in the fiscal year ended {last['end']}, at or above the {RULES['growth_good_pct']:.0f}% mark used here for strong growth.", ["revenue"])
        elif g < 0:
            add(bear, "growth", f"Revenue fell {abs(g):.1f}% in the fiscal year ended {last['end']}.", ["revenue"])
    om, pom = last.get("operating_margin_pct"), prev.get("operating_margin_pct") if prev else None
    if om is not None and pom is not None:
        if om - pom >= RULES["margin_gain_pp"]:
            add(bull, "margin", f"Operating margin widened from {pom:.1f}% to {om:.1f}%: more of each sales dollar was kept as operating profit.", ["operating_income", "revenue"])
        elif pom - om >= RULES["margin_gain_pp"]:
            add(bear, "margin", f"Operating margin narrowed from {pom:.1f}% to {om:.1f}%: less of each sales dollar was kept as operating profit.", ["operating_income", "revenue"])
    f = last.get("free_cash_flow")
    if f is not None:
        (bull if f > 0 else bear).append({"id": "fcf", "text": f"Free cash flow (operating cash flow minus capital spending) was {'positive' if f > 0 else 'negative'} at ${abs(f) / 1e9:.2f}B.", "based_on": ["operating_cash_flow", "capex"], "kind": "Interpretation (rule-based)"})
    nc = last.get("net_cash")
    if nc is not None and nc > 0:
        add(bull, "net_cash", f"Cash exceeded long-term debt by ${nc / 1e9:.2f}B at fiscal year end.", ["cash", "debt"])
    de = last.get("debt_to_equity")
    if de is not None and de >= RULES["de_high"]:
        add(bear, "leverage", f"Long-term debt is {de:.1f}x shareholders' equity, above the {RULES['de_high']:.0f}x mark used here for heavy borrowing.", ["debt", "equity"])
    ni = last.get("net_income")
    if ni is not None and ni < 0:
        add(bear, "loss", f"The company lost ${abs(ni) / 1e9:.2f}B in the fiscal year ended {last['end']}.", ["net_income"])
    vals = (valuation or {}).get("values") or {}
    pe, ps = vals.get("pe"), vals.get("ps")
    if pe is not None and pe >= RULES["pe_high"]:
        add(bear, "pe", f"The price is {pe:.0f}x trailing earnings, above the {RULES['pe_high']:.0f}x mark used here for a demanding valuation: growth has to keep delivering.", ["pe"])
    if ps is not None and ps >= RULES["ps_high"]:
        add(bear, "ps", f"The market value is {ps:.1f}x annual sales, above the {RULES['ps_high']:.0f}x mark used here for a demanding valuation.", ["ps"])
    return bull, bear


def catalysts(earnings_date: str | None, filings: list[dict], today: date) -> list[dict]:
    out = []
    if earnings_date and earnings_date >= today.isoformat():
        out.append({"kind": "scheduled", "date": earnings_date, "title": "Next earnings report", "source": "Yahoo Finance calendar (unofficial; confirm with the company)", "link": None})
    for f in filings:
        if f["form"] == "8-K" and any(i["item"] == "2.02" for i in f["items"]):
            out.append({"kind": "filed", "date": f["filed"], "title": "Latest earnings release filed (8-K item 2.02)", "source": "SEC EDGAR", "link": f["link"]})
            break
    return out


def pick_valuation(snap: dict | None) -> dict | None:
    if not snap:
        return None
    g = next((x for x in snap.get("groups", []) if x["name"] == "Valuation"), None)
    return {"rows": (g or {}).get("rows", []), "values": snap.get("values", {}), "flags": snap.get("flags", []), "financials_as_of": snap.get("financials_as_of"),
            "price": snap.get("price"), "source": (snap.get("prov") or {}).get("provider"), "fetched_at": (snap.get("prov") or {}).get("fetched_at"), "status": (snap.get("prov") or {}).get("status")}


class StockResearch:
    def __init__(self, edgar, fundamentals, news, demo: bool = False):
        self.edgar, self.fundamentals, self.news, self.demo = edgar, fundamentals, news, demo

    async def research(self, inst, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        sym = inst.symbol
        errors: list[str] = []
        snap = None
        try:
            snap = await self.fundamentals.get(inst)
        except ProviderUnavailable as e:
            errors.append(f"Valuation and earnings date: {e.message[:100]}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"Valuation and earnings date: {type(e).__name__}")
        fin = subs = None
        fin_meta = subs_meta = None
        if self.demo:
            errors.append("Demo mode: SEC filings are not loaded; the figures below that exist are synthetic.")
        elif not self.edgar.enabled:
            errors.append("SEC filings are off: ATLAS_SEC_CONTACT is not set. Windows: add the line $env:ATLAS_SEC_CONTACT = \"you@example.com\" to local-settings.ps1 and restart ATLAS. The email is sent only to sec.gov.")
        else:
            try:
                hit = await self.edgar.cik(sym)
                if hit is None:
                    errors.append(f"SEC filings: no company with ticker {sym} was found.")
                else:
                    cik, title = hit
                    fin, fo, fat = await self.edgar.financials(cik)
                    fin_meta = {"origin": fo, "fetched_at": fat.isoformat(), "cik": cik}
                    subs, so, sat = await self.edgar.filings(cik)
                    subs_meta = {"origin": so, "fetched_at": sat.isoformat()}
            except ProviderUnavailable as e:
                errors.append(f"SEC filings: {e.message[:120]}")
            except Exception as e:  # noqa: BLE001
                errors.append(f"SEC filings: {type(e).__name__}")
        years = compute(fin["years"]) if fin else []
        valuation = pick_valuation(snap)
        bull, bear = cases(years, valuation)
        filings = (subs or {}).get("filings", [])
        earnings_date = (snap or {}).get("next_earnings_date")
        stories = []
        if self.news:
            try:
                await self.news.refresh_symbol(sym, sym)
            except Exception:  # noqa: BLE001  headlines are optional
                pass
            try:
                stories = [{"title": s["title"], "link": s.get("link"), "feed": s["feed"], "published": s.get("published")} for s in self.news.items(symbol=sym, hours=24 * 14, limit=8)["items"]]
            except Exception:  # noqa: BLE001
                stories = []
        return {"symbol": sym, "as_of": now.isoformat(), "demo": self.demo,
                "company": {"name": (snap or {}).get("name") or (fin or {}).get("name"), "sector": (snap or {}).get("sector"), "industry": (snap or {}).get("industry"),
                            "sic_description": (subs or {}).get("sic_description"), "fiscal_year_end": (subs or {}).get("fiscal_year_end"), "exchanges": (subs or {}).get("exchanges"),
                            "source": "SEC EDGAR (SIC industry, fiscal year end) and Yahoo Finance (sector, industry)"},
                "financials": {"available": bool(years), "years": years, "revenue_cagr": cagr(years), "source": "SEC EDGAR XBRL company facts, annual 10-K filings", "meta": fin_meta,
                               "note": "Growth needs the previous fiscal year; free cash flow = operating cash flow minus capital spending; net cash = cash minus long-term debt."},
                "valuation": valuation, "earnings": {"next_date": earnings_date, "source": "Yahoo Finance calendar (unofficial)",
                                                     "guidance": {"available": False, "reason": "Management guidance is not available from free sources."},
                                                     "consensus": {"available": False, "reason": "Analyst consensus is not available from free sources."}},
                "bull": bull, "bear": bear, "case_note": "Points come from fixed rules over the figures above. They are not predictions, ratings or advice, and a stock can do the opposite of its bull case.",
                "catalysts": catalysts(earnings_date, filings, now.date()), "filings": filings, "filings_meta": subs_meta, "news": stories,
                "errors": errors, "gaps": GAPS, "labels": {"fact": "A number from a filing or provider, with its period or time.", "calculated": "Computed here from the facts; the formula is stated.",
                                                                "interpretation": "Rule-based text, not a prediction or advice."}}

    async def earnings_calendar(self, instruments: list, days: int = 30, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        today, rows, errors = now.date(), [], []
        for inst in instruments:
            try:
                snap = await self.fundamentals.get(inst)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{inst.symbol}: {getattr(e, 'message', type(e).__name__)[:80]}")
                continue
            d = snap.get("next_earnings_date")
            if d and 0 <= (date.fromisoformat(d) - today).days <= days:
                rows.append({"symbol": inst.symbol, "name": snap.get("name"), "instrument_id": inst.id, "date": d, "days_away": (date.fromisoformat(d) - today).days,
                             "sector": snap.get("sector"), "status": (snap.get("prov") or {}).get("status"), "source": "Yahoo Finance calendar (unofficial; confirm with the company)"})
        rows.sort(key=lambda r: (r["date"], r["symbol"]))
        return {"as_of": now.isoformat(), "window_days": days, "items": rows, "checked": len(instruments), "errors": errors,
                "note": "Only symbols you ask about are checked, because no free source lists every company's next earnings date reliably."}
