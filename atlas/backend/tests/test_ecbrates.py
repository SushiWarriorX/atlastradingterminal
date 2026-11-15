"""ECB key interest rates and the euro short-term rate (ECB Data Portal): parsed from the real responses fetched 2026-11-15 17:28 UTC (the three key-rate series, 2025-01-01 to 2026-11-15, 684 days each; the euro short-term rate,
2025-09-22 to 2026-11-12, 293 business days). Hand-worked figures (recomputed a second way with pandas), every check with its boundary and the window it looks at, what must NOT be refused, what is read and what is left out, the dating by the oldest
series, the stale labels, caching, failure, demo, the route and the request details."""
import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import ecbrates as E
from atlas_api.app import create_app

FIX = Path(__file__).parent / "fixtures"
K = (FIX / "ecb_keyrates.csv").read_bytes().decode()          # as the ECB sent it, with its CRLF line ends
ES = (FIX / "ecb_estr.csv").read_bytes().decode()
END = date(2026, 11, 15)
LAST_ESTR = date(2026, 11, 12)                                  # a Thursday
TODAY = END
NOW = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)


def _series(values, end=END):
    """A daily series from a list of values, oldest first, ending on `end`."""
    n = len(values)
    return {end - timedelta(days=n - 1 - i): v for i, v in enumerate(values)}


def _flat(d=2.0, m=2.15, l=2.4, n=500, end=END):
    return {"DFR": _series([d] * n, end), "MRR_FR": _series([m] * n, end), "MLFR": _series([l] * n, end)}


def _weekdays(n, last=LAST_ESTR):
    out, d = [], last
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d -= timedelta(days=1)
    return sorted(out)


def _estr(vals=None, n=70, gap=-0.06, deposit=2.0, last=LAST_ESTR):
    """Business-day observations, the last `n` weekdays up to `last`: all at deposit + gap, or the given values (oldest first)."""
    if vals is None:
        vals = [round(deposit + gap, 3)] * n
    return dict(zip(_weekdays(len(vals), last), vals))


def _sum(kr=None, estr=None, today=TODAY):
    """summarize() on a synthetic set; unless the euro short-term rate is given it follows the deposit rate 0.06 under it on each of the last 70 weekdays, so a test changing only the key rates does not trip the market check."""
    kr = kr or _flat()
    estr = estr or {d: round(kr["DFR"][d] - 0.06, 3) for d in _weekdays(70) if d in kr["DFR"]}
    return E.summarize(kr, estr, today)


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=K if "/FM/" in req.url.path else ES)


# ---- the real responses, by hand -----------------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_latest_rates_changes_and_market_rate_by_hand():
    s = E.summarize(E.parse_keyrates(K), E.parse_estr(ES), TODAY)
    assert (s["date"], s["age_days"], s["freshness"], s["year_ago_date"]) == ("2026-11-15", 0, "CURRENT", "2025-11-15")
    assert [r["id"] for r in s["rates"]] == ["DFR", "MRR_FR", "MLFR"]
    by = {r["id"]: r for r in s["rates"]}
    assert by["DFR"] == {"id": "DFR", "name": "Deposit facility rate", "meaning": "what the ECB pays banks for money left with it overnight", "rate": 2.5, "above_deposit_rate": None, "year_ago": 2.0, "change_1y": 0.5,
                         "last_change": {"date": "2026-09-16", "from": 2.25, "to": 2.5, "change": 0.25}}
    assert by["MRR_FR"] == {"id": "MRR_FR", "name": "Main refinancing rate", "meaning": "what banks pay for the ECB's regular one-week loans at a fixed rate", "rate": 2.65, "above_deposit_rate": 0.15, "year_ago": 2.15,
                            "change_1y": 0.5, "last_change": {"date": "2026-09-16", "from": 2.4, "to": 2.65, "change": 0.25}}
    assert by["MLFR"] == {"id": "MLFR", "name": "Marginal lending rate", "meaning": "what banks pay to borrow from the ECB overnight", "rate": 2.9, "above_deposit_rate": 0.4, "year_ago": 2.4,
                          "change_1y": 0.5, "last_change": {"date": "2026-09-16", "from": 2.65, "to": 2.9, "change": 0.25}}
    assert all(s["checks"].values()) and len(s["checks"]) == 6
    assert s["url"].startswith("https://www.ecb.europa.eu/stats/") and s["source"].startswith("European Central Bank")


