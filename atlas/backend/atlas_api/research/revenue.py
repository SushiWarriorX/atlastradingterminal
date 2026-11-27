"""Revenue-first analysis from filed figures (pure functions over the condensed SEC facts).

Every number says what kind it is: REPORTED (filed by the company for exactly that period), DERIVED (a difference of two filed cumulative figures) or CALCULATED (arithmetic here, formula stated).
Missing stays missing with a reason. Growth rates need a comparable period one year earlier; a base of zero or less gives "not meaningful", never a number.
Not available from SEC structured data and therefore not shown: revenue by segment or geography, organic versus acquired growth, currency effects, one-off items, customer concentration,
retention, backlog and management guidance. They are in the filing text, so every block links to the filing for reading.
"""
from __future__ import annotations

from datetime import date

from .facts import annual, discrete_quarters, filing_link, flow_facts, latest_instant, run, ttm

SECTOR_BY_SIC = [((6000, 6199), "bank"), ((6200, 6299), "financial"), ((6300, 6499), "insurer"), ((6500, 6599), "reit"), ((6700, 6799), "other_financial")]
SPECIAL = {"bank": "bank (use net interest margin, efficiency ratio, credit quality and book value; revenue and free cash flow are not comparable)",
           "financial": "broker or asset manager (use fee revenue, assets under management and return on equity; free cash flow is not comparable)",
           "insurer": "insurer (use combined ratio, premiums and book value; free cash flow is not comparable)",
           "reit": "real-estate company (use funds from operations and net asset value; free cash flow after capital spending understates property economics)",
           "other_financial": "financial vehicle such as a fund, trust or blank-check company (company-style revenue and cash-flow measures do not apply)"}
SOFTWARE_SIC = (7370, 7371, 7372, 7373, 7374)
ACCEL_PP = 1.0


def sector_kind(sic) -> str:
    try:
        n = int(sic)
    except (TypeError, ValueError):
        return "unknown"
    if n == 6798:
        return "reit"                                                     # real-estate investment trusts sit inside the broader 6700 range of financial vehicles
    for (lo, hi), kind in SECTOR_BY_SIC:
        if lo <= n <= hi:
            return kind
    return "software" if n in SOFTWARE_SIC else "standard"


def growth_pct(cur, prev):
    if cur is None or prev is None:
        return None, "a comparable earlier period is missing"
    if prev <= 0:
        return None, "not meaningful: the earlier figure is zero or negative"
    return (cur / prev - 1) * 100, None


def _src(cik, q: dict) -> dict:
    return {"form": q["form"], "filed": q["filed"], "link": filing_link(cik, q["accn"])}


def quarterly_table(rf: dict, metric: str, n: int = 8) -> tuple[list[dict], dict[date, dict]]:
    quarters = discrete_quarters(flow_facts(rf, metric))
    ends = sorted(quarters)
    rows = []
    shown = run(quarters, min(n, len(ends)), ends[-1]) if ends else None
    if ends and not shown:                                              # a gap in the filings: show the latest unbroken stretch
        for k in range(min(n, len(ends)), 0, -1):
            shown = run(quarters, k, ends[-1])
            if shown:
                break
    for q in shown or []:
        prior = next((p for e, p in quarters.items() if 350 <= (q["end"] - e).days <= 380), None)
        g, why = growth_pct(q["value"], prior["value"] if prior else None)
        rows.append({"period_start": q["start"].isoformat(), "period_end": q["end"].isoformat(), "value": q["value"], "basis": q["basis"], "yoy_pct": g, "yoy_note": why,
                     "yoy_vs": prior["end"].isoformat() if prior else None, "source": _src(rf.get("cik"), q)})
    return rows, quarters


