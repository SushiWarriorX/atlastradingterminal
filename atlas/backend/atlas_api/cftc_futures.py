"""CFTC Commitments of Traders for big US futures: who holds the contracts, by trader group. Free official data from the CFTC, no key. Two report families share this code:
FINANCIAL (Traders in Financial Futures: S&P 500, Nasdaq-100, 2-year and 10-year Treasury, US dollar index) and COMMODITY (Disaggregated Futures Only: gold, crude oil, copper, natural gas).

What it is: every Tuesday the CFTC counts the open contracts held by each trader group and publishes the table that Friday. What it is not: all of the market. It covers only these exchange-traded futures, not the cash
market, options or swaps. "Net short" is not the same as "bearish": asset managers hold stock futures as a way to own stocks, leveraged funds are often short Treasury futures as the other half of a basis trade,
and producers are short commodity futures to lock in prices for what they make. Everything shown is read from the report or simple arithmetic on it (net = long minus short, change from the week before, one-year rank).
Each week is checked against the report's own totals (the groups' longs and shorts, with their spreading positions, must add up to the reportable total, and reportable plus small traders must equal open interest);
a contract that does not add up is not shown. A failure says so and shows nothing.
"""
from __future__ import annotations

import asyncio
import time
from datetime import date, datetime, timezone

import httpx

PAGE = "https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm"
# (key, name, who, long field, short field, spread field or None)
GROUPS = [("lev_money", "Leveraged funds", "hedge funds and similar fast-moving money", "lev_money_positions_long", "lev_money_positions_short", "lev_money_positions_spread"),
          ("asset_mgr", "Asset managers", "institutional investors such as funds and pensions", "asset_mgr_positions_long", "asset_mgr_positions_short", "asset_mgr_positions_spread"),
          ("dealer", "Dealers", "banks and market makers, usually on the other side of clients", "dealer_positions_long_all", "dealer_positions_short_all", "dealer_positions_spread_all"),
          ("other_rept", "Other reportable", "large traders that fit none of the groups above", "other_rept_positions_long", "other_rept_positions_short", "other_rept_positions_spread")]
COMMODITY_GROUPS = [("m_money", "Managed money", "hedge funds and other speculators", "m_money_positions_long_all", "m_money_positions_short_all", "m_money_positions_spread"),
                    ("prod_merc", "Producers and merchants", "companies that make, store or trade the commodity, mostly hedging real stock", "prod_merc_positions_long", "prod_merc_positions_short", None),
                    ("swap", "Swap dealers", "banks that sell commodity exposure to clients and hedge it in futures", "swap_positions_long_all", "swap__positions_short_all", "swap__positions_spread_all"),
                    ("other_rept", "Other reportable", "large traders that fit none of the groups above", "other_rept_positions_long", "other_rept_positions_short", "other_rept_positions_spread")]
COMMON_FIELDS = ("report_date_as_yyyy_mm_dd,open_interest_all,change_in_open_interest_all,traders_tot_all,tot_rept_positions_long_all,tot_rept_positions_short,"
                 "nonrept_positions_long_all,nonrept_positions_short_all")
TAIL = ("Each week is checked against the report's own totals. The 1-year rank says where this week's net position sits among the last 52 weeks (0 = lowest, 100 = highest). "
        "This describes what already happened: it is not a market signal or a forecast.")


class Family:
    """One CFTC report family: which dataset, which contracts, which trader groups, and the wording that goes with them."""

    def __init__(self, url: str, contracts: list, groups: list, source: str, note: str):
        self.url, self.contracts, self.groups, self.source, self.note = url, contracts, groups, source, note
        self.select = ",".join([COMMON_FIELDS] + [f for g in groups for f in g[3:] if f])