def test_the_last_six_deposit_rate_changes_by_hand_newest_first():
    s = E.summarize(E.parse_keyrates(K), E.parse_estr(ES), TODAY)
    assert s["decisions"] == [{"date": "2026-09-16", "from": 2.25, "to": 2.5, "change": 0.25}, {"date": "2026-06-17", "from": 2.0, "to": 2.25, "change": 0.25},
                              {"date": "2025-06-11", "from": 2.25, "to": 2.0, "change": -0.25}, {"date": "2025-04-23", "from": 2.5, "to": 2.25, "change": -0.25},
                              {"date": "2025-03-12", "from": 2.75, "to": 2.5, "change": -0.25}, {"date": "2025-02-05", "from": 3.0, "to": 2.75, "change": -0.25}]


def test_the_market_rate_beside_the_deposit_rate_by_hand():
    s = E.summarize(E.parse_keyrates(K), E.parse_estr(ES), TODAY)
    # 60 business days 2026-08-21 to 2026-11-12; the newest is 2.443 against a deposit rate of 2.50 (-0.057); across the 60 days the gap is between -0.065 and -0.055
    assert s["market"] == {"date": "2026-11-12", "age_days": 3, "freshness": "CURRENT", "rate": 2.443, "deposit_rate": 2.5, "gap": -0.057, "observations": 60, "first_date": "2026-08-21", "gap_low": -0.065, "gap_high": -0.055}


# ---- reading the CSV ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_the_csv_is_read_by_key_and_what_cannot_be_read_is_left_out_never_filled():
    text = ("KEY,FREQ,TIME_PERIOD,OBS_VALUE\r\n"
            "FM.D.U2.EUR.4F.KR.DFR.LEV,D,2026-11-13,2.5\r\n"
            "FM.D.U2.EUR.4F.KR.DFR.LEV,D,2026-11-14,\r\n"                  # blank: left out
            "FM.D.U2.EUR.4F.KR.DFR.LEV,D,2026-11-15,nan\r\n"                # not a finite number
            "FM.D.U2.EUR.4F.KR.DFR.LEV,D,2026-11-16,inf\r\n"
            "FM.D.U2.EUR.4F.KR.DFR.LEV,D,2026-W46,2.5\r\n"                  # not a date
            "FM.D.U2.EUR.4F.KR.MRR_FR.LEV,D,2026-11-13,2.65\r\n"
            "FM.D.U2.EUR.4F.KR.MLFR.LEV,D,2026-11-13,2.9\r\n"
            "FM.D.U2.EUR.4F.KR.DFR.MAT,D,2026-11-13,9\r\n")                 # another series: ignored
    assert E.parse_keyrates(text) == {"DFR": {date(2026, 11, 13): 2.5}, "MRR_FR": {date(2026, 11, 13): 2.65}, "MLFR": {date(2026, 11, 13): 2.9}}


def test_the_real_key_rate_response_reads_to_684_days_of_each_series():
    kr = E.parse_keyrates(K)
    assert {i: len(kr[i]) for i in kr} == {"DFR": 684, "MRR_FR": 684, "MLFR": 684}
    assert min(kr["DFR"]) == date(2025, 1, 1) and max(kr["DFR"]) == END and kr["DFR"][date(2025, 1, 1)] == 3.0
    es = E.parse_estr(ES)
    assert len(es) == 293 and min(es) == date(2025, 9, 22) and max(es) == LAST_ESTR and es[LAST_ESTR] == 2.443


def test_two_values_for_one_day_are_an_error_not_a_choice():
    row = "FM.D.U2.EUR.4F.KR.DFR.LEV,D,2026-11-13,%s\r\n"
    with pytest.raises(ValueError, match="deposit facility rate has two values for 2026-11-13"):
        E.parse_keyrates("KEY,FREQ,TIME_PERIOD,OBS_VALUE\r\n" + row % "2.5" + row % "2.55")
    with pytest.raises(ValueError, match="euro short-term rate has two values for 2026-11-12"):
        E.parse_estr("KEY,TIME_PERIOD,OBS_VALUE\r\n" + "EST.B.EU000A2X2A25.WT,2026-11-12,2.443\r\nEST.B.EU000A2X2A25.WT,2026-11-12,2.444\r\n")


