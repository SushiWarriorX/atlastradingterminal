"""Puts the pieces together for one company: revenue, quality, Rule of 40 and valuation from filed figures plus a price, with a code-built list of thesis questions.

Pure: give it the condensed SEC facts, the SIC code and a price (with its time and source). The caller does the network work. Claude is not involved in any figure here; an explanation layer, when added,
may only restate these figures and the filings behind them.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from . import valuation as V
from .facts import annual, discrete_quarters, filing_link, flow_facts, latest_instant, ttm
from .revenue import SPECIAL, analyze_revenue, quality, sector_kind
from .rule40 import rule_of_40

COVERAGE = {
    "covered": ["Annual revenue (five years) and quarterly revenue (eight quarters) from 10-K and 10-Q filings", "Trailing-twelve-month revenue, year-over-year growth, multi-year growth rate and acceleration",
                "Revenue per diluted share and the change in diluted share count", "Margins, cash conversion, free cash flow, stock-based compensation, cash, debt, a pre-tax return on capital",
                "Rule of 40 (software only), with an EBITDA-basis variant labelled separately", "Enterprise value, multiples, a scenario DCF, a reverse DCF and an evidence-quality grade"],
    "not_covered": ["Revenue by segment or geography, organic versus acquired growth, currency effects, one-off items (in the filing text, not in structured data)",
                    "Customer concentration, recurring revenue, retention and backlog (filing text)", "Management guidance (never mixed with reported results; not available from free structured sources)",
                    "Peer comparison and the company's own historical multiples (not built yet)", "Banks, insurers and REITs: sector-specific metrics (not built yet; company-style measures are marked not applicable)",
                    "Foreign filers that report under IFRS (only US-GAAP filings are read)", "Analyst estimates (not available from free sources)"],
}


def latest_diluted_shares(rf: dict) -> dict | None:
    """The newest weighted-average diluted share count filed: a quarter's own figure when available, otherwise the fiscal year's. Weighted averages are not cumulative, so quarters are not derived."""
    facts = flow_facts(rf, "diluted_shares")
    best = None
    for f in facts:
        days = (f.end - f.start).days
        kind = "quarter" if 80 <= days <= 100 else "year" if 350 <= days <= 380 else None
        if kind and (best is None or f.end > best["end"] or (f.end == best["end"] and f.filed > best["filed"])):
            best = {"value": f.val, "end": f.end, "filed": f.filed, "kind": kind, "accn": f.accn}
    return best


def _t(rf, metric, end):
    r = ttm(discrete_quarters(flow_facts(rf, metric)), end)
    return r["value"] if r else None


def valuation_inputs(rf: dict, sic, price, price_time, price_source, rev: dict, now: datetime) -> dict:
    end = date.fromisoformat(rev["ttm"]["period_end"]) if rev.get("ttm") else None
    shares = latest_diluted_shares(rf)
    nq = len(discrete_quarters(flow_facts(rf, "revenue")))
    reliable, note = True, None
    if shares is None:
        reliable, note = False, "No diluted share count is on file."
    elif nq < 4 or not rev.get("annual"):
        reliable, note = False, ("This company has a short filing history, so its weighted-average share count lags the count after listing; a reliable post-listing share count (from the filing's cover page "
                                 "and the prospectus) is needed and is not read yet.")
    cash = latest_instant(rf, "cash", end) if end else None
    debt = latest_instant(rf, "debt", end) if end else None
    ocf, cx = (_t(rf, "operating_cash_flow", end), _t(rf, "capex", end)) if end else (None, None)
    oi, da = (_t(rf, "operating_income", end), _t(rf, "da", end)) if end else (None, None)
    revv = rev["ttm"]["value"] if rev.get("ttm") else None
    fcf = None if ocf is None or cx is None else ocf - abs(cx)
    sc = rev.get("share_count_change")
    dil = None
    if sc:
        yrs = (date.fromisoformat(sc["to"]) - date.fromisoformat(sc["from"])).days / 365.25
        if yrs >= 0.9:                                                         # consecutive fiscal year-ends are about 0.999 years apart
            dil = ((1 + sc["change_pct"] / 100) ** (1 / yrs) - 1) * 100
    return {"price": price, "price_time": price_time, "price_source": price_source, "shares": shares["value"] if shares else None, "shares_reliable": reliable, "shares_note": note,
            "shares_basis": (f"weighted-average diluted shares for the {shares['kind']} ended {shares['end'].isoformat()}" if shares else None),
            "cash": cash["value"] if cash else None, "debt": debt["value"] if debt else None, "ttm_revenue": revv, "ttm_gross_profit": _t(rf, "gross_profit", end) if end else None,
            "ttm_ebitda": (oi + da) if oi is not None and da is not None else None, "ttm_net_income": _t(rf, "net_income", end) if end else None, "ttm_fcf": fcf,
            "ttm_growth_pct": rev.get("ttm_growth_pct"), "fcf_margin_pct": (fcf / revv * 100) if fcf is not None and revv and revv > 0 else None, "annual_dilution_pct": dil,
            "financials_end": end, "annual_years": len(rev.get("annual") or []), "sic": sic}


def thesis(rev: dict, val: dict, r40: dict) -> dict:
    """Questions built from the computed figures (never from a model's opinion): what must be true, what would disprove it, what to research next."""
    must, disprove, nxt = [], [], []
    rd = (val or {}).get("reverse_dcf") or {}
    if rd.get("available"):
        must.append(f"Revenue growth has to start near {rd['implied_growth_pct']:.1f}% a year and fade toward the terminal rate for today's price to be justified at today's free-cash-flow margin "
                    f"(reported trailing growth: {rd['reported_ttm_growth_pct']:.1f}%).")
        disprove.append(f"Growth settling clearly below about {rd['implied_growth_pct']:.1f}% a year without a rising margin would argue the price already asks for too much.")
    for t in (val or {}).get("invalidators", [])[:1]:
        disprove.append(t)
    tr = rev.get("trend") or {}
    if tr.get("label") in ("accelerating", "decelerating"):
        must.append(f"The recent {tr['label']} in growth ({tr['latest_yoy_pct']:.1f}% against an earlier average of {tr['earlier_average_pct']:.1f}%) has to be explained by something durable, not timing.")
    if r40.get("applicable") and r40.get("available"):
        c = r40["current"]
        must.append(f"Rule of 40 (FCF basis) is {c['score']:.1f} ({c['growth_pct']:.1f}% growth + {c['margin_pct']:.1f}% free-cash-flow margin); a falling score would weaken the case.")
    sc = rev.get("share_count_change")
    if sc and sc["change_pct"] > 5:
        disprove.append(f"Diluted share count rose {sc['change_pct']:.1f}% ({sc['from']} to {sc['to']}): continued dilution erodes per-share value even when revenue grows.")
    nxt += ["Open the latest annual report and read the segment, geography and customer-concentration notes (not in structured data).",
            "Find recurring-revenue, retention and backlog disclosures, and separate organic growth from acquisitions and currency effects.",
            "Check stock-based compensation and any acquisitions or one-off cash flows inside the trailing twelve months.",
            "Compare with two or three similar companies side by side (peer comparison is not built into this page yet)."]
    return {"what_must_be_true": must or ["Not enough computed evidence to say what the price requires."], "what_would_disprove_it": disprove or ["Not enough computed evidence to name a specific test."], "research_next": nxt}


def assemble(rf: dict, sic, price, price_time: str | None, price_source: str | None, now: datetime | None = None, policy: dict | None = None, name: str | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    rev = analyze_revenue(rf, now.date())
    kind = sector_kind(sic)
    out = {"as_of": now.isoformat(), "company": {"name": name or rf.get("name"), "cik": rf.get("cik"), "sic": sic, "sector_kind": kind,
                                                  "special_sector_note": SPECIAL.get(kind)},
           "revenue": rev, "coverage": COVERAGE, "definitions": {"reported": "filed by the company for exactly that period", "derived": "a difference of two filed cumulative figures",
                                                              "calculated": "arithmetic done here, formula stated", "estimate": "model output under stated assumptions"}}
    if not rev.get("available"):
        out.update({"quality": {"available": False, "reason": rev["reason"]}, "rule_of_40": rule_of_40(rf, sic),
                    "valuation": {**V.EMPTY, "label": V.LABELS["none"], "label_key": "none", "reason": rev["reason"], "evidence": {"level": "insufficient", "checks": [], "limits": []}},
                    "thesis": thesis(rev, {}, {})})
        return out
    q = quality(rf)
    r40 = rule_of_40(rf, sic)
    vin = valuation_inputs(rf, sic, price, price_time, price_source, rev, now)
    val = V.assess(vin, policy, now)
    val["inputs"] = {k: v for k, v in vin.items() if k not in ("sic",)} | {"financials_end": vin["financials_end"].isoformat() if vin["financials_end"] else None}
    out.update({"quality": q, "rule_of_40": r40, "valuation": val, "thesis": thesis(rev, val, r40)})
    return out
