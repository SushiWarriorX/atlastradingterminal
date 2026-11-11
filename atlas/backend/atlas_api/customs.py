"""US customs duties (tariff revenue): what the Treasury collected on imports, paid back in refunds, and kept, by month and for the fiscal year so far (US Treasury FiscalData, Monthly Treasury Statement Table 4, free, no key).

How to read it: customs duties are taxes on imported goods (tariffs). "Gross" is what was collected, "refunds" is what was paid back to importers, and "net" is gross minus refunds, which is what the budget actually counts. The report does not say WHY
refunds were large in any month, so this panel does not either; a month with big refunds can show a small or even negative net. The fiscal year starts on October 1. The table is published about eight business days after a month ends, so
the newest month is normally five to six weeks old. Amounts are in dollars in the source and shown here in billions. Every month and the year-so-far figure are checked against the source's own arithmetic: gross minus refunds must equal net,
and the fiscal-year-so-far net must equal the sum of that year's monthly nets. If a check fails nothing is shown. It describes what already happened: it is not a market signal or a forecast.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts/mts_table_4"
FIELDS = ("record_date,classification_desc,current_month_gross_rcpt_amt,current_month_refund_amt,current_month_net_rcpt_amt,current_fytd_gross_rcpt_amt,current_fytd_refund_amt,current_fytd_net_rcpt_amt,"
          "prior_fytd_gross_rcpt_amt,prior_fytd_refund_amt,prior_fytd_net_rcpt_amt")
SOURCE = "US Treasury FiscalData, Monthly Treasury Statement Table 4, customs duties (official, free public data)"
PAGE = "https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/receipts-of-the-u-s-government"
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 50
TOL = 2.0                      # dollars: the source rounds to cents
SHOWN_MONTHS = 12


def _num(x):
    try:
        return None if x in (None, "", "null") else float(x)
    except (TypeError, ValueError):
        return None


def parse(payload: dict) -> list[dict]:
    """Months, oldest first, amounts in dollars. A row with an unreadable amount refuses the whole response; two different rows for one month refuse it too."""
    by: dict[date, dict] = {}
    for r in payload.get("data") or []:
        if r.get("classification_desc") != "Customs Duties":
            continue
        try:
            d = date.fromisoformat(r["record_date"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("a row had no usable date")
        vals = {k: _num(r.get(f)) for k, f in (("m_gross", "current_month_gross_rcpt_amt"), ("m_refund", "current_month_refund_amt"), ("m_net", "current_month_net_rcpt_amt"),
                                              ("y_gross", "current_fytd_gross_rcpt_amt"), ("y_refund", "current_fytd_refund_amt"), ("y_net", "current_fytd_net_rcpt_amt"),
                                              ("py_net", "prior_fytd_net_rcpt_amt"))}
        if any(v is None for v in vals.values()):
            raise ValueError("a customs row had an unreadable amount")
        row = {"date": d, **vals}
        if d in by and by[d] != row:
            raise ValueError("two different rows for the same month")
        by[d] = row
    if not by:
        raise ValueError("the source returned no customs duties rows")
    return [by[k] for k in sorted(by)]


def _fy(d: date) -> int:
    return d.year + 1 if d.month >= 10 else d.year


def checks(rows: list[dict]) -> dict:
    """gross - refunds = net for the month and for the year so far on the newest months, and the year-so-far net equals the sum of that fiscal year's monthly nets wherever every month of that year so far is present."""
    recent = rows[-(SHOWN_MONTHS + 12):]
    ident_bad = sum(1 for r in recent if abs(r["m_gross"] - r["m_refund"] - r["m_net"]) > TOL or abs(r["y_gross"] - r["y_refund"] - r["y_net"]) > TOL)
    have = {r["date"]: r for r in rows}
    checked = bad = 0
    for r in recent:
        months = [d for d in have if _fy(d) == _fy(r["date"]) and d <= r["date"]]
        if len(months) == (r["date"].month - 10) % 12 + 1:
            checked += 1
            if abs(sum(have[d]["m_net"] for d in months) - r["y_net"]) > TOL:
                bad += 1
    return {"months_checked": len(recent), "identity_failures": ident_bad, "fytd_sum_checks": checked, "fytd_sum_mismatches": bad, "ok": ident_bad == 0 and bad == 0 and checked > 0}


def _b(x: float) -> float:
    return round(x / 1e9, 1)


def summarize(rows: list[dict], today: date) -> dict:
    last = rows[-1]
    ck = checks(rows)
    if not ck["ok"]:
        raise ValueError(f"the source's own arithmetic did not add up ({ck['identity_failures']} identity failures, {ck['fytd_sum_mismatches']} year-to-date sum mismatches)")
    age = (today - last["date"]).days
    share = None if last["m_gross"] <= 0 else round(last["m_refund"] / last["m_gross"] * 100, 1)
    change = None if last["py_net"] == 0 else round((last["y_net"] / last["py_net"] - 1) * 100, 1)
    return {"available": True, "date": last["date"].isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "url": PAGE,
            "fiscal_year": _fy(last["date"]), "latest": {"gross_billions": _b(last["m_gross"]), "refunds_billions": _b(last["m_refund"]), "net_billions": _b(last["m_net"]), "refunds_share_of_gross_pct": share},
            "year_so_far": {"gross_billions": _b(last["y_gross"]), "refunds_billions": _b(last["y_refund"]), "net_billions": _b(last["y_net"]), "same_point_last_year_net_billions": _b(last["py_net"]), "change_vs_last_year_pct": change,
                            "months": (last["date"].month - 10) % 12 + 1},
            "months": [{"date": r["date"].isoformat(), "gross_billions": _b(r["m_gross"]), "refunds_billions": _b(r["m_refund"]), "net_billions": _b(r["m_net"])} for r in rows[-SHOWN_MONTHS:]],
            "checks": ck,
            "note": ("Customs duties are taxes on imported goods (tariffs). Gross is what was collected, refunds is what was paid back to importers, and net is gross minus refunds, which is what the budget counts. The report does not say why refunds "
                     "were large in any month, so this panel does not either: a month with big refunds can show a small or even negative net. The fiscal year starts on October 1, and the table is published about eight business days after a month ends. "
                     "Every month and the year-so-far figure are checked against the source's own arithmetic. This describes what already happened: it is not a market signal or a forecast.")}


class Customs:
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
            r = await c.get(URL, params={"filter": "classification_desc:eq:Customs Duties", "sort": "-record_date", "page[size]": 40, "fields": FIELDS}, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            res = {**base, **summarize(parse(r.json()), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"Treasury customs duties could not be read right now ({type(e).__name__}: {str(e)[:100]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