def test_a_missing_series_is_named():
    base = "KEY,TIME_PERIOD,OBS_VALUE\r\nFM.D.U2.EUR.4F.KR.DFR.LEV,2026-11-13,2.5\r\nFM.D.U2.EUR.4F.KR.MRR_FR.LEV,2026-11-13,2.65\r\n"
    with pytest.raises(ValueError, match="no values for the marginal lending rate$"):
        E.parse_keyrates(base)
    with pytest.raises(ValueError, match="no values for the deposit facility rate or the main refinancing rate or the marginal lending rate$"):
        E.parse_keyrates("KEY,TIME_PERIOD,OBS_VALUE\r\n")
    with pytest.raises(ValueError, match="no euro short-term rate"):
        E.parse_estr("KEY,TIME_PERIOD,OBS_VALUE\r\nFM.D.U2.EUR.4F.KR.DFR.LEV,2026-11-13,2.5\r\n")          # another series' row does not count


# ---- the key-rate checks --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_every_calendar_day_of_the_last_400_must_be_present_and_older_gaps_are_not_looked_at():
    k = _flat(n=500)
    del k["MRR_FR"][END - timedelta(days=399)]                     # inside the window: the day before it is END-400, so the window has a hole
    with pytest.raises(ValueError, match="main refinancing rate skips a day in its last 400"):
        _sum(k)
    k = _flat(n=500)
    del k["MRR_FR"][END - timedelta(days=400)]                     # one day outside the window of 400
    assert _sum(k)["available"]
    k = _flat(n=500)
    del k["DFR"][END - timedelta(days=100)]
    with pytest.raises(ValueError, match="deposit facility rate skips a day"):
        _sum(k)


def test_400_days_are_needed_and_399_are_not_enough():
    assert _sum(_flat(n=400))["available"]
    with pytest.raises(ValueError, match="marginal lending rate has 399 days, 400 are needed"):
        _sum({**_flat(n=400), "MLFR": _series([2.4] * 399)})


def test_values_must_be_between_minus_1_5_and_10_percent_inclusive():
    assert _sum(_flat(9.8, 9.9, 10.0))["rates"][2]["rate"] == 10.0
    assert _sum(_flat(-1.5, -1.4, -1.3), _estr(gap=0.0, deposit=-1.5))["rates"][0]["rate"] == -1.5       # the euro short-term rate must itself stay inside -1.5
    first = (END - timedelta(days=399)).isoformat()                                          # every day is out of range: the oldest day of the window is the first reported
    with pytest.raises(ValueError, match=f"marginal lending rate is 10.05% on {first}, outside -1.5% to 10%"):
        _sum(_flat(9.85, 9.95, 10.05))
    with pytest.raises(ValueError, match=f"deposit facility rate is -1.55% on {first}, outside -1.5% to 10%"):
        _sum(_flat(-1.55, -1.45, -1.35))
    newest_high = {"DFR": _series([2.0] * 500), "MRR_FR": _series([2.15] * 500), "MLFR": _series([2.4] * 499 + [10.05])}            # only the newest day
    with pytest.raises(ValueError, match="marginal lending rate is 10.05% on 2026-11-15"):
        _sum(newest_high)
    newest_low = {"DFR": _series([2.0] * 499 + [-1.55]), "MRR_FR": _series([5.0] * 500), "MLFR": _series([6.0] * 500)}
    with pytest.raises(ValueError, match="deposit facility rate is -1.55% on 2026-11-15"):
        _sum(newest_low)


def test_values_must_be_multiples_of_0_05():
    with pytest.raises(ValueError, match="main refinancing rate is 2.17% .* not a multiple of 0.05"):
        _sum(_flat(2.0, 2.17, 2.4))
    with pytest.raises(ValueError, match="not a multiple of 0.05"):                       # a unit slip, percent divided by 100: in range and in order, but not a quoted step
        _sum(_flat(0.02, 0.0215, 0.024))
    assert _sum(_flat(-0.1, 0.15, 0.4))["rates"][0]["rate"] == -0.1                         # a negative rate such as the real 2014 to 2022 ones is a multiple of 0.05 too


