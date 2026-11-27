"""Primary dealer net Treasury positions (New York Fed): parsed from real responses (fetched 2026-11-10, trimmed to Sept 2024 onward); the week-on-week change checked against the source's own change series;
year-ago, 52-week range, stale, missing-week, failure and demo paths."""
import asyncio
import json
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import dealers as D
from atlas_api.app import create_app

RAW = json.loads((Path(__file__).parent / "fixtures" / "nyfed_pd_treasury.json").read_text())
TODAY = date(2026, 11, 10)
NOW = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)


def _s(today=TODAY, level=None):
    return D.summarize(D.parse(level or RAW["level"]), D.parse(RAW["change"]), today)


def test_the_latest_week_matches_the_source():
    s = _s()
    assert s["date"] == "2026-10-28" and s["net_position_billions"] == 452.8 and s["previous_date"] == "2026-10-21"        # 452,759 million
    assert s["week_change_billions"] == 27.1 and s["freshness"] == "CURRENT" and s["age_days"] == 13                       # 452,759 - 425,643 = 27,116


def test_our_weekly_change_equals_the_sources_own_change_series_for_26_weeks():
    c = _s()["check"]
    assert c == {"weeks": 26, "mismatches": 0, "match": True, "latest_match": True, "bad_weeks": [], "latest_ours_billions": 27.1, "latest_source_billions": 27.1}
    broken = json.loads(json.dumps(RAW["level"]))
    broken["pd"]["timeseries"][-3]["value"] = str(float(broken["pd"]["timeseries"][-3]["value"]) + 20000)                 # one level 20 billion off: it breaks its own week (2026-10-14) and the next one (2026-10-21)
    c2 = _s(level=broken)["check"]
    assert c2["match"] is False and c2["mismatches"] == 2 and c2["latest_match"] is True
    assert [w["date"] for w in c2["bad_weeks"]] == ["2026-10-21", "2026-10-14"]                                          # newest first


def _change_off(back, delta):
    """The source's change series with the figure `back` weeks from the end moved by `delta` million (1 = the latest week)."""
    ch = json.loads(json.dumps(RAW["change"]))
    row = ch["pd"]["timeseries"][-back]
    row["value"] = str(float(row["value"]) + delta)
    return D.parse(ch)


def _check(change):
    return D.summarize(D.parse(RAW["level"]), change, TODAY)["check"]


def test_the_latest_week_disagreeing_with_the_sources_change_figure_is_said_to_be_the_latest_week():
    c = _check(_change_off(1, 5000))                                                                                       # 27,116 becomes 32,116
    assert c == {"weeks": 26, "mismatches": 1, "match": False, "latest_match": False,
                 "bad_weeks": [{"date": "2026-10-28", "ours_billions": 27.1, "source_billions": 32.1}],
                 "latest_ours_billions": 27.1, "latest_source_billions": 32.1}


def test_an_older_week_disagreeing_is_named_and_leaves_the_latest_week_matching():
    c = _check(_change_off(3, -20000))                                                                                     # the change of 2026-10-14: -1,185 becomes -21,185
    assert c == {"weeks": 26, "mismatches": 1, "match": False, "latest_match": True,
                 "bad_weeks": [{"date": "2026-10-14", "ours_billions": -1.2, "source_billions": -21.2}],
                 "latest_ours_billions": 27.1, "latest_source_billions": 27.1}


def test_a_difference_of_one_million_is_rounding_and_more_than_that_is_not_in_either_direction():
    for delta, ok in ((1.0, True), (-1.0, True), (1.5, False), (-1.5, False)):
        c = _check(_change_off(2, delta))                                                                                  # the change of 2026-10-21 (-17,855) moved by delta
        assert c["match"] is ok and c["mismatches"] == (0 if ok else 1) and c["latest_match"] is True and (c["bad_weeks"] == []) is ok


def test_many_disagreeing_weeks_are_counted_all_and_listed_three_at_most_newest_first():
    ch = _change_off(1, 0)
    for d in sorted(ch)[-5:]:
        ch[d] += 9000
    c = _check(ch)                                                                                                         # the five newest weeks (2026-09-30 to 2026-10-28) are 9 billion off
    assert c["mismatches"] == 5 and c["match"] is False and c["latest_match"] is False and c["weeks"] == 26
    assert c["bad_weeks"] == [{"date": "2026-10-28", "ours_billions": 27.1, "source_billions": 36.1},
                              {"date": "2026-10-21", "ours_billions": -17.9, "source_billions": -8.9},
                              {"date": "2026-10-14", "ours_billions": -1.2, "source_billions": 7.8}]


