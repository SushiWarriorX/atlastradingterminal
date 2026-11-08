"""The network side of company research: SEC filings (official) plus a price from the existing fundamentals service, handed to the pure assembler.

Every failure is said in words and keeps whatever else is available; nothing is invented. Demo mode shows no company figures because made-up filings would look real.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..models import ProviderUnavailable
from . import valuation as V
from .service import assemble

POLICY_LIMITS = {"discount_rate_pct": (6.0, 20.0), "terminal_growth_pct": (0.0, 4.0), "band_pct": (5.0, 50.0), "years": (3, 10)}


def clean_policy(raw: dict | None) -> dict:
    """Only known keys, only inside sane limits; anything else is ignored rather than trusted."""
    out = {}
    for k, (lo, hi) in POLICY_LIMITS.items():
        v = (raw or {}).get(k)
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if lo <= x <= hi:
            out[k] = int(x) if k == "years" else x
    return out


class FundamentalResearch:
    def __init__(self, edgar, fundamentals, demo: bool = False):
        self.edgar, self.fundamentals, self.demo = edgar, fundamentals, demo

    async def filing_research(self, symbol: str, price, price_time, price_source, now: datetime | None = None, policy: dict | None = None) -> dict:
        """The full analysis for one ticker with a price the caller already has. Returns {'available': False, 'reason': ...} when the filings cannot be read."""
        now = now or datetime.now(timezone.utc)
        base = {"symbol": symbol, "as_of": now.isoformat(), "demo": self.demo, "errors": [], "default_policy": V.POLICY}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: filing-based research is not shown because made-up company figures would look real."}
        if not self.edgar.enabled:
            return {**base, "available": False, "reason": "SEC filings are off: ATLAS_SEC_CONTACT is not set. The SEC requires a contact email in the request; set it as an environment setting on the machine that runs "
                                                           "ATLAS (never in the repository) and restart."}
        try:
            hit = await self.edgar.cik(symbol)
        except ProviderUnavailable as e:
            return {**base, "available": False, "reason": f"SEC filings: {e.message[:120]}"}
        if hit is None:
            return {**base, "available": False, "reason": f"No SEC company with ticker {symbol} was found (ETFs and some foreign shares have none)."}
        cik, title = hit
        try:
            rf, origin, at = await self.edgar.research_facts(cik)
        except ProviderUnavailable as e:
            return {**base, "available": False, "reason": f"SEC filings: {e.message[:120]}"}
        meta = {"origin": origin, "fetched_at": at.isoformat(), "source": "SEC EDGAR XBRL company facts (official)"}
        sic = None
        subs_meta = None
        try:
            subs, so, sat = await self.edgar.filings(cik)
            sic = subs.get("sic")
            subs_meta = {"origin": so, "fetched_at": sat.isoformat(), "sic_description": subs.get("sic_description"), "fiscal_year_end": subs.get("fiscal_year_end"), "exchanges": subs.get("exchanges")}
        except ProviderUnavailable as e:
            base["errors"].append(f"Industry code (SIC): {e.message[:100]}. Sector-specific rules cannot be applied without it, so treat the Rule of 40 and valuation with extra caution.")
        out = assemble(rf, sic, price, price_time, price_source, now, clean_policy(policy), name=title)
        return {**base, **out, "available": True, "sources": {"filings": meta, "submissions": subs_meta}}

    async def research(self, inst, policy: dict | None = None, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        price = price_time = price_source = None
        price_error = None
        if not self.demo and self.edgar.enabled:
            try:
                snap = await self.fundamentals.get(inst)
                price, price_time = snap.get("price"), (snap.get("prov") or {}).get("fetched_at")
                price_source = f"{(snap.get('prov') or {}).get('provider')} ({(snap.get('prov') or {}).get('status')})"
            except (ProviderUnavailable, Exception) as e:  # noqa: BLE001  a missing price removes the valuation verdict, not the filing analysis
                price_error = f"Price: {getattr(e, 'message', type(e).__name__)[:100]}. The valuation verdict needs a current price."
        out = await self.filing_research(inst.symbol, price, price_time, price_source, now, policy)
        out["instrument_id"] = inst.id
        if price_error and out.get("available"):
            out["errors"].append(price_error)
        return out
