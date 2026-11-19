"""Discover scoring: transparent, rule-based, no learned weights. Pure functions over facts that other modules computed.

Six factors, each scored 0-100 by a stated piecewise-linear scale, combined with fixed weights. A factor whose inputs are missing is left out and the weights of
the others are rescaled, so a missing number is never guessed; a stock needs at least five of the six factors to be ranked. The score orders candidates for
YOUR research. It is not a prediction, a rating or advice.
"""
from __future__ import annotations

WEIGHTS = {"growth": 0.25, "profitability": 0.20, "momentum": 0.20, "valuation": 0.15, "balance_sheet": 0.10, "liquidity": 0.10}
MIN_FACTORS = 5
MIN_DOLLAR_VOLUME = 10e6          # average daily dollar volume below this is not liquid enough to consider
MAX_PER_SECTOR = 2

SCALES = {
    "growth": "Latest fiscal-year revenue growth: 0% or less scores 0, 10% scores 50, 25% or more scores 100. When a 3-5 year growth rate exists the two are averaged.",
    "profitability": "60% operating margin (0% or less = 0, 5% = 40, 20% = 80, 30% or more = 100) plus 40% free-cash-flow margin (0% or less = 0, 5% = 50, 15% or more = 100).",
    "momentum": "50% six-month return (-20% = 0, 0% = 35, +20% = 70, +50% or more = 100), 25% price above its 50- and 200-day averages, 25% distance from the 52-week high (40% below = 0, 5% below or closer = 100).",
    "valuation": "Price divided by last fiscal year's diluted EPS: 15 or less scores 100, 25 = 70, 40 = 40, 60 = 15, 80 or more = 0. A loss scores 0.",
    "balance_sheet": "More cash than long-term debt scores 100; otherwise debt/equity 0.5 = 80, 1 = 60, 2 = 30, 3 or more = 0.",
    "liquidity": "Average daily dollar volume: $5M or less scores 0, $20M = 60, $100M or more = 100. Below $10M a stock is excluded.",
}


def interp(x: float | None, pts: list[tuple[float, float]]) -> float | None:
    if x is None:
        return None
    if x <= pts[0][0]:
        return pts[0][1]
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return pts[-1][1]


def factors(feat: dict, fin: dict | None) -> dict:
    """Each factor -> {score, inputs} or None when it cannot be computed. `feat` from scanner.features.compute, `fin` = {'last': year dict, 'cagr': float|None, 'pe': float|None}."""
    out: dict = {k: None for k in WEIGHTS}
    last = (fin or {}).get("last") or {}
    g = last.get("revenue_growth_pct")
    if g is not None:
        s = interp(g, [(0, 0), (10, 50), (25, 100)])
        cg = (fin or {}).get("cagr")
        if cg is not None:
            s = (s + interp(cg, [(0, 0), (10, 50), (25, 100)])) / 2
        out["growth"] = {"score": s, "inputs": {"revenue_growth_pct": g, "revenue_cagr_pct": cg}}
    om, fm = last.get("operating_margin_pct"), last.get("fcf_margin_pct")
    if om is not None and fm is not None:
        out["profitability"] = {"score": 0.6 * interp(om, [(0, 0), (5, 40), (20, 80), (30, 100)]) + 0.4 * interp(fm, [(0, 0), (5, 50), (15, 100)]), "inputs": {"operating_margin_pct": om, "fcf_margin_pct": fm}}
    pe = (fin or {}).get("pe")
    eps = last.get("eps_diluted")
    if eps is not None and feat.get("price"):
        out["valuation"] = {"score": 0.0 if eps <= 0 else interp(pe, [(15, 100), (25, 70), (40, 40), (60, 15), (80, 0)]), "inputs": {"pe": pe, "eps": eps}}
    nc, de = last.get("net_cash"), last.get("debt_to_equity")
    if nc is not None:
        out["balance_sheet"] = {"score": 100.0 if nc > 0 else (interp(de, [(0, 100), (0.5, 80), (1, 60), (2, 30), (3, 0)]) if de is not None else 0.0), "inputs": {"net_cash": nc, "debt_to_equity": de}}
    r6, a50, a200, d52 = feat.get("ret_126d"), feat.get("above_sma50"), feat.get("above_sma200"), feat.get("dist_52w_high_pct")
    if r6 is not None and a50 is not None and a200 is not None and d52 is not None:
        out["momentum"] = {"score": 0.5 * interp(r6, [(-20, 0), (0, 35), (20, 70), (50, 100)]) + 0.25 * (50 * a50 + 50 * a200) + 0.25 * interp(d52, [(-40, 0), (-20, 40), (-5, 100), (0, 100)]),
                           "inputs": {"ret_126d_pct": r6, "above_sma50": a50, "above_sma200": a200, "dist_52w_high_pct": d52}}
    dv = feat.get("dollar_volume_avg20")
    if dv is not None:
        out["liquidity"] = {"score": interp(dv, [(5e6, 0), (20e6, 60), (100e6, 100)]), "inputs": {"dollar_volume_avg20": dv}}
    return out