REAL = json.loads((Path(__file__).parent / "fixtures" / "nyfed_pd_treasury_20261124.json").read_text())                    # fetched 2026-11-24, trimmed to Sept 2024 onward


def test_the_real_download_of_2026_11_24_has_one_week_where_the_sources_own_figures_disagree():
    """Between the downloads of 2026-11-10 and 2026-11-24 the source revised the level of 2026-10-21 (425,643 to 411,822 million) and the change figure of that week by a different amount (-17,855 to -17,132), so
    for that one week the two series no longer fit (the levels give -31,676, the change figure says -17,132). The latest week fits."""
    s = D.summarize(D.parse(REAL["level"]), D.parse(REAL["change"]), date(2026, 11, 24))
    assert s["date"] == "2026-11-11" and s["net_position_billions"] == 456.0 and s["week_change_billions"] == -11.3
    assert s["check"] == {"weeks": 26, "mismatches": 1, "match": False, "latest_match": True,
                          "bad_weeks": [{"date": "2026-10-21", "ours_billions": -31.7, "source_billions": -17.1}],
                          "latest_ours_billions": -11.3, "latest_source_billions": -11.3}


def test_a_check_looks_at_the_last_26_weeks_and_no_further_back():
    assert _check(_change_off(26, 5000))["mismatches"] == 1                                                                # the oldest of the 26 weeks is looked at
    c = _check(_change_off(27, 5000))                                                                                      # one week older is not
    assert c["mismatches"] == 0 and c["weeks"] == 26 and c["match"] is True


def test_a_week_missing_from_the_levels_is_not_compared_as_if_it_were_one_week():
    lv = json.loads(json.dumps(RAW["level"]))
    del lv["pd"]["timeseries"][-5]                                                                                          # 2026-10-07 is missing: its neighbours (09-30 and 10-14) are two weeks apart
    c = _s(level=lv)["check"]
    assert c["weeks"] == 25 and c["mismatches"] == 0 and c["match"] is True and c["latest_match"] is True                  # 26 neighbours, one of them two weeks apart and left out


def test_a_week_without_a_change_figure_in_the_source_is_left_out_not_failed():
    ch = _change_off(1, 0)
    del ch[date(2026, 10, 14)]
    c = _check(ch)
    assert c["weeks"] == 25 and c["mismatches"] == 0 and c["match"] is True


def test_a_date_in_the_middle_of_a_week_is_not_a_week_on_week_change():
    lv = json.loads(json.dumps(RAW["level"]))
    lv["pd"]["timeseries"].append({"asofdate": "2026-11-02", "keyid": "PDPOSGST-TOT", "value": "470000"})                  # five days after 2026-10-28
    s = _s(level=lv)
    assert s["date"] == "2026-11-02" and s["week_change_billions"] is None and s["check"] is None


def test_a_date_in_the_middle_of_an_older_week_is_not_compared_as_a_week_even_with_a_change_figure_of_its_own():
    start = date(2026, 1, 7)
    level = {start + timedelta(days=7 * i): 100000.0 + 3000.0 * i * i for i in range(30)}
    change = {d: level[d] - level[d - timedelta(days=7)] for d in level if d != start}
    stray = start + timedelta(days=7 * 10 + 3)                                                                              # three days after the eleventh week
    level[stray], change[stray] = 555555.0, 12345.0                                                                         # a figure for it that fits nothing
    c = D.summarize(level, change, max(level))["check"]
    assert c["mismatches"] == 0 and c["match"] is True and c["weeks"] == 24                                                # the two neighbours of the stray date (three and four days apart) are left out


def test_one_comparable_week_is_enough_for_the_check_to_say_it_matched():
    start = date(2026, 1, 7)
    level = {start + timedelta(days=14 * i): 100000.0 + 5000.0 * i for i in range(10)}                                    # ten dates two weeks apart: none comparable
    last = max(level) + timedelta(days=7)
    level[last] = level[max(level)] + 5000.0
    c = D.summarize(level, {last: 5000.0}, last)["check"]
    assert c == {"weeks": 1, "mismatches": 0, "match": True, "latest_match": True, "bad_weeks": [], "latest_ours_billions": 5.0, "latest_source_billions": 5.0}


