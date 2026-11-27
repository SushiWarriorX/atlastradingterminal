"""SYNTHETIC SEC "company facts" for tests: fictional companies built in the exact SEC schema, with numbers chosen so the expected results can be checked by hand.
These are NOT real company data. (Live SEC data needs ATLAS_SEC_CONTACT; a real response should be added as a fixture once it can be fetched.)"""
from __future__ import annotations

CONCEPT = {"revenue": "RevenueFromContractWithCustomerExcludingAssessedTax", "gross_profit": "GrossProfit", "operating_income": "OperatingIncomeLoss", "net_income": "NetIncomeLoss",
           "operating_cash_flow": "NetCashProvidedByUsedInOperatingActivities", "capex": "PaymentsToAcquirePropertyPlantAndEquipment", "sbc": "ShareBasedCompensation",
           "da": "DepreciationDepletionAndAmortization", "cap_software": "PaymentsToDevelopSoftware"}
INCOME = {"revenue", "gross_profit", "operating_income", "net_income"}                  # these also carry a direct three-month figure in every 10-Q
QEND = [("01-01", "03-31"), ("04-01", "06-30"), ("07-01", "09-30"), ("10-01", "12-31")]
FILED = ["{y}-05-02", "{y}-08-02", "{y}-11-01"]                                          # Q1, Q2, Q3 reports; the annual report follows in February of the next year


def build(name: str, cik: int, first_year: int, q: dict[str, list[float]], instants: dict[str, list[float]] | None = None, shares: dict[int, float] | None = None, restate: dict | None = None,
          q_shares: list[float] | None = None) -> dict:
    """q[metric] = flat list of quarterly values from Q1 of first_year. instants[metric] = value at each quarter end. shares[year] = weighted diluted shares for that fiscal year."""
    gaap: dict = {}
    n = 0

    def add(concept, unit, row):
        gaap.setdefault(concept, {"units": {}})["units"].setdefault(unit, []).append(row)

    for metric, vals in q.items():
        cumulative = 0.0
        for i, v in enumerate(vals):
            y, k = first_year + i // 4, i % 4
            cumulative = v if k == 0 else cumulative + v
            start, end = f"{y}-{QEND[0][0]}", f"{y}-{QEND[k][1]}"
            if k == 3:
                form, filed, accn = "10-K", f"{y + 1}-02-20", f"0000999999-{(y + 1) % 100:02d}-{900000 + cik % 1000:06d}"
            else:
                form, filed, accn = "10-Q", FILED[k].format(y=y), f"0000999999-{y % 100:02d}-{k * 1000 + cik % 1000:06d}"
            val = cumulative
            if restate and (metric, end) in restate:                            # a later filing restates this cumulative figure
                add(CONCEPT[metric], "USD", {"start": start, "end": end, "val": val, "accn": accn, "fy": y, "fp": f"Q{k + 1}", "form": form, "filed": filed})
                val = restate[(metric, end)]
                filed = f"{int(filed[:4]) + 1}-{filed[5:]}"
                accn = "0000999999-99-999999"
            add(CONCEPT[metric], "USD", {"start": start, "end": end, "val": val, "accn": accn, "fy": y, "fp": "FY" if k == 3 else f"Q{k + 1}", "form": form, "filed": filed})
            if metric in INCOME and k in (1, 2):                                # direct three-month figure
                qs = f"{y}-{QEND[k][0]}"
                add(CONCEPT[metric], "USD", {"start": qs, "end": end, "val": v, "accn": accn, "fy": y, "fp": f"Q{k + 1}", "form": form, "filed": filed})
    for metric, vals in (instants or {}).items():
        concept = {"cash": "CashAndCashEquivalentsAtCarryingValue", "debt": "LongTermDebt", "equity": "StockholdersEquity"}[metric]
        for i, v in enumerate(vals):
            y, k = first_year + i // 4, i % 4
            form = "10-K" if k == 3 else "10-Q"
            add(concept, "USD", {"end": f"{y}-{QEND[k][1]}", "val": v, "accn": f"0000999999-{y % 100:02d}-{k * 1000 + 7:06d}", "fy": y, "fp": "FY" if k == 3 else f"Q{k + 1}", "form": form,
                                  "filed": f"{y + 1}-02-20" if k == 3 else FILED[k].format(y=y)})
    for y, v in (shares or {}).items():
        add("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", {"start": f"{y}-01-01", "end": f"{y}-12-31", "val": v, "accn": f"0000999999-{(y + 1) % 100:02d}-{900000 + cik % 1000:06d}",
                                                                       "fy": y, "fp": "FY", "form": "10-K", "filed": f"{y + 1}-02-20"})
    for i, v in enumerate(q_shares or []):                                              # weighted-average diluted shares for each quarter, as filed in the 10-Q
        y, k = first_year + i // 4, i % 4
        add("WeightedAverageNumberOfDilutedSharesOutstanding", "shares", {"start": f"{y}-{QEND[k][0]}", "end": f"{y}-{QEND[k][1]}", "val": v, "accn": f"0000999999-{y % 100:02d}-{k * 1000 + cik % 1000:06d}",
                                                                       "fy": y, "fp": f"Q{k + 1}", "form": "10-Q", "filed": FILED[min(k, 2)].format(y=y)})
    return {"cik": cik, "entityName": name, "facts": {"us-gaap": gaap}}