FINANCIAL = Family(
    "https://publicreporting.cftc.gov/resource/gpe5-46if.json",
    [("13874A", "S&P 500 futures (E-mini)", "US large-company stocks"), ("209742", "Nasdaq-100 futures (E-mini)", "US large technology-heavy stocks"),
     ("042601", "2-year Treasury note futures", "short-term US interest rates"), ("043602", "10-year Treasury note futures", "long-term US interest rates"),
     ("098662", "US dollar index futures", "the dollar against a basket of currencies")],
    GROUPS, "CFTC Commitments of Traders, Traders in Financial Futures (official, free public data)",
    "Positions are counted on Tuesdays and published the following Friday, so they are at least three days old. Net is long minus short, with spreading positions left out. Net short is not the same as bearish: "
    "asset managers hold stock futures as a way to own stocks, and leveraged funds are often short Treasury futures as the other half of a basis trade (long the bond, short the future). " + TAIL)
COMMODITY = Family(
    "https://publicreporting.cftc.gov/resource/72hh-3qpy.json",
    [("088691", "Gold futures", "Gold"), ("067651", "Crude oil futures (WTI)", "US crude oil"), ("085692", "Copper futures", "Copper, often read as a gauge of industrial demand"), ("023651", "Natural gas futures", "US natural gas")],
    COMMODITY_GROUPS, "CFTC Commitments of Traders, Disaggregated Futures Only report (official, free public data)",
    "Positions are counted on Tuesdays and published the following Friday, so they are at least three days old. Net is long minus short, with spreading positions left out. Net short is not the same as bearish: "
    "producers and merchants are usually short futures to lock in a price for what they make or store, and swap dealers are on the other side of their clients. " + TAIL)

# kept for the financial family's callers and tests
URL, CONTRACTS, SOURCE, NOTE = FINANCIAL.url, FINANCIAL.contracts, FINANCIAL.source, FINANCIAL.note
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 12
MIN_RANK_WEEKS = 20
CHECK_WEEKS = 26


def _i(x) -> int | None:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def parse(rows: list[dict], groups: list = GROUPS) -> list[dict]:
    """Weeks, oldest first. A week with a missing or unreadable field is skipped; every kept week carries the result of its own totals check."""
    out = []
    for r in rows:
        try:
            d = date.fromisoformat(str(r["report_date_as_yyyy_mm_dd"])[:10])
        except (KeyError, ValueError):
            continue
        oi, tl, ts = _i(r.get("open_interest_all")), _i(r.get("tot_rept_positions_long_all")), _i(r.get("tot_rept_positions_short"))
        nl, ns = _i(r.get("nonrept_positions_long_all")), _i(r.get("nonrept_positions_short_all"))
        rec: dict = {"date": d, "open_interest": oi, "oi_change": _i(r.get("change_in_open_interest_all")), "traders": _i(r.get("traders_tot_all"))}
        ok = bool(oi) and None not in (tl, ts, nl, ns)
        sum_l = sum_s = 0
        for key, _, _, fl, fs, fp in groups:
            lg, sh = _i(r.get(fl)), _i(r.get(fs))
            sp = 0 if fp is None else _i(r.get(fp))
            if None in (lg, sh, sp):
                ok = False
                break
            rec[key] = {"long": lg, "short": sh, "spread": sp, "net": lg - sh}
            sum_l += lg + sp
            sum_s += sh + sp
        if not ok:
            continue
        rec["adds_up"] = sum_l == tl and sum_s == ts and tl + nl == oi and ts + ns == oi
        out.append(rec)
    out.sort(key=lambda x: x["date"])
    if not out:
        raise ValueError("the source returned no readable reports")
    return out


def rank(values: list[int], v: int) -> float | None:
    """Share of the last weeks (including this one) whose net position was at or below this week's, 0 to 100."""
    if len(values) < MIN_RANK_WEEKS:
        return None
    return round(sum(1 for x in values if x <= v) / len(values) * 100)