def test_a_history_shorter_than_26_weeks_is_checked_week_against_week_too():
    start = date(2026, 1, 7)
    level = {start + timedelta(days=7 * i): 100000.0 + 3000.0 * i * i for i in range(15)}                                  # fifteen weeks, each step different
    change = {d: level[d] - level[d - timedelta(days=7)] for d in level if d != start}
    c = D.summarize(level, change, max(level))["check"]
    assert c["weeks"] == 14 and c["mismatches"] == 0 and c["match"] is True and c["latest_match"] is True               # (the first version of the check paired each date with itself here and found nothing to compare)
    change[sorted(change)[-3]] += 5000.0
    c = D.summarize(level, change, max(level))["check"]
    assert c["weeks"] == 14 and c["mismatches"] == 1 and c["latest_match"] is True and c["bad_weeks"][0]["date"] == sorted(change)[-3].isoformat()


def test_a_figure_is_current_for_sixteen_days_and_overdue_from_the_seventeenth():
    assert _s(today=date(2026, 11, 12))["age_days"] == 15                                                                     # the newest week is 2026-10-28
    assert _s(today=date(2026, 11, 13))["age_days"] == 16 and _s(today=date(2026, 11, 13))["freshness"] == "CURRENT"
    assert _s(today=date(2026, 11, 14))["age_days"] == 17 and _s(today=date(2026, 11, 14))["freshness"] == "OVERDUE"


def test_the_source_and_the_page_are_named_as_the_source_names_them():
    assert _s()["source"] == "Federal Reserve Bank of New York, Primary Dealer Statistics (official, free public data)"
    r = asyncio.run(D.Dealers(client=_client(lambda req: httpx.Response(200, json=RAW["change"] if str(req.url).endswith("TOTC.json") else RAW["level"]))).overview(NOW))
    assert r["url"] == "https://www.newyorkfed.org/markets/counterparties/primary-dealers-statistics"


def test_both_series_are_asked_for_from_the_new_york_fed_by_a_named_client():
    seen = []

    def handler(req):
        seen.append((str(req.url), req.headers.get("user-agent")))
        return httpx.Response(200, json=RAW["change"] if str(req.url).endswith("TOTC.json") else RAW["level"])
    asyncio.run(D.Dealers(client=_client(handler)).overview(NOW))
    assert sorted(u for u, _ in seen) == ["https://markets.newyorkfed.org/api/pd/get/PDPOSGST-TOT.json", "https://markets.newyorkfed.org/api/pd/get/PDPOSGST-TOTC.json"]
    assert {ua for _, ua in seen} == {"ATLAS research terminal"}


def _rows(n, start=date(2026, 1, 7)):
    return [{"asofdate": (start + timedelta(days=7 * i)).isoformat(), "value": str(1000 + i)} for i in range(n)]


def test_a_response_needs_ten_weeks_and_ten_are_enough():
    assert len(D.parse({"pd": {"timeseries": _rows(10)}})) == 10
    with pytest.raises(ValueError, match="enough weeks"):
        D.parse({"pd": {"timeseries": _rows(9)}})


def test_a_row_without_a_usable_date_refuses_the_whole_response_not_only_the_row():
    for bad in ({"value": "1"}, {"asofdate": None, "value": "1"}, {"asofdate": "soon", "value": "1"}):                        # no date at all, a date of the wrong type, a date that is not one
        with pytest.raises(ValueError, match="no usable date"):
            D.parse({"pd": {"timeseries": _rows(12) + [bad]}})


def test_a_zero_is_a_figure_and_a_missing_value_is_not():
    rows = _rows(12) + [{"asofdate": "2026-04-01", "value": "0"}, {"asofdate": "2026-04-08", "value": None}, {"asofdate": "2026-04-15"}]
    got = D.parse({"pd": {"timeseries": rows}})
    assert got[date(2026, 4, 1)] == 0.0 and date(2026, 4, 8) not in got and date(2026, 4, 15) not in got


def _ok(req):
    return httpx.Response(200, json=RAW["change"] if str(req.url).endswith("TOTC.json") else RAW["level"])


def test_a_response_that_is_not_the_expected_shape_is_refused_as_too_few_weeks():
    for bad in ([], "text", 5, None, {"pd": "text"}, {"pd": []}, {"pd": {"timeseries": "abc"}}, {"pd": {"timeseries": ["abc", None, 3, [1]]}}, {"pd": {"timeseries": {"a": 1}}}):
        with pytest.raises(ValueError):
            D.parse(bad)


