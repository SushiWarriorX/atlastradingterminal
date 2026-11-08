"""What does today's price imply? A transparent valuation built in code from stated assumptions (pure functions).

Nothing here is a forecast, a price target or advice. Every assumption is visible in the output and configurable in POLICY; every scenario is derived from the company's OWN latest figures by a
rule written down here, not chosen by a person or a language model. The answer is a label under those assumptions, together with how good the evidence is and what would invalidate it.

Methods, each with the conditions under which it is meaningful:
  * Enterprise value (EV) = price x diluted shares + debt - cash.   EV/revenue, EV/gross profit (when positive), EV/EBITDA (only when EBITDA is positive), P/E (only when earnings are positive),
    free-cash-flow yield (free cash flow / market value).
  * Scenario DCF (discounted free cash flow), only when free cash flow is positive: revenue growth fades linearly from the starting rate to the terminal rate over the forecast years, the free-cash-flow
    margin moves linearly to its scenario target, cash flows are discounted at one rate, a terminal value closes the model, then debt and cash adjust the equity value and the per-share value is
    computed on today's diluted shares grown by the dilution assumption.
  * Reverse DCF: the constant growth rate the price requires over the forecast years, holding today's margin.
Not built yet (so never claimed): comparison with peers and with the company's own historical multiples, sector-specific methods for banks, insurers and REITs.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from .revenue import SPECIAL, sector_kind

POLICY = {
    "discount_rate_pct": 10.0, "terminal_growth_pct": 2.5, "years": 5,
    "band_pct": 20.0,                                    # base-case value +/- this share is "within the estimated fair-value range"
    "bear": {"growth_factor": 0.5, "margin_shift_pp": -4.0, "extra_dilution_pp": 1.0},
    "base": {"growth_factor": 1.0, "margin_shift_pp": 0.0, "extra_dilution_pp": 0.0},
    "bull": {"growth_factor": 1.3, "margin_shift_pp": 3.0, "extra_dilution_pp": 0.0},
    "max_start_growth_pct": 40.0,                        # a starting growth rate above this is capped: very fast growth rarely persists
    "min_start_growth_pct": 0.0,                         # a shrinking company is modelled as flat at the start, not shrinking forever
    "max_bull_to_bear": 3.0,                             # if the bull value is more than this multiple of the bear value the range is too wide to call
    "stale_price_hours": 36, "stale_financials_days": 135,
    "min_evidence": "moderate",
}
LEVELS = ["insufficient", "weak", "moderate", "strong"]
LABELS = {"under": "Potentially undervalued under these assumptions", "within": "Within estimated fair-value range", "over": "Potentially overvalued under these assumptions",
          "none": "Insufficient evidence"}


def _p(policy, k):
    return policy[k]


def dcf(rev0: float, m0_pct: float, g_start_pct: float, g_term_pct: float, m_target_pct: float, r_pct: float, years: int, debt: float, cash: float, shares: float, dilution_pct: float) -> dict | None:
    """Per-share value of a free-cash-flow model. Returns None when the discount rate does not exceed terminal growth by at least 0.5 points or an input is unusable."""
    r, gt = r_pct / 100, g_term_pct / 100
    if rev0 <= 0 or shares <= 0 or r - gt < 0.005 or years < 2:
        return None
    rev, pv, path = rev0, 0.0, []
    for t in range(1, years + 1):
        g = (g_start_pct + (g_term_pct - g_start_pct) * (t - 1) / (years - 1)) / 100
        rev *= 1 + g
        m = (m0_pct + (m_target_pct - m0_pct) * t / years) / 100
        fcf = rev * m
        pv += fcf / (1 + r) ** t
        path.append({"year": t, "growth_pct": g * 100, "revenue": rev, "fcf_margin_pct": m * 100, "fcf": fcf})
    tv = path[-1]["fcf"] * (1 + gt) / (r - gt)
    pv_tv = tv / (1 + r) ** years
    ev = pv + pv_tv
    equity = ev - debt + cash
    shares_end = shares * (1 + dilution_pct / 100) ** years
    return {"ev": ev, "equity": equity, "per_share": equity / shares_end, "terminal_share_of_ev_pct": pv_tv / ev * 100 if ev > 0 else None, "path": path, "shares_end": shares_end}


def _scenario(name: str, inp: dict, policy: dict, g0: float, m0: float, dil0: float) -> dict | None:
    s = policy[name]
    g_start = min(max(g0 * s["growth_factor"], policy["min_start_growth_pct"]), policy["max_start_growth_pct"] * max(s["growth_factor"], 1.0))
    m_t = m0 + s["margin_shift_pp"]
    dil = dil0 + s["extra_dilution_pp"]
    d = dcf(inp["ttm_revenue"], m0, g_start, policy["terminal_growth_pct"], m_t, policy["discount_rate_pct"], policy["years"], inp["debt"], inp["cash"], inp["shares"], dil)
    if d is None:
        return None
    return {"name": name, "assumptions": {"start_growth_pct": g_start, "terminal_growth_pct": policy["terminal_growth_pct"], "fcf_margin_start_pct": m0, "fcf_margin_end_pct": m_t,
                                         "discount_rate_pct": policy["discount_rate_pct"], "years": policy["years"], "annual_dilution_pct": dil},
            "fair_value_per_share": d["per_share"], "equity_value": d["equity"], "enterprise_value": d["ev"], "terminal_share_of_ev_pct": d["terminal_share_of_ev_pct"], "path": d["path"]}


def multiples(inp: dict) -> list[dict]:
    """Valuation ratios with the reason when one is not meaningful (an earnings multiple is never applied to negative earnings)."""
    out = []
    price, sh = inp["price"], inp["shares"]
    mcap = price * sh
    ev = mcap + inp["debt"] - inp["cash"] if inp.get("debt") is not None and inp.get("cash") is not None else None

    def add(key, label, value, basis, note=None):
        out.append({"key": key, "label": label, "value": value, "basis": basis, "note": note})
    rev, gp, ebitda, ni, fcf = inp.get("ttm_revenue"), inp.get("ttm_gross_profit"), inp.get("ttm_ebitda"), inp.get("ttm_net_income"), inp.get("ttm_fcf")
    add("market_value", "Market value (diluted)", mcap, "price x diluted shares")
    add("enterprise_value", "Enterprise value", ev, "market value + debt - cash", None if ev is not None else "debt or cash is missing from the filings")
    add("ev_revenue", "EV / revenue", ev / rev if ev is not None and rev and rev > 0 else None, "enterprise value / TTM revenue", None if ev is not None and rev and rev > 0 else "needs enterprise value and positive revenue")
    add("ev_gross_profit", "EV / gross profit", ev / gp if ev is not None and gp and gp > 0 else None, "enterprise value / TTM gross profit", None if ev is not None and gp and gp > 0 else "not meaningful: gross profit is missing or not positive")
    add("ev_ebitda", "EV / EBITDA", ev / ebitda if ev is not None and ebitda and ebitda > 0 else None, "enterprise value / TTM EBITDA (operating income + depreciation and amortisation)",
        None if ev is not None and ebitda and ebitda > 0 else "not meaningful: EBITDA is missing or not positive")
    pe = price / (ni / sh) if ni and ni > 0 and sh > 0 else None
    add("pe", "P/E", pe, "price / (TTM net income / diluted shares)", None if pe is not None else "not meaningful: earnings are missing or not positive")
    fy = fcf / mcap * 100 if fcf is not None and mcap > 0 else None
    add("fcf_yield_pct", "Free-cash-flow yield (%)", fy, "TTM free cash flow / market value x 100",
        "free cash flow is missing" if fy is None else ("negative: the company consumes cash" if fy < 0 else None))
    return out


def evidence(inp: dict, policy: dict, now: datetime) -> dict:
    checks = []

    def chk(key, ok, text_ok, text_bad, essential=True):
        checks.append({"key": key, "ok": bool(ok), "essential": essential, "text": text_ok if ok else text_bad})
    age_h = (now - datetime.fromisoformat(inp["price_time"])).total_seconds() / 3600 if inp.get("price_time") else None
    chk("price_fresh", age_h is not None and age_h <= policy["stale_price_hours"], "The price is recent.", "The price is missing or older than the freshness limit; a stale price makes the comparison unreliable.")
    fin_age = (now.date() - inp["financials_end"]).days if inp.get("financials_end") else None
    chk("financials_fresh", fin_age is not None and fin_age <= policy["stale_financials_days"], "The latest filed quarter is recent.", "The latest filed quarter is older than the freshness limit.")
    chk("ttm_growth", inp.get("ttm_growth_pct") is not None, "Trailing revenue growth is known from eight consecutive quarters.", "Trailing revenue growth is unknown: eight consecutive quarters are not on file.")
    chk("fcf_positive", inp.get("fcf_margin_pct") is not None and inp["fcf_margin_pct"] > 0, "Free cash flow is positive, so a cash-flow model is defensible.",
        "Free cash flow is missing or not positive, so a cash-flow model would rest entirely on an assumed turn to profit.")
    chk("balance_sheet", inp.get("debt") is not None and inp.get("cash") is not None, "Cash and debt are on file.", "Cash or debt is missing, so enterprise value and equity value are unreliable.")
    chk("shares", bool(inp.get("shares")) and inp.get("shares_reliable", True), "The diluted share count is on file.", inp.get("shares_note") or "The diluted share count is missing or unreliable.")
    chk("history", (inp.get("annual_years") or 0) >= 3, "Three or more fiscal years of revenue are on file.", "Fewer than three fiscal years of revenue are on file.", essential=False)
    bad = [c for c in checks if c["essential"] and not c["ok"]]
    level = "strong" if not bad and all(c["ok"] for c in checks) and inp.get("methods_agree") else "moderate" if not bad else "weak" if len(bad) <= 2 and checks[3]["ok"] else "insufficient"
    return {"level": level, "checks": checks, "limits": ["Only one valuation method (a scenario DCF) is built, so no independent method can confirm it: the level cannot reach 'strong'.",
                                                          "Peer multiples and the company's own historical multiples are not built yet."]}


def _swing(base_fn, label, lo_arg, hi_arg) -> dict:
    lo, hi = base_fn(lo_arg), base_fn(hi_arg)
    return {"input": label, "low_value": lo, "high_value": hi, "swing": abs((hi or 0) - (lo or 0))} if lo is not None and hi is not None else None


def assess(inp: dict, policy: dict | None = None, now: datetime | None = None) -> dict:
    """The full valuation answer. `inp` keys: price, price_time (ISO), price_source, shares, shares_note, shares_reliable, cash, debt, ttm_revenue, ttm_gross_profit, ttm_ebitda, ttm_net_income,
    ttm_fcf, ttm_growth_pct, fcf_margin_pct, annual_dilution_pct, financials_end (date), annual_years, sic."""
    policy = {**POLICY, **(policy or {})}
    now = now or datetime.now(timezone.utc)
    kind = sector_kind(inp.get("sic"))
    base = {"policy": policy, "price": inp.get("price"), "price_time": inp.get("price_time"), "price_source": inp.get("price_source"),
            "caveat": "A model-dependent estimate under stated assumptions: not a forecast, price target or advice. Different reasonable assumptions give different answers."}
    if kind in SPECIAL:
        return {**base, "label": LABELS["none"], "label_key": "none", "reason": f"This company is a {SPECIAL[kind]}. Sector-specific valuation methods are not built yet, so no verdict is given.", "sector": kind,
                "evidence": {"level": "insufficient", "checks": [], "limits": []}}
    if not inp.get("price") or inp["price"] <= 0 or not inp.get("shares") or inp["shares"] <= 0:
        return {**base, "label": LABELS["none"], "label_key": "none", "reason": "A current price and a diluted share count are both needed.", "evidence": {"level": "insufficient", "checks": [], "limits": []}}
    ev = evidence(inp, policy, now)
    mult = multiples(inp)
    out = {**base, "sector": kind, "multiples": mult, "evidence": ev, "scenarios": [], "reverse_dcf": None, "sensitivity": None, "influence": [], "invalidators": [],
           "methods": {"multiples": "shown above where meaningful", "dcf": None, "peers": {"available": False, "reason": "Peer comparison is not built yet; a lower multiple alone would not prove cheapness."},
                       "own_history": {"available": False, "reason": "The company's own historical multiples need historical prices and share counts; not built yet."}}}
    m0, g0 = inp.get("fcf_margin_pct"), inp.get("ttm_growth_pct")
    if inp.get("ttm_revenue") is None or inp["ttm_revenue"] <= 0 or m0 is None or m0 <= 0 or g0 is None or inp.get("debt") is None or inp.get("cash") is None:
        why = []
        if m0 is None or (m0 is not None and m0 <= 0):
            why.append("free cash flow is missing or not positive")
        if g0 is None:
            why.append("trailing revenue growth is unknown")
        if inp.get("debt") is None or inp.get("cash") is None:
            why.append("cash or debt is missing")
        out["methods"]["dcf"] = {"available": False, "reason": "A DCF is not defensible here: " + "; ".join(why or ["a required input is missing"]) + "."}
        return {**out, "label": LABELS["none"], "label_key": "none", "reason": out["methods"]["dcf"]["reason"] + " No fair-value range is given."}
    dil0 = max(0.0, inp.get("annual_dilution_pct") or 0.0)
    shared = {"ttm_revenue": inp["ttm_revenue"], "debt": inp["debt"], "cash": inp["cash"], "shares": inp["shares"]}
    sc = {n: _scenario(n, shared, policy, g0, m0, dil0) for n in ("bear", "base", "bull")}
    if any(v is None for v in sc.values()):
        out["methods"]["dcf"] = {"available": False, "reason": "The discount rate must exceed terminal growth by at least 0.5 points."}
        return {**out, "label": LABELS["none"], "label_key": "none", "reason": out["methods"]["dcf"]["reason"]}
    out["methods"]["dcf"] = {"available": True, "description": "Scenario DCF on free cash flow; see each scenario's assumptions."}
    price = inp["price"]
    for n in ("bear", "base", "bull"):
        v = sc[n]
        v["upside_pct"] = (v["fair_value_per_share"] / price - 1) * 100
        out["scenarios"].append(v)
    bear, basev, bull = (sc[n]["fair_value_per_share"] for n in ("bear", "base", "bull"))
    out["fair_value_range"] = {"low": min(bear, basev, bull), "base": basev, "high": max(bear, basev, bull)}

    # reverse DCF: the constant growth rate the price requires
    def ps_at(g):
        d = dcf(inp["ttm_revenue"], m0, g, policy["terminal_growth_pct"], m0, policy["discount_rate_pct"], policy["years"], inp["debt"], inp["cash"], inp["shares"], dil0)
        return d["per_share"] if d else None
    lo, hi = -20.0, 100.0
    f_lo, f_hi = ps_at(lo), ps_at(hi)
    if f_lo is not None and f_hi is not None and f_lo <= price <= f_hi:
        for _ in range(60):
            mid = (lo + hi) / 2
            if ps_at(mid) < price:
                lo = mid
            else:
                hi = mid
        out["reverse_dcf"] = {"available": True, "implied_growth_pct": (lo + hi) / 2, "reported_ttm_growth_pct": g0, "difference_pp": (lo + hi) / 2 - g0,
                              "reading": "Starting growth the price requires if growth then fades to the terminal rate over the forecast years with today's free-cash-flow margin held (a constant-margin DCF)."}
    else:
        out["reverse_dcf"] = {"available": False, "reason": "The price cannot be matched by starting growth between -20% and 100% under these assumptions."}

    # sensitivity grid and ranking of inputs by how much they move the base value
    def base_fv(r=None, g=None, gt=None, m=None):
        d = dcf(inp["ttm_revenue"], m0, g if g is not None else min(max(g0, policy["min_start_growth_pct"]), policy["max_start_growth_pct"]), gt if gt is not None else policy["terminal_growth_pct"],
                m if m is not None else m0, r if r is not None else policy["discount_rate_pct"], policy["years"], inp["debt"], inp["cash"], inp["shares"], dil0)
        return d["per_share"] if d else None
    g_start = sc["base"]["assumptions"]["start_growth_pct"]
    out["sensitivity"] = {"rows": "discount rate (%)", "cols": "starting revenue growth (%)", "discount_rates": [policy["discount_rate_pct"] + d for d in (-2, -1, 0, 1, 2)],
                          "growths": [g_start * f for f in (0.5, 0.75, 1.0, 1.25, 1.5)],
                          "values": [[base_fv(r=policy["discount_rate_pct"] + d, g=min(g_start * f, 100)) for f in (0.5, 0.75, 1.0, 1.25, 1.5)] for d in (-2, -1, 0, 1, 2)], "unit": "base-case fair value per share"}
    inf = [_swing(lambda x: base_fv(r=x), "discount rate +/- 1 point", policy["discount_rate_pct"] - 1, policy["discount_rate_pct"] + 1),
           _swing(lambda x: base_fv(gt=x), "terminal growth +/- 1 point", policy["terminal_growth_pct"] - 1, policy["terminal_growth_pct"] + 1),
           _swing(lambda x: base_fv(g=x), "starting revenue growth +/- 5 points", max(g_start - 5, 0), g_start + 5),
           _swing(lambda x: base_fv(m=x), "free-cash-flow margin +/- 3 points", m0 - 3, m0 + 3)]
    out["influence"] = sorted([i for i in inf if i], key=lambda i: -i["swing"])

    # what would invalidate it: the margin at which the base case just equals the price
    k = (sc["base"]["enterprise_value"] / m0) if m0 else None
    shares_eff = sc["base"]["equity_value"] / basev if basev else None
    if k and shares_eff:
        m_even = ((price * shares_eff) - (inp["cash"] - inp["debt"])) / k
        out["invalidators"].append(f"If the free-cash-flow margin stayed near {m_even:.1f}% instead of {m0:.1f}% (growth as in the base case), the base-case value would equal today's price.")
    if out["reverse_dcf"].get("available"):
        out["invalidators"].append(f"The price requires starting growth of about {out['reverse_dcf']['implied_growth_pct']:.1f}% a year; reported trailing growth is {g0:.1f}%. If growth settles clearly below the required rate, an undervalued reading would not hold.")
    out["invalidators"].append("A restatement, a large acquisition or a one-off cash flow in the trailing twelve months would change the starting figures; read the filings behind them.")

    # classification under the visible policy
    bp = policy["band_pct"]
    band = bp / 100
    ratio = max(bear, basev, bull) / min(bear, basev, bull) if min(bear, basev, bull) > 0 else None
    need = LEVELS.index(policy["min_evidence"])
    if LEVELS.index(ev["level"]) < need:
        key, reason = "none", f"Evidence quality is {ev['level']} (the policy needs at least {policy['min_evidence']}): " + "; ".join(c["text"] for c in ev["checks"] if c["essential"] and not c["ok"])
    elif min(bear, basev, bull) <= 0 or (ratio is not None and ratio > policy["max_bull_to_bear"]):
        key, reason = "none", "The bear-to-bull range is too wide (or not positive) to call: the assumptions disagree materially."
    elif price < bear or (price <= basev * (1 - band) and price <= bull):
        key, reason = "under", "Price is below even the bear case." if price < bear else f"Price is at least {bp:g}% below the base case."
    elif price > bull or price >= basev * (1 + band):
        key, reason = "over", "Price is above even the bull case." if price > bull else f"Price is at least {bp:g}% above the base case."
    else:
        key, reason = "within", f"Price is within {bp:g}% of the base case."
    me, mb = policy["min_evidence"], policy["max_bull_to_bear"]
    out["classification_rule"] = (f"Potentially undervalued if the price is below the bear case or at least {bp:g}% below the base case; potentially overvalued if above the bull case or at least "
                                  f"{bp:g}% above the base case; otherwise within the range. No verdict when evidence quality is below {me} or the bear-to-bull ratio exceeds {mb:g}.")
    return {**out, "label": LABELS[key], "label_key": key, "reason": reason}