def test_a_one_day_move_over_1_5_points_is_refused_and_exactly_1_5_is_not():
    def stepped(to):
        return {"DFR": _series([2.0] * 499 + [to]), "MRR_FR": _series([5.0] * 500), "MLFR": _series([6.0] * 500)}
    assert _sum(stepped(3.5))["rates"][0]["rate"] == 3.5
    with pytest.raises(ValueError, match="deposit facility rate moved \\+1.55 points in one day, to 2026-11-15"):
        _sum(stepped(3.55))
    down = {"DFR": _series([4.0] * 499 + [2.45]), "MRR_FR": _series([5.0] * 500), "MLFR": _series([6.0] * 500)}
    with pytest.raises(ValueError, match="moved -1.55 points"):
        _sum(down)


def test_the_three_rates_must_be_in_order_on_every_common_day_and_strictly():
    first = (END - timedelta(days=399)).isoformat()                                          # every day breaks the order: the oldest day of the window is the first reported
    for args in [(2.0, 2.0, 2.4), (2.0, 2.15, 2.15), (2.4, 2.15, 2.0), (2.0, 2.4, 2.15), (2.15, 2.0, 2.4)]:
        with pytest.raises(ValueError, match=f"deposit, main refinancing and marginal lending rates are not in that order on {first}"):
            _sum(_flat(*args))


def test_the_order_is_checked_on_the_last_400_common_days_only():
    k = _flat(n=500)
    k["MRR_FR"] = _series([1.0] * 100 + [2.15] * 400)              # below the deposit rate only in the oldest 100 days: outside the 400
    assert _sum(k)["available"]
    k["MRR_FR"] = _series([2.15] * 99 + [1.0] + [2.15] * 400)      # only END-400, the day just outside
    assert _sum(k)["available"]
    k["MRR_FR"] = _series([2.15] * 100 + [1.0] + [2.15] * 399)     # only END-399, the oldest day inside
    with pytest.raises(ValueError, match=f"not in that order on {(END - timedelta(days=399)).isoformat()}"):
        _sum(k)
    k["MRR_FR"] = _series([2.15] * 499 + [1.0])                    # only the newest day
    with pytest.raises(ValueError, match="not in that order on 2026-11-15"):
        _sum(k)


def test_values_outside_the_last_400_days_are_not_judged():
    k = _flat(n=500)
    k["DFR"] = _series([12.0] * 100 + [2.0] * 400)                  # out of range and a 10-point step, but older than the window
    assert _sum(k)["rates"][0]["rate"] == 2.0


def test_the_figures_are_dated_by_the_oldest_of_the_three_newest_dates():
    k = _flat()
    k["MLFR"] = {d: v for d, v in k["MLFR"].items() if d <= END - timedelta(days=3)}
    s = _sum(k)
    assert (s["date"], s["age_days"], s["year_ago_date"]) == ("2026-11-12", 3, "2025-11-12")
    assert [r["rate"] for r in s["rates"]] == [2.0, 2.15, 2.4]


def test_a_series_far_behind_the_others_marks_the_card_overdue_and_a_missing_year_ago_figure_is_not_invented():
    k = {"DFR": _series([2.0] * 400), "MRR_FR": _series([2.15] * 440, END - timedelta(days=40)), "MLFR": _series([2.4] * 400)}
    s = _sum(k)
    assert (s["date"], s["age_days"], s["freshness"]) == ("2026-10-06", 40, "OVERDUE")
    by = {r["id"]: r for r in s["rates"]}
    assert by["DFR"]["year_ago"] is None and by["DFR"]["change_1y"] is None            # 2025-10-06 is before the deposit series starts (2025-10-12)
    assert by["MRR_FR"]["year_ago"] == 2.15 and by["MRR_FR"]["change_1y"] == 0.0


