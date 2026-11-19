"""US housing starts (Census Bureau and HUD via FRED): parsed from real responses (fetched 2026-11-17 08:18 UTC: 813 monthly values per series since 1959-01, newest 2026-09). Hand-worked level, changes, parts, ten-year growth range and remainders (recomputed a second way in plain Python before the module was written), every refusal with its boundary and the window it looks at, the real shocks of 1982 to 2021 that must NOT be refused, a short history, the overdue label, caching, failure, demo, the route, the plain-client rule, and that the two-to-four-unit series (calculated by a third party from the other two) is never asked for."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import housingstarts as H
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_housing.json").read_text())
TODAY = date(2026, 11, 17)
NOW = datetime(2026, 11, 17, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)


def _data():
    return {sid: H.parse(F[sid], sid) for sid in H.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _idx(d):
    """Months from LAST: 0 for the newest month, -1 for the one before."""
    return (d.year * 12 + d.month) - (LAST.year * 12 + LAST.month)


def _synthetic(total=lambda d: 1300, single=None, five=None, n_months=40):
    """A clean synthetic set: `n_months` months ending 2026-09, a total of `total(month)` thousand homes, single-family 70% of it and five-or-more 28% (whole thousands, so a remainder of about 2% is left) or `single(month)` and `five(month)`. For testing one check at a time."""
    months = [H._months_back(LAST, i) for i in range(n_months - 1, -1, -1)]
    tot = {d: float(total(d)) for d in months}
    sf = {d: float(single(d)) if single else float(int(tot[d]) * 70 // 100) for d in months}
    mf = {d: float(five(d)) if five else float(int(tot[d]) * 28 // 100) for d in months}
    return {"HOUST": tot, "HOUST1F": sf, "HOUST5F": mf}


def _exact(total=lambda d: 1300, n_months=40):
    """The same, with the two parts adding up to the total exactly (single-family 70%, five-or-more the rest): a remainder of zero, so the edge of the parts check can be reached."""
    return _synthetic(total, single=lambda d: int(total(d)) * 70 // 100, five=lambda d: int(total(d)) - int(total(d)) * 70 // 100, n_months=n_months)


def test_latest_level_changes_parts_growth_and_remainders_by_hand():
    s = H.summarize(_data(), TODAY)
    assert (s["date"], s["month"], s["age_days"], s["freshness"]) == ("2026-09-01", "2026-09", 77, "CURRENT")
    assert s["level_thousands"] == 1221.0
    assert s["change_1m_pct"] == -5.2 and s["change_3m_pct"] == -15.1 and s["change_1y_pct"] == -7.4          # against 1,288 (Aug), 1,439 (Jun) and 1,319 (Sep 2025): -5.20%, -15.15%, -7.43%
    assert s["single_family"] == {"level_thousands": 859.0, "share_pct": 70.4, "change_1m_pct": -4.6, "change_1y_pct": 2.6}       # 859 against 900 (-4.56%) and 837 (+2.63%); 70.356% of the total
    assert s["five_plus"] == {"level_thousands": 349.0, "share_pct": 28.6, "change_1m_pct": -7.2, "change_1y_pct": -25.9}         # 349 against 376 (-7.18%) and 471 (-25.90%); 28.583% of the total
    assert s["growth"] == {"months": 120, "slowest": {"pct": -26.4, "month": "2020-04"}, "fastest": {"pct": 59.1, "month": "2021-04"}, "share_slower_pct": 18}    # 2016-10 to 2026-09; 22 of the 120 months changed less than -7.43% over the year
    assert s["parts"] == {"months_checked": 24, "smallest_remainder_thousands": 6.0, "largest_remainder_thousands": 30.0,
                          "newest": {"month": "2026-09", "total_thousands": 1221.0, "single_family_thousands": 859.0, "five_plus_thousands": 349.0, "remainder_thousands": 13.0}}       # 1,221 - 859 - 349 = 13
    assert all(s["checks"].values()) and "not a market signal or a forecast" in s["note"] and "estimate that is revised" in s["note"] and "no exact parts-add-up check" in s["note"]


def test_levels_keep_one_decimal_for_the_total_and_for_each_part():
    s = H.summarize(_synthetic(lambda d: 1300.46 if d == LAST else 1300, single=lambda d: 910.46, five=lambda d: 364.04), TODAY)
    assert s["level_thousands"] == 1300.5 and s["single_family"]["level_thousands"] == 910.5 and s["five_plus"]["level_thousands"] == 364.0       # the real series are whole thousands today; the card does not round them to whole ones in case they stop being


def test_the_history_is_the_last_36_months_in_thousands_oldest_first():
    s = H.summarize(_data(), TODAY)
    assert len(s["history"]) == 36 and s["history"][0] == {"date": "2023-10-01", "level": 1380.0} and s["history"][-1] == {"date": "2026-09-01", "level": 1221.0}
    assert [h["date"] for h in s["history"]] == sorted(h["date"] for h in s["history"])


def test_a_short_history_says_not_available_for_what_it_cannot_compute():
    d = _data()
    keep = LAST - timedelta(days=300)                                                # about 10 months
    d = {sid: {k: v for k, v in s.items() if k >= keep} for sid, s in d.items()}
    s = H.summarize(d, TODAY)
    assert s["change_1y_pct"] is None and s["growth"] is None and s["change_3m_pct"] == -15.1 and s["level_thousands"] == 1221.0
    assert s["single_family"]["change_1y_pct"] is None and s["five_plus"]["change_1y_pct"] is None and s["single_family"]["change_1m_pct"] == -4.6


def test_the_ten_year_growth_comparison_needs_at_least_60_months_of_yearly_growth():
    assert H.summarize(_synthetic(n_months=71), TODAY)["growth"] is None             # 71 months give 59 yearly growth figures
    g = H.summarize(_synthetic(n_months=72), TODAY)["growth"]                        # 72 give 60
    assert g == {"months": 60, "slowest": {"pct": 0.0, "month": g["slowest"]["month"]}, "fastest": {"pct": 0.0, "month": g["fastest"]["month"]}, "share_slower_pct": 0}


def test_overdue_after_90_days_from_the_first_of_the_month():
    assert H.summarize(_data(), LAST + timedelta(days=90))["freshness"] == "CURRENT"
    s = H.summarize(_data(), LAST + timedelta(days=91))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 91


def test_the_level_range_is_300_to_3000_thousand_inclusive():
    assert H.summarize(_synthetic(lambda d: 300), TODAY)["level_thousands"] == 300.0
    assert H.summarize(_synthetic(lambda d: 3000), TODAY)["level_thousands"] == 3000.0
    with pytest.raises(ValueError, match="plausible range"):
        H.summarize(_synthetic(lambda d: 299), TODAY)
    with pytest.raises(ValueError, match="plausible range"):
        H.summarize(_synthetic(lambda d: 3001), TODAY)
    d = _data()
    for sid in d:
        for k in d[sid]:
            d[sid][k] *= 10.0
    with pytest.raises(ValueError, match="plausible range"):                         # a x10 slip in every series
        H.summarize(d, TODAY)
    d = _data()
    for sid in d:
        for k in d[sid]:
            d[sid][k] /= 10.0
    with pytest.raises(ValueError, match="plausible range"):                         # a /10 slip in every series
        H.summarize(d, TODAY)


def test_the_range_check_looks_at_the_last_24_months_and_no_further_back():
    def low_until(cut):
        """Every month up to `cut` months back from 2026-09 is under the floor (299); the later ones are in range (320): a step of 7.0% that the move and year-on-year checks allow."""
        return _synthetic(lambda d: 299 if _idx(d) <= -cut else 320)
    with pytest.raises(ValueError, match="plausible range"):
        H.summarize(low_until(23), TODAY)                                            # the oldest month of the window (23 months before 2026-09) is under the floor: inside
    assert H.summarize(low_until(24), TODAY)["available"]                            # only the month before the window and older are under the floor: outside every window


def test_the_months_must_follow_each_other_in_the_last_24_and_start_on_the_1st():
    def without(pos):
        d = _synthetic()
        del d["HOUST"][sorted(d["HOUST"])[pos]]
        return d
    with pytest.raises(ValueError, match="skip a month"):
        H.summarize(without(-10), TODAY)
    with pytest.raises(ValueError, match="skip a month"):
        H.summarize(without(-24), TODAY)                                             # the oldest month of the window: the gap sits between it and the next one
    assert H.summarize(without(-25), TODAY)["available"]                             # the gap sits before the oldest month of the window: not looked at
    d = _synthetic()
    d["HOUST"][date(2026, 8, 15)] = d["HOUST"].pop(date(2026, 8, 1))
    with pytest.raises(ValueError, match="not the 1st"):
        H.summarize(d, TODAY)


def test_a_date_that_is_not_the_1st_matters_only_inside_the_window():
    d = _synthetic()
    old = H._months_back(LAST, 30)
    d["HOUST"][date(old.year, old.month, 15)] = d["HOUST"].pop(old)                  # 30 months back: outside the 24-month window
    assert H.summarize(d, TODAY)["available"]


def test_a_one_month_move_under_minus_35_or_over_plus_40_percent_is_refused():
    def last_month(level_last):
        return _synthetic(lambda d: level_last if d == LAST else 1000)
    assert H.summarize(last_month(1399), TODAY)["change_1m_pct"] == 39.9            # +39.9%
    assert H.summarize(last_month(651), TODAY)["change_1m_pct"] == -34.9            # -34.9%
    with pytest.raises(ValueError, match=r"changed by 40.1% in 2026-09, outside -35% to \+40%"):
        H.summarize(last_month(1401), TODAY)
    with pytest.raises(ValueError, match=r"changed by -35.1% in 2026-09, outside -35% to \+40%"):
        H.summarize(last_month(649), TODAY)


def test_the_month_move_check_looks_at_the_last_24_months_and_no_further_back():
    def step_up_at(months_back, f):
        return _synthetic(lambda d: 1000 * f if _idx(d) >= -months_back else 1000)
    with pytest.raises(ValueError, match="changed by 50.0% in"):
        H.summarize(step_up_at(22, 1.5), TODAY)                                      # the step lands on the 2nd month of the window (22 months before 2026-09): the move into it is inside
    assert H.summarize(step_up_at(23, 1.5), TODAY)["available"]                      # the step lands on the first month of the window: the move into it comes from before the window


def test_year_on_year_change_over_115_percent_or_under_minus_65_is_refused_and_real_shocks_are_not():
    def ramp(rate, base):
        return _synthetic(lambda d: base * (1 + rate) ** max(0, 12 + _idx(d)))       # flat, then twelve months of steady change ending in 2026-09
    def yearly(rate):
        return round(100 * ((1 + rate) ** 12 - 1), 1)                                # the year-on-year change of twelve steady months, worked outside the module
    assert yearly(0.06583) == 114.9 and H.summarize(ramp(0.06583, 800), TODAY)["change_1y_pct"] == 114.9      # +114.9%: just under the +115% limit, like the real +96.2% of February 1983
    with pytest.raises(ValueError, match=r"changed by 115.1% over the year to 2026-09, outside -65% to \+115%"):
        H.summarize(ramp(0.06591, 800), TODAY)                                       # +115.1%: just over it
    assert yearly(-0.08355) == -64.9 and H.summarize(ramp(-0.08355, 2500), TODAY)["change_1y_pct"] == -64.9  # -64.9%: just inside, like the real -54.8% of January 2009
    with pytest.raises(ValueError, match=r"changed by -65.1% over the year to 2026-09, outside -65% to \+115%"):
        H.summarize(ramp(-0.08399, 2500), TODAY)                                     # -65.1%


def test_the_real_shocks_of_1982_to_2021_are_not_refused():
    cuts = ((date(1982, 7, 1), date(1982, 9, 20), 29.3, 12.0),                      # the largest rise on the month, +29.27%
            (date(1983, 2, 1), date(1983, 4, 20), 7.1, 96.2),                       # the largest rise on the year, +96.19%
            (date(1984, 3, 1), date(1984, 5, 20), -26.4, 3.5),                      # the largest fall on the month, -26.42%
            (date(2009, 1, 1), date(2009, 3, 20), -12.5, -54.8),                    # the largest fall on the year, -54.80%
            (date(2020, 4, 1), date(2020, 6, 20), -26.1, -26.4),                    # the spring of 2020
            (date(2021, 4, 1), date(2021, 6, 20), -11.8, 59.1))                     # and its rebound
    for cut, today, month_move, year_move in cuts:
        d = {sid: {k: v for k, v in s.items() if k <= cut} for sid, s in _data().items()}
        s = H.summarize(d, today)
        assert s["available"] and s["month"] == f"{cut.year}-{cut.month:02d}" and (s["change_1m_pct"], s["change_1y_pct"]) == (month_move, year_move) and s["growth"] is not None


def test_single_family_plus_five_or_more_may_not_exceed_the_total_by_more_than_one_thousand_in_any_of_the_last_24_months():
    def off(month, by, part="HOUST5F"):
        d = _exact()
        d[part][month] += by
        return d
    assert H.summarize(off(LAST, 1.0), TODAY)["parts"]["newest"]["remainder_thousands"] == -1.0           # rounding-sized: allowed
    assert H.summarize(off(LAST, -50.0), TODAY)["parts"]["newest"]["remainder_thousands"] == 50.0          # a remainder (the buildings of two to four units) is what the real record shows
    with pytest.raises(ValueError, match=r"are \+1.1 thousand above the total in 2026-09"):
        H.summarize(off(LAST, 1.1), TODAY)
    with pytest.raises(ValueError, match="above the total in 2026-09"):
        H.summarize(off(LAST, 100.0, part="HOUST1F"), TODAY)                         # the other part too
    oldest = H._months_back(LAST, 23)
    with pytest.raises(ValueError, match="above the total in 2024-10"):
        H.summarize(off(oldest, 50.0), TODAY)                                        # the 24th month back: inside
    assert H.summarize(off(H._months_back(LAST, 24), 50.0), TODAY)["available"]      # the 25th: outside


def test_the_smallest_and_largest_remainders_over_the_window_are_reported_not_the_first_or_the_last_one():
    d = _exact()
    d["HOUST5F"][H._months_back(LAST, 10)] -= 0.5                                    # remainder +0.5
    d["HOUST5F"][H._months_back(LAST, 5)] -= 1.0                                     # remainder +1.0
    d["HOUST5F"][H._months_back(LAST, 2)] += 0.25                                    # remainder -0.25
    p = H.summarize(d, TODAY)["parts"]
    assert p["smallest_remainder_thousands"] == -0.25 and p["largest_remainder_thousands"] == 1.0 and p["newest"]["remainder_thousands"] == 0.0 and p["months_checked"] == 24


def test_single_family_homes_must_be_between_40_and_95_percent_of_the_total():
    def share(x, month=None):
        """Single-family x of 1,000 (and five-or-more 990 - x, a remainder of 10) in `month` only, or in every month."""
        return _synthetic(lambda d: 1000, single=lambda d: x if month in (None, d) else 700, five=lambda d: 990 - x if month in (None, d) else 290)
    assert H.summarize(share(400), TODAY)["single_family"]["share_pct"] == 40.0                            # exactly 40% in every month
    assert H.summarize(share(950), TODAY)["single_family"]["share_pct"] == 95.0                            # exactly 95% in every month
    with pytest.raises(ValueError, match="single-family homes are 39.9% of housing starts in 2026-09, outside 40% to 95%"):
        H.summarize(share(399, LAST), TODAY)
    with pytest.raises(ValueError, match="single-family homes are 95.1% of housing starts in 2026-09, outside 40% to 95%"):
        H.summarize(share(951, LAST), TODAY)
    oldest = H._months_back(LAST, 23)
    with pytest.raises(ValueError, match="single-family homes are 30.0% of housing starts in 2024-10"):
        H.summarize(share(300, oldest), TODAY)                                       # the 24th month back: inside
    assert H.summarize(share(300, H._months_back(LAST, 24)), TODAY)["available"]     # the 25th: outside
    d = _data()
    d["HOUST1F"], d["HOUST5F"] = d["HOUST5F"], d["HOUST1F"]                          # the two parts swapped: they still add up the same, but single-family would be about 29% of the total
    with pytest.raises(ValueError, match="single-family homes are 29.0% of housing starts in 2024-10, outside 40% to 95%"):      # the oldest month of the window is the first one named
        H.summarize(d, TODAY)


def test_a_part_missing_a_month_or_a_series_ending_in_another_month_is_refused():
    d = _synthetic()
    del d["HOUST1F"][LAST]
    with pytest.raises(ValueError, match="end in different months"):
        H.summarize(d, TODAY)
    d = _synthetic()
    d["HOUST5F"][date(2026, 10, 1)] = 360.0                                          # a part that is a month AHEAD of the total
    with pytest.raises(ValueError, match="end in different months"):
        H.summarize(d, TODAY)
    for part in ("HOUST1F", "HOUST5F"):
        d = _synthetic()
        del d[part][H._months_back(LAST, 5)]
        with pytest.raises(ValueError, match="single-family or five-or-more-unit starts are missing for 2026-04"):
            H.summarize(d, TODAY)
    d = _synthetic()
    del d["HOUST1F"][H._months_back(LAST, 24)]                                       # a hole before the window: not looked at
    assert H.summarize(d, TODAY)["parts"]["months_checked"] == 24


def test_missing_values_are_skipped_never_filled():
    s = H.parse("observation_date,HOUST\n2026-07-01,1369\n2026-08-01,.\n2026-09-01,\n", "HOUST")
    assert s == {date(2026, 7, 1): 1369.0}


def test_the_series_calculated_by_a_third_party_is_not_asked_for():
    assert set(H.SERIES) == {"HOUST", "HOUST1F", "HOUST5F"} and "HOUST2F" not in H.SERIES
    assert "calculated by a third party" in H.__doc__ and "Haver Analytics" in H.__doc__ and "NO exact" in H.__doc__          # the module says why there is no exact parts check


def test_overview_fetches_three_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = H.HousingStarts(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["level_thousands"] == 1221.0 and n["n"] == 3 and r["source"].startswith("U.S. Census Bureau") and r["url"] == "https://fred.stlouisfed.org/series/HOUST"
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(H.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = H.HousingStarts(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 3
    clock["t"] += H.FAIL_TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 3                                                               # still the failure from the cache
    clock["t"] += 2
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 6       # two minutes on it asks again
    clock["t"] += H.TTL - 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6
    clock["t"] += 2
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 9 and (H.FAIL_TTL, H.TTL) == (120.0, 21600.0)


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(H.HousingStarts(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "level_thousands" not in r
    bad = dict(F)
    bad["HOUST"] = F["HOUST"].replace("2026-09-01,1221", "2026-09-01,12210")                                       # a decimal slip in the newest value: a check failing shows nothing either
    r = asyncio.run(H.HousingStarts(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "plausible range" in r["reason"] and "level_thousands" not in r


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(H.HousingStarts(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "Housing starts could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(H.HousingStarts(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "level_thousands" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/housing-starts")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(H.HousingStarts(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(H.SERIES) == {"HOUST", "HOUST1F", "HOUST5F"}
    start = date.fromisoformat(seen[0].url.params["cosd"])
    assert 4100 <= (date.today() - start).days <= 4300                                       # about 11.5 years, enough for ten years of yearly change
