"""Raw provider fields -> a fundamentals snapshot (pure, no I/O).

Principles: every ratio is COMPUTED HERE from raw figures (never taken from the provider's pre-computed fields, whose units change between
library versions: e.g. Yahoo's dividendYield switched from a fraction to a percent); a field that cannot be computed is None and listed in
`missing`, never guessed; a ratio on a non-positive denominator is "not meaningful" with the reason, not a number; every row carries its basis.
Inputs are untrusted third-party data: numbers must be finite, text is control-stripped and length-capped.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from ..numeric import num

STALE_FINANCIALS_DAYS = 135          # a quarter plus the usual reporting lag
_CTRL = re.compile(r"[\x00-\x1f\x7f]")


def text(x, limit: int = 80) -> str | None:
    if not isinstance(x, str):
        return None
    t = _CTRL.sub("", x).strip()
    return t[:limit] or None


def _div(a, b):
    """a/b when both exist and b is positive; else (None, reason)."""
    if a is None or b is None:
        return None, "input missing"
    if b <= 0:
        return None, "not meaningful (non-positive denominator)"
    return a / b, None


def _pct(frac):
    return None if frac is None else frac * 100


def _day(ts) -> date | None:
    v = num(ts)
    if v is None or v <= 0 or v > 4_102_444_800:       # year 2100
        return None
    return datetime.fromtimestamp(v, timezone.utc).date()


def normalize(info: dict, price: float | None = None, calendar: dict | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    info = info or {}
    price = num(price) if num(price) and num(price) > 0 else (num(info.get("currentPrice")) or num(info.get("regularMarketPrice")))
    price = price if price and price > 0 else None
    kind = text(info.get("quoteType"), 20)
    is_fund = kind in ("ETF", "MUTUALFUND")

    eps, feps, rev, ebitda = num(info.get("trailingEps")), num(info.get("forwardEps")), num(info.get("totalRevenue")), num(info.get("ebitda"))
    mcap, ev, bvps = num(info.get("marketCap")), num(info.get("enterpriseValue")), num(info.get("bookValue"))
    shares, cash, debt = num(info.get("sharesOutstanding")), num(info.get("totalCash")), num(info.get("totalDebt"))
    drate = num(info.get("dividendRate"))

    rows: dict[str, dict] = {}

    def put(key, label, value, unit, basis, note=None):
        rows[key] = {"key": key, "label": label, "value": value, "unit": unit, "basis": basis, "note": note}

    pe, pe_n = _div(price, eps)
    fpe, fpe_n = _div(price, feps)
    ps, ps_n = _div(mcap, rev)
    pb, pb_n = _div(price, bvps)
    eve, eve_n = _div(ev, ebitda)
    put("pe", "P/E (trailing)", pe, "x", "price / trailing EPS", pe_n)
    put("pe_forward", "P/E (forward)", fpe, "x", "price / forward EPS (analyst estimate)", fpe_n)
    put("ps", "Price / sales", ps, "x", "market cap / trailing revenue", ps_n)
    put("pb", "Price / book", pb, "x", "price / book value per share", pb_n)
    put("ev_ebitda", "EV / EBITDA", eve, "x", "enterprise value / EBITDA", eve_n)
    put("market_cap", "Market cap", mcap, "$", "reported")
    put("enterprise_value", "Enterprise value", ev, "$", "reported")

    put("revenue", "Revenue (TTM)", rev, "$", "reported")
    put("revenue_growth_pct", "Revenue growth (YoY, latest quarter)", _pct(num(info.get("revenueGrowth"))), "%", "reported fraction x 100")
    put("earnings_growth_pct", "Earnings growth (YoY, latest quarter)", _pct(num(info.get("earningsGrowth"))), "%", "reported fraction x 100")
    put("gross_margin_pct", "Gross margin", _pct(num(info.get("grossMargins"))), "%", "reported fraction x 100")
    put("operating_margin_pct", "Operating margin", _pct(num(info.get("operatingMargins"))), "%", "reported fraction x 100")
    put("profit_margin_pct", "Net margin", _pct(num(info.get("profitMargins"))), "%", "reported fraction x 100")
    put("roe_pct", "Return on equity", _pct(num(info.get("returnOnEquity"))), "%", "reported fraction x 100")
    put("roa_pct", "Return on assets", _pct(num(info.get("returnOnAssets"))), "%", "reported fraction x 100")

    ocf, fcf = num(info.get("operatingCashflow")), num(info.get("freeCashflow"))
    fcfm, fcfm_n = _div(fcf, rev)
    put("operating_cash_flow", "Operating cash flow (TTM)", ocf, "$", "reported")
    put("free_cash_flow", "Free cash flow (TTM)", fcf, "$", "reported")
    put("fcf_margin_pct", "Free cash flow margin", None if fcfm is None else fcfm * 100, "%", "free cash flow / trailing revenue x 100", fcfm_n)

    equity = bvps * shares if bvps is not None and shares is not None else None
    de, de_n = _div(debt, equity)
    put("cash", "Cash", cash, "$", "reported")
    put("debt", "Total debt", debt, "$", "reported")
    put("net_debt", "Net debt", debt - cash if debt is not None and cash is not None else None, "$", "total debt - cash",
        None if debt is not None and cash is not None else "input missing")
    put("debt_to_equity", "Debt / equity", de, "x", "total debt / (book value per share x shares)", de_n)
    put("current_ratio", "Current ratio", num(info.get("currentRatio")), "x", "reported")

    dy, dy_n = _div(drate, price)
    put("dividend_rate", "Dividend (annual)", drate, "$/share", "reported")
    put("dividend_yield_pct", "Dividend yield", None if dy is None else dy * 100, "%", "annual dividend / price x 100 (computed: the provider's own yield field changes units)", dy_n)
    put("payout_ratio_pct", "Payout ratio", _pct(num(info.get("payoutRatio"))), "%", "reported fraction x 100")

    put("shares", "Shares outstanding", shares, "", "reported")
    put("high_52w", "52-week high", num(info.get("fiftyTwoWeekHigh")), "$", "reported")
    put("low_52w", "52-week low", num(info.get("fiftyTwoWeekLow")), "$", "reported")
    hi, lo = rows["high_52w"]["value"], rows["low_52w"]["value"]
    put("range_pos_pct", "Position in 52-week range", (price - lo) / (hi - lo) * 100 if None not in (price, hi, lo) and hi > lo else None, "%", "(price - low) / (high - low) x 100")

    if is_fund:       # funds have no company financials: say so once instead of a wall of dashes
        for k in ("pe", "pe_forward", "ps", "pb", "ev_ebitda", "revenue", "revenue_growth_pct", "earnings_growth_pct", "gross_margin_pct", "operating_margin_pct",
                  "profit_margin_pct", "roe_pct", "roa_pct", "debt_to_equity", "net_debt", "cash", "debt", "current_ratio", "payout_ratio_pct", "enterprise_value",
                  "operating_cash_flow", "free_cash_flow", "fcf_margin_pct"):
            rows[k]["note"] = f"not applicable to a {kind}"

    nxt = None
    if calendar:
        ds = calendar.get("Earnings Date")
        cands = [d for d in (ds if isinstance(ds, (list, tuple)) else [ds]) if isinstance(d, date)]
        future = sorted(d for d in cands if d >= now.date())
        nxt = future[0] if future else None
    mrq = _day(info.get("mostRecentQuarter"))
    age = (now.date() - mrq).days if mrq else None
    flags = []
    if age is not None and age > STALE_FINANCIALS_DAYS:
        flags.append(f"latest reported quarter ended {age} days ago: the financials may be out of date")
    if eps is not None and eps <= 0:
        flags.append("negative trailing earnings: P/E is not meaningful")
    if price is None:
        flags.append("no price: price-based ratios are unavailable")

    groups = [("Valuation", ["pe", "pe_forward", "ps", "pb", "ev_ebitda", "market_cap", "enterprise_value"]),
              ("Growth and profitability", ["revenue", "revenue_growth_pct", "earnings_growth_pct", "gross_margin_pct", "operating_margin_pct", "profit_margin_pct", "roe_pct", "roa_pct"]),
              ("Cash flow", ["operating_cash_flow", "free_cash_flow", "fcf_margin_pct"]),
              ("Balance sheet", ["cash", "debt", "net_debt", "debt_to_equity", "current_ratio"]),
              ("Dividend", ["dividend_rate", "dividend_yield_pct", "payout_ratio_pct"]),
              ("Share data", ["shares", "high_52w", "low_52w", "range_pos_pct"])]
    return {
        "name": text(info.get("longName") or info.get("shortName")), "sector": text(info.get("sector")), "industry": text(info.get("industry")),
        "quote_type": kind, "currency": text(info.get("currency"), 8) or "USD", "price": price,
        "groups": [{"name": n, "rows": [rows[k] for k in ks]} for n, ks in groups],
        "values": {k: r["value"] for k, r in rows.items()},
        "missing": sorted(k for k, r in rows.items() if r["value"] is None and r["note"] in (None, "input missing")),      # the provider did not supply an input
        "not_meaningful": {k: r["note"] for k, r in rows.items() if r["value"] is None and r["note"] not in (None, "input missing")},      # supplied, but the ratio is undefined
        "next_earnings_date": nxt.isoformat() if nxt else None,
        "financials_as_of": mrq.isoformat() if mrq else None, "financials_age_days": age, "flags": flags,
    }
