"""ETF details for the Fundamentals agent: objective, fees, size, holdings, concentration.

Source: Yahoo's fund data through yfinance (unofficial; field names and units shift, and holdings may be absent). Everything that can be computed is computed
here (concentration from the listed holdings); anything the provider does not supply is reported as missing, never filled in. The adapter was written from the
documented shape and has NOT been run against the live service.
"""
from __future__ import annotations

import asyncio
import math
import re
from datetime import datetime, timezone

from ..instruments import Instrument
from ..models import ProviderUnavailable

_TAGS = re.compile(r"<[^>]*>")
_WS = re.compile(r"\s+")


def clean(s, limit: int) -> str | None:
    if not isinstance(s, str) or not s.strip():
        return None
    t = _WS.sub(" ", _TAGS.sub(" ", s)).strip()
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _n(x):
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


class YahooEtfData:
    name = "yahoo"

    async def fetch(self, inst: Instrument) -> dict:
        return await asyncio.to_thread(self._fetch, inst)

    def _fetch(self, inst: Instrument) -> dict:
        import yfinance as yf

        try:
            t = yf.Ticker(inst.provider_symbol)
            info = t.info
            if not isinstance(info, dict) or not info:
                raise ProviderUnavailable(self.name, f"no fund data for {inst.provider_symbol}")
            raw: dict = {"info": {k: info.get(k) for k in ("longName", "shortName", "quoteType", "category", "fundFamily", "longBusinessSummary", "netExpenseRatio",
                                                          "annualReportExpenseRatio", "totalAssets", "yield", "navPrice", "fundInceptionDate", "legalType")},
                         "top_holdings": None, "sector_weights": None, "asset_classes": None}
            try:
                fd = t.funds_data
                try:
                    df = fd.top_holdings
                    raw["top_holdings"] = [{"symbol": str(i), "name": str(r.get("Name", "")), "weight": r.get("Holding Percent")} for i, r in df.iterrows()]
                except Exception:  # noqa: BLE001  holdings are optional
                    pass
                for attr, key in (("sector_weightings", "sector_weights"), ("asset_classes", "asset_classes")):
                    try:
                        v = getattr(fd, attr)
                        raw[key] = dict(v) if v else None
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass
            return raw
        except ProviderUnavailable:
            raise
        except Exception as e:  # noqa: BLE001
            raise ProviderUnavailable(self.name, f"{type(e).__name__}: {e}"[:160]) from e


def _expense_ratio_pct(info: dict) -> tuple[float | None, str | None]:
    """annualReportExpenseRatio is a fraction (0.0009); netExpenseRatio is already a percent (0.09). Normalised to percent; implausible values are dropped."""
    a, n = _n(info.get("annualReportExpenseRatio")), _n(info.get("netExpenseRatio"))
    for v, basis in ((None if a is None else a * 100, "annual report expense ratio"), (n, "net expense ratio")):
        if v is not None and 0 <= v <= 5:
            return v, basis
    return None, None


def concentration_label(top10_pct: float) -> str:
    return "concentrated" if top10_pct >= 50 else "moderately concentrated" if top10_pct >= 30 else "diversified"


def normalize_etf(raw: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    info = raw.get("info") or {}
    er, er_basis = _expense_ratio_pct(info)
    hold = []
    for h in raw.get("top_holdings") or []:
        w = _n(h.get("weight"))
        if w is not None and w >= 0:
            hold.append({"symbol": clean(h.get("symbol"), 12) or "?", "name": clean(h.get("name"), 60), "weight": w})
    if hold and max(h["weight"] for h in hold) <= 1.0:        # fractions -> percent
        for h in hold:
            h["weight"] *= 100
    hold = [h for h in hold if h["weight"] <= 100]
    hold.sort(key=lambda h: -h["weight"])
    top10 = sum(h["weight"] for h in hold[:10]) if hold else None
    sectors = None
    sw = raw.get("sector_weights")
    if isinstance(sw, dict) and sw:
        items = [(str(k).replace("_", " ").title(), _n(v)) for k, v in sw.items() if _n(v) is not None]
        scale = 100 if items and max(v for _, v in items) <= 1.0 else 1
        sectors = sorted(((k, v * scale) for k, v in items), key=lambda x: -x[1])[:5]
    missing = []
    if er is None:
        missing.append(("expense_ratio", "the provider did not supply a plausible expense ratio"))
    if not hold:
        missing.append(("holdings", "the provider did not supply fund holdings"))
    aum = _n(info.get("totalAssets"))
    if aum is None:
        missing.append(("aum", "the provider did not supply total assets"))
    return {
        "name": clean(info.get("longName") or info.get("shortName"), 100), "category": clean(info.get("category"), 60), "family": clean(info.get("fundFamily"), 60),
        "objective": clean(info.get("longBusinessSummary"), 420), "expense_ratio_pct": er, "expense_basis": er_basis, "aum": aum, "yield_pct": None if _n(info.get("yield")) is None else _n(info.get("yield")) * 100,
        "holdings": hold[:10], "holdings_listed": len(hold), "top1_pct": hold[0]["weight"] if hold else None, "top10_pct": top10,
        "concentration": concentration_label(top10) if top10 is not None else None, "sector_weights": sectors,
        "missing": missing, "fetched_at": now.isoformat(),
    }