def total(f: dict) -> tuple[float | None, int]:
    have = {k: v for k, v in f.items() if v is not None}
    if len(have) < MIN_FACTORS:
        return None, len(have)
    w = sum(WEIGHTS[k] for k in have)
    return sum(WEIGHTS[k] * v["score"] for k, v in have.items()) / w, len(have)


def risks(feat: dict, fin: dict | None) -> list[str]:
    out = []
    last = (fin or {}).get("last") or {}
    pe = (fin or {}).get("pe")
    if last.get("eps_diluted") is not None and last["eps_diluted"] <= 0:
        out.append("Lost money in the last fiscal year, so earnings-based valuation does not apply.")
    elif pe is not None and pe >= 40:
        out.append(f"Expensive on earnings: the price is {pe:.0f}x last year's EPS, so growth has to keep delivering.")
    if feat.get("dist_sma50_pct") is not None and feat["dist_sma50_pct"] >= 20:
        out.append(f"Stretched: the price is {feat['dist_sma50_pct']:.0f}% above its 50-day average, so a pullback would not be unusual.")
    if feat.get("ret_126d") is not None and feat["ret_126d"] >= 60:
        out.append(f"Already up {feat['ret_126d']:.0f}% in six months; much of the move may be behind it.")
    if last.get("debt_to_equity") is not None and last["debt_to_equity"] >= 2:
        out.append(f"Heavily borrowed: long-term debt is {last['debt_to_equity']:.1f}x equity.")
    if last.get("operating_margin_pct") is not None and last["operating_margin_pct"] < 5:
        out.append(f"Thin operating margin ({last['operating_margin_pct']:.1f}%).")
    if last.get("revenue_growth_pct") is not None and last["revenue_growth_pct"] < 0:
        out.append("Revenue shrank in the last fiscal year.")
    if feat.get("dollar_volume_avg20") is not None and feat["dollar_volume_avg20"] < 30e6:
        out.append("Relatively thinly traded, so prices can move sharply on small orders.")
    out.append("Annual filings can be up to a year old; the latest quarter and any guidance are not included.")
    return out


def reasons(f: dict, feat: dict, fin: dict | None, sector_note: str | None) -> list[str]:
    last = (fin or {}).get("last") or {}
    cand = []
    if f["growth"] and f["growth"]["score"] >= 60:
        cand.append((f["growth"]["score"], f"Revenue grew {last['revenue_growth_pct']:.1f}% in the latest fiscal year" + (f" and about {fin['cagr']:.1f}% a year over the longer span." if fin.get("cagr") is not None else ".")))
    if f["profitability"] and f["profitability"]["score"] >= 60:
        cand.append((f["profitability"]["score"], f"Profitable: {last['operating_margin_pct']:.1f}% operating margin and {last['fcf_margin_pct']:.1f}% free-cash-flow margin."))
    if f["momentum"] and f["momentum"]["score"] >= 60:
        cand.append((f["momentum"]["score"], f"Price is up {feat['ret_126d']:.0f}% in six months, above its 50- and 200-day averages, {abs(feat['dist_52w_high_pct']):.0f}% from its 52-week high."))
    if f["valuation"] and f["valuation"]["score"] >= 60:
        cand.append((f["valuation"]["score"], f"Reasonably priced on earnings: {fin['pe']:.1f}x last year's EPS."))
    if f["balance_sheet"] and f["balance_sheet"]["score"] >= 80:
        cand.append((f["balance_sheet"]["score"], "Strong balance sheet: " + ("more cash than long-term debt." if (last.get("net_cash") or 0) > 0 else f"debt is {last['debt_to_equity']:.1f}x equity.")))
    cand.sort(key=lambda x: -x[0])
    out = [t for _, t in cand[:3]]
    if sector_note:
        out.append(sector_note)
    return out or ["Ranks well on the combined rules, with no single standout strength."]