def mature(first_year: int = 2021, years: int = 5) -> dict:
    """Steady, profitable, slow growth: quarterly revenue 1,000 growing 0.75% each quarter."""
    n = years * 4
    rev = [round(1000 * 1.0075 ** i, 2) for i in range(n)]
    q = {"revenue": rev, "gross_profit": [r * 0.4 for r in rev], "operating_income": [r * 0.15 for r in rev], "net_income": [r * 0.1 for r in rev],
         "operating_cash_flow": [r * 0.14 for r in rev], "capex": [r * 0.04 for r in rev], "sbc": [r * 0.01 for r in rev]}
    inst = {"cash": [500.0] * n, "debt": [800.0] * n, "equity": [3000.0] * n}
    return build("Mature Industrial Co (synthetic)", 1001, first_year, q, inst, {first_year + i: 100.0 - i for i in range(years)})


def software() -> dict:
    """Calendar 2024 quarters of 100, calendar 2025 quarters of 125: TTM revenue 500 vs 400 = +25.0%. TTM operating cash flow 100 and capex 10: free cash flow 90 = 18.0% margin: Rule of 40 = 43.0."""
    rev = [100.0] * 4 + [125.0] * 4
    q = {"revenue": rev, "gross_profit": [r * 0.75 for r in rev], "operating_income": [r * 0.05 for r in rev], "net_income": [r * 0.04 for r in rev],
         "operating_cash_flow": [20.0] * 4 + [25.0] * 4, "capex": [2.0] * 4 + [2.5] * 4, "sbc": [r * 0.15 for r in rev], "da": [3.0] * 8}
    inst = {"cash": [400.0] * 8, "debt": [0.0] * 8, "equity": [900.0] * 8}
    return build("Cloud Software Inc (synthetic)", 2002, 2024, q, inst, {2024: 50.0, 2025: 52.0})


def recent_ipo() -> dict:
    """Public for three quarters only: no annual report yet, no year-earlier comparison."""
    q = {"revenue": [40.0, 48.0, 57.0], "operating_cash_flow": [-5.0, -4.0, -2.0], "capex": [1.0, 1.0, 1.5], "net_income": [-12.0, -10.0, -9.0]}
    return build("New Listing Corp (synthetic)", 3003, 2026, q, {"cash": [300.0] * 3, "debt": [0.0] * 3, "equity": [250.0] * 3}, q_shares=[60.0, 75.0, 90.0])    # share count still rising after the listing


def loss_making_software() -> dict:
    """Growing fast and burning cash: Rule of 40 is computable and low (growth 60%, FCF margin -30% = 30)."""
    rev = [50.0] * 4 + [80.0] * 4
    q = {"revenue": rev, "gross_profit": [r * 0.6 for r in rev], "operating_income": [-r * 0.4 for r in rev], "net_income": [-r * 0.45 for r in rev],
         "operating_cash_flow": [-r * 0.25 for r in rev], "capex": [r * 0.05 for r in rev]}
    return build("Burning Cash Software (synthetic)", 4004, 2024, q, {"cash": [200.0] * 8, "debt": [0.0] * 8, "equity": [150.0] * 8}, {2024: 40.0, 2025: 42.0})


def bank() -> dict:
    """A bank: files interest income, not a revenue line the engine reads."""
    return {"cik": 5005, "entityName": "Sample Bank (synthetic)", "facts": {"us-gaap": {"InterestAndDividendIncomeOperating": {"units": {"USD": [
        {"start": "2025-01-01", "end": "2025-12-31", "val": 900.0, "accn": "0000999999-26-000001", "fy": 2025, "fp": "FY", "form": "10-K", "filed": "2026-02-20"}]}}}}}


def research_payload(symbol: str, kind: str = "software", price: float = 40.0) -> dict:
    """What FundamentalResearch.research returns, for a SYNTHETIC company (test harnesses patch the research source with this; nothing about it is real)."""
    from datetime import datetime, timezone
    from atlas_api.research import facts, service
    makers = {"software": (software, 7372), "mature": (mature, 3490), "loss_making": (loss_making_software, 7372), "recent_ipo": (recent_ipo, 7372), "bank": (bank, 6022)}
    mk, sic = makers[kind]
    now = datetime(2026, 11, 8, 12, tzinfo=timezone.utc) if kind == "recent_ipo" else datetime(2026, 2, 1, 12, tzinfo=timezone.utc)
    out = service.assemble(facts.condense(mk(), now.date()), sic, price, now.isoformat(), "test quote (synthetic)", now)
    return {"symbol": symbol, "as_of": now.isoformat(), "demo": False, "errors": [], "available": True, **out,
            "filings": [{"form": "10-K", "filed": "2026-02-20", "items": [], "link": "https://www.sec.gov/Archives/edgar/data/2002/000099999926000001/0000999999-26-000001-index.htm"}],
            "sources": {"filings": {"origin": "fixture", "fetched_at": now.isoformat(), "source": "SYNTHETIC SEC-schema fixture (not real company data)"}, "submissions": {"sic_description": "Services-Prepackaged Software", "exchanges": ["Nasdaq"]}}}