def test_the_year_ago_week_may_sit_three_days_either_side_and_no_further():
    start = date(2025, 1, 1)
    base = {start + timedelta(days=7 * i): 100000.0 + 1000.0 * i for i in range(70)}                                         # weekly for 70 weeks
    last = max(base)
    year_ago = last - timedelta(days=364)
    assert D.summarize(base, {}, last)["year_ago_date"] == year_ago.isoformat()                                               # exactly 52 weeks back
    for shift, found in ((-4, False), (-3, True), (3, True), (4, False)):
        w = dict(base)
        del w[year_ago]
        moved = year_ago + timedelta(days=shift)
        w[moved] = 777000.0
        r = D.summarize(w, {}, last)
        assert (r["year_ago_date"] == moved.isoformat()) is found and (r["year_ago_billions"] == 777.0) is found, shift
        if not found:
            assert r["year_ago_date"] is None and r["year_ago_billions"] is None


def test_without_a_year_of_history_there_is_no_year_ago_figure_and_nothing_breaks():
    start = date(2026, 1, 7)
    level = {start + timedelta(days=7 * i): 100000.0 + 2000.0 * i for i in range(20)}
    r = D.summarize(level, {}, max(level))
    assert r["year_ago_date"] is None and r["year_ago_billions"] is None and r["range_52w"]["weeks"] == 20


def test_the_history_is_104_weeks_in_billions_oldest_first():
    s = _s()
    h = s["history"]
    assert len(h) == 104 and h[-1] == {"date": "2026-10-28", "net_billions": 452.8}
    assert h[0]["date"] == (date(2026, 10, 28) - timedelta(weeks=103)).isoformat() == "2024-11-06" and h[0]["net_billions"] == round(float(RAW["level"]["pd"]["timeseries"][-104]["value"]) / 1000, 1)
    assert [x["date"] for x in h] == sorted(x["date"] for x in h)


def test_the_demo_answer_says_why_in_full():
    d = asyncio.run(D.Dealers(demo=True).overview(NOW))
    assert d["reason"] == "Demo mode: the real primary dealer figures are not shown because made-up values would look real."
    assert d["url"] == "https://www.newyorkfed.org/markets/counterparties/primary-dealers-statistics" and d["as_of"] == NOW.isoformat()


def test_the_answer_carries_the_time_of_the_question_and_its_age_is_counted_from_it():
    svc = D.Dealers(client=_client(_ok))
    first = asyncio.run(svc.overview(NOW))
    assert first["as_of"] == NOW.isoformat() and first["age_days"] == 13 and first["freshness"] == "CURRENT"               # 2026-10-28 to 2026-11-10
    later = NOW + timedelta(minutes=5)
    assert asyncio.run(svc.overview(later))["as_of"] == later.isoformat()                                                   # the kept copy is stamped with the new question's time


def test_a_good_answer_is_kept_for_six_hours_exactly(monkeypatch):
    clock = types.SimpleNamespace(t=1000.0, monotonic=lambda: clock.t)
    monkeypatch.setattr(D, "time", clock)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return _ok(req)
    svc = D.Dealers(client=_client(handler))
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == 2                                                                                                  # one request for each series
    clock.t += 6 * 3600 - 1
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == 2                                                                                                  # one second short of six hours: kept
    clock.t += 1
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == 4                                                                                                  # six hours: asked again


def test_a_failed_answer_is_kept_for_two_minutes_exactly(monkeypatch):
    clock = types.SimpleNamespace(t=1000.0, monotonic=lambda: clock.t)
    monkeypatch.setattr(D, "time", clock)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        return httpx.Response(503)
    svc = D.Dealers(client=_client(handler))
    asyncio.run(svc.overview(NOW))
    n = calls["n"]
    assert n >= 1
    clock.t += 119
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == n                                                                                                  # kept
    clock.t += 1
    asyncio.run(svc.overview(NOW))
    assert calls["n"] > n                                                                                                   # two minutes: asked again


def test_every_way_a_fetch_can_fail_shows_one_plain_sentence_and_no_figures():
    def boom(exc):
        def handler(req):
            raise exc
        return handler
    cases = [
        (boom(httpx.ConnectError("")), "the connection could not be made"),
        (boom(httpx.ReadTimeout("")), "the request timed out"),
        (lambda req: httpx.Response(503), "the server had an error, HTTP 503"),
        (lambda req: httpx.Response(200, text="<html>maintenance</html>"), "the answer was not valid JSON"),
        (lambda req: httpx.Response(200, json=["not", "an", "object"]), "the data failed a check"),
        (lambda req: httpx.Response(200, json={"pd": {"timeseries": []}}), "the data failed a check"),
    ]
    for handler, words in cases:
        r = asyncio.run(D.Dealers(client=_client(handler)).overview(NOW))
        assert r["available"] is False and r["reason"].startswith("The New York Fed could not be read right now (") and words in r["reason"], (words, r["reason"])
        assert "net_position_billions" not in r and r["demo"] is False


