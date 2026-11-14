"""From SEC XBRL "company facts" to clean period series (pure functions).

What the SEC publishes: for each reported figure, every value the company ever filed, with the period it covers (start and end), the form and the filing date. Flow figures (revenue, cash flow)
come as a quarter, as a year-to-date total (6 months, 9 months) or as a full year; the fourth quarter is never filed on its own. So:

  reported  - a three-month figure the company filed itself;
  derived   - the difference of two cumulative figures of the same fiscal year (for example the 9-month total minus the 6-month total, or the full year minus the 9-month total).

Both are labelled; nothing is estimated. When a restated value was filed later for the same period, the latest filing wins. A figure the company never filed stays missing (None); it is never zero.
Only US-GAAP facts in US dollars (and share counts) are read: companies that report under IFRS are not covered, and dimensional breakdowns (segments, geography) are not part of this data.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

FORMS_OK = ("10-K", "10-K/A", "10-Q", "10-Q/A")
YEARS_KEPT = 9

# metric -> (unit, fallback concepts in priority order). Earlier concepts win; later ones only fill periods the earlier ones lack.
FLOWS = {
    "revenue": ("USD", ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"]),
    "gross_profit": ("USD", ["GrossProfit"]),
    "operating_income": ("USD", ["OperatingIncomeLoss"]),
    "net_income": ("USD", ["NetIncomeLoss", "ProfitLoss"]),
    "operating_cash_flow": ("USD", ["NetCashProvidedByUsedInOperatingActivities"]),
    "capex": ("USD", ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]),
    "cap_software": ("USD", ["PaymentsToDevelopSoftware", "PaymentsForSoftware"]),
    "sbc": ("USD", ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"]),
    "da": ("USD", ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"]),
    "diluted_shares": ("shares", ["WeightedAverageNumberOfDilutedSharesOutstanding"]),
}
INSTANTS = {
    "cash": ("USD", ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]),
    "debt": ("USD", ["LongTermDebt", "LongTermDebtNoncurrent", "DebtAndCapitalLeaseObligations"]),
    "equity": ("USD", ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]),
}


@dataclass(frozen=True)
class Fact:
    start: date | None
    end: date
    val: float
    form: str
    filed: str
    accn: str


def _row(r: dict):
    """One raw fact -> (start, end, value, form, filed, accession), or None when it is not a usable annual or quarterly report figure."""
    try:
        if r.get("form") not in FORMS_OK:
            return None
        v = r.get("val")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        return (r.get("start"), r["end"], float(v), r["form"], str(r.get("filed", "")), str(r.get("accn", "")))
    except (KeyError, TypeError):
        return None


def condense(raw: dict, today: date | None = None) -> dict:
    """Raw company facts -> {'name','cik','flows':{metric: [[start,end,val,form,filed,accn]]},'instants':{metric: [[end,val,form,filed,accn]]}} for the periods we use (small enough to cache).
    Concepts are tried in priority order: a later concept only fills a period the earlier ones lack; for one concept a later filing (a restatement) replaces an earlier one."""
    today = today or date.today()
    cutoff = (today - timedelta(days=int(365.25 * YEARS_KEPT))).isoformat()
    gaap = (raw.get("facts") or {}).get("us-gaap") or {}
    out = {"name": raw.get("entityName"), "cik": raw.get("cik"), "flows": {}, "instants": {}}
    for table, spec, flow in ((out["flows"], FLOWS, True), (out["instants"], INSTANTS, False)):
        for metric, (unit, concepts) in spec.items():
            seen: dict[tuple, tuple] = {}                                  # period -> (row, concept it came from)
            for c in concepts:
                for r in ((gaap.get(c) or {}).get("units") or {}).get(unit) or []:
                    p = _row(r)
                    if p is None or p[1] < cutoff or bool(p[0]) != flow:     # flows need a start date, balances must not have one
                        continue
                    key = (p[0], p[1]) if flow else (p[1],)
                    if key not in seen or (seen[key][1] == c and p[4] > seen[key][0][4]):
                        seen[key] = (p, c)
            rows = sorted((v[0] for v in seen.values()), key=lambda p: (p[1], p[0] or ""))
            table[metric] = [list(p) for p in rows] if flow else [[p[1], p[2], p[3], p[4], p[5]] for p in rows]
    return out


def flow_facts(rf: dict, metric: str) -> list[Fact]:
    out = []
    for s, e, v, form, filed, accn in rf.get("flows", {}).get(metric) or []:
        try:
            out.append(Fact(date.fromisoformat(s), date.fromisoformat(e), float(v), form, filed, accn))
        except (TypeError, ValueError):
            continue
    return out


def _months(days: int) -> int:
    return round(days / 30.4375)


def annual(facts: list[Fact]) -> list[dict]:
    """Full fiscal years (350 to 380 days) from annual reports, oldest first. A later filing for the same period replaces an earlier one."""
    best: dict[date, Fact] = {}
    for f in facts:
        if not f.form.startswith("10-K") or not 350 <= (f.end - f.start).days <= 380:
            continue
        if f.end not in best or f.filed > best[f.end].filed:
            best[f.end] = f
    return [{"start": f.start, "end": f.end, "value": f.val, "form": f.form, "filed": f.filed, "accn": f.accn} for f in sorted(best.values(), key=lambda f: f.end)]


def discrete_quarters(facts: list[Fact]) -> dict[date, dict]:
    """Quarter end -> {'start','end','value','basis','form','filed','accn'}. Three-month figures the company filed are 'reported'; the rest are 'derived' from cumulative figures of one fiscal year."""
    best: dict[tuple, Fact] = {}
    for f in facts:
        k = (f.start, f.end)
        if k not in best or f.filed > best[k].filed:
            best[k] = f
    chains: dict[date, dict[int, Fact]] = defaultdict(dict)
    direct: dict[date, Fact] = {}
    for f in best.values():
        days = (f.end - f.start).days
        m = _months(days)
        if 80 <= days <= 100:
            if f.end not in direct or f.filed > direct[f.end].filed:
                direct[f.end] = f
        if m in (3, 6, 9, 12) and abs(days - m * 30.4375) <= 14:
            chains[f.start][m] = f
    out: dict[date, dict] = {}
    for start, ch in chains.items():
        for k in (2, 3, 4):
            cur, prev = ch.get(3 * k), ch.get(3 * (k - 1))
            if cur is None or prev is None:
                continue
            latest = max((cur, prev), key=lambda f: f.filed)
            out[cur.end] = {"start": prev.end + timedelta(days=1), "end": cur.end, "value": cur.val - prev.val, "basis": f"derived: {3 * k}-month total minus {3 * (k - 1)}-month total",
                            "form": latest.form, "filed": latest.filed, "accn": latest.accn}
    for end, f in direct.items():
        out[end] = {"start": f.start, "end": end, "value": f.val, "basis": "reported (three-month figure)", "form": f.form, "filed": f.filed, "accn": f.accn}
    return out


def run(quarters: dict[date, dict], n: int, ending: date | None = None) -> list[dict] | None:
    """The n consecutive quarters (each 80 to 100 days after the one before) ending at `ending` (default: the latest). None unless all n exist."""
    ends = sorted(e for e in quarters if ending is None or e <= ending)
    if not ends or (ending is not None and ends[-1] != ending):
        return None
    chosen = [ends[-1]]
    for e in reversed(ends[:-1]):
        if len(chosen) == n:
            break
        if 80 <= (chosen[-1] - e).days <= 100:
            chosen.append(e)
        else:
            break
    return [quarters[e] for e in reversed(chosen)] if len(chosen) == n else None


def ttm(quarters: dict[date, dict], ending: date | None = None) -> dict | None:
    """Sum of four consecutive quarters ending at `ending` (default: the latest quarter on file)."""
    r = run(quarters, 4, ending)
    if not r:
        return None
    return {"value": sum(q["value"] for q in r), "end": r[-1]["end"], "start": r[0]["start"], "quarters": [q["end"] for q in r], "basis": "calculated: sum of four consecutive quarters",
            "filed": max(q["filed"] for q in r)}


def latest_instant(rf: dict, metric: str, on_or_before: date | None = None) -> dict | None:
    rows = rf.get("instants", {}).get(metric) or []
    best = None
    for e, v, form, filed, accn in rows:
        try:
            d = date.fromisoformat(e)
        except ValueError:
            continue
        if on_or_before is not None and d > on_or_before:
            continue
        if best is None or d > best["end"] or (d == best["end"] and filed > best["filed"]):
            best = {"end": d, "value": float(v), "form": form, "filed": filed, "accn": accn}
    return best


def filing_link(cik, accn: str) -> str | None:
    """A link to the filing's index page on sec.gov (accession number and company number checked for plain digits and dashes)."""
    import re
    if not accn or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", accn):
        return None
    try:
        c = int(cik)
    except (TypeError, ValueError):
        return None
    return f"https://www.sec.gov/Archives/edgar/data/{c}/{accn.replace('-', '')}/{accn}-index.htm"
