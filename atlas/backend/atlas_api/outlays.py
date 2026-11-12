"""Where US federal money goes: net outlays (spending) by purpose, the government's receipts, and the gap between them, for the latest month and the fiscal year so far, with the same point last year (US Treasury FiscalData,
Monthly Treasury Statement Table 9, free, no key).

How to read it: "outlays" is what the government spent, grouped by purpose (defense, Social Security, Medicare, interest on the debt and so on). They are NET outlays: spending after money that is counted against it, so a purpose can be small or even
negative when offsetting receipts exceed its spending. "Deficit" here is outlays minus receipts. The fiscal year starts on October 1; the table is published about eight business days after a month ends. Amounts are in dollars in the source and shown in billions.
Checks: the purposes must add up to the source's own total outlays, the receipts lines to its total receipts, each for the month, the year so far and last year's same point; if a check fails nothing is shown.
It describes what already happened: it is not a market signal or a forecast, and it does not say why any purpose rose or fell.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_9"
FIELDS = "record_date,classification_desc,print_order_nbr,sequence_level_nbr,data_type_cd,current_month_rcpt_outly_amt,current_fytd_rcpt_outly_amt,prior_fytd_rcpt_outly_amt"
SOURCE = "US Treasury FiscalData, Monthly Treasury Statement Table 9, receipts and outlays by function (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/summary-of-receipts-and-outlays-of-the-u-s-government"
WHAT = {"National Defense": "the military and related spending", "International Affairs": "foreign aid and diplomacy", "General Science, Space, and Technology": "space and science research",
        "Energy": "energy programs", "Natural Resources and Environment": "land, water and environmental programs", "Agriculture": "farm programs",
        "Commerce and Housing Credit": "net of fees and loan programs, so it can be negative", "Transportation": "roads, transit and aviation",
        "Community and Regional Development": "disaster relief and local development", "Education, Training, Employment, and Social Services": "schools, job training and social services",
        "Health": "health care programs such as Medicaid, and health research", "Medicare": "health insurance for older people", "Income Security": "unemployment pay, food and housing aid, and some retirement pay",
        "Social Security": "retirement and disability benefits", "Veterans Benefits and Services": "benefits and care for veterans", "Administration of Justice": "law enforcement, courts and prisons",
        "General Government": "running the government itself", "Net Interest": "interest paid on the debt, net of interest the government receives",
        "Undistributed Offsetting Receipts": "money counted against spending, such as the government's own contributions to retirement funds"}
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 50
TOL = 5.0                       # dollars: the source rounds to cents and these sums add up to 20 lines


def _num(x):
    try:
        return None if x in (None, "", "null") else float(x)
    except (TypeError, ValueError):
        return None


def parse(payload: dict) -> tuple[date, dict]:
    """The newest month's table: {"receipts_total", "receipts_leaves", "outlays_total", "outlays_leaves", "functions": [(name, {m, y, p})]} in dollars. A missing or unreadable line refuses the response."""
    rows = payload.get("data") or []
    dates = []
    for r in rows:
        try:
            dates.append(date.fromisoformat(r["record_date"]))
        except (KeyError, TypeError, ValueError):
            raise ValueError("a row had no usable date")
    if not dates:
        raise ValueError("the source returned no outlays rows")
    newest = max(dates)
    mine = sorted((r for r in rows if date.fromisoformat(r["record_date"]) == newest), key=lambda r: int(r["print_order_nbr"]))
    hdr = next((i for i, r in enumerate(mine) if r.get("classification_desc") == "Net Outlays"), None)
    if hdr is None:
        raise ValueError("the table had no Net Outlays section")

    def val(r):
        v = {"m": _num(r.get("current_month_rcpt_outly_amt")), "y": _num(r.get("current_fytd_rcpt_outly_amt")), "p": _num(r.get("prior_fytd_rcpt_outly_amt"))}
        if None in v.values():
            raise ValueError(f"the line {r.get('classification_desc')!r} had an unreadable amount")
        return v

    def section(rs):
        total = [val(r) for r in rs if r.get("data_type_cd") == "T"]
        leaves = [(r["classification_desc"], val(r)) for r in rs if r.get("data_type_cd") == "D"]
        if len(total) != 1 or not leaves:
            raise ValueError("a section did not have exactly one total line and its detail lines")
        return total[0], leaves

    r_tot, r_leaves = section(mine[:hdr])
    o_tot, o_leaves = section(mine[hdr + 1:])
    missing = set(WHAT) - {n for n, _ in o_leaves}
    if missing:
        raise ValueError(f"missing outlay lines: {sorted(missing)[:2]}")
    return newest, {"receipts_total": r_tot, "receipts_leaves": [v for _, v in r_leaves], "outlays_total": o_tot, "functions": o_leaves}