def checks(weeks: list[dict]) -> dict:
    """The self-checks over the newest weeks: every week's groups add up to the report's own totals, and the reported change in open interest equals the difference of consecutive weeks."""
    recent = weeks[-CHECK_WEEKS:]
    adds = all(w["adds_up"] for w in recent)
    mism = 0
    pairs = 0
    for a, b in zip(recent, recent[1:]):
        if (b["date"] - a["date"]).days == 7 and b["oi_change"] is not None:
            pairs += 1
            if b["open_interest"] - a["open_interest"] != b["oi_change"]:
                mism += 1
    return {"weeks_checked": len(recent), "groups_add_up": adds, "oi_change_pairs": pairs, "oi_change_mismatches": mism, "ok": adds and mism == 0}


def summarize_contract(weeks: list[dict], today: date, groups: list = GROUPS) -> dict:
    last, prev = weeks[-1], weeks[-2] if len(weeks) >= 2 else None
    ck = checks(weeks)
    if not ck["ok"]:
        return {"available": False, "reason": "The report's groups did not add up to its own totals, so nothing is shown for this contract.", "checks": ck}
    year = weeks[-52:]
    out = []
    for key, name, who, *_ in groups:
        g = last[key]
        nets = [w[key]["net"] for w in year]
        pg = prev[key] if prev and (last["date"] - prev["date"]).days == 7 else None
        out.append({"key": key, "name": name, "who": who, "long": g["long"], "short": g["short"], "spread": g["spread"], "net": g["net"], "net_change": None if not pg else g["net"] - pg["net"],
                    "long_pct_oi": round(g["long"] / last["open_interest"] * 100, 1), "short_pct_oi": round(g["short"] / last["open_interest"] * 100, 1),
                    "net_rank_1y": rank(nets, g["net"]), "net_history": [w[key]["net"] for w in weeks[-26:]]})
    age = (today - last["date"]).days
    return {"available": True, "date": last["date"].isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "open_interest": last["open_interest"],
            "open_interest_change": last["oi_change"], "traders": last["traders"], "weeks_of_history": len(weeks), "groups": out, "checks": ck}


def summarize(per_contract: dict[str, list[dict]], today: date, fam: Family = FINANCIAL) -> dict:
    items = []
    for code, name, what in fam.contracts:
        base = {"code": code, "name": name, "what": what}
        weeks = per_contract.get(code)
        if not weeks:
            items.append({**base, "available": False, "reason": "no readable reports came back for this contract"})
        else:
            items.append({**base, **summarize_contract(weeks, today, fam.groups)})
    live = [x for x in items if x.get("available")]
    if not live:
        return {"available": False, "reason": "no contract could be read and verified", "contracts": items}
    newest = max(date.fromisoformat(x["date"]) for x in live)
    age = (today - newest).days
    return {"available": True, "date": newest.isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": fam.source, "url": PAGE, "contracts": items, "note": fam.note}


class CftcFutures:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False, family: Family = FINANCIAL):
        self._client, self.demo, self.fam = client, demo, family
        self._cache: tuple[float, dict] | None = None

    async def _one(self, c: httpx.AsyncClient, code: str) -> list[dict] | None:
        try:
            r = await c.get(self.fam.url, params={"$where": f"cftc_contract_market_code='{code}'", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 60, "$select": self.fam.select},
                            headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            return parse(r.json(), self.fam.groups)
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            return None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real CFTC positions are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            got = await asyncio.gather(*[self._one(c, code) for code, _, _ in self.fam.contracts])
            res = {**base, **summarize({code: w for (code, _, _), w in zip(self.fam.contracts, got)}, now.date(), self.fam)}
            if not res.get("available"):
                res["reason"] = f"CFTC could not be read right now ({res.get('reason', 'unknown')})"
            self._cache = (time.monotonic() + (TTL if res.get("available") else FAIL_TTL), res)
            return res
        finally:
            if self._client is None:
                await c.aclose()


class CftcCommodities(CftcFutures):
    """Gold, crude oil, copper and natural gas futures from the CFTC's Disaggregated report."""

    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        super().__init__(client=client, demo=demo, family=COMMODITY)
