"""Which unfamiliar companies are worth a closer look, and why. Scores order candidates for MY research; they are not ratings, predictions or advice.

Four factors, each 0 to 100, all computed from filed figures by fixed rules (the same input always gives the same score):
  growth (25%)              trailing revenue growth
  revenue quality (25%)     gross margin, free-cash-flow margin, growth consistency, stock-based compensation burden
  financial resilience (20%) positive free cash flow, net cash (or years of cash runway when burning cash), positive operating return on capital
  valuation interest (20%)  the valuation reading under stated assumptions, plus whether the price asks for less growth than the company reports
A factor that cannot be computed is left out and the rest are rescaled; three of four are required. Novelty is NOT a factor: it only decides what I have not already seen.

Weak evidence is excluded, not padded: a company needs eight quarters of revenue, a known growth rate, two quality measures and a total at or above the minimum. If fewer than the daily target pass,
fewer are shown. The pool is later narrowed by my filters and by what I have already seen, saved or dismissed, with at most two per sector so the list stays varied.
"""
from __future__ import annotations

from datetime import date

WEIGHTS = {"growth": 25, "quality": 25, "resilience": 20, "valuation": 20}
MIN_FACTORS = 3
MIN_TOTAL = 60.0
DEFAULT_TARGET = 5
MAX_PER_SECTOR = 2
MAX_PER_SIZE = 3


def interp(x, pts):
    if x is None:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return None


def _row(research: dict, key: str):
    return next((r for r in (research.get("quality") or {}).get("rows", []) if r["key"] == key), None)


def _val(research: dict, key: str):
    r = _row(research, key)
    return r["value"] if r else None


def factors(research: dict) -> dict:
    rev = research.get("revenue") or {}
    g = rev.get("ttm_growth_pct")
    f = {"growth": interp(g, [(0, 0), (10, 40), (25, 75), (40, 100)])}
    q = []
    gm, fm = _val(research, "gross_margin"), _val(research, "fcf_margin")
    if gm is not None:
        q.append(interp(gm, [(20, 20), (40, 60), (70, 100)]))
    if fm is not None:
        q.append(interp(fm, [(-10, 0), (0, 25), (10, 60), (20, 100)]))
    ann = [a["growth_pct"] for a in rev.get("annual") or [] if a.get("growth_pct") is not None]
    if len(ann) >= 3:
        q.append(100.0 * sum(1 for x in ann if x > 0) / len(ann))
    sbc = _val(research, "sbc_pct_revenue")
    if sbc is not None:
        q.append(interp(sbc, [(0, 100), (5, 100), (15, 50), (30, 0)]))
    f["quality"] = sum(q) / len(q) if len(q) >= 2 else None
    f["_quality_parts"] = len(q)
    bal = (research.get("quality") or {}).get("balance") or {}
    parts = []
    if fm is not None:
        parts.append(100.0 if fm > 0 else 0.0)
    nc, cash = bal.get("net_cash"), (bal.get("cash") or {}).get("value")
    ttm_fcf = (research.get("valuation") or {}).get("inputs", {}).get("ttm_fcf")
    if fm is not None and fm <= 0 and cash is not None and ttm_fcf is not None and ttm_fcf < 0:
        runway = cash / -ttm_fcf                                              # years of cash at the current burn
        parts.append(100.0 if runway >= 3 else 50.0 if runway >= 1.5 else 0.0)
    elif nc is not None:
        parts.append(100.0 if nc >= 0 else 40.0)
    roc = _val(research, "pretax_return_on_capital")
    if roc is not None:
        parts.append(100.0 if roc > 0 else 20.0)
    f["resilience"] = sum(parts) / len(parts) if len(parts) >= 2 else None
    v = research.get("valuation") or {}
    base = {"under": 90.0, "within": 60.0, "over": 25.0}.get(v.get("label_key"))
    rd = v.get("reverse_dcf") or {}
    if base is not None and rd.get("available") and rd.get("difference_pp") is not None and rd["difference_pp"] < -5:
        base = min(100.0, base + 10.0)                                       # the price asks for clearly less growth than the company reports
    f["valuation"] = base
    return f


def total(f: dict) -> tuple[float | None, int]:
    have = {k: v for k, v in f.items() if k in WEIGHTS and v is not None}
    if len(have) < MIN_FACTORS:
        return None, len(have)
    w = sum(WEIGHTS[k] for k in have)
    return sum(WEIGHTS[k] * v for k, v in have.items()) / w, len(have)


def evidence_gate(research: dict) -> tuple[bool, str | None]:
    rev = research.get("revenue") or {}
    if not rev.get("available"):
        return False, "no revenue in the filings"
    if len(rev.get("quarterly") or []) < 8:
        return False, "fewer than eight consecutive quarters of revenue"
    if rev.get("ttm_growth_pct") is None:
        return False, "trailing revenue growth is unknown"
    if rev.get("stale"):
        return False, "the latest filed quarter is stale"
    return True, None