def test_a_client_the_service_made_is_closed_with_a_30_second_timeout_and_one_it_was_given_is_left_open(monkeypatch):
    real = httpx.AsyncClient
    made = []

    def factory(**kw):
        c = real(transport=httpx.MockTransport(_ok))
        made.append((c, kw))
        return c
    monkeypatch.setattr(D.httpx, "AsyncClient", factory)
    r = asyncio.run(D.Dealers().overview(NOW))
    assert r["available"] and len(made) == 1 and made[0][0].is_closed and made[0][1] == {"timeout": 30}
    given = real(transport=httpx.MockTransport(_ok))
    asyncio.run(D.Dealers(client=given).overview(NOW))
    assert not given.is_closed and len(made) == 1


def test_year_ago_and_52_week_range_equal_an_independent_calculation():
    rows = {r["asofdate"]: float(r["value"]) for r in RAW["level"]["pd"]["timeseries"] if r["value"] not in ("*", "N/A")}
    last = max(rows)
    window = {d: v for d, v in rows.items() if (date.fromisoformat(last) - date.fromisoformat(d)).days < 365}
    s = _s()
    assert s["year_ago_date"] == "2025-10-29" and s["year_ago_billions"] == round(rows["2025-10-29"] / 1000, 1) == 413.3
    r = s["range_52w"]
    assert r["low_billions"] == round(min(window.values()) / 1000, 1) == 382.9 and r["high_billions"] == round(max(window.values()) / 1000, 1) == 557.1
    assert r["weeks"] == len(window) and r["weeks_lower_than_now"] == sum(1 for v in window.values() if v < rows[last])


def test_weeks_the_source_does_not_report_are_left_out_not_zero():
    lv = json.loads(json.dumps(RAW["level"]))
    lv["pd"]["timeseries"].append({"asofdate": "2026-11-04", "keyid": "PDPOSGST-TOT", "value": "*"})
    s = _s(level=lv)
    assert s["date"] == "2026-10-28"                                                                                          # the "*" week is not the newest week and not a zero
    lv["pd"]["timeseries"][-3]["value"] = "N/A"                                                                              # and 2026-10-21 is not reported either
    parsed = D.parse(lv)
    assert date(2026, 10, 21) not in parsed and date(2026, 11, 4) not in parsed and parsed[date(2026, 10, 28)] == 452759.0


def test_a_gap_in_the_weeks_gives_no_week_change_instead_of_a_two_week_change():
    lv = json.loads(json.dumps(RAW["level"]))
    del lv["pd"]["timeseries"][-2]                                                                                           # drop 2026-10-21
    s = _s(level=lv)
    assert s["week_change_billions"] is None and s["check"] is None


def test_old_data_is_overdue():
    s = _s(today=date(2026, 12, 15))
    assert s["freshness"] == "OVERDUE" and s["age_days"] == 48


def test_bad_data_is_refused():
    with pytest.raises(ValueError):
        D.parse({"pd": {"timeseries": [{"asofdate": "soon", "value": "1"}]}})
    with pytest.raises(ValueError):
        D.parse({"pd": {"timeseries": RAW["level"]["pd"]["timeseries"][:5]}})
    with pytest.raises(ValueError):
        D.parse({})


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_failure_then_recovery_and_caching():
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] <= 2:
            return httpx.Response(503)
        return httpx.Response(200, json=RAW["change"] if str(req.url).endswith("TOTC.json") else RAW["level"])

    svc = D.Dealers(client=_client(handler))
    bad = asyncio.run(svc.overview(NOW))
    assert bad["available"] is False and "HTTP 503" in bad["reason"] and "net_position_billions" not in bad
    svc._cache = None
    good = asyncio.run(svc.overview(NOW))
    assert good["available"] and good["net_position_billions"] == 452.8 and good["check"]["match"]
    n = calls["n"]
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == n


def test_the_change_series_failing_to_parse_still_shows_the_level_but_no_check():
    def handler(req):
        return httpx.Response(200, json={"pd": {"timeseries": []}} if str(req.url).endswith("TOTC.json") else RAW["level"])
    r = asyncio.run(D.Dealers(client=_client(handler)).overview(NOW))
    assert r["available"] and r["net_position_billions"] == 452.8 and r["check"] is None


def test_demo_mode_invents_nothing():
    d = asyncio.run(D.Dealers(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and "Demo" in d["reason"] and "net_position_billions" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/dealers")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