def test_changes_are_rounded_to_hundredths_so_binary_noise_never_shows():
    k = {"DFR": _series([0.1] * 450 + [0.3] * 50), "MRR_FR": _series([5.0] * 500), "MLFR": _series([6.0] * 500)}
    s = _sum(k)
    assert 0.3 - 0.1 != 0.2                                                              # in binary arithmetic the difference is 0.19999999999999998
    assert s["rates"][0]["last_change"] == {"date": (END - timedelta(days=49)).isoformat(), "from": 0.1, "to": 0.3, "change": 0.2}
    assert s["rates"][0]["change_1y"] == 0.2 and s["rates"][0]["year_ago"] == 0.1 and s["rates"][1]["above_deposit_rate"] == 4.7
    assert s["decisions"] == [s["rates"][0]["last_change"]]


def test_a_missing_value_on_the_dating_day_is_an_error_not_a_guess():
    stale = END - timedelta(days=450)
    k = {"DFR": _series([2.0] * 500), "MRR_FR": _series([2.15] * 500, stale), "MLFR": _series([2.4] * 500)}
    del k["DFR"][stale]                                                                  # outside DFR's checked 400 days, but it is the day the card would be dated by
    with pytest.raises(ValueError, match=f"deposit facility rate has no value for {stale.isoformat()}"):
        _sum(k)


def test_the_card_is_overdue_after_5_days():
    assert _sum(today=END + timedelta(days=5))["freshness"] == "CURRENT"
    s = _sum(today=END + timedelta(days=6))
    assert (s["freshness"], s["age_days"]) == ("OVERDUE", 6)
    assert _sum(today=END - timedelta(days=1))["age_days"] == 0                       # a server clock a day behind never gives a negative age


def test_a_rate_that_never_changed_has_no_last_change_and_a_gap_is_not_read_as_a_change():
    s = _sum()
    assert all(r["last_change"] is None for r in s["rates"]) and s["decisions"] == []
    k = _flat(n=500)
    k["DFR"] = {**_series([1.0] * 50 + [2.0] * 450)}
    del k["DFR"][END - timedelta(days=450)]                                            # the day between the 1.0 and the 2.0: the move across the hole is not a dated change
    s = _sum(k)
    assert s["rates"][0]["last_change"] is None and s["decisions"] == []


def test_decisions_are_the_six_newest_changes_of_the_deposit_rate_newest_first():
    levels = [1.0 + 0.25 * i for i in range(9)]                                         # 8 changes, 25 days each, the last level held for 25 days
    k = _flat(n=500)
    k["DFR"] = _series([1.0] * 275 + [x for lv in levels[1:] for x in [lv] * 25])
    k["MRR_FR"], k["MLFR"] = _series([6.0] * 500), _series([7.0] * 500)
    s = _sum(k)
    assert [d["to"] for d in s["decisions"]] == [3.0, 2.75, 2.5, 2.25, 2.0, 1.75] and len(s["decisions"]) == 6
    assert s["decisions"][0] == {"date": (END - timedelta(days=24)).isoformat(), "from": 2.75, "to": 3.0, "change": 0.25}
    assert s["rates"][0]["last_change"] == s["decisions"][0]
    k["DFR"] = _series([2.0] * 300 + [2.25] * 100 + [2.5] * 100)
    assert [d["to"] for d in _sum(k)["decisions"]] == [2.5, 2.25]


# ---- the euro short-term rate checks ---------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_60_observations_are_needed_and_older_ones_are_not_judged():
    assert _sum(estr=_estr(n=60))["market"]["observations"] == 60
    with pytest.raises(ValueError, match="euro short-term rate has 59 days, 60 are needed"):
        _sum(estr=_estr(n=59))
    old_bad = _estr(n=70)
    old_bad[min(old_bad)] = 9.0                                                         # the oldest of 70: outside the 60 looked at
    assert _sum(estr=old_bad)["market"]["first_date"] == _weekdays(60)[0].isoformat()


def test_every_date_must_be_a_weekday_and_an_older_weekend_date_is_not_looked_at():
    e = _estr(n=70)
    e[date(2026, 11, 7)] = 1.94                                                         # a Saturday inside the 60
    with pytest.raises(ValueError, match="a euro short-term rate date is not a weekday"):
        _sum(estr=e)
    e = _estr(n=70)
    e[date(2026, 5, 2)] = 1.94                                                          # a Saturday older than the 60
    assert _sum(estr=e)["available"]