def trend(rows: list[dict]) -> dict:
    ys = [r["yoy_pct"] for r in rows if r["yoy_pct"] is not None]
    rule = f"latest quarter's year-over-year growth versus the average of up to three earlier quarters; more than {ACCEL_PP:g} point above is accelerating, more than {ACCEL_PP:g} below is decelerating"
    if len(ys) < 2:
        return {"label": "unknown", "reason": "needs at least two quarters with a year-earlier comparison", "rule": rule}
    prior = ys[-4:-1]
    base = sum(prior) / len(prior)
    d = ys[-1] - base
    return {"label": "accelerating" if d > ACCEL_PP else "decelerating" if d < -ACCEL_PP else "steady", "latest_yoy_pct": ys[-1], "earlier_average_pct": base, "change_pp": d, "rule": rule}


def analyze_revenue(rf: dict, now: date | None = None) -> dict:
    now = now or date.today()
    cik = rf.get("cik")
    facts = flow_facts(rf, "revenue")
    if not facts:
        return {"available": False, "reason": "No US-GAAP revenue figure was found in the company's filings (banks, insurers and foreign filers often report differently).", "currency": "USD"}
    yrs = annual(facts)[-5:]
    all_yrs = annual(facts)
    ann = []
    for i, y in enumerate(yrs):
        prev = next((p for p in all_yrs if 350 <= (y["end"] - p["end"]).days <= 380), None)
        g, why = growth_pct(y["value"], prev["value"] if prev else None)
        ann.append({"period_start": y["start"].isoformat(), "period_end": y["end"].isoformat(), "value": y["value"], "basis": "reported (full fiscal year)", "growth_pct": g, "growth_note": why,
                    "source": {"form": y["form"], "filed": y["filed"], "link": filing_link(cik, y["accn"])}})
    qrows, quarters = quarterly_table(rf, "revenue", 8)
    cur = ttm(quarters)
    prev_ttm = ttm(quarters, run(quarters, 8, cur["end"])[3]["end"]) if cur and run(quarters, 8, cur["end"]) else None
    tg, tg_why = growth_pct(cur["value"] if cur else None, prev_ttm["value"] if prev_ttm else None)
    cg = None
    if len(yrs) >= 3 and yrs[0]["value"] > 0 and yrs[-1]["value"] > 0:
        n = (yrs[-1]["end"] - yrs[0]["end"]).days / 365.25
        if n >= 1.5:
            cg = {"from": yrs[0]["end"].isoformat(), "to": yrs[-1]["end"].isoformat(), "years": round(n, 1), "value_pct": ((yrs[-1]["value"] / yrs[0]["value"]) ** (1 / n) - 1) * 100,
                  "formula": "(last year / first year) ^ (1 / years) - 1 over the fiscal years shown"}
    # revenue per diluted share (annual): revenue divided by the weighted-average diluted share count for the same fiscal year
    sh = {a["end"]: a for a in annual(flow_facts(rf, "diluted_shares"))}
    per_share = []
    for y in yrs:
        s = sh.get(y["end"])
        per_share.append({"period_end": y["end"].isoformat(), "revenue_per_diluted_share": y["value"] / s["value"] if s and s["value"] > 0 else None, "diluted_shares": s["value"] if s else None})
    have = [p for p in per_share if p["diluted_shares"]]
    share_change = None
    if len(have) >= 2:
        share_change = {"from": have[0]["period_end"], "to": have[-1]["period_end"], "change_pct": (have[-1]["diluted_shares"] / have[0]["diluted_shares"] - 1) * 100,
                        "basis": "weighted-average diluted shares, fiscal years"}
    latest_end = max([ann[-1]["period_end"]] + ([qrows[-1]["period_end"]] if qrows else [])) if ann else (qrows[-1]["period_end"] if qrows else None)
    age = (now - date.fromisoformat(latest_end)).days if latest_end else None
    missing = []
    if len(ann) < 5:
        missing.append(f"only {len(ann)} fiscal years of revenue are on file (the request is five)")
    if len(qrows) < 8:
        missing.append(f"only {len(qrows)} consecutive quarters of revenue are on file (the request is eight)")
    if not cur:
        missing.append("trailing-twelve-month revenue needs four consecutive quarters")
    if not prev_ttm:
        missing.append("the earlier trailing-twelve-month figure needs eight consecutive quarters")
    return {"available": True, "currency": "USD", "units": "US dollars, as filed (not thousands)", "annual": ann, "quarterly": qrows,
            "ttm": {"value": cur["value"], "period_start": cur["start"].isoformat(), "period_end": cur["end"].isoformat(), "basis": cur["basis"], "quarters": [e.isoformat() for e in cur["quarters"]]} if cur else None,
            "ttm_previous": {"value": prev_ttm["value"], "period_end": prev_ttm["end"].isoformat()} if prev_ttm else None,
            "ttm_growth_pct": tg, "ttm_growth_note": tg_why, "cagr": cg, "trend": trend(qrows), "per_share": per_share, "share_count_change": share_change,
            "latest_period_end": latest_end, "age_days": age, "stale": bool(age is not None and age > 135), "missing": missing,
            "not_in_structured_data": ["revenue by segment or geography", "organic versus acquisition-driven growth", "currency effects and one-off items", "customer concentration and major contracts",
                                       "recurring revenue, retention and backlog", "management guidance"]}