def reasons_and_risks(research: dict, f: dict) -> tuple[list[str], list[str]]:
    rev, v, r40 = research.get("revenue") or {}, research.get("valuation") or {}, research.get("rule_of_40") or {}
    why, risks = [], []
    g = rev.get("ttm_growth_pct")
    if g is not None:
        why.append(f"Revenue grew {g:.1f}% over the last twelve months ({rev['ttm']['period_end']}), and its growth is {rev['trend']['label']}." if (rev.get("trend") or {}).get("label") != "unknown"
                   else f"Revenue grew {g:.1f}% over the last twelve months ({rev['ttm']['period_end']}).")
    fm, gm = _val(research, "fcf_margin"), _val(research, "gross_margin")
    if fm is not None:
        (why if fm > 0 else risks).append(f"Free-cash-flow margin is {fm:.1f}%." if fm > 0 else f"It is not generating free cash flow (margin {fm:.1f}%).")
    if gm is not None and gm >= 50:
        why.append(f"Gross margin is {gm:.0f}%, a sign of pricing power or a product-like business model.")
    if r40.get("applicable") and r40.get("available"):
        (why if r40["current"]["reaches_40"] else risks).append(f"Rule of 40 (FCF basis) is {r40['current']['score']:.1f}" + (" (reaches 40)." if r40["current"]["reaches_40"] else " (below 40)."))
    lab = v.get("label_key")
    if lab in ("under", "within"):
        why.append("Valuation under stated assumptions: " + v["label"].lower() + f" (evidence: {v['evidence']['level']}).")
    elif lab == "over":
        risks.append("Valuation under stated assumptions: potentially overvalued.")
    sc = rev.get("share_count_change")
    if sc and sc["change_pct"] > 10:
        risks.append(f"Diluted share count rose {sc['change_pct']:.0f}% ({sc['from']} to {sc['to']}).")
    sbc = _val(research, "sbc_pct_revenue")
    if sbc is not None and sbc > 15:
        risks.append(f"Stock-based compensation is {sbc:.0f}% of revenue, a real cost that free cash flow does not show.")
    nc = ((research.get("quality") or {}).get("balance") or {}).get("net_cash")
    if nc is not None and nc < 0:
        risks.append("Debt exceeds cash on the balance sheet (long-term debt line only).")
    if (rev.get("trend") or {}).get("label") == "decelerating":
        risks.append("Revenue growth is slowing.")
    if not risks:
        risks.append("No specific risk stands out in the filed figures; segment, customer and competitive risks are in the filing text.")
    return why, risks


def evaluate(research: dict) -> dict:
    """Score one researched company. Returns the score, the reasons, and either 'eligible' or the reason it was left out."""
    ok, why_not = evidence_gate(research)
    f = factors(research)
    t, n = total(f)
    out = {"factors": {k: (round(v, 1) if v is not None else None) for k, v in f.items() if k in WEIGHTS}, "factors_used": n, "score": round(t, 1) if t is not None else None}
    if not ok:
        return {**out, "eligible": False, "excluded_because": why_not}
    if t is None:
        return {**out, "eligible": False, "excluded_because": f"only {n} of 4 factors could be computed (3 are needed)"}
    if f["_quality_parts"] < 2:
        return {**out, "eligible": False, "excluded_because": "fewer than two revenue-quality measures are available"}
    if t < MIN_TOTAL:
        return {**out, "eligible": False, "excluded_because": f"score {t:.0f} is below the minimum of {MIN_TOTAL:.0f}"}
    why, risks = reasons_and_risks(research, f)
    best = max((k for k in WEIGHTS if f.get(k) is not None), key=lambda k: f[k])
    opp = {"growth": "Fast revenue growth", "quality": "Revenue quality: margins and cash generation", "resilience": "Financial resilience", "valuation": "Valuation looks interesting under stated assumptions"}[best]
    return {**out, "eligible": True, "why_selected": why, "risks": risks, "main_opportunity": opp, "main_risk": risks[0]}


def material_key(research: dict) -> str:
    """What counts as 'material new information' for a company already shown: a new filed quarter or a different valuation reading."""
    rev, v = research.get("revenue") or {}, research.get("valuation") or {}
    return f"{(rev.get('ttm') or {}).get('period_end')}|{v.get('label_key')}"


def pick(pool: list[dict], target: int = DEFAULT_TARGET, max_per_sector: int = MAX_PER_SECTOR, max_per_size: int = MAX_PER_SIZE) -> tuple[list[dict], list[dict]]:
    """Best first, at most two per sector and three per size group. Returns (chosen, skipped for variety)."""
    chosen, skipped = [], []
    per_sec: dict = {}
    per_size: dict = {}
    for c in sorted(pool, key=lambda x: (-x["score"], x["symbol"])):
        sec, sz = c.get("sector") or "(unclassified)", c.get("size_bucket")
        if len(chosen) >= target:
            break
        if per_sec.get(sec, 0) >= max_per_sector or per_size.get(sz, 0) >= max_per_size:
            skipped.append({"symbol": c["symbol"], "reason": f"kept the list varied (limit per {'sector' if per_sec.get(sec, 0) >= max_per_sector else 'size group'})"})
            continue
        chosen.append(c)
        per_sec[sec] = per_sec.get(sec, 0) + 1
        per_size[sz] = per_size.get(sz, 0) + 1
    return chosen, skipped
