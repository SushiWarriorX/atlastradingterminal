"""Rule of 40 (software and SaaS companies): growth plus profitability, with every definition stated and never mixed.

Default, explicitly labelled: Rule of 40 (FCF basis) = TTM revenue growth % + TTM free-cash-flow margin %.
  TTM revenue growth = (TTM revenue now / TTM revenue one year earlier - 1) x 100, both from four consecutive quarters (the earlier one is the four quarters before).
  TTM FCF margin     = (TTM operating cash flow - TTM capital expenditures) / TTM revenue x 100, all from the same four quarters.
Capital expenditures are the payments for property and equipment the company files (reported as positive payments; the absolute value is subtracted). Capitalised software development costs
are NOT subtracted, because companies tag them inconsistently; when the company files such a line it is shown beside the score so the effect can be judged.
A score reaching 40 does not mean the stock is undervalued, and missing it does not disqualify a company. Outside software the measure is "Not applicable".
An EBITDA-basis variant (operating income plus depreciation and amortisation) is offered only as a separately labelled second measure; it is never substituted for the default.
"""
from __future__ import annotations

from datetime import date

from .facts import discrete_quarters, flow_facts, run, ttm
from .revenue import SOFTWARE_SIC, SPECIAL, growth_pct, sector_kind

THRESHOLD = 40.0


def _ttm_at(q_by_metric: dict, metric: str, end: date):
    r = ttm(q_by_metric[metric], end)
    return r["value"] if r else None


def score_at(q_by_metric: dict, end: date, basis: str = "fcf") -> dict:
    """Rule of 40 for the four quarters ending at `end`; each missing input gives a reason instead of a number."""
    rq = q_by_metric["revenue"]
    ends = sorted(rq)
    r8 = run(rq, 8, end)
    if not r8:
        return {"end": end.isoformat(), "available": False, "reason": "needs eight consecutive quarters of revenue (four for now and four for the comparison year)"}
    now_rev, prev_rev = sum(q["value"] for q in r8[4:]), sum(q["value"] for q in r8[:4])
    g, why = growth_pct(now_rev, prev_rev)
    if g is None:
        return {"end": end.isoformat(), "available": False, "reason": f"revenue growth is {why}"}
    if now_rev <= 0:
        return {"end": end.isoformat(), "available": False, "reason": "not meaningful: TTM revenue is zero or negative"}
    if basis == "fcf":
        ocf, cx = _ttm_at(q_by_metric, "operating_cash_flow", end), _ttm_at(q_by_metric, "capex", end)
        if ocf is None:
            return {"end": end.isoformat(), "available": False, "reason": "operating cash flow is missing for these four quarters"}
        if cx is None:
            return {"end": end.isoformat(), "available": False, "reason": "capital expenditures are missing for these four quarters (a missing figure is not treated as zero)"}
        m = (ocf - abs(cx)) / now_rev * 100
        label = "FCF basis"
        parts = {"ttm_operating_cash_flow": ocf, "ttm_capital_expenditures": abs(cx), "ttm_free_cash_flow": ocf - abs(cx)}
    else:
        oi, da = _ttm_at(q_by_metric, "operating_income", end), _ttm_at(q_by_metric, "da", end)
        if oi is None or da is None:
            return {"end": end.isoformat(), "available": False, "reason": "operating income or depreciation and amortisation is missing for these four quarters"}
        m = (oi + da) / now_rev * 100
        label = "EBITDA basis"
        parts = {"ttm_operating_income": oi, "ttm_depreciation_amortisation": da, "ttm_ebitda": oi + da}
    return {"end": end.isoformat(), "available": True, "basis": label, "growth_pct": g, "margin_pct": m, "score": g + m, "reaches_40": (g + m) >= THRESHOLD,
            "ttm_revenue": now_rev, "ttm_revenue_previous": prev_rev, **parts}


def rule_of_40(rf: dict, sic) -> dict:
    kind = sector_kind(sic)
    base = {"definition": "Rule of 40 (FCF basis) = TTM revenue growth % + TTM free-cash-flow margin %", "threshold": THRESHOLD,
            "caveat": "Reaching 40 does not mean a stock is undervalued, and missing it does not disqualify a company. Working-capital timing (for example annual upfront billing), stock-based compensation "
                      "(not subtracted from free cash flow), acquisitions and unusual cash flows can move the score; check them in the filings."}
    if kind in SPECIAL:
        return {**base, "applicable": False, "label": "Not applicable", "reason": f"This company is a {SPECIAL[kind]}.", "sector": kind}
    if kind != "software":
        return {**base, "applicable": False, "label": "Not applicable", "reason": "The Rule of 40 is a software and SaaS measure; it is not applied to other industries. See revenue quality, margins and cash conversion instead.", "sector": kind}
    qm = {m: discrete_quarters(flow_facts(rf, m)) for m in ("revenue", "operating_cash_flow", "capex", "operating_income", "da")}
    ends = sorted(qm["revenue"])
    if not ends:
        return {**base, "applicable": True, "available": False, "label": "N/A", "reason": "No quarterly revenue is on file.", "sector": kind}
    cur = score_at(qm, ends[-1], "fcf")
    hist = []
    for e in ends[-12:]:                                                  # the score at each of the latest quarter ends that have enough history
        h = score_at(qm, e, "fcf")
        if h.get("available"):
            hist.append({"end": h["end"], "score": h["score"], "growth_pct": h["growth_pct"], "margin_pct": h["margin_pct"], "reaches_40": h["reaches_40"]})
    alt = score_at(qm, ends[-1], "ebitda")
    out = {**base, "applicable": True, "sector": kind, "current": cur, "available": bool(cur.get("available")), "history": hist[-8:],
           "label": ("Reaches 40" if cur.get("reaches_40") else "Below 40") if cur.get("available") else "N/A",
           "ebitda_variant": {"label": "Rule of 40 (EBITDA basis): a separate measure, not the default", **alt},
           "peers": {"available": False, "reason": "Peer comparison needs the filings of comparable companies; add them to the comparison to see their scores side by side."}}
    if not cur.get("available"):
        out["reason"] = cur["reason"]
    cs = ttm(discrete_quarters(flow_facts(rf, "cap_software")), ends[-1])
    if cs:
        out["capitalised_software_ttm"] = cs["value"]
        out["capitalised_software_note"] = "This company also files capitalised software development costs; they are not subtracted in the score above, so the free-cash-flow margin is higher than if they were."
    return out