def _ttm_val(rf, metric):
    q = discrete_quarters(flow_facts(rf, metric))
    return ttm(q), q


def quality(rf: dict) -> dict:
    """Revenue quality alongside margins, cash conversion, dilution and balance-sheet strength: trailing-twelve-month figures from the same four quarters."""
    rev, rq = _ttm_val(rf, "revenue")
    out: dict = {"available": bool(rev), "basis": "trailing twelve months: the same four consecutive quarters for every line" if rev else None, "rows": []}
    if not rev:
        out["reason"] = "four consecutive quarters of revenue are needed"
        return out
    end = rev["end"]

    def line(key, label, num, den, unit="%", note=None, positive_den=True):
        if num is None or den is None:
            out["rows"].append({"key": key, "label": label, "value": None, "unit": unit, "note": "an input is missing from the filings"})
        elif positive_den and den <= 0:
            out["rows"].append({"key": key, "label": label, "value": None, "unit": unit, "note": "not meaningful: the denominator is zero or negative"})
        else:
            out["rows"].append({"key": key, "label": label, "value": num / den * 100 if unit == "%" else num / den, "unit": unit, "note": note})

    def t(metric):
        r, _ = _ttm_val(rf, metric)
        return r["value"] if r and r["end"] == end else None
    gp, oi, ni, ocf, cx, sbc = t("gross_profit"), t("operating_income"), t("net_income"), t("operating_cash_flow"), t("capex"), t("sbc")
    fcf = None if ocf is None or cx is None else ocf - abs(cx)
    line("gross_margin", "Gross margin", gp, rev["value"])
    line("operating_margin", "Operating margin", oi, rev["value"], note="can be negative")
    line("fcf_margin", "Free cash flow margin", fcf, rev["value"], note="operating cash flow minus capital spending on property and equipment; capitalised software is not subtracted", positive_den=True)
    line("cash_conversion", "Cash conversion (operating cash flow / net income)", ocf, ni, unit="x", note="shown only when net income is positive")
    line("sbc_pct_revenue", "Stock-based compensation / revenue", sbc, rev["value"], note="a real cost to shareholders that free cash flow does not subtract")
    cash, debt, eq = latest_instant(rf, "cash", end), latest_instant(rf, "debt", end), latest_instant(rf, "equity", end)
    out["balance"] = {"cash": cash, "debt": debt, "equity": eq,
                      "net_cash": (cash["value"] - debt["value"]) if cash and debt else None,
                      "note": "debt here is the long-term debt line the company tags; leases and short-term borrowings may be excluded, so it can understate what is owed",
                      "as_of": max([x["end"] for x in (cash, debt, eq) if x], default=None)}
    cap = (eq["value"] + debt["value"] - cash["value"]) if eq and debt and cash else None
    line("pretax_return_on_capital", "Operating income / invested capital (pre-tax)", oi, cap, note="invested capital = equity + long-term debt - cash; a rough, pre-tax measure, not a full ROIC")
    out["ttm_period_end"] = end.isoformat()
    cs = t("cap_software")
    out["capitalised_software_ttm"] = cs
    return out