def test_two_dates_more_than_7_days_apart_are_refused_and_7_is_not():
    a = date(2026, 10, 15)
    assert a.weekday() == 3
    seven = {d: v for d, v in _estr(n=80).items() if not (a < d < a + timedelta(days=7))}             # Friday to Wednesday removed: Thursday to the next Thursday, 7 days
    assert max((y - x).days for x, y in zip(sorted(seven)[-60:], sorted(seven)[-59:])) == 7
    assert _sum(estr=seven)["available"]
    eight = {d: v for d, v in _estr(n=80).items() if not (a < d < a + timedelta(days=8))}             # Thursday to the Friday after: 8 days
    assert max((y - x).days for x, y in zip(sorted(eight)[-60:], sorted(eight)[-59:])) == 8
    with pytest.raises(ValueError, match="two euro short-term rate dates are more than 7 days apart"):
        _sum(estr=eight)


def test_the_euro_short_term_rate_range_is_minus_1_5_to_10_inclusive():
    hi = _flat(9.9, 9.95, 10.0)
    assert _sum(hi, _estr(gap=0.1, deposit=9.9))["market"]["rate"] == 10.0
    with pytest.raises(ValueError, match="euro short-term rate is 10.05% on .* outside -1.5% to 10%"):
        _sum(hi, _estr(gap=0.15, deposit=9.9))
    lo = _flat(-1.4, -1.35, -1.3)
    assert _sum(lo, _estr(gap=-0.1, deposit=-1.4))["market"]["rate"] == -1.5
    with pytest.raises(ValueError, match="euro short-term rate is -1.55% on .* outside -1.5% to 10%"):
        _sum(lo, _estr(gap=-0.15, deposit=-1.4))


def test_the_market_rate_must_be_within_0_30_under_and_0_10_over_the_deposit_rate():
    assert _sum(estr=_estr(gap=-0.299))["market"]["gap"] == -0.299
    assert _sum(estr=_estr(gap=0.099))["market"]["gap"] == 0.099
    first = _weekdays(60)[0].isoformat()                                                  # every day is outside: the oldest of the 60 is the first reported
    with pytest.raises(ValueError, match=f"euro short-term rate is -0.301 points from the deposit rate on {first}, outside -0.30 to \\+0.10"):
        _sum(estr=_estr(gap=-0.301))
    with pytest.raises(ValueError, match=f"euro short-term rate is \\+0.101 points from the deposit rate on {first}, outside -0.30 to \\+0.10"):
        _sum(estr=_estr(gap=0.101))


def test_the_gap_is_checked_on_each_of_the_last_60_days_not_only_the_newest():
    vals = [-0.06] * 60
    vals[10] = -0.4                                                                      # one day in the middle of the window
    e = _estr([round(2.0 + g, 3) for g in vals])
    with pytest.raises(ValueError, match="-0.400 points from the deposit rate"):
        _sum(estr=e)


def test_every_euro_short_term_rate_date_needs_a_deposit_rate_for_that_day():
    k = _flat(end=date(2026, 11, 10))                                                    # the key rates stop two days before the euro short-term rate's newest date
    with pytest.raises(ValueError, match="deposit rate has no value for 2026-11-11, a day the euro short-term rate has"):
        _sum(k, _estr(n=60))
    assert _sum(k, _estr(n=60, last=date(2026, 11, 10)))["market"]["date"] == "2026-11-10"


def test_the_gap_figures_by_hand_on_a_synthetic_window():
    vals = [round(2.0 - 0.05, 3)] * 60
    vals[3], vals[30], vals[-1] = 1.9, 2.02, 1.96                                        # gaps -0.10, +0.02, -0.04; all the others -0.05
    m = _sum(estr=_estr(vals))["market"]
    assert (m["rate"], m["deposit_rate"], m["gap"], m["gap_low"], m["gap_high"], m["observations"]) == (1.96, 2.0, -0.04, -0.1, 0.02, 60)