def checks(t: dict) -> dict:
    bad = []
    for k, label in (("m", "month"), ("y", "year so far"), ("p", "last year's same point")):
        if abs(sum(v[k] for _, v in t["functions"]) - t["outlays_total"][k]) > TOL:
            bad.append(f"the purposes do not add up to total outlays for the {label}")
        if abs(sum(v[k] for v in t["receipts_leaves"]) - t["receipts_total"][k]) > TOL:
            bad.append(f"the receipts lines do not add up to total receipts for the {label}")
    return {"purposes_add_up_to_total_outlays": not any("purposes" in b for b in bad), "receipts_lines_add_up_to_total": not any("receipts lines" in b for b in bad), "problems": bad, "ok": not bad}


def _b(x: float) -> float:
    return round(x / 1e9, 1)


def _chg(now: float, then: float) -> float | None:
    return None if then == 0 else round((now / then - 1) * 100, 1)


def summarize(newest: date, t: dict, today: date) -> dict:
    ck = checks(t)
    if not ck["ok"]:
        raise ValueError("the source's own arithmetic did not add up: " + "; ".join(ck["problems"]))
    o, r = t["outlays_total"], t["receipts_total"]
    deficit = {k: o[k] - r[k] for k in ("m", "y", "p")}
    funcs = []
    for name, v in t["functions"]:
        funcs.append({"name": name, "what": WHAT[name], "month_billions": _b(v["m"]), "year_so_far_billions": _b(v["y"]), "share_of_outlays_pct": round(v["y"] / o["y"] * 100, 1) if o["y"] else None,
                      "same_point_last_year_billions": _b(v["p"]), "change_vs_last_year_pct": _chg(v["y"], v["p"]) if v["p"] > 0 and v["y"] > 0 else None, "_y": v["y"]})
    funcs.sort(key=lambda f: -f["_y"])
    for f in funcs:
        del f["_y"]
    age = (today - newest).days
    fy = newest.year + 1 if newest.month >= 10 else newest.year
    return {"available": True, "date": newest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "url": PAGE, "fiscal_year": fy,
            "months_in_year": (newest.month - 10) % 12 + 1,
            "outlays": {"month_billions": _b(o["m"]), "year_so_far_billions": _b(o["y"]), "same_point_last_year_billions": _b(o["p"]), "change_vs_last_year_pct": _chg(o["y"], o["p"])},
            "receipts": {"month_billions": _b(r["m"]), "year_so_far_billions": _b(r["y"]), "same_point_last_year_billions": _b(r["p"]), "change_vs_last_year_pct": _chg(r["y"], r["p"])},
            "deficit": {"month_billions": _b(deficit["m"]), "year_so_far_billions": _b(deficit["y"]), "same_point_last_year_billions": _b(deficit["p"]), "change_vs_last_year_pct": _chg(deficit["y"], deficit["p"])},
            "functions": funcs, "checks": ck,
            "note": ("Outlays are NET: spending after money that is counted against it, so a purpose can be small or even negative when offsetting receipts exceed its spending. Deficit here is outlays minus receipts; a negative deficit would be a surplus. "
                     "The fiscal year starts on October 1, and the table is published about eight business days after a month ends. The purposes are checked against the source's own total outlays and the receipts lines against its total receipts, "
                     "for the month, the year so far and last year's same point. This describes what already happened: it is not a market signal or a forecast, and it does not say why any purpose rose or fell.")}


class Outlays:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real Treasury figures are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=30)
        try:
            r = await c.get(URL, params={"sort": "-record_date", "page[size]": 40, "fields": FIELDS}, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            newest, t = parse(r.json())
            res = {**base, **summarize(newest, t, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Treasury outlays could not be read right now ({type(e).__name__}: {str(e)[:110]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
