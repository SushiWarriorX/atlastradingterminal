"""Fundamentals agent: adapts to the asset type and uses only supported data.

Stocks: revenue, earnings growth, margins, cash flow, balance sheet, valuation, next earnings date (ATLAS fundamentals service; Yahoo company data, unofficial).
ETFs:   objective, fees, size, holdings, concentration, underlying exposure (Yahoo fund data; concentration is computed here).
Crypto: token supply and dilution (CoinGecko), plus Bitcoin's protocol schedule computed in code from the block height (mempool.space). Token unlock schedules,
        governance and on-chain activity (other than Bitcoin's) are NOT available from any source used and are reported as missing.
Nothing is substituted: a metric that is unavailable or does not apply is said to be so.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from ...models import ProviderUnavailable
from .. import fmt
from ..assets import Asset
from ..exposure import exposure_for, phrase
from ..models import EventItem, Finding, Interpretation, Missing, Point, Source
from .common import Ctx, iso, mk_fact, unavailable

YAHOO = "Yahoo Finance company data (unofficial)"
YAHOO_FUND = "Yahoo Finance fund data (unofficial)"
CG = "CoinGecko (public API)"
MEMPOOL = "mempool.space (Bitcoin network)"
DEMO = "Demo fixture (synthetic, not real)"
STOCK_RULE = ("Four business-health checks, each uncalibrated rules of thumb: revenue growth above 0%, net margin above 0%, free cash flow above 0, debt/equity below 2. "
              "All available checks pass = supportive; two or more fail = cautious; otherwise mixed. At least two checks must be available. This is not a valuation call.")


class FundamentalsAgent:
    name = "fundamentals"

    async def run(self, ctx: Ctx) -> Finding:
        a = ctx.asset
        if a.type == "crypto":
            return await _crypto(ctx)
        if a.type == "etf":
            return await _etf(ctx)
        return await _stock(ctx)


# --- stocks ---------------------------------------------------------------------------------------------------------------------------------
async def _stock(ctx: Ctx) -> Finding:
    a, now = ctx.asset, ctx.now
    try:
        snap = await ctx.fundamentals.get(a.inst)
    except ProviderUnavailable as e:
        return unavailable("fundamentals", f"Company data unavailable ({e.message[:120]})", ctx.demo)
    except Exception as e:  # noqa: BLE001
        return unavailable("fundamentals", f"Company data failed ({type(e).__name__})", ctx.demo)
    if snap.get("quote_type") in ("ETF", "MUTUALFUND") and a.type == "stock":
        return await _etf(ctx)                                      # an unverified ticker turned out to be a fund
    v, prov = snap["values"], snap["prov"]
    demo = prov["provider"] == "demo"
    src = DEMO if demo else YAHOO
    asof = snap.get("financials_as_of")
    F = lambda key, label, val, disp, kind="reported", unit=None: mk_fact(key, label, val, disp, src, unit=unit, as_of=asof, kind=kind)
    facts = []
    spec = [("revenue", "Revenue (last 12 months)", fmt.big, "reported", None), ("revenue_growth_pct", "Revenue growth (latest quarter, year over year)", lambda x: fmt.pct(x, signed=True), "reported", "%"),
            ("earnings_growth_pct", "Earnings growth (latest quarter, year over year)", lambda x: fmt.pct(x, signed=True), "reported", "%"),
            ("gross_margin_pct", "Gross margin", fmt.pct, "reported", "%"), ("operating_margin_pct", "Operating margin", fmt.pct, "reported", "%"), ("profit_margin_pct", "Net margin", fmt.pct, "reported", "%"),
            ("free_cash_flow", "Free cash flow (last 12 months)", fmt.big, "reported", None), ("fcf_margin_pct", "Free cash flow margin", fmt.pct, "calculated", "%"),
            ("cash", "Cash", fmt.big, "reported", None), ("debt", "Total debt", fmt.big, "reported", None), ("debt_to_equity", "Debt / equity", fmt.times, "calculated", None),
            ("pe", "P/E (trailing)", fmt.times, "calculated", None), ("pe_forward", "P/E (forward, analyst estimates)", fmt.times, "calculated", None), ("ps", "Price / sales", fmt.times, "calculated", None),
            ("ev_ebitda", "EV / EBITDA", fmt.times, "calculated", None), ("market_cap", "Market cap", fmt.big, "reported", None)]
    for key, label, f, kind, unit in spec:
        if v.get(key) is not None:
            facts.append(F(key, label, round(v[key], 4), f(v[key]), kind, unit))
    nxt = snap.get("next_earnings_date")
    if nxt:
        facts.append(mk_fact("next_earnings", "Next earnings date (provider estimate)", nxt, nxt, src, kind="reported"))
    interp: list[Interpretation] = []
    g, nm, fcf, de = v.get("revenue_growth_pct"), v.get("profit_margin_pct"), v.get("free_cash_flow"), v.get("debt_to_equity")
    if g is not None or nm is not None:
        bits = []
        if g is not None:
            bits.append(f"revenue {'grew' if g >= 0 else 'shrank'} {fmt.pct(abs(g))} year over year in the latest quarter")
        if nm is not None:
            bits.append(f"the net margin is {fmt.pct(nm)}" + (" (the company is losing money)" if nm < 0 else ""))
        interp.append(Interpretation(text="Growth and profitability: " + ", and ".join(bits) + ".", based_on=[k for k in ("revenue_growth_pct", "profit_margin_pct") if v.get(k) is not None], timeframe="latest quarter / TTM"))
    if fcf is not None:
        interp.append(Interpretation(text=f"Cash flow: free cash flow was {fmt.big(fcf)} over the last twelve months ({'positive: the business funds itself' if fcf > 0 else 'negative: it is spending more cash than it generates'}).", based_on=["free_cash_flow"]))
    if v.get("debt") is not None and v.get("cash") is not None:
        net = v["debt"] - v["cash"]
        interp.append(Interpretation(text=f"Balance sheet: {fmt.big(v['cash'])} cash against {fmt.big(v['debt'])} of debt ({'net cash' if net < 0 else 'net debt of ' + fmt.big(net)})." + (f" Debt is {fmt.times(de)} equity." if de is not None else ""), based_on=["cash", "debt"] + (["debt_to_equity"] if de is not None else [])))
    pe, fpe, ps = v.get("pe"), v.get("pe_forward"), v.get("ps")
    if pe is not None or ps is not None:
        t = "Valuation: the stock trades at " + " and ".join(x for x in ((f"{pe:.1f}× trailing earnings" if pe is not None else None), (f"{ps:.1f}× sales" if ps is not None else None)) if x) + "."
        if pe is not None and fpe is not None:
            t += f" The forward P/E is {fpe:.1f}×, {'lower, which means analysts expect earnings to grow' if fpe < pe else 'higher, which means analysts expect earnings to shrink'}."
        interp.append(Interpretation(text=t, based_on=[k for k in ("pe", "pe_forward", "ps") if v.get(k) is not None], caveat="Signal has no peer or historical valuation data, so it does not call the stock cheap or expensive."))
    checks = {"revenue growth > 0%": None if g is None else g > 0, "net margin > 0%": None if nm is None else nm > 0, "free cash flow > 0": None if fcf is None else fcf > 0, "debt/equity < 2×": None if de is None else de < 2}
    avail = {k: ok for k, ok in checks.items() if ok is not None}
    failing = [k for k, ok in avail.items() if not ok]
    stance = "insufficient" if len(avail) < 2 else "supportive" if not failing else "cautious" if len(failing) >= 2 else "mixed"
    pts = _stock_points(a, v, snap, failing, avail, now)
    missing = [Missing(what=_label(k), why="the provider did not supply the inputs") for k in snap.get("missing", []) if k in ("revenue", "profit_margin_pct", "free_cash_flow", "debt_to_equity", "pe", "revenue_growth_pct")]
    for k, why in (snap.get("not_meaningful") or {}).items():
        if k in ("pe", "pe_forward") and v.get(k) is None:
            missing.append(Missing(what=_label(k), why=why))
    if not nxt:
        missing.append(Missing(what="Next earnings date", why="the provider did not supply one"))
    events = []
    if nxt:
        events.append(EventItem(id="earnings", title="Next earnings report (provider estimate)", date=nxt, kind="scheduled", note="Dates can change; confirm with the company."))
    takeaway = _stock_takeaway(a, v, stance, failing, nxt, now)
    limits = ["Company data is from Yahoo Finance's unofficial endpoints and lags filings; ratios are computed here from the raw figures.", "Check rules are rules of thumb, not a quality rating or a valuation call."] + [f for f in snap.get("flags", [])][:3]
    if prov.get("origin") == "stale" or prov.get("status") == "STALE":
        limits.append("The latest refresh failed: this is the last good snapshot (marked STALE).")
    sources = [Source(name=src, url=None if demo else f"https://finance.yahoo.com/quote/{a.inst.provider_symbol}", kind="data", as_of=asof, status=prov["status"], note=f"fetched {prov['fetched_at'][:16]} UTC")]
    return Finding(agent="fundamentals", status="ok" if len(facts) >= 6 else "partial", stance=stance, stance_rule=STOCK_RULE, takeaway=takeaway, facts=facts, interpretations=interp, events=events,
                   missing=missing, sources=sources, limitations=limits, points=pts, data_as_of=asof, demo=demo)


def _label(k: str) -> str:
    return {"revenue": "Revenue", "profit_margin_pct": "Net margin", "free_cash_flow": "Free cash flow", "debt_to_equity": "Debt / equity", "pe": "P/E (trailing)", "pe_forward": "P/E (forward)",
            "revenue_growth_pct": "Revenue growth"}.get(k, k)


def _days_to(nxt: str | None, now: datetime) -> int | None:
    try:
        return (date.fromisoformat(nxt) - now.date()).days if nxt else None
    except ValueError:
        return None


def _stock_takeaway(a, v, stance, failing, nxt, now) -> str:
    g, nm = v.get("revenue_growth_pct"), v.get("profit_margin_pct")
    bits = []
    if g is not None:
        bits.append(f"revenue {'up' if g >= 0 else 'down'} {fmt.pct(abs(g))} year over year")
    if nm is not None:
        bits.append(f"net margin {fmt.pct(nm)}")
    head = ("Business health checks look solid" if stance == "supportive" else "Several business health checks are weak" if stance == "cautious" else "Business health is mixed" if stance == "mixed" else "Not enough data to judge business health")
    d = _days_to(nxt, now)
    tail = f" Next earnings in {d} days." if d is not None and d >= 0 else ""
    return head + (": " + ", ".join(bits) if bits else "") + "." + tail


def _stock_points(a, v, snap, failing, avail, now) -> list[Point]:
    P: list[Point] = []
    add = lambda kind, text, prio, keys, dk, at=None: P.append(Point(kind=kind, text=text, agent="fundamentals", fact_keys=keys, priority=prio, dedupe_key=dk))
    g, nm, fcf = v.get("revenue_growth_pct"), v.get("profit_margin_pct"), v.get("free_cash_flow")
    if snap.get("financials_as_of"):
        add("changed", f"Latest reported quarter ended {snap['financials_as_of']}" + (f": revenue {fmt.pct(g, signed=True)} year over year." if g is not None else "."), 35, ["revenue_growth_pct"], "fund-quarter")
    if g is not None and g > 5 and nm is not None and nm > 0:
        add("supports", f"Revenue is growing ({fmt.pct(g, signed=True)} year over year) and the business is profitable (net margin {fmt.pct(nm)}).", 62, ["revenue_growth_pct", "profit_margin_pct"], "fund-growth")
    if fcf is not None and fcf > 0:
        add("supports", f"The business generates cash (free cash flow {fmt.big(fcf)}).", 45, ["free_cash_flow"], "fund-fcf")
    if v.get("debt") is not None and v.get("cash") is not None and v["cash"] > v["debt"]:
        add("supports", "More cash than debt (net cash balance sheet).", 40, ["cash", "debt"], "fund-netcash")
    if nm is not None and nm < 0:
        add("risk", f"The company is not profitable (net margin {fmt.pct(nm)}).", 70, ["profit_margin_pct"], "fund-loss")
    if fcf is not None and fcf < 0:
        add("risk", f"Free cash flow is negative ({fmt.big(fcf)}): the business is using more cash than it generates.", 66, ["free_cash_flow"], "fund-fcf-neg")
    if g is not None and g < 0:
        add("risk", f"Revenue is shrinking ({fmt.pct(g, signed=True)} year over year).", 68, ["revenue_growth_pct"], "fund-shrink")
    if v.get("debt_to_equity") is not None and v["debt_to_equity"] >= 2:
        add("risk", f"High leverage: debt is {fmt.times(v['debt_to_equity'])} equity.", 58, ["debt_to_equity"], "fund-debt")
    if v.get("pe") is not None and v["pe"] > 40:
        add("risk", f"A P/E of {v['pe']:.0f}× means the price already assumes strong growth: disappointments can hit hard.", 48, ["pe"], "fund-pe")
    for f in snap.get("flags", [])[:2]:
        if "may be out of date" in f:
            add("risk", f.capitalize() + ".", 42, [], "fund-stale")
    d = _days_to(snap.get("next_earnings_date"), now)
    if d is not None and d >= 0:
        add("watch", f"Next earnings report in {d} day{'s' if d != 1 else ''} ({snap['next_earnings_date']}, provider estimate).", 90 if d <= 14 else 60, ["next_earnings"], "fund-earnings")
    return P


# --- ETFs -----------------------------------------------------------------------------------------------------------------------------------
async def _etf(ctx: Ctx) -> Finding:
    from ..etf import normalize_etf
    a, now = ctx.asset, ctx.now
    if ctx.demo:
        from .. import fixtures
        raw, demo = fixtures.etf_raw(a), True
    else:
        demo = False
        try:
            raw = await ctx.etf.fetch(a.inst)
        except ProviderUnavailable as e:
            return unavailable("fundamentals", f"Fund data unavailable ({e.message[:120]})", False)
        except Exception as e:  # noqa: BLE001
            return unavailable("fundamentals", f"Fund data failed ({type(e).__name__})", False)
    n = normalize_etf(raw, now)
    src = DEMO if demo else YAHOO_FUND
    F = lambda key, label, val, disp, kind="reported", unit=None: mk_fact(key, label, val, disp, src, unit=unit, as_of=n["fetched_at"], kind=kind)
    facts, interp, pts = [], [], []
    if n["objective"]:
        facts.append(F("objective", "Objective (the fund's own description)", n["objective"], n["objective"]))
    if n["category"]:
        facts.append(F("category", "Category", n["category"], n["category"]))
    if n["family"]:
        facts.append(F("family", "Fund company", n["family"], n["family"]))
    er = n["expense_ratio_pct"]
    if er is not None:
        facts.append(F("expense_ratio_pct", "Expense ratio (yearly cost)", round(er, 4), f"{er:.2f}%", unit="%"))
        interp.append(Interpretation(text=f"Cost: the fund charges {er:.2f}% a year, about {fmt.price(er / 100 * 10000)} per year for every $10,000 invested.", based_on=["expense_ratio_pct"]))
        if er <= 0.2:
            pts.append(Point(kind="supports", agent="fundamentals", text=f"Low cost: {er:.2f}% a year.", fact_keys=["expense_ratio_pct"], priority=40, dedupe_key="etf-cost"))
        elif er >= 0.75:
            pts.append(Point(kind="risk", agent="fundamentals", text=f"Relatively high cost: {er:.2f}% a year.", fact_keys=["expense_ratio_pct"], priority=45, dedupe_key="etf-cost"))
    if n["aum"] is not None:
        facts.append(F("aum", "Total assets", n["aum"], fmt.big(n["aum"])))
    if n["yield_pct"] is not None:
        facts.append(F("yield_pct", "Distribution yield", round(n["yield_pct"], 3), f"{n['yield_pct']:.2f}%", unit="%"))
    for h in n["holdings"][:5]:
        facts.append(F(f"holding_{h['symbol']}", f"Top holding: {h['name'] or h['symbol']}", round(h["weight"], 2), f"{h['symbol']} {h['weight']:.1f}%", unit="%"))
    if n["top10_pct"] is not None:
        facts.append(F("top10_pct", "Largest 10 holdings, share of the fund", round(n["top10_pct"], 2), f"{n['top10_pct']:.0f}%", kind="calculated", unit="%"))
        interp.append(Interpretation(text=f"Concentration: the ten largest holdings are {n['top10_pct']:.0f}% of the fund ({n['concentration']})" + (f", and the largest alone is {n['top1_pct']:.1f}%" if n["top1_pct"] else "") + ". A more concentrated fund moves more with a few holdings.", based_on=["top10_pct"]))
        if n["top10_pct"] >= 50:
            pts.append(Point(kind="risk", agent="fundamentals", text=f"Concentrated: the ten largest holdings are {n['top10_pct']:.0f}% of the fund.", fact_keys=["top10_pct"], priority=60, dedupe_key="etf-conc"))
        elif n["top10_pct"] < 30:
            pts.append(Point(kind="supports", agent="fundamentals", text=f"Diversified: the ten largest holdings are only {n['top10_pct']:.0f}% of the fund.", fact_keys=["top10_pct"], priority=42, dedupe_key="etf-conc"))
    if n["sector_weights"]:
        top = ", ".join(f"{k} {v:.0f}%" for k, v in n["sector_weights"][:3])
        facts.append(F("sector_weights", "Largest sector exposures", top, top, kind="reported"))
    exp = exposure_for(a)
    interp.append(Interpretation(text=f"Underlying exposure: {phrase(exp.label)}. {exp.rationale}", based_on=[], caveat="Classified from the fund's ticker and name by fixed rules; check the fund's own documents."))
    missing = [Missing(what=w.replace("_", " ").capitalize(), why=why) for w, why in n["missing"]]
    limits = ["Fund data is from Yahoo Finance's unofficial endpoints and may be incomplete or out of date.", "Holdings shown are only the largest ones the provider lists; concentration is computed from them.",
              "Equity-style metrics (earnings, margins, cash flow) do not apply to funds."]
    sources = [Source(name=src, url=None if demo else f"https://finance.yahoo.com/quote/{a.inst.provider_symbol}", kind="data", as_of=n["fetched_at"], status="DEMO" if demo else "DELAYED")]
    bits = [f"{er:.2f}% a year" if er is not None else None, f"top 10 = {n['top10_pct']:.0f}% of assets ({n['concentration']})" if n["top10_pct"] is not None else None, fmt.big(n["aum"]) + " in assets" if n["aum"] else None]
    takeaway = (f"{exp.label}: " if exp.profile != "other" else "Fund: ") + (", ".join(b for b in bits if b) or "limited fund data available") + "."
    status = "partial" if len(n["missing"]) >= 2 else "ok"
    return Finding(agent="fundamentals", status=status, stance=None, stance_rule="ETF fundamentals are descriptive (cost, size, holdings). They do not point up or down, so no stance is given.", takeaway=takeaway,
                   facts=facts, interpretations=interp, missing=missing, sources=sources, limitations=limits, points=pts, data_as_of=n["fetched_at"], demo=demo)


# --- crypto ---------------------------------------------------------------------------------------------------------------------------------
async def _crypto(ctx: Ctx) -> Finding:
    from ..cryptodata import btc_protocol, normalize_coin
    a, now = ctx.asset, ctx.now
    coin = proto = None
    errors: list[str] = []
    if ctx.demo:
        from .. import fixtures
        coin, proto, demo = normalize_coin(fixtures.coin_raw(a), now), (btc_protocol(fixtures.btc_snapshot(), now) if a.symbol == "BTC" else None), True
    else:
        demo = False
        if a.coingecko_id and ctx.coingecko is not None:
            try:
                coin = normalize_coin(await ctx.coingecko.coin(a.coingecko_id), now)
            except ProviderUnavailable as e:
                errors.append(f"CoinGecko: {e.message[:100]}")
        else:
            errors.append("This token has no supply data source configured.")
        if a.symbol == "BTC" and ctx.mempool is not None:
            try:
                proto = btc_protocol(await ctx.mempool.snapshot(), now)
            except ProviderUnavailable as e:
                errors.append(f"mempool.space: {e.message[:100]}")
    if coin is None and proto is None:
        return unavailable("fundamentals", "Token data unavailable (" + "; ".join(errors)[:160] + ")", demo)
    src_c, src_p = (DEMO, DEMO) if demo else (CG, MEMPOOL)
    facts, interp, pts, sources = [], [], [], []
    if coin:
        F = lambda key, label, val, disp, kind="reported", unit=None: mk_fact(key, label, val, disp, src_c, unit=unit, as_of=coin["last_updated"] or coin["fetched_at"], kind=kind)
        if coin["circulating"] is not None:
            facts.append(F("circulating", "Circulating supply", coin["circulating"], fmt.num(coin["circulating"], 0) + f" {a.symbol}"))
        if coin["max"] is not None:
            facts.append(F("max_supply", "Maximum supply", coin["max"], fmt.num(coin["max"], 0) + f" {a.symbol}"))
        elif coin["total"] is not None:
            facts.append(F("total_supply", "Total supply (no fixed maximum reported)", coin["total"], fmt.num(coin["total"], 0) + f" {a.symbol}"))
        if coin["pct_of_max_circulating"] is not None:
            facts.append(F("pct_of_max", "Share of maximum supply in circulation", round(coin["pct_of_max_circulating"], 2), f"{coin['pct_of_max_circulating']:.1f}%", "calculated", "%"))
        if coin["market_cap"] is not None:
            facts.append(F("market_cap", "Market cap", coin["market_cap"], fmt.big(coin["market_cap"])))
        if coin["fdv"] is not None:
            facts.append(F("fdv", "Fully diluted value (if the whole maximum supply existed)", coin["fdv"], fmt.big(coin["fdv"])))
        if coin["fdv_to_mcap"] is not None:
            facts.append(F("fdv_to_mcap", "Fully diluted value / market cap", round(coin["fdv_to_mcap"], 3), fmt.times(coin["fdv_to_mcap"], 2), "calculated"))
            if coin["fdv_to_mcap"] > 1.25:
                un = (1 - 1 / coin["fdv_to_mcap"]) * 100
                interp.append(Interpretation(text=f"Dilution: about {un:.0f}% of the token's fully diluted value is not yet circulating. Future issuance or unlocks can add supply, but Signal has no unlock schedule for this token.", based_on=["fdv_to_mcap"], caveat="Whether new supply is sold depends on who holds it."))
                pts.append(Point(kind="risk", agent="fundamentals", text=f"About {un:.0f}% of the fully diluted value is not circulating yet: future supply can dilute holders.", fact_keys=["fdv_to_mcap"], priority=55, dedupe_key="crypto-dilution"))
            elif coin["fdv_to_mcap"] <= 1.05:
                pts.append(Point(kind="supports", agent="fundamentals", text="Nearly the whole maximum supply is already circulating, so there is little scheduled dilution.", fact_keys=["fdv_to_mcap"], priority=45, dedupe_key="crypto-dilution"))
        if coin["rank"]:
            facts.append(F("rank", "Market-cap rank (CoinGecko)", coin["rank"], f"#{coin['rank']}"))
        if coin["categories"]:
            facts.append(F("categories", "Categories", ", ".join(coin["categories"]), ", ".join(coin["categories"])))
        if coin["genesis_date"]:
            facts.append(F("genesis", "Launched", coin["genesis_date"], coin["genesis_date"]))
        if coin["description"]:
            facts.append(F("description", "What it is (CoinGecko description)", coin["description"], coin["description"]))
        if coin["commits_4w"] is not None:
            facts.append(F("commits_4w", "Developer commits, last 4 weeks (GitHub)", coin["commits_4w"], f"{coin['commits_4w']:.0f}"))
        sources.append(Source(name=src_c, url=None if demo else f"https://www.coingecko.com/en/coins/{a.coingecko_id}", kind="data", as_of=coin["last_updated"], status="DEMO" if demo else "DELAYED"))
    if proto:
        P = lambda key, label, val, disp, kind="calculated", unit=None: mk_fact(key, label, val, disp, src_p, unit=unit, as_of=proto["fetched_at"], kind=kind)
        facts += [P("btc_height", "Latest block height", proto["height"], f"{proto['height']:,}", "reported"), P("btc_subsidy", "Block reward (new coins per block)", proto["subsidy_btc"], f"{proto['subsidy_btc']:g} BTC"),
                  P("btc_supply", "Bitcoin issued so far (from the protocol schedule)", round(proto["supply_btc"], 2), fmt.num(proto["supply_btc"], 0) + " BTC"),
                  P("btc_pct_issued", "Share of the 21 million cap issued", round(proto["pct_issued"], 2), f"{proto['pct_issued']:.1f}%", unit="%"),
                  P("btc_issuance", "New supply per year, as a share of supply", round(proto["annual_issuance_pct"], 3), f"{proto['annual_issuance_pct']:.2f}%", unit="%"),
                  P("btc_halving", "Next halving (estimate at 10 minutes per block)", proto["halving_estimate"], f"~{proto['halving_estimate']} (in {proto['blocks_to_halving']:,} blocks)")]
        if proto["hashrate_ehs"] is not None:
            facts.append(P("btc_hashrate", "Network hash rate", round(proto["hashrate_ehs"], 1), f"{proto['hashrate_ehs']:.0f} EH/s", "reported"))
        if proto["fee_sat_vb"] is not None:
            facts.append(P("btc_fee", "Recommended fee (about 30 minutes)", proto["fee_sat_vb"], f"{proto['fee_sat_vb']:.0f} sat/vB", "reported"))
        interp.append(Interpretation(text=f"Issuance: Bitcoin's new supply is now {proto['annual_issuance_pct']:.2f}% a year, and {proto['pct_issued']:.1f}% of the 21 million cap exists. The block reward halves in about {proto['blocks_to_halving']:,} blocks (estimated {proto['halving_estimate']}).", based_on=["btc_issuance", "btc_pct_issued", "btc_halving"], caveat="Fixed by protocol rules; the halving date is an estimate that depends on block times."))
        pts.append(Point(kind="watch", agent="fundamentals", text=f"Next Bitcoin halving (block reward cut in half) is about {proto['blocks_to_halving']:,} blocks away, estimated {proto['halving_estimate']}.", fact_keys=["btc_halving"], priority=40, dedupe_key="btc-halving"))
        sources.append(Source(name=src_p, url=None if demo else "https://mempool.space/", kind="protocol", as_of=proto["fetched_at"], status="DEMO" if demo else "LIVE"))
    missing = [Missing(what="Token unlock and vesting schedule", why="no free data source is used for this; unlocks can change supply and are not shown"),
              Missing(what="Governance", why="not available from the sources used")]
    if a.symbol != "BTC":
        missing += [Missing(what="Protocol / network activity", why="on-chain activity is only available for Bitcoin here"), Missing(what="Issuance schedule", why="only Bitcoin's schedule is computed")]
    if coin:
        missing += [Missing(what=w.replace("_", " ").capitalize(), why=why) for w, why in coin["missing"] if w == "max_supply" and a.symbol != "BTC"]
    for e in errors:
        missing.append(Missing(what="Data source", why=e))
    limits = ["Crypto assets are not companies: earnings, margins and valuation ratios do not apply and are not shown.", "Supply figures come from a public aggregator and can differ between providers.",
              "The CoinGecko and mempool.space connections were written from their documented shapes and have not been verified against the live services; check their terms before redistributing the data."]
    if a.symbol == "BTC" and proto:
        takeaway = f"Bitcoin's supply is {proto['pct_issued']:.1f}% issued; new supply is {proto['annual_issuance_pct']:.2f}% a year and the next halving is estimated for {proto['halving_estimate']}."
    elif coin and coin["pct_of_max_circulating"] is not None:
        takeaway = f"{coin['pct_of_max_circulating']:.0f}% of the maximum supply is circulating" + (f"; fully diluted value is {coin['fdv_to_mcap']:.2f}× market cap." if coin["fdv_to_mcap"] else ".") + " Unlock schedule not available."
    elif coin and coin["circulating"] is not None:
        takeaway = f"{fmt.num(coin['circulating'], 0)} {a.symbol} circulating; no maximum supply reported. Unlock schedule not available."
    else:
        takeaway = "Only limited token data is available."
    return Finding(agent="fundamentals", status="partial" if errors else "ok", stance=None, stance_rule="Token fundamentals describe supply and issuance; they do not point up or down, so no stance is given.",
                   takeaway=takeaway, facts=facts, interpretations=interp, missing=missing, sources=sources, limitations=limits, points=pts, data_as_of=(coin or proto)["fetched_at"], demo=demo)