def test_the_market_rate_has_its_own_date_and_label_and_is_overdue_after_8_days():
    k, last = _flat(), date(2026, 11, 5)                                                 # key rates dated 2026-11-15, the euro short-term rate's newest day 10 days earlier
    s = _sum(k, _estr(last=last), today=last + timedelta(days=8))
    assert s["market"]["age_days"] == 8 and s["market"]["freshness"] == "CURRENT" and s["freshness"] == "CURRENT"
    s = _sum(k, _estr(last=last), today=last + timedelta(days=9))
    assert s["market"]["age_days"] == 9 and s["market"]["freshness"] == "OVERDUE" and s["freshness"] == "CURRENT"      # each label is its own: the rates are 0 days old
    assert _sum(k, _estr(last=last), today=last - timedelta(days=1))["market"]["age_days"] == 0


# ---- the service ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_overview_fetches_the_two_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = E.EcbRates(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["rates"][0]["rate"] == 2.5 and r["market"]["rate"] == 2.443 and n["n"] == 2 and "not a market signal or a forecast" in r["note"]
    assert r["demo"] is False and r["source"].startswith("European Central Bank")
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 2


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(E.EcbRates(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and r["reason"] == "The ECB interest rates could not be read right now (the server had an error, HTTP 503)" and "rates" not in r
    bad = re.sub(r"(,DFR,LEV,2026-11-15,)2\.5", r"\g<1>25", K)                           # a decimal slip in the newest deposit rate
    assert bad != K
    r = asyncio.run(E.EcbRates(client=_client(lambda req: httpx.Response(200, text=bad if "/FM/" in req.url.path else ES))).overview(NOW))
    assert r["available"] is False and "outside -1.5% to 10%" in r["reason"] and "rates" not in r and "market" not in r


def test_one_failing_request_of_the_two_shows_nothing():
    r = asyncio.run(E.EcbRates(client=_client(lambda req: httpx.Response(200, text=K) if "/FM/" in req.url.path else httpx.Response(404))).overview(NOW))
    assert r["available"] is False and "HTTP 404" in r["reason"] and "rates" not in r
    r = asyncio.run(E.EcbRates(client=_client(lambda req: httpx.Response(200, text=K) if "/FM/" in req.url.path else httpx.Response(200, text="KEY,TIME_PERIOD,OBS_VALUE\n"))).overview(NOW))
    assert r["available"] is False and "no euro short-term rate" in r["reason"]


def test_a_failure_is_cached_briefly_and_then_asked_again():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return httpx.Response(503)

    svc = E.EcbRates(client=_client(handler))
    asyncio.run(svc.overview(NOW))
    asyncio.run(svc.overview(NOW))
    assert n["n"] <= 2 and E.FAIL_TTL < E.TTL
    svc._cache = (0.0, svc._cache[1])                                                    # expired
    asyncio.run(svc.overview(NOW))
    assert n["n"] >= 3


def test_an_unexpected_missing_key_in_the_data_is_reported_plainly_not_raised(monkeypatch):
    def broken(kr, estr, today):
        raise KeyError("DFR")

    monkeypatch.setattr(E, "summarize", broken)
    r = asyncio.run(E.EcbRates(client=_client(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The ECB interest rates could not be read right now (the answer was not in the expected shape)"


def test_a_dropped_connection_reads_plainly():
    def boom(req):
        raise httpx.ConnectError("")

    r = asyncio.run(E.EcbRates(client=_client(boom)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The ECB interest rates could not be read right now (the connection could not be made)"


def test_demo_mode_invents_nothing():
    d = asyncio.run(E.EcbRates(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "rates" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/ecb-rates")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_details_the_two_series_a_limited_window_and_no_personal_details():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(E.EcbRates(client=_client(handler)).overview(NOW))
    by = {("FM" if "/FM/" in r.url.path else "EST"): r for r in seen}
    assert by["FM"].url.path == "/service/data/FM/D.U2.EUR.4F.KR.DFR+MRR_FR+MLFR.LEV" and by["EST"].url.path == "/service/data/EST/B.EU000A2X2A25.WT"
    assert by["FM"].url.params["startPeriod"] == (NOW.date() - timedelta(days=1500)).isoformat() and by["EST"].url.params["startPeriod"] == (NOW.date() - timedelta(days=120)).isoformat()
    assert all(r.url.params["format"] == "csvdata" and r.url.params["detail"] == "dataonly" and r.url.host == "data-api.ecb.europa.eu" for r in seen)
    assert all(r.headers["user-agent"] == "ATLAS research terminal" and "@" not in "".join(r.headers.values()) for r in seen)
