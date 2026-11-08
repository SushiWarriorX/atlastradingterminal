"""CFTC Commitments of Traders (Traders in Financial Futures) for CME Bitcoin futures: who holds the contracts, by trader group. Free official data from the CFTC, no key.

What it is: every Tuesday the CFTC counts the open Bitcoin futures contracts at the CME held by dealers, asset managers, leveraged funds and others, and publishes the table that Friday.
What it is not: all of Bitcoin. It covers only the CME's regulated Bitcoin futures, not spot, perpetual swaps or ETFs. And "net short" is not the same as "bearish": leveraged
funds are often hedge funds running the basis trade (long spot or ETF, short futures), so their futures shorts can be the other half of a bullish-looking hold.
Everything shown is read from the report or simple arithmetic on it (net = long minus short, share of open interest, change, one-year rank). A failure says so and shows nothing.
"""
from __future__ import annotations

import time
from datetime import date, datetime, timezone

import httpx

URL = "https://publicreporting.cftc.gov/resource/gpe5-46if.json"
CODE = "133741"                    # BITCOIN - CHICAGO MERCANTILE EXCHANGE
SOURCE = "CFTC Commitments of Traders, Traders in Financial Futures, CME Bitcoin futures (official, free public data)"
FIELDS = ("report_date_as_yyyy_mm_dd,open_interest_all,change_in_open_interest_all,dealer_positions_long_all,dealer_positions_short_all,asset_mgr_positions_long,asset_mgr_positions_short,"
          "lev_money_positions_long,lev_money_positions_short,other_rept_positions_long,other_rept_positions_short,traders_tot_all")
GROUPS = [("lev_money", "Leveraged funds", "hedge funds and similar fast-moving money"), ("asset_mgr", "Asset managers", "institutional investors such as funds and pensions"),
          ("dealer", "Dealers", "banks and market makers, usually on the other side of clients"), ("other_rept", "Other reportable", "large traders that fit none of the groups above")]
TTL = 6 * 3600.0
FAIL_TTL = 120.0
OVERDUE_AFTER_DAYS = 12        # Tuesday data is published on Friday; a missed week still leaves the newest report under 12 days old for a while
MIN_RANK_WEEKS = 20


def _i(x) -> int | None:
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return None


def parse(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        try:
            d = date.fromisoformat(str(r["report_date_as_yyyy_mm_dd"])[:10])
        except (KeyError, ValueError):
            continue
        rec = {"date": d, "open_interest": _i(r.get("open_interest_all")), "oi_change": _i(r.get("change_in_open_interest_all")), "traders": _i(r.get("traders_tot_all"))}
        for key, _, _ in GROUPS:
            lg = _i(r.get({"lev_money": "lev_money_positions_long", "asset_mgr": "asset_mgr_positions_long", "dealer": "dealer_positions_long_all", "other_rept": "other_rept_positions_long"}[key]))
            sh = _i(r.get({"lev_money": "lev_money_positions_short", "asset_mgr": "asset_mgr_positions_short", "dealer": "dealer_positions_short_all", "other_rept": "other_rept_positions_short"}[key]))
            rec[key] = None if lg is None or sh is None else {"long": lg, "short": sh, "net": lg - sh}
        if rec["open_interest"]:
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


def summarize(weeks: list[dict], today: date) -> dict:
    last, prev = weeks[-1], weeks[-2] if len(weeks) >= 2 else None
    year = weeks[-52:]
    groups = []
    for key, name, who in GROUPS:
        g = last.get(key)
        if g is None:
            continue
        nets = [w[key]["net"] for w in year if w.get(key)]
        pg = prev.get(key) if prev else None
        groups.append({"key": key, "name": name, "who": who, "long": g["long"], "short": g["short"], "net": g["net"], "net_change": None if not pg else g["net"] - pg["net"],
                       "long_pct_oi": round(g["long"] / last["open_interest"] * 100, 1), "short_pct_oi": round(g["short"] / last["open_interest"] * 100, 1),
                       "net_rank_1y": rank(nets, g["net"]), "net_history": [w[key]["net"] for w in weeks[-26:] if w.get(key)]})
    age = (today - last["date"]).days
    return {"available": True, "date": last["date"].isoformat(), "age_days": age, "freshness": "CURRENT" if age <= OVERDUE_AFTER_DAYS else "OVERDUE", "source": SOURCE, "market": "Bitcoin futures at the CME (regulated, USD)",
            "open_interest": last["open_interest"], "open_interest_change": last["oi_change"], "traders": last["traders"], "weeks_of_history": len(weeks), "groups": groups,
            "note": "Positions are counted on Tuesdays and published the following Friday, so they are at least three days old. This covers CME Bitcoin futures only, not spot, ETFs or perpetual swaps. "
                    "Net short is not the same as bearish: leveraged funds are often short futures as the other half of a basis trade (long spot or ETF, short futures). "
                    "The 1-year rank says where this week's net position sits among the last 52 weeks (0 = lowest, 100 = highest); it is a description, not a signal."}


class CftcBitcoin:
    def __init__(self, client: httpx.AsyncClient | None = None, demo: bool = False):
        self._client, self.demo = client, demo
        self._cache: tuple[float, dict] | None = None

    async def overview(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        base = {"as_of": now.isoformat(), "demo": self.demo}
        if self.demo:
            return {**base, "available": False, "reason": "Demo mode: the real CFTC positions are not shown because made-up values would look real."}
        if self._cache and self._cache[0] > time.monotonic():
            return {**self._cache[1], "as_of": now.isoformat()}
        c = self._client or httpx.AsyncClient(timeout=25)
        try:
            r = await c.get(URL, params={"$where": f"cftc_contract_market_code='{CODE}'", "$order": "report_date_as_yyyy_mm_dd DESC", "$limit": 60, "$select": FIELDS}, headers={"User-Agent": "ATLAS research terminal"})
            if r.status_code != 200:
                raise ValueError(f"HTTP {r.status_code}")
            res = {**base, **summarize(parse(r.json()), now.date())}
            self._cache = (time.monotonic() + TTL, res)
            return res
        except (httpx.HTTPError, ValueError, TypeError, KeyError) as e:
            res = {**base, "available": False, "reason": f"CFTC could not be read right now ({type(e).__name__}: {str(e)[:80]})"}
            self._cache = (time.monotonic() + FAIL_TTL, res)
            return res
        finally:
            if self._client is None:
                await c.aclose()
