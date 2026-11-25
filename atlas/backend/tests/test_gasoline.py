"""US retail gasoline price (weekly, EIA via FRED) with a cross-check against WTI crude: parsed from real responses (fetched 2026-11-14: 80 weekly gasoline prices and 400 daily WTI prices since 2025-05). Hand-worked changes, rank and the per-barrel gap to crude,
every refusal with the windows it looks at (12 weeks spacing, 60 weeks range and move, 8 weeks cross-check), the stale label, caching, failure, demo, the route and the plain-client rule."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import gasoline as G
from atlas_api.app import create_app

F = json.loads((Path(__file__).parent / "fixtures" / "fred_gasoline.json").read_text())
TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)
LAST = date(2026, 11, 9)


def _data():
    return {sid: G.parse(F[sid], sid) for sid in G.SERIES}


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _handler(req):
    return httpx.Response(200, text=F[req.url.params["id"]])


def _with_margin(week_offsets, margin):
    """The data with WTI replaced, for the gasoline weeks `week_offsets` from the end (-1 is the newest), by (gasoline per barrel - margin), so the cross-check sees exactly that margin there."""
    d = _data()
    weeks = sorted(d["GASREGW"])
    for off in week_offsets:
        day = weeks[off]
        d["DCOILWTICO"][day] = d["GASREGW"][day] * 42.0 - margin
    return d


L = json.loads((Path(__file__).parent / "fixtures" / "fred_gasoline_lagday.json").read_text())
LAG_TODAY = date(2026, 11, 25)


def _lag():
    """The real record read on Wednesday 2026-11-25 00:2x UTC (the whole two years from 2024-09-16): GASREGW ends on Monday 2026-11-23 (EIA posted it on Tuesday, 9:03 AM CST), DCOILWTICO ends on Tuesday 2026-11-17 (posted on Wednesday 2026-11-18; the next release was due on Wednesday 2026-11-25)."""
    return {sid: G.parse(L[sid], sid) for sid in G.SERIES}


def _crude_ends_on(end, price=80.0):
    """The data with the crude series cut after `end` and one price of `price` on `end` itself (the day may be a weekend: the tests only count days): the weekly crude release has not come yet."""
    d = _data()
    for day in [x for x in d["DCOILWTICO"] if x > end]:
        del d["DCOILWTICO"][day]
    d["DCOILWTICO"][end] = price
    return d


def test_latest_week_changes_rank_and_the_gap_to_crude_by_hand():
    s = G.summarize(_data(), TODAY)
    assert (s["date"], s["age_days"], s["freshness"]) == ("2026-11-09", 5, "CURRENT")
    assert s["price"] == 3.995 and s["change_1w"] == -0.158                       # 3.995 - 4.153 on 2026-11-02
    assert s["change_4w_pct"] == -7.8                                              # (3.995 - 4.331 on 2026-10-12) / 4.331
    assert s["change_1y_pct"] == 30.7                                              # (3.995 - 3.056 on 2025-11-10) / 3.056
    assert (s["year_low"], s["year_high"], s["weeks_in_year"], s["rank_in_year"]) == (2.779, 4.5, 53, 49)
    assert s["reading"] == "in the middle of the past year's range"
    assert s["crude"] == {"wti": 90.4, "date": "2026-11-09", "per_barrel": 167.79, "gap": 77.39}         # 3.995 x 42 = 167.79 a barrel against WTI at 90.40 on the same Monday: 77.39 for refining, distribution, marketing and taxes
    assert len(s["history"]) == 52 and s["history"][-1] == {"date": "2026-11-09", "price": 3.995}
    assert all(s["checks"].values())


def test_the_note_describes_the_monday_figure_not_a_week_starting_on_it():
    # FRED lists GASREGW as "Weekly, Ending Monday" and its notes say the average is of about 900 retail outlets sampled at 8:00AM Monday: the figure belongs to the Monday itself.
    n = G.summarize(_data(), TODAY)["note"]
    assert "on the Monday shown" in n and "8:00AM" in n and "week starting" not in n.lower()


def test_a_missing_earlier_week_is_not_available_never_guessed():
    d = _data()
    del d["GASREGW"][LAST - timedelta(days=52 * 7)]
    s = G.summarize(d, TODAY)
    assert s["change_1y_pct"] is None and s["change_4w_pct"] == -7.8


def test_stale_is_overdue_with_real_age():
    assert G.summarize(_data(), LAST + timedelta(days=14))["freshness"] == "CURRENT"
    s = G.summarize(_data(), LAST + timedelta(days=15))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 15


def test_a_date_that_is_not_a_monday_is_refused():
    d = _data()
    d["GASREGW"][date(2026, 11, 10)] = 3.99
    with pytest.raises(ValueError, match="not a Monday"):
        G.summarize(d, TODAY)


def test_the_spacing_check_looks_at_the_last_12_weeks_and_no_further_back():
    d = _data()
    del d["GASREGW"][sorted(d["GASREGW"])[-5]]                                     # a missing week 5 from the end
    with pytest.raises(ValueError, match="one week apart"):
        G.summarize(d, TODAY)
    d = _data()
    del d["GASREGW"][sorted(d["GASREGW"])[-15]]                                    # 15 from the end: outside the 12 weeks, so this check does not care
    assert G.summarize(d, TODAY)["available"]


@pytest.mark.parametrize("bad", [0.4, 11.0])
def test_a_price_outside_the_plausible_range_is_refused(bad):
    d = _data()
    d["GASREGW"][max(d["GASREGW"])] = bad
    with pytest.raises(ValueError, match="plausible range"):
        G.summarize(d, TODAY)


def test_the_range_and_move_checks_look_at_the_last_60_weeks_and_no_further_back():
    def with_bad(off, value):
        d = _data()
        d["GASREGW"][sorted(d["GASREGW"])[off]] = value
        return d
    with pytest.raises(ValueError, match="plausible range"):
        G.summarize(with_bad(-30, 20.0), TODAY)                                    # 30 weeks back: inside the last 60
    assert G.summarize(with_bad(-70, 20.0), TODAY)["available"]                    # 70 weeks back: outside every window
    d = _data()
    weeks = sorted(d["GASREGW"])
    d["GASREGW"][weeks[-30]] = d["GASREGW"][weeks[-31]] * 0.5                      # half of the week before: inside the price range, but a 50% weekly move, 30 weeks back
    with pytest.raises(ValueError, match="moved more than 25%"):
        G.summarize(d, TODAY)
    d = _data()
    d["GASREGW"][weeks[-70]] = d["GASREGW"][weeks[-71]] * 0.5                      # the same thing 70 weeks back: outside the window
    assert G.summarize(d, TODAY)["available"]


def test_a_weekly_move_over_25_percent_is_refused_and_24_is_allowed():
    def last_scaled(f):
        d = _data()
        last = max(d["GASREGW"])
        d["GASREGW"][last] = d["GASREGW"][last - timedelta(days=7)] * f
        return d
    with pytest.raises(ValueError, match="moved more than 25%"):
        G.summarize(last_scaled(1.26), TODAY)
    with pytest.raises(ValueError, match="moved more than 25%"):
        G.summarize(last_scaled(0.74), TODAY)
    assert G.summarize(last_scaled(1.24), TODAY)["price"] == pytest.approx(4.153 * 1.24, abs=0.001)
    assert G.summarize(last_scaled(0.76), TODAY)["price"] == pytest.approx(4.153 * 0.76, abs=0.001)


def test_the_gap_to_crude_must_be_between_10_and_130_dollars_a_barrel():
    assert G.summarize(_with_margin([-1], 10.5), TODAY)["crude"]["gap"] == pytest.approx(10.5)
    assert G.summarize(_with_margin([-1], 129.5), TODAY)["crude"]["gap"] == pytest.approx(129.5)
    with pytest.raises(ValueError, match="outside 10 to 130"):
        G.summarize(_with_margin([-1], 9.5), TODAY)
    with pytest.raises(ValueError, match="outside 10 to 130"):
        G.summarize(_with_margin([-1], 130.5), TODAY)
    # a /10 slip in WTI (the case a wider band would miss) and a x10 slip in gasoline are both caught
    d = _data()
    for day in sorted(d["DCOILWTICO"]):
        d["DCOILWTICO"][day] /= 10.0
    with pytest.raises(ValueError, match="outside 10 to 130"):
        G.summarize(d, TODAY)
    d = _data()
    for day in sorted(d["GASREGW"])[-60:]:
        d["GASREGW"][day] *= 10.0
    with pytest.raises(ValueError):
        G.summarize(d, TODAY)


def test_the_cross_check_looks_at_the_last_8_weeks_and_no_further_back():
    with pytest.raises(ValueError, match="outside 10 to 130"):
        G.summarize(_with_margin([-8], 200.0), TODAY)                              # 8 weeks back: inside
    assert G.summarize(_with_margin([-9], 200.0), TODAY)["available"]              # 9 weeks back: outside


def test_when_the_newest_monday_has_no_crude_price_the_latest_one_before_it_is_used_after_a_holiday_and_at_5_days():
    d = _data()
    for day in (date(2026, 11, 7), date(2026, 11, 8), date(2026, 11, 9)):
        d["DCOILWTICO"].pop(day, None)                                             # a Monday holiday: the latest price is Friday 2026-11-06, 3 days earlier
    s = G.summarize(d, TODAY)
    assert s["crude"]["wti"] == d["DCOILWTICO"][date(2026, 11, 6)] and s["crude"]["date"] == "2026-11-06"
    for day in (date(2026, 11, 5), date(2026, 11, 6)):
        d["DCOILWTICO"].pop(day, None)                                             # now the latest is 2026-11-04, exactly 5 days earlier: allowed
    s = G.summarize(d, TODAY)
    assert s["crude"]["wti"] == d["DCOILWTICO"][date(2026, 11, 4)] and s["crude"]["date"] == "2026-11-04"


def test_a_missing_crude_price_means_the_check_cannot_be_made_and_the_card_says_so():
    d = _data()
    for day in list(d["DCOILWTICO"]):
        if day >= date(2026, 10, 31):
            del d["DCOILWTICO"][day]                                               # the latest WTI price is Friday 2026-10-30, 10 days before the newest Monday: more than the 8 days it may be behind
    with pytest.raises(ValueError, match="no WTI crude price"):
        G.summarize(d, TODAY)


def test_the_refusals_that_name_a_week_write_it_in_words_because_the_phone_shows_them():
    d = _data()
    for day in list(d["DCOILWTICO"]):
        if day >= date(2026, 10, 31):
            del d["DCOILWTICO"][day]
    with pytest.raises(ValueError) as e:
        G.summarize(d, TODAY)
    assert str(e.value) == "there is no WTI crude price near November 9, 2026 to check the gasoline price against"          # the live card said "near 2026-11-23" on 2026-11-24 and the Macro browser test refused a raw date
    third = sorted(_data()["GASREGW"])[-3]
    with pytest.raises(ValueError) as e:
        G.summarize(_with_margin([-3], 9.5), TODAY)
    assert str(e.value) == f"gasoline per barrel minus WTI crude is 9.5 on {third:%B} {third.day}, {third.year}, outside 10 to 130" and "2026-" not in str(e.value)


def test_on_the_day_the_newest_monday_has_no_crude_price_yet_the_card_still_shows_it_with_the_crude_price_of_the_Tuesday_before():
    # The failure seen live on 2026-11-24 (and so on every week): EIA posts the Monday gasoline price on Tuesday morning and the crude prices once a week, on Wednesday, through the Tuesday before. For about 27 hours the newest Monday has no crude price within the 5 days the check used to allow (6 days here), and the whole card said "unavailable".
    s = G.summarize(_lag(), LAG_TODAY)
    assert (s["date"], s["age_days"], s["freshness"]) == ("2026-11-23", 2, "CURRENT")
    assert s["price"] == 3.642 and s["change_1w"] == -0.163 and s["change_4w_pct"] == -14.7 and s["change_1y_pct"] == 19.0
    assert (s["year_low"], s["year_high"], s["weeks_in_year"], s["rank_in_year"]) == (2.779, 4.5, 53, 32)
    assert s["crude"] == {"wti": 89.53, "date": "2026-11-17", "per_barrel": 152.96, "gap": 63.43}          # 3.642 x 42 = 152.964 against the 89.53 of Tuesday 2026-11-17: 63.43
    assert s["history"][-1] == {"date": "2026-11-23", "price": 3.642} and all(s["checks"].values())


def test_the_real_lag_day_record_has_the_shape_the_fix_relies_on():
    d = _lag()
    assert max(d["GASREGW"]) == date(2026, 11, 23) and max(d["DCOILWTICO"]) == date(2026, 11, 17) and (max(d["GASREGW"]) - max(d["DCOILWTICO"])).days == 6
    assert len(d["GASREGW"]) == 115 and all(day.weekday() == 0 for day in d["GASREGW"])
    older = sorted(d["GASREGW"])[-8:-1]                                             # the seven Mondays before the newest all have crude on the Monday itself
    assert all(day in d["DCOILWTICO"] for day in older)


@pytest.mark.parametrize("back, day", [(0, "2026-11-09"), (3, "2026-11-06"), (5, "2026-11-04"), (6, "2026-11-03"), (7, "2026-11-02"), (8, "2026-11-01")])
def test_the_newest_monday_may_use_a_crude_price_up_to_8_days_before_it_and_the_card_names_the_day(back, day):
    d = _crude_ends_on(LAST - timedelta(days=back))
    s = G.summarize(d, TODAY)
    assert s["crude"]["date"] == day and s["crude"]["wti"] == 80.0
    assert s["crude"]["per_barrel"] == 167.79 and s["crude"]["gap"] == round(167.79 - 80.0, 2)               # the gap is worked against the crude price of that day


def test_the_newest_monday_with_no_crude_price_in_the_8_days_before_it_is_refused_and_9_days_is_the_edge():
    with pytest.raises(ValueError) as e:
        G.summarize(_crude_ends_on(LAST - timedelta(days=9)), TODAY)
    assert str(e.value) == "there is no WTI crude price near November 9, 2026 to check the gasoline price against"
    assert G.summarize(_crude_ends_on(LAST - timedelta(days=8)), TODAY)["available"]


@pytest.mark.parametrize("back, ok", [(5, True), (6, False)])
def test_an_older_monday_still_needs_a_crude_price_within_5_days_only_the_newest_one_may_wait_for_the_weekly_release(back, ok):
    d = _data()
    older = sorted(d["GASREGW"])[-2]                                               # 2026-11-02, the Monday before the newest
    for day in [x for x in d["DCOILWTICO"] if older - timedelta(days=back) < x <= older]:
        del d["DCOILWTICO"][day]                                                   # the nearest crude price before it is `back` days earlier (the newest Monday keeps its own)
    if ok:
        assert G.summarize(d, TODAY)["available"]
    else:
        with pytest.raises(ValueError) as e:
            G.summarize(d, TODAY)
        assert str(e.value) == "there is no WTI crude price near November 2, 2026 to check the gasoline price against"


def test_the_gap_check_of_the_newest_monday_uses_the_older_crude_price_and_keeps_its_limits():
    day = LAST - timedelta(days=6)
    per_barrel = 3.995 * 42.0
    assert G.summarize(_crude_ends_on(day, per_barrel - 10.5), TODAY)["crude"]["gap"] == pytest.approx(10.5)
    assert G.summarize(_crude_ends_on(day, per_barrel - 129.5), TODAY)["crude"]["gap"] == pytest.approx(129.5)
    with pytest.raises(ValueError) as e:
        G.summarize(_crude_ends_on(day, per_barrel - 9.5), TODAY)
    assert str(e.value) == "gasoline per barrel minus WTI crude is 9.5 on November 9, 2026, outside 10 to 130"
    with pytest.raises(ValueError) as e:
        G.summarize(_crude_ends_on(day, per_barrel - 130.5), TODAY)
    assert str(e.value) == "gasoline per barrel minus WTI crude is 130.5 on November 9, 2026, outside 10 to 130"


def test_the_lookup_windows_are_these_literals_and_the_module_says_why_the_newest_monday_has_more():
    assert G.LOOKUP_DAYS == 5 and G.NEWEST_LOOKUP_DAYS == 8
    assert "Wednesday" in G.__doc__ and "newest Monday" in G.__doc__ and "8 days" in G.__doc__


def _flat(price=4.0, weeks=70, margin=50.0):
    """A synthetic world for the exact edges of the older checks: `weeks` Mondays ending on LAST at one price and WTI on every Monday at price x 42 - margin (numbers a binary float holds exactly), so every check passes and a test changes one thing."""
    mondays = [LAST - timedelta(days=7 * i) for i in range(weeks - 1, -1, -1)]
    return {"GASREGW": {d: price for d in mondays}, "DCOILWTICO": {d: price * 42.0 - margin for d in mondays}}


def test_the_flat_world_passes_every_check_so_a_test_can_change_one_thing():
    s = G.summarize(_flat(), TODAY)
    assert s["price"] == 4.0 and s["crude"] == {"wti": 118.0, "date": "2026-11-09", "per_barrel": 168.0, "gap": 50.0} and all(s["checks"].values())
    assert (s["change_1w"], s["change_4w_pct"], s["change_1y_pct"], s["weeks_in_year"], s["rank_in_year"]) == (0.0, 0.0, 0.0, 53, 100)


@pytest.mark.parametrize("price, ok", [(0.5, True), (0.49, False), (10.0, True), (10.01, False)])
def test_the_price_range_is_0_50_to_10_dollars_and_both_edges_are_allowed(price, ok):
    d = _flat(price=price, margin=15.0)
    if ok:
        assert G.summarize(d, TODAY)["price"] == price
    else:
        with pytest.raises(ValueError) as e:
            G.summarize(d, TODAY)
        assert str(e.value) == "a gasoline price is outside the plausible range"


@pytest.mark.parametrize("off, ok", [(-60, False), (-61, True)])
def test_the_range_check_looks_at_exactly_the_last_60_weeks(off, ok):
    d = _flat()
    d["GASREGW"][sorted(d["GASREGW"])[off]] = 20.0
    if ok:
        assert G.summarize(d, TODAY)["available"]
    else:
        with pytest.raises(ValueError, match="plausible range"):
            G.summarize(d, TODAY)


@pytest.mark.parametrize("off, ok", [(-60, False), (-61, True)])
def test_the_move_check_looks_at_exactly_the_pairs_inside_the_last_60_weeks(off, ok):
    d = _flat()
    d["GASREGW"][sorted(d["GASREGW"])[off]] = 1.5                                  # inside the price range, and a 100% move against the next week when that pair is inside the window
    if ok:
        assert G.summarize(d, TODAY)["available"]
    else:
        with pytest.raises(ValueError) as e:
            G.summarize(d, TODAY)
        assert str(e.value) == "gasoline moved more than 25% in a week"


@pytest.mark.parametrize("price, crude_price, ok", [(5.0, 160.0, True), (5.01, 160.0, False), (3.0, 76.0, True), (2.99, 76.0, False)])
def test_a_weekly_move_of_exactly_25_percent_is_allowed_and_a_cent_more_is_not(price, crude_price, ok):
    d = _flat()
    d["GASREGW"][LAST] = price                                                     # from 4.00: +25% is 5.00, -25% is 3.00 (exact in binary)
    d["DCOILWTICO"][LAST] = crude_price
    if ok:
        assert G.summarize(d, TODAY)["price"] == price
    else:
        with pytest.raises(ValueError) as e:
            G.summarize(d, TODAY)
        assert str(e.value) == "gasoline moved more than 25% in a week"


@pytest.mark.parametrize("k, ok", [(12, False), (13, True)])
def test_the_spacing_check_looks_at_exactly_the_last_12_weeks(k, ok):
    d = _flat()
    del d["GASREGW"][sorted(d["GASREGW"])[-k]]                                     # a hole: the pair across it is inside the last 12 weeks for k = 12 and just outside for k = 13
    if ok:
        assert G.summarize(d, TODAY)["available"]
    else:
        with pytest.raises(ValueError) as e:
            G.summarize(d, TODAY)
        assert str(e.value) == "the last weeks are not one week apart"


@pytest.mark.parametrize("gap, ok", [(10.0, True), (9.99, False), (130.0, True), (130.01, False)])
def test_the_gap_to_crude_edges_are_10_and_130_dollars_a_barrel_and_both_are_allowed(gap, ok):
    d = _flat()
    d["DCOILWTICO"][LAST] = 168.0 - gap
    if ok:
        assert G.summarize(d, TODAY)["crude"]["gap"] == gap
    else:
        with pytest.raises(ValueError, match="outside 10 to 130"):
            G.summarize(d, TODAY)


def test_the_summary_names_its_source_and_page_and_the_note_says_why_the_newest_monday_may_be_checked_against_an_older_crude_price():
    s = G.summarize(_data(), TODAY)
    assert s["source"] == "US Energy Information Administration weekly retail gasoline prices, via FRED, St. Louis Fed (official, free public data)"
    assert s["url"] == "https://fred.stlouisfed.org/series/GASREGW" and G.URL == "https://fred.stlouisfed.org/graph/fredgraph.csv" and G.PAGE == s["url"]
    assert "crude prices come once a week, after the gasoline price, so the newest Monday is checked against the latest crude price, which can be a few days older" in s["note"]


# ---------------------------------------------------------------- the class: caches by a fake clock, reasons, the clock of the question, the client

def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = {"t": 1000.0}
    monkeypatch.setattr(G.time, "monotonic", lambda: clock["t"])
    n = {"n": 0, "ok": False}

    def handler(req):
        n["n"] += 1
        return _handler(req) if n["ok"] else httpx.Response(503)

    svc = G.GasolinePrices(client=_client(handler))
    assert asyncio.run(svc.overview(NOW))["available"] is False and n["n"] == 2
    clock["t"] += 119
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 2                                                             # a failure is still remembered after 119 seconds
    clock["t"] += 1
    n["ok"] = True
    assert asyncio.run(svc.overview(NOW))["available"] is True and n["n"] == 4     # and asked again at 120
    clock["t"] += 21599
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 4                                                             # a success is remembered for 6 hours less a second
    clock["t"] += 1
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 6


def test_an_answer_from_the_cache_carries_the_time_of_the_question_and_the_age_is_worked_from_it():
    svc = G.GasolinePrices(client=_client(_handler))
    a = asyncio.run(svc.overview(NOW))
    later = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    b = asyncio.run(svc.overview(later))
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == later.isoformat() and a["age_days"] == 5
    fresh = asyncio.run(G.GasolinePrices(client=_client(_handler)).overview(later))
    assert fresh["age_days"] == 11 and fresh["freshness"] == "CURRENT"                  # 2026-11-09 to 2026-11-20, not to the day the test runs


def test_without_a_time_the_question_is_asked_at_the_present_moment_in_utc():
    r = asyncio.run(G.GasolinePrices(client=_client(_handler)).overview())
    asked = datetime.fromisoformat(r["as_of"])
    assert asked.tzinfo is not None and asked.utcoffset() == timedelta(0) and abs((datetime.now(timezone.utc) - asked).total_seconds()) < 60


def test_the_reasons_read_plainly_and_a_status_other_than_200_is_a_failure():
    r = asyncio.run(G.GasolinePrices(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["reason"] == "Gasoline prices could not be read right now (the server had an error, HTTP 503)"
    r = asyncio.run(G.GasolinePrices(client=_client(lambda req: httpx.Response(204))).overview(NOW))
    assert r["available"] is False and r["reason"].startswith("Gasoline prices could not be read right now (") and "HTTP 204" in r["reason"]

    def boom(data, today):
        raise KeyError("GASREGW")

    import atlas_api.gasoline as module
    original = module.summarize
    module.summarize = boom
    try:
        r = asyncio.run(G.GasolinePrices(client=_client(_handler)).overview(NOW))
    finally:
        module.summarize = original
    assert r["available"] is False and r["reason"] == "Gasoline prices could not be read right now (the answer was not in the expected shape)"


def test_demo_mode_says_why_and_flags_itself():
    d = asyncio.run(G.GasolinePrices(demo=True).overview(NOW))
    assert d["reason"] == "Demo mode: the real gasoline prices are not shown because made-up values would look real." and d["demo"] is True and d["as_of"] == NOW.isoformat()


def test_a_client_made_here_waits_25_seconds_and_is_closed_and_one_given_is_left_open_and_the_download_starts_800_days_back(monkeypatch):
    seen = {"closed": False, "params": []}

    class Fake:
        def __init__(self, **kw):
            seen["timeout"] = kw.get("timeout")

        async def get(self, url, params=None):
            seen["params"].append(params)
            return httpx.Response(200, text=F[params["id"]])

        async def aclose(self):
            seen["closed"] = True

    monkeypatch.setattr(G.httpx, "AsyncClient", Fake)
    r = asyncio.run(G.GasolinePrices().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 25.0 and seen["closed"] is True
    assert {p["cosd"] for p in seen["params"]} == {(date.today() - timedelta(days=800)).isoformat()}
    monkeypatch.undo()
    given = _client(_handler)
    asyncio.run(G.GasolinePrices(client=given).overview(NOW))
    assert given.is_closed is False


def test_a_missing_key_while_reading_the_answer_is_not_a_crash_and_the_two_series_ask_for_different_ids():
    seen = []

    def handler(req):
        seen.append(req.url.params["id"])
        return _handler(req)

    asyncio.run(G.GasolinePrices(client=_client(handler)).overview(NOW))
    assert sorted(seen) == ["DCOILWTICO", "GASREGW"] and G.SERIES == {"GASREGW": "gasoline", "DCOILWTICO": "wti"}


def test_missing_values_are_skipped_never_filled():
    s = G.parse("observation_date,GASREGW\n2026-11-02,4.153\n2026-11-09,.\n2026-11-16,\n", "GASREGW")
    assert s == {date(2026, 11, 2): 4.153}


def test_overview_fetches_two_series_and_caches():
    n = {"n": 0}

    def handler(req):
        n["n"] += 1
        return _handler(req)

    svc = G.GasolinePrices(client=_client(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["price"] == 3.995 and n["n"] == 2 and "not a market signal or a forecast" in r["note"]
    asyncio.run(svc.overview(NOW))
    assert n["n"] == 2


def test_failure_says_so_and_shows_no_numbers():
    r = asyncio.run(G.GasolinePrices(client=_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["available"] is False and "HTTP 503" in r["reason"] and "price" not in r
    bad = dict(F)
    bad["GASREGW"] = F["GASREGW"].replace("2026-11-09,3.995", "2026-11-09,39.95")                                   # a decimal slip: a check failing shows nothing either
    r = asyncio.run(G.GasolinePrices(client=_client(lambda req: httpx.Response(200, text=bad[req.url.params["id"]]))).overview(NOW))
    assert r["available"] is False and "plausible range" in r["reason"] and "price" not in r


def test_demo_mode_invents_nothing():
    d = asyncio.run(G.GasolinePrices(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "price" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/gasoline-prices")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True


def test_request_has_no_custom_user_agent_and_limits_the_download():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    asyncio.run(G.GasolinePrices(client=_client(handler)).overview(NOW))
    assert all("atlas" not in req.headers.get("user-agent", "").lower() for req in seen)     # FRED stalls on an unfamiliar one
    assert all("cosd" in req.url.params for req in seen) and {req.url.params["id"] for req in seen} == set(G.SERIES)
