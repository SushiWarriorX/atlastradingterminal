"""Where US federal revenue comes from: the seven categories of receipts in the Monthly Treasury Statement (Table 4), for the latest month and the fiscal year so far, with the same point last year (US Treasury FiscalData, free, no key).

How to read it: individual income taxes (what people pay on pay and returns), corporate income taxes, social insurance (Social Security, Medicare and other payroll taxes), excise taxes (fuel, airline tickets and similar), estate and gift taxes, customs duties (tariffs)
and miscellaneous receipts (such as Federal Reserve earnings and fees). Every figure is NET: collected minus refunds. The fiscal year starts on October 1. The table is published about eight business days after a month ends. Amounts are in dollars in the source and shown in billions.
Checks: the seven categories must add up to the source's own "Total -- Receipts" for the month, the year so far and last year's same point, and on-budget plus off-budget must equal that total as well; if any of these fail nothing is shown.
It describes what already happened: it is not a market signal or a forecast, and it does not say why any category rose or fell.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_4"
FIELDS = "record_date,classification_desc,print_order_nbr,sequence_level_nbr,data_type_cd,current_month_net_rcpt_amt,current_fytd_net_rcpt_amt,prior_fytd_net_rcpt_amt"
SOURCE = "US Treasury FiscalData, Monthly Treasury Statement Table 4, receipts by source (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/receipts-of-the-u-s-government"
# (source line, plain name, what it is)
CATEGORIES = [("Total -- Individual Income Taxes", "Individual income taxes", "what people pay on pay and personal returns"),
              ("Total -- Social Insurance and Retirement Receipts", "Social Security, Medicare and other payroll taxes", "taken from pay and from the self-employed"),
              ("Corporation Income Taxes", "Corporate income taxes", "what companies pay on profits"),
              ("Customs Duties", "Customs duties (tariffs)", "taxes on imported goods"),
              ("Total -- Excise Taxes", "Excise taxes", "fuel, airline tickets and similar"),
              ("Total -- Miscellaneous Receipts", "Miscellaneous receipts", "such as Federal Reserve earnings and fees"),
              ("Estate and Gift Taxes", "Estate and gift taxes", "on large inheritances and gifts")]
TOTAL, ON_BUDGET, OFF_BUDGET = "Total -- Receipts", "Total -- On-Budget", "Total -- Off-Budget"
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 50
TOL = 2.0                      # dollars: the source rounds to cents


def _num(x):
    try:
        return None if x in (None, "", "null") else float(x)
    except (TypeError, ValueError):
        return None


def parse(payload: dict) -> tuple[date, dict[str, dict]]:
    """The newest month's lines the panel needs: {source line: {m, y, p}} in dollars (month, fiscal year so far, same point last year). Rows of older months are ignored. A needed line that is missing or unreadable refuses the response."""
    rows = payload.get("data") or []
    dates = []
    for r in rows:
        try:
            dates.append(date.fromisoformat(r["record_date"]))
        except (KeyError, TypeError, ValueError):
            raise ValueError("a row had no usable date")
    if not dates:
        raise ValueError("the source returned no receipts rows")
    newest = max(dates)
    need = {c[0] for c in CATEGORIES} | {TOTAL, ON_BUDGET, OFF_BUDGET}
    out: dict[str, dict] = {}
    for r in rows:
        if date.fromisoformat(r["record_date"]) != newest or r.get("classification_desc") not in need:
            continue
        v = {"m": _num(r.get("current_month_net_rcpt_amt")), "y": _num(r.get("current_fytd_net_rcpt_amt")), "p": _num(r.get("prior_fytd_net_rcpt_amt"))}
        if None in v.values():
            raise ValueError(f"the line {r['classification_desc']!r} had an unreadable amount")
        if r["classification_desc"] in out and out[r["classification_desc"]] != v:
            raise ValueError("two different rows for one line")
        out[r["classification_desc"]] = v
    missing = need - set(out)
    if missing:
        raise ValueError(f"missing lines: {sorted(missing)[:2]}")
    return newest, out


def checks(lines: dict[str, dict]) -> dict:
    bad = []
    for k, label in (("m", "month"), ("y", "year so far"), ("p", "last year's same point")):
        s = sum(lines[c[0]][k] for c in CATEGORIES)
        if abs(s - lines[TOTAL][k]) > TOL:
            bad.append(f"the seven categories do not add up to the total for the {label}")
        if abs(lines[ON_BUDGET][k] + lines[OFF_BUDGET][k] - lines[TOTAL][k]) > TOL:
            bad.append(f"on-budget plus off-budget does not equal the total for the {label}")
    return {"categories_add_up_to_total": not any("seven" in b for b in bad), "on_plus_off_budget_equals_total": not any("on-budget" in b for b in bad), "problems": bad, "ok": not bad}


def _b(x: float) -> float:
    return round(x / 1e9, 1)


def _chg(now: float, then: float) -> float | None:
    return None if then == 0 else round((now / then - 1) * 100, 1)


def summarize(newest: date, lines: dict[str, dict], today: date) -> dict:
    ck = checks(lines)
    if not ck["ok"]:
        raise ValueError("the source's own arithmetic did not add up: " + "; ".join(ck["problems"]))
    tot = lines[TOTAL]
    cats = []
    for src, name, what in CATEGORIES:
        v = lines[src]
        cats.append({"name": name, "what": what, "month_billions": _b(v["m"]), "year_so_far_billions": _b(v["y"]), "share_of_year_pct": round(v["y"] / tot["y"] * 100, 1) if tot["y"] else None,
                     "same_point_last_year_billions": _b(v["p"]), "change_vs_last_year_pct": _chg(v["y"], v["p"]), "_y": v["y"]})
    cats.sort(key=lambda c: -c["_y"])
    for c in cats:
        del c["_y"]
    age = (today - newest).days
    fy = newest.year + 1 if newest.month >= 10 else newest.year
    return {"available": True, "date": newest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "url": PAGE, "fiscal_year": fy,
            "months_in_year": (newest.month - 10) % 12 + 1,
            "total": {"month_billions": _b(tot["m"]), "year_so_far_billions": _b(tot["y"]), "same_point_last_year_billions": _b(tot["p"]), "change_vs_last_year_pct": _chg(tot["y"], tot["p"])},
            "categories": cats, "checks": ck,
            "note": ("Every figure is net: collected minus refunds. The fiscal year starts on October 1, and the table is published about eight business days after a month ends. The seven categories are checked against the source's own total "
                     "(for the month, the year so far and last year's same point), and on-budget plus off-budget must equal it too. This describes what already happened: it is not a market signal or a forecast, and it does not say why any category rose or fell.")}


class Receipts:
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
            r = await c.get(URL, params={"sort": "-record_date", "page[size]": 60, "fields": FIELDS}, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            newest, lines = parse(r.json())
            res = {**base, **summarize(newest, lines, now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Treasury receipts could not be read right now ({type(e).__name__}: {str(e)[:110]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
