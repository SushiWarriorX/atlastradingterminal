"""Euro-area bank interest rates on EXISTING loans and deposits (ECB Data Portal, MIR dataflow, outstanding amounts: the average rate on what banks already hold, monthly, with the ECB's own split of each month's change into a
rate part and a weight part): parsed from real responses (fetched 2026-11-24 05:1x UTC: the provider's four requests with 125 months each; the whole record, 285 months from 2003-01, was read to set the checks, see the module's docstring)."""
import asyncio
import json
import types
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import eurostockrates as S
from atlas_api.app import create_app
from atlas_api.failreason import dates_in_words, fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_stock_rates.json").read_text())
TODAY = date(2026, 11, 24)
NOW = datetime(2026, 11, 24, 12, tzinfo=timezone.utc)
LAST = date(2026, 9, 1)                                                  # the newest month of the real record
BLOCKS = ("firms", "households", "house", "consumer", "firms_dep", "hh_dep")
SPLIT = ("firms", "house", "consumer", "firms_dep", "hh_dep")            # the five that come with the rate and weight components
LOANS = ("firms", "households", "house", "consumer")
DEPOSITS = ("firms_dep", "hh_dep")
PARTS = {"firms": ("F", "I", "J"), "households": (), "house": ("F", "I", "J"), "consumer": ("F", "I", "J"), "firms_dep": ("L", "H"), "hh_dep": ("L", "H")}
PART_WORDS = {"F": "up to 1 year", "I": "1 to 5 years", "J": "over 5 years", "L": "up to 2 years", "H": "over 2 years"}
KINDS = ("rate", "rate_step", "mix_step", "rate_cum", "mix_cum", "total_cum")
LABEL = {"firms": "loans to firms", "households": "loans to households", "house": "loans for house purchase", "consumer": "loans for consumption and other purposes",
         "firms_dep": "firms' deposits with an agreed maturity", "hh_dep": "households' deposits with an agreed maturity"}
SHORT = {"firms": "loans to firms", "households": "loans to households", "house": "house purchase loans", "consumer": "consumer and other loans", "firms_dep": "firms' deposits", "hh_dep": "households' deposits"}
IDS = tuple(i for b in BLOCKS for i in ([f"{b}.A.{k}" for k in KINDS] if b in SPLIT else [f"{b}.A.rate"]) + [f"{b}.{p}.rate" for p in PARTS[b]])
RATES = tuple(i for i in IDS if i.endswith(".rate"))
RATE_U, POINT_U = ("PCPA", "0"), ("PO", "0")
UNITS = {sid: RATE_U if sid.endswith(".rate") else POINT_U for sid in IDS}
KIND_WORDS = {"rate_step": "the rate component of the change in {}", "mix_step": "the weight component of the change in {}", "rate_cum": "the accumulated rate component for {}",
              "mix_cum": "the accumulated weight component for {}", "total_cum": "the accumulated change for {}"}
NAMES = {}
for _b in BLOCKS:
    NAMES[f"{_b}.A.rate"] = f"the rate on {SHORT[_b]}"
    for _p in PARTS[_b]:
        NAMES[f"{_b}.{_p}.rate"] = f"the rate on {SHORT[_b]} ({PART_WORDS[_p]})"
    if _b in SPLIT:
        for _k, _w in KIND_WORDS.items():
            NAMES[f"{_b}.A.{_k}"] = _w.format(SHORT[_b])
# the limits set from the real record, spelled out here so that a changed limit fails a test instead of moving the test with it
RATE_LIMITS, STEP_LIMITS, CUM_LIMITS = (-1.0, 12.0), (-2.0, 2.0), (-10.0, 10.0)
TOL = 2 ** -6                                                            # 0.015625
MOVE = 1.5
# a world: per block (rate at the start, the rate component and the weight component of each month's change), all exact in binary, so that every identity holds with a gap of exactly zero and an edge can be hit exactly
STEP = {"firms": (2.0, 0.03125, -0.015625), "house": (2.5, 0.015625, 0.0), "consumer": (3.25, 0.0625, -0.03125), "firms_dep": (1.0, 0.046875, -0.015625), "hh_dep": (1.5, 0.015625, 0.015625)}
# the rates of the parts sit around the rate on all of it (exact offsets), and "households" is the middle of house purchase and consumption: every total lies inside the range of its parts
OFFSET = {"firms": {"F": -0.5, "I": 0.25, "J": 0.5}, "house": {"F": 0.5, "I": 0.25, "J": -0.5}, "consumer": {"F": 1.0, "I": 0.5, "J": -0.25}, "firms_dep": {"L": -0.25, "H": 0.5}, "hh_dep": {"L": -0.5, "H": 0.25}}


def _i(d):
    return d.year * 12 + d.month - 1


def _d(i):
    return date(i // 12, i % 12 + 1, 1)


def _lab(d):
    return f"{d.year}-{d.month:02d}"


def _back(d, n):
    return _d(_i(d) - n)


def _world(last=LAST, extra=0, status=None):
    """The 44 series for the 120 months (plus `extra` older ones) ending on `last`, where every check passes by construction."""
    n = 120 + extra
    months = [_d(_i(last) - n + 1 + k) for k in range(n)]
    v = {}
    for b, (base, rs, ms) in STEP.items():
        rate = {m: base + (rs + ms) * k for k, m in enumerate(months)}
        v[f"{b}.A.rate"] = rate
        v[f"{b}.A.rate_step"] = {m: rs for m in months}
        v[f"{b}.A.mix_step"] = {m: ms for m in months}
        v[f"{b}.A.rate_cum"] = {m: rs * k for k, m in enumerate(months)}
        v[f"{b}.A.mix_cum"] = {m: ms * k for k, m in enumerate(months)}
        v[f"{b}.A.total_cum"] = {m: (rs + ms) * k for k, m in enumerate(months)}
        for p, off in OFFSET[b].items():
            v[f"{b}.{p}.rate"] = {m: x + off for m, x in rate.items()}
    v["households.A.rate"] = {m: (v["house.A.rate"][m] + v["consumer.A.rate"][m]) / 2 for m in months}
    return {sid: v[sid] for sid in IDS}, dict(UNITS), {} if status is None else status


def _real():
    v = {sid: {date(int(m[:4]), int(m[5:]), 1): x for m, x in zip(d["months"], d["values"])} for sid, d in F["series"].items()}
    return v, {sid: tuple(d["unit"]) for sid, d in F["series"].items()}, {sid: d["status"][-1] for sid, d in F["series"].items()}


def _run(world, today=TODAY):
    return S.summarize(*world, today)


def _err(world, today=TODAY):
    """The refusal's text, or None when the world passes every check."""
    try:
        _run(world, today)
    except ValueError as e:
        return str(e)
    return None


def _set(w, sid, delta, back=0):
    """Add `delta` to one series in the month `back` before the newest, and say which month it was."""
    d = _back(LAST, back)
    w[0][sid][d] += delta
    return d


def _moved(sid, ch, d):
    return f"{NAMES[sid]} moved by {ch:+.2f} points in {_lab(d)}, more than 1.5"


def _a_msg(b, d, ch, s, gap):
    return f"{SHORT[b]}: the rate moved {ch:+.2f} in {_lab(d)}, its two components add up to {s:+.2f} (gap {gap:.3f})"


def _b_msg(b, d, x, y, gap):
    return f"{SHORT[b]}: accumulated rate part moved {x:+.2f}, month's part {y:+.2f} in {_lab(d)} (gap {gap:.3f})"


def _c_msg(b, d, x, y, gap):
    return f"{SHORT[b]}: accumulated weight part moved {x:+.2f}, month's part {y:+.2f} in {_lab(d)} (gap {gap:.3f})"


def _d_msg(b, d, o, m, n, gap):
    return f"{SHORT[b]}: accumulated change {o:+.2f} is not {m:+.2f} plus {n:+.2f} in {_lab(d)} (gap {gap:.3f})"


def _e_msg(b, r, o, gap):
    return f"{SHORT[b]}: over 119 months the rate moved {r:+.2f} but the accumulated change {o:+.2f} (gap {gap:.3f})"


def _between_msg(block, d, t, out, lo, hi):
    return f"{SHORT[block]}: {t:.2f}% in {_lab(d)} is {out:.3f} outside its parts' {lo:.2f}% to {hi:.2f}%"


def test_the_world_passes_every_check_with_gaps_of_exactly_zero():
    r = _run(_world())
    assert r["available"] is True and r["detail"]["largest_identity_gap_points"] == 0.0 and r["detail"]["largest_identity_gap_month"] is None and r["detail"]["largest_identity_gap_series"] is None
    assert _err(_world(extra=10)) is None                                                                                     # older months before the 120 are held to nothing


def test_the_real_latest_rates_changes_ranges_splits_and_parts_by_hand():
    r = _run(_real())
    assert r["available"] is True and r["month"] == "2026-09" and r["date"] == "2026-09-01" and r["age_days"] == 55 and r["freshness"] == "CURRENT" and r["provisional"] is True      # 2026-09-30 to 2026-11-24 is 55 days
    window = lambda lo, lo_m, hi, hi_m, share: {"months": 120, "lowest": {"pct": lo, "month": lo_m}, "highest": {"pct": hi, "month": hi_m}, "share_lower_pct": share}
    parts = lambda *xs: [{"id": p, "label": PART_WORDS[p], "rate_pct": x} for p, x in xs]
    assert r["loans"] == [
        {"id": "firms", "label": "loans to firms", "rate_pct": 3.58, "change_month_points": 0.07, "change_year_points": 0.28, "window": window(1.59, "2021-12", 4.06, "2024-04", 82),
         "month_split": {"rates_points": 0.07, "mix_points": 0.0}, "year_split": {"rates_points": 0.27, "mix_points": 0.01}, "parts": parts(("F", 3.94), ("I", 4.15), ("J", 3.27))},
        {"id": "households", "label": "loans to households", "rate_pct": 3.3, "change_month_points": 0.05, "change_year_points": 0.2, "window": window(2.12, "2022-04", 3.3, "2026-09", 99),
         "month_split": None, "year_split": None, "parts": []},
        {"id": "house", "label": "loans for house purchase", "rate_pct": 2.57, "change_month_points": 0.03, "change_year_points": 0.17, "window": window(1.61, "2022-01", 2.57, "2026-09", 99),
         "month_split": {"rates_points": 0.03, "mix_points": 0.0}, "year_split": {"rates_points": 0.17, "mix_points": 0.01}, "parts": parts(("F", 4.06), ("I", 3.91), ("J", 2.56))},
        {"id": "consumer", "label": "loans for consumption and other purposes", "rate_pct": 6.02, "change_month_points": 0.09, "change_year_points": 0.32, "window": window(3.99, "2022-04", 6.02, "2026-09", 99),
         "month_split": {"rates_points": 0.09, "mix_points": 0.0}, "year_split": {"rates_points": 0.3, "mix_points": 0.02}, "parts": parts(("F", 7.27), ("I", 6.8), ("J", 5.48))}]
    assert r["deposits"] == [
        {"id": "firms_dep", "label": "firms' deposits with an agreed maturity", "rate_pct": 2.48, "change_month_points": 0.09, "change_year_points": 0.25, "window": window(0.16, "2021-12", 3.55, "2024-05", 79),
         "month_split": {"rates_points": 0.09, "mix_points": 0.0}, "year_split": {"rates_points": 0.26, "mix_points": -0.01}, "parts": parts(("L", 2.38), ("H", 3.0))},
        {"id": "hh_dep", "label": "households' deposits with an agreed maturity", "rate_pct": 1.97, "change_month_points": 0.04, "change_year_points": 0.04, "window": window(1.13, "2022-01", 2.54, "2024-05", 78),
         "month_split": {"rates_points": 0.04, "mix_points": 0.0}, "year_split": {"rates_points": 0.06, "mix_points": -0.02}, "parts": parts(("L", 1.92), ("H", 2.05))}]
    assert r["detail"] == {"months_checked": 120, "identities_checked": 2390, "largest_identity_gap_points": 0.01, "largest_identity_gap_month": "2016-12", "largest_identity_gap_series": "loans to firms", "between_checked": 720}
    assert r["checks"] == {"units_ok": True, "months_in_a_row": True, "range_ok": True, "monthly_move_ok": True, "identities_ok": True, "totals_inside_parts_ok": True}
    assert r["source"].startswith("European Central Bank") and r["url"] == "https://data-api.ecb.europa.eu/service/data/MIR/M.U2.B.A20.A.R.A.2240.EUR.O"
    assert "not a market signal or a forecast" in r["note"] and "already have on their books" in r["note"] and "Plain checks: the units are the ones assumed and no month is missing" in r["note"] and "The newest month is provisional and is revised later" in r["note"]


def test_the_real_record_by_plain_python_outside_the_module():
    s = F["series"]
    assert len(s) == 44 and all(d["months"][-1] == "2026-09" and len(d["months"]) == 125 and d["months"][0] == "2016-05" for d in s.values())
    assert {sid: tuple(d["unit"]) for sid, d in s.items()} == UNITS
    for sid, now, m1, m12, lower, lo, lo_m, hi, hi_m in (
            ("firms.A.rate", 3.58, 3.51, 3.3, 98, 1.59, "2021-12", 4.06, "2024-04"), ("households.A.rate", 3.3, 3.25, 3.1, 119, 2.12, "2022-04", 3.3, "2026-09"), ("house.A.rate", 2.57, 2.54, 2.4, 119, 1.61, "2022-01", 2.57, "2026-09"),
            ("consumer.A.rate", 6.02, 5.93, 5.7, 119, 3.99, "2022-04", 6.02, "2026-09"), ("firms_dep.A.rate", 2.48, 2.39, 2.23, 95, 0.16, "2021-12", 3.55, "2024-05"), ("hh_dep.A.rate", 1.97, 1.93, 1.93, 94, 1.13, "2022-01", 2.54, "2024-05")):
        m, x = s[sid]["months"], s[sid]["values"]
        ten, ten_m = x[-120:], m[-120:]
        assert (x[-1], x[-2], x[-13]) == (now, m1, m12) and ten_m[0] == "2016-10"                                                  # the newest value, a month and a year before it
        assert sum(1 for y in ten if y < now) == lower
        assert (min(ten), ten_m[ten.index(min(ten))], max(ten), ten_m[ten.index(max(ten))]) == (lo, lo_m, hi, hi_m)
    for b, rate, mix in (("firms", 0.27, 0.01), ("house", 0.17, 0.01), ("consumer", 0.3, 0.02), ("firms_dep", 0.26, -0.01), ("hh_dep", 0.06, -0.02)):
        assert (round(s[f"{b}.A.rate_cum"]["values"][-1] - s[f"{b}.A.rate_cum"]["values"][-13], 2), round(s[f"{b}.A.mix_cum"]["values"][-1] - s[f"{b}.A.mix_cum"]["values"][-13], 2)) == (rate, mix)
    # the ECB's arithmetic by hand for loans to firms in the newest month: the rate rose 0.07 (3.58 against 3.51), its rate part is +0.07 and its weight part 0.00; the accumulated parts are -1.29 and -0.20, which make the accumulated change -1.49
    f = lambda k: s[f"firms.A.{k}"]["values"]
    assert (f("rate")[-1] - f("rate")[-2], f("rate_step")[-1], f("mix_step")[-1], f("rate_cum")[-1], f("mix_cum")[-1], f("total_cum")[-1]) == (pytest.approx(0.07), 0.07, 0.0, -1.29, -0.2, -1.49)
    assert round(-1.29 + -0.2, 2) == -1.49 and round(3.58 - 5.06, 2) == -1.48                                                  # 5.06 was the rate in 2003-01, when the accumulated change starts at zero: -1.48 against -1.49, one rounding
    assert {sid: d["status"][-1] for sid, d in s.items() if d["status"][-1] != "A"} == {sid: "P" for sid in RATES}              # the ECB marks the newest month of every RATE provisional and the newest month of the components final


@pytest.mark.parametrize("sid", RATES)
def test_the_newest_value_is_provisional_when_any_rate_the_card_prints_is_not_final(sid):
    for st, expected in (("A", False), ("", False), ("P", True), ("E", True), ("F", True)):
        assert _run(_world(status={sid: st}))["provisional"] is expected, (sid, st)


def test_only_the_rates_decide_whether_it_says_provisional_not_the_components():
    components = {sid: "P" for sid in IDS if sid not in RATES}
    assert len(components) == 25 and _run(_world(status=components))["provisional"] is False                                 # the rate and weight parts are provisional too and are not printed as rates
    assert _run(_world(status={**components, "hh_dep.L.rate": "P"}))["provisional"] is True
    assert _run(_world(status={sid: "A" for sid in IDS}))["provisional"] is False


def test_overdue_after_75_days_from_the_end_of_the_newest_month():
    end = date(2026, 9, 30)
    r = _run(_world(), end + timedelta(days=75))
    assert (r["age_days"], r["freshness"]) == (75, "CURRENT")
    r = _run(_world(), end + timedelta(days=76))
    assert (r["age_days"], r["freshness"]) == (76, "OVERDUE")
    assert _run(_world(), end)["age_days"] == 0


def test_each_month_ends_on_its_own_last_day():
    for last, today, age in ((date(2026, 2, 1), date(2026, 3, 5), 5), (date(2024, 2, 1), date(2024, 3, 2), 2), (date(2025, 12, 1), date(2026, 1, 4), 4), (date(2026, 4, 1), date(2026, 5, 2), 2), (date(2026, 1, 1), date(2026, 2, 3), 3)):
        r = _run(_world(last), today)
        assert r["month"] == _lab(last) and r["age_days"] == age, last                                                         # February 2024 has 29 days, April 30, December 31


def _g(n, last=LAST, f=lambda k: 0.1 * k):
    """A rate series of `n` months ending on `last` with the values f(0), f(1), ..., for the ten-year comparison."""
    return {_back(last, n - 1 - k): f(k) for k in range(n)}


def test_the_ten_year_comparison_needs_60_months_and_counts_only_the_120_newest():
    short = S._range(_g(59), LAST)
    assert short is None and S._range(_g(60), LAST)["months"] == 60
    r = S._range(_g(125, f=lambda k: 1000.0 - k), LAST)                                                                          # older months are higher but only the newest 120 count
    assert r["months"] == 120 and r["highest"] == {"pct": 995.0, "month": _lab(_back(LAST, 119))} and r["lowest"] == {"pct": 876.0, "month": _lab(LAST)}


def test_the_ten_year_comparison_looks_only_at_months_up_to_the_one_asked_about():
    g = _g(125, f=lambda k: 0.1 * k)                                                                                          # rising to 12.4 in the newest month
    r = S._range(g, _back(LAST, 5))                                                                                           # asked about the month five before the newest: the later months are not part of its ten years
    assert r["months"] == 120 and r["highest"] == {"pct": 11.9, "month": _lab(_back(LAST, 5))} and r["lowest"] == {"pct": 0.0, "month": _lab(_back(LAST, 124))} and r["share_lower_pct"] == 99


def test_the_share_of_lower_months_counts_only_months_strictly_below_and_is_a_whole_percent():
    g = _g(120, f=lambda k: 1.0 if k < 60 else 2.0)
    g[LAST] = 2.0
    assert S._range(g, LAST)["share_lower_pct"] == 50                                                                         # 60 of 120 are below, the 59 equal ones and the newest itself are not
    g = _g(120, f=lambda k: 0.0 if k < 77 else 1.0)
    assert S._range(g, LAST)["share_lower_pct"] == 64                                                                         # 77 of 120 is 64.17, shown as 64
    g = _g(120, f=lambda k: 0.0 if k < 93 else 1.0)
    assert S._range(g, LAST)["share_lower_pct"] == 78                                                                         # 93 of 120 is 77.5, shown as 78 (the even one)
    g = _g(120, f=lambda k: 0.0 if k < 103 else 1.0)
    assert S._range(g, LAST)["share_lower_pct"] == 86                                                                         # 103 of 120 is 85.8


def test_lowest_and_highest_with_their_months_and_two_decimals():
    g = _g(120, f=lambda k: 2.1049 if k == 7 else (1.7451 if k == 40 else 2.0))
    r = S._range(g, LAST)
    assert r["lowest"] == {"pct": 1.75, "month": _lab(_back(LAST, 119 - 40))} and r["highest"] == {"pct": 2.1, "month": _lab(_back(LAST, 119 - 7))}


def test_every_figure_is_shown_to_the_decimals_the_card_prints():
    v = _world()[0]
    last, prev, ya = LAST, _back(LAST, 1), _back(LAST, 12)
    v["firms.A.rate"][last], v["firms.A.rate"][prev], v["firms.A.rate"][ya] = 3.5849, 3.5051, 3.3049                          # unrounded values, as a source with four decimals would give
    v["firms.F.rate"][last] = 3.9449
    r = S._row(v, "firms", last)
    assert r["rate_pct"] == 3.58 and r["change_month_points"] == 0.08 and r["change_year_points"] == 0.28 and r["parts"][0]["rate_pct"] == 3.94
    v["hh_dep.A.rate_cum"][last] = v["hh_dep.A.rate_cum"][ya] + 0.1249
    v["hh_dep.A.mix_cum"][last] = v["hh_dep.A.mix_cum"][ya] - 0.0051
    v["hh_dep.A.rate_step"][last] = 0.0149
    v["hh_dep.A.mix_step"][last] = -0.0051
    s = S._row(v, "hh_dep", last)
    assert s["year_split"] == {"rates_points": 0.12, "mix_points": -0.01} and s["month_split"] == {"rates_points": 0.01, "mix_points": -0.01}
    v["hh_dep.A.rate_step"][last] = 0.0151
    assert S._row(v, "hh_dep", last)["month_split"]["rates_points"] == 0.02                                                   # 0.0151 rounds up


def test_a_figure_that_rounds_to_zero_is_zero_not_minus_zero():
    v = _world()[0]
    v["hh_dep.A.mix_step"][LAST] = -0.004
    v["hh_dep.A.mix_cum"][LAST] = v["hh_dep.A.mix_cum"][_back(LAST, 12)] - 0.004
    v["hh_dep.A.rate"][LAST] = v["hh_dep.A.rate"][_back(LAST, 1)] - 0.004
    v["hh_dep.A.rate"][_back(LAST, 12)] = v["hh_dep.A.rate"][LAST] + 0.003
    r = S._row(v, "hh_dep", LAST)
    for x in (r["month_split"]["mix_points"], r["year_split"]["mix_points"], r["change_month_points"], r["change_year_points"]):
        assert str(x) == "0.0"                                                                                                # -0.004 rounds to -0.0 in Python: the card must not be handed a minus zero


def test_only_the_blocks_the_source_splits_have_a_split_and_the_parts_come_in_the_order_of_the_card():
    r = _run(_world())
    rows = {x["id"]: x for x in r["loans"] + r["deposits"]}
    assert [x["id"] for x in r["loans"]] == list(LOANS) and [x["id"] for x in r["deposits"]] == list(DEPOSITS)
    assert [(b, x["month_split"] is not None, x["year_split"] is not None) for b, x in rows.items()] == [("firms", True, True), ("households", False, False), ("house", True, True), ("consumer", True, True), ("firms_dep", True, True), ("hh_dep", True, True)]
    assert {b: [p["label"] for p in x["parts"]] for b, x in rows.items()} == {"firms": ["up to 1 year", "1 to 5 years", "over 5 years"], "households": [], "house": ["up to 1 year", "1 to 5 years", "over 5 years"],
                                                                              "consumer": ["up to 1 year", "1 to 5 years", "over 5 years"], "firms_dep": ["up to 2 years", "over 2 years"], "hh_dep": ["up to 2 years", "over 2 years"]}
    assert {b: x["label"] for b, x in rows.items()} == LABEL


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    for sid in ("firms.A.rate", "households.A.rate", "hh_dep.H.rate", "firms.A.rate_step", "consumer.A.mix_cum", "firms_dep.A.total_cum"):
        for other in (("PCPA", "2"), ("PCPA", ""), ("PO", "0"), ("EUR", "6"), ("", ""), ("PURE_NUMB", "0")):
            w = _world()
            if other == UNITS[sid]:
                continue
            w[1][sid] = other
            assert _err(w) == f"the ECB reports {NAMES[sid]} in other units than the card assumes", (sid, other)
    w = _world()
    w[1]["firms.A.rate"], w[1]["hh_dep.L.rate"] = ("PO", "0"), ("PCPA", "9")
    assert _err(w) == f"the ECB reports {NAMES['firms.A.rate']} in other units than the card assumes"                          # the first in the card's order speaks
    w = _world()
    assert _err((w[0], {k: u for k, u in w[1].items() if k != "firms.A.rate"}, {})) is None                                  # a series with no unit given is not a different unit: parse always gives one for a series it read


def test_series_ending_in_different_months_are_refused():
    for sid in ("firms.A.rate", "hh_dep.A.total_cum", "consumer.J.rate", "households.A.rate"):
        w = _world()
        del w[0][sid][LAST]
        assert _err(w) == "the stock rate series end in different months", sid
        w = _world()
        w[0][sid][_back(LAST, -1)] = 3.0
        assert _err(w) == "the stock rate series end in different months", sid


def test_a_month_missing_in_the_last_120_is_refused_and_an_older_one_is_not():
    for back in (0, 1, 60, 118, 119):
        w = _world(extra=5)
        d = _back(LAST, back)
        del w[0]["consumer.I.rate"][d]
        if back == 0:
            assert _err(w) == "the stock rate series end in different months"
        else:
            assert _err(w) == f"{NAMES['consumer.I.rate']} is missing for {_lab(d)}", back
    w = _world(extra=5)
    del w[0]["consumer.I.rate"][_back(LAST, 120)]
    assert _err(w) is None                                                                                                   # the 121st month back is not held to anything
    w = _world(extra=5)
    del w[0]["firms.A.mix_cum"][_back(LAST, 50)]
    w2 = _world(extra=5)
    del w2[0]["firms.A.rate"][_back(LAST, 50)]
    assert _err(w) == f"{NAMES['firms.A.mix_cum']} is missing for {_lab(_back(LAST, 50))}" and _err(w2) == f"{NAMES['firms.A.rate']} is missing for {_lab(_back(LAST, 50))}"


def test_the_series_must_be_there_for_all_120_months_when_only_119_are_held():
    w = _world()
    for sid in w[0]:
        del w[0][sid][_back(LAST, 119)]
    assert _err(w) == f"{NAMES['firms.A.rate']} is missing for {_lab(_back(LAST, 119))}"


def _range_msg(sid, x, d, lo, hi, percent):
    if percent:
        return f"{NAMES[sid]} is {x:.2f}% in {_lab(d)}, outside {lo:g}% to {hi:g}%"
    return f"{NAMES[sid]} is {x:.2f} in {_lab(d)}, outside {lo:g} to {hi:g} points"


@pytest.mark.parametrize("sid, lo, hi, percent", [("firms.A.rate", -1.0, 12.0, True), ("hh_dep.L.rate", -1.0, 12.0, True), ("households.A.rate", -1.0, 12.0, True), ("consumer.A.rate_step", -2.0, 2.0, False),
                                                  ("house.A.mix_step", -2.0, 2.0, False), ("firms_dep.A.rate_cum", -10.0, 10.0, False), ("hh_dep.A.mix_cum", -10.0, 10.0, False), ("firms.A.total_cum", -10.0, 10.0, False)])
def test_a_value_must_lie_inside_the_limit_of_its_kind_in_every_month_of_the_window(sid, lo, hi, percent):
    for edge, ok in ((lo, True), (hi, True), (lo - 0.0625, False), (hi + 0.0625, False)):
        for back in (0, 60, 119):
            w = _world()
            d = _back(LAST, back)
            w[0][sid][d] = edge
            err = _err(w)
            if ok:
                assert err is None or not err.startswith(f"{NAMES[sid]} is {edge:.2f}"), (sid, edge, back, err)                  # at the limit itself the range check says nothing (a later check may)
            else:
                assert err == _range_msg(sid, edge, d, lo, hi, percent), (sid, edge, back, err)


def test_a_range_error_names_the_series_the_value_the_month_and_the_limits():
    w = _world()
    w[0]["consumer.F.rate"][_back(LAST, 7)] = 12.5
    assert _err(w) == _range_msg("consumer.F.rate", 12.5, _back(LAST, 7), -1.0, 12.0, True) == f"{NAMES['consumer.F.rate']} is 12.50% in {_lab(_back(LAST, 7))}, outside -1% to 12%"
    w = _world()
    w[0]["firms_dep.A.mix_step"][_back(LAST, 9)] = -2.5
    assert _err(w) == f"{NAMES['firms_dep.A.mix_step']} is -2.50 in {_lab(_back(LAST, 9))}, outside -2 to 2 points"
    w = _world()
    w[0]["hh_dep.A.rate_cum"][_back(LAST, 3)] = 10.5
    assert _err(w) == f"{NAMES['hh_dep.A.rate_cum']} is 10.50 in {_lab(_back(LAST, 3))}, outside -10 to 10 points"


def test_the_oldest_month_outside_the_window_is_not_held_to_the_ranges():
    w = _world(extra=5)
    w[0]["firms.A.rate"][_back(LAST, 120)] = 99.0
    assert _err(w) is None


@pytest.mark.parametrize("sid", RATES)
def test_a_rate_may_move_by_up_to_one_and_a_half_points_in_a_month(sid):
    for ch, ok in ((MOVE, True), (-MOVE, True), (MOVE + 0.0625, False), (-MOVE - 0.0625, False)):
        w = _world()
        prev = _back(LAST, 1)
        w[0][sid][LAST] = w[0][sid][prev] + ch                                                                                # the newest month is exactly `ch` away from the month before it
        err = _err(w)
        if ok:
            assert err is None or "moved by" not in err, (sid, ch, err)
        else:
            assert err == _moved(sid, ch, LAST), (sid, ch, err)


def test_a_move_error_names_the_series_the_size_the_month_and_the_limit():
    w = _world()
    d = _back(LAST, 4)
    w[0]["consumer.I.rate"][d] = w[0]["consumer.I.rate"][_back(d, 1)] + 1.75
    assert _err(w) == f"{NAMES['consumer.I.rate']} moved by +1.75 points in {_lab(d)}, more than 1.5" == _moved("consumer.I.rate", 1.75, d)


def test_the_components_and_accumulated_figures_are_not_held_to_the_monthly_move():
    w = _world()
    w[0]["firms.A.rate_step"][_back(LAST, 6)] = 1.9                                                                          # a monthly component of 1.9 points is inside its own limit of 2 and may be far from last month's
    err = _err(w)
    assert err is not None and "moved by" not in err                                                                         # (the identities speak instead)


@pytest.mark.parametrize("b", SPLIT)
def test_the_rate_must_change_by_the_sum_of_the_ecbs_rate_and_weight_parts_to_0_015625_points_for_each_block(b):
    sid = f"{b}.A.rate_step"
    for back in (0, 1, 50, 118):                                                                                             # the oldest month of the window has no month before it
        for delta, ok in ((TOL, True), (-TOL, True), (TOL + 2 ** -7, False), (-TOL - 2 ** -7, False)):
            w = _world()
            d = _set(w, sid, delta, back)
            err = _err(w)
            if ok:
                assert err is None, (b, back, delta, err)
            else:
                s = w[0][sid][d] + w[0][f"{b}.A.mix_step"][d]
                ch = w[0][f"{b}.A.rate"][d] - w[0][f"{b}.A.rate"][_back(d, 1)]
                assert err == _a_msg(b, d, ch, s, abs(ch - s)), (b, back, delta, err)


def test_the_oldest_month_of_the_window_has_no_change_to_compare_and_is_not_held_to_the_first_identity():
    w = _world()
    d = _set(w, "firms.A.rate_step", 0.5, 119)
    assert d == _back(LAST, 119) and _err(w) is None


@pytest.mark.parametrize("b", SPLIT)
def test_the_accumulated_rate_part_must_follow_the_months_rate_part_to_0_015625_points_for_each_block(b):
    sid = f"{b}.A.rate_cum"
    for back in (1, 50, 118):
        for delta, ok in ((TOL, True), (-TOL, True), (TOL + 2 ** -7, False), (-TOL - 2 ** -7, False)):
            w = _world()
            d = _set(w, sid, delta, back)
            err = _err(w)
            if ok:
                assert err is None, (b, back, delta, err)
            else:
                x = w[0][sid][d] - w[0][sid][_back(d, 1)]
                y = w[0][f"{b}.A.rate_step"][d]
                assert err == _b_msg(b, d, x, y, abs(x - y)), (b, back, delta, err)


@pytest.mark.parametrize("b", SPLIT)
def test_the_accumulated_weight_part_must_follow_the_months_weight_part_to_0_015625_points_for_each_block(b):
    sid = f"{b}.A.mix_cum"
    for back in (1, 50, 118):
        for delta, ok in ((TOL, True), (-TOL, True), (TOL + 2 ** -7, False), (-TOL - 2 ** -7, False)):
            w = _world()
            d = _set(w, sid, delta, back)
            err = _err(w)
            if ok:
                assert err is None, (b, back, delta, err)
            else:
                prev = _back(d, 1)
                x = w[0][sid][d] - w[0][sid][prev]
                y = w[0][f"{b}.A.mix_step"][d]
                assert err == _c_msg(b, d, x, y, abs(x - y)), (b, back, delta, err)


@pytest.mark.parametrize("b", SPLIT)
def test_the_accumulated_change_must_be_the_sum_of_its_two_accumulated_parts_to_0_015625_points_for_each_block(b):
    sid = f"{b}.A.total_cum"
    for back in (0, 1, 50, 119):
        for delta, ok in ((TOL, True), (-TOL, True), (TOL + 2 ** -7, False), (-TOL - 2 ** -7, False)):
            w = _world()
            d = _set(w, sid, delta, back)
            err = _err(w)
            if ok:
                assert err is None, (b, back, delta, err)
            else:
                o, m, n = w[0][sid][d], w[0][f"{b}.A.rate_cum"][d], w[0][f"{b}.A.mix_cum"][d]
                assert err == _d_msg(b, d, o, m, n, abs(o - (m + n))), (b, back, delta, err)


def _ramp(w, b, steps):
    """Raise the rate of `b` in the newest `steps` months by 2**-7, 2 * 2**-7, ... : each month's own change is off by only 2**-7 (inside the tolerance), the whole window by `steps` times that."""
    for i in range(1, steps + 1):
        w[0][f"{b}.A.rate"][_back(LAST, steps - i)] += i * 2 ** -7


@pytest.mark.parametrize("b", SPLIT)
def test_the_whole_window_must_not_drift_between_the_rate_and_the_accumulated_change_by_more_than_0_015625_points(b):
    w = _world()
    _ramp(w, b, 2)                                                                                                            # a drift of exactly 2 to the power -6: allowed
    assert _err(w) is None
    w = _world()
    _ramp(w, b, 3)                                                                                                            # 3 times 2 to the power -7 is 0.0234375: refused, though no single month is off by more than 2 to the power -7
    r = w[0][f"{b}.A.rate"][LAST] - w[0][f"{b}.A.rate"][_back(LAST, 119)]
    o = w[0][f"{b}.A.total_cum"][LAST] - w[0][f"{b}.A.total_cum"][_back(LAST, 119)]
    assert _err(w) == _e_msg(b, r, o, 0.0234375) and abs(r - o) == 0.0234375
    w = _world()
    for i in range(120):                                                                                                      # and a slow drift over the whole window: 2 to the power -7 more each month
        w[0][f"{b}.A.rate"][_back(LAST, 119 - i)] += 2 ** -7 * i
    r = w[0][f"{b}.A.rate"][LAST] - w[0][f"{b}.A.rate"][_back(LAST, 119)]
    o = w[0][f"{b}.A.total_cum"][LAST] - w[0][f"{b}.A.total_cum"][_back(LAST, 119)]
    assert abs(r - o) == 119 * 2 ** -7 and _err(w) == _e_msg(b, r, o, 119 * 2 ** -7)                                         # 0.9296875: the first identity does not see it (each month is off by 2 to the power -7), this one does
    w = _world()
    w[0][f"{b}.A.rate"][_back(LAST, 119)] -= TOL                                                                              # the oldest month off by exactly the tolerance: allowed here, and not held to the month-by-month identity
    assert _err(w) is None


@pytest.mark.parametrize("total, parts, block", [("firms.A.rate", ("firms.F.rate", "firms.I.rate", "firms.J.rate"), "firms"), ("households.A.rate", ("house.A.rate", "consumer.A.rate"), "households"),
                                                 ("house.A.rate", ("house.F.rate", "house.I.rate", "house.J.rate"), "house"), ("consumer.A.rate", ("consumer.F.rate", "consumer.I.rate", "consumer.J.rate"), "consumer"),
                                                 ("firms_dep.A.rate", ("firms_dep.L.rate", "firms_dep.H.rate"), "firms_dep"), ("hh_dep.A.rate", ("hh_dep.L.rate", "hh_dep.H.rate"), "hh_dep")])
def test_a_total_must_lie_within_0_015625_points_of_the_range_of_its_parts_in_every_month(total, parts, block):
    for back in (0, 1, 60, 119):
        d = _back(LAST, back)
        for side in ("above", "below"):
            for gap, ok in ((TOL, True), (TOL + 2 ** -7, False)):
                w = _world()
                if block == "households":                                                                                   # its parts carry identities of their own, so the total is the one that is moved
                    lo, hi = sorted((w[0]["house.A.rate"][d], w[0]["consumer.A.rate"][d]))
                    w[0][total][d] = hi + gap if side == "above" else lo - gap
                else:
                    t = w[0][total][d]
                    for i, p in enumerate(parts):                                                                            # every part on the far side of the total, the nearest one by exactly `gap`
                        w[0][p][d] = (t - gap - 0.25 * i) if side == "above" else (t + gap + 0.25 * i)
                err = _err(w)
                if ok:
                    assert err is None, (total, back, side, err)
                else:
                    rest = [w[0][p][d] for p in parts]
                    t = w[0][total][d]
                    out = max(min(rest) - t, t - max(rest))
                    assert out == gap and err == _between_msg(block, d, t, out, min(rest), max(rest)), (total, back, side, err)


def test_a_total_may_sit_exactly_on_the_edge_of_its_parts_and_in_the_middle():
    w = _world()
    for b in ("house", "firms_dep"):
        d = _back(LAST, 5)
        t = w[0][f"{b}.A.rate"][d]
        w[0][f"{b}.{PARTS[b][-1]}.rate"][d] = t                                                                              # the real record has months where the total equals its highest or lowest part
    assert _err(w) is None


def test_the_between_check_for_households_uses_the_rates_of_house_purchase_and_consumption_not_their_parts():
    w = _world()
    d = _back(LAST, 2)
    w[0]["households.A.rate"][d] = w[0]["consumer.A.rate"][d] + 0.125
    err = _err(w)
    assert err is not None and err.startswith("loans to households:") and "outside its parts'" in err


def test_the_checks_are_applied_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    def with_faults(*faults):
        w = _world()
        for f in faults:
            f(w)
        return _err(w)
    units = lambda w: w[1].__setitem__("hh_dep.L.rate", ("PCPA", "9"))
    ends = lambda w: w[0]["firms.A.rate"].pop(LAST)
    missing = lambda w: w[0]["house.F.rate"].pop(_back(LAST, 40))
    rng = lambda w: w[0]["consumer.A.rate_step"].__setitem__(_back(LAST, 30), 3.0)
    move = lambda w: w[0]["firms.J.rate"].__setitem__(_back(LAST, 20), w[0]["firms.J.rate"][_back(LAST, 20)] + 1.75)
    ident_a = lambda w: w[0]["firms.A.rate_step"].__setitem__(_back(LAST, 10), w[0]["firms.A.rate_step"][_back(LAST, 10)] + 0.25)
    ident_b = lambda w: w[0]["house.A.rate_cum"].__setitem__(_back(LAST, 11), w[0]["house.A.rate_cum"][_back(LAST, 11)] + 0.25)
    ident_c = lambda w: w[0]["consumer.A.mix_cum"].__setitem__(_back(LAST, 12), w[0]["consumer.A.mix_cum"][_back(LAST, 12)] + 0.25)
    ident_d = lambda w: w[0]["firms_dep.A.total_cum"].__setitem__(_back(LAST, 13), w[0]["firms_dep.A.total_cum"][_back(LAST, 13)] + 0.25)
    between = lambda w: w[0]["hh_dep.L.rate"].__setitem__(_back(LAST, 14), w[0]["hh_dep.A.rate"][_back(LAST, 14)] + 0.5)
    chain = [("units", units), ("ends", ends), ("missing", missing), ("range", rng), ("move", move), ("a", ident_a), ("b", ident_b), ("c", ident_c), ("d", ident_d), ("between", between)]
    expect = {"units": "other units", "ends": "end in different months", "missing": "is missing for", "range": "outside -2 to 2 points", "move": "moved by", "a": "components add up", "b": "accumulated rate part", "c": "accumulated weight part",
              "d": "is not", "between": "outside its parts"}
    for i, (name, fault) in enumerate(chain):
        err = with_faults(*[f for _, f in chain[i:]])
        assert err is not None and expect[name] in err, (name, err)
        if i + 1 < len(chain):
            later = with_faults(*[f for _, f in chain[i + 1:]])
            assert later is not None and expect[chain[i + 1][0]] in later, (chain[i + 1][0], later)


def test_the_largest_identity_gap_is_reported_with_its_month_and_block_and_keeps_the_earlier_of_two_equal_ones():
    w = _world()
    d1, d2 = _back(LAST, 30), _back(LAST, 10)
    w[0]["house.A.rate_step"][d1] += 2 ** -7                                                                                  # the first identity and the second both see 2 to the power -7 here
    w[0]["firms.A.rate_step"][d2] += 2 ** -7
    r = _run(w)["detail"]
    assert (r["largest_identity_gap_points"], r["largest_identity_gap_month"], r["largest_identity_gap_series"]) == (0.0078, _lab(d2), "loans to firms")      # firms come before house purchase in the card's order, whatever the month
    w = _world()
    w[0]["consumer.A.rate_step"][d1] += 2 ** -7
    w[0]["consumer.A.rate_step"][d2] += 2 ** -6
    r = _run(w)["detail"]
    assert (r["largest_identity_gap_points"], r["largest_identity_gap_month"], r["largest_identity_gap_series"]) == (0.0156, _lab(d2), "consumer and other loans")
    w = _world()
    w[0]["hh_dep.A.mix_cum"][_back(LAST, 50)] += 0.0078125                                                                    # only the accumulated identities see this one (it is a gap of 2 to the power -7 in two of them)
    r = _run(w)["detail"]
    assert r["largest_identity_gap_points"] == 0.0078 and r["largest_identity_gap_series"] == "households' deposits" and r["largest_identity_gap_month"] == _lab(_back(LAST, 50))
    w = _world()
    w[0]["firms.A.rate_step"][d1] += 2 ** -7
    w[0]["firms.A.rate_step"][d2] -= 2 ** -6
    assert _run(w)["detail"]["largest_identity_gap_points"] == 0.0156                                                         # a negative gap counts by its size
    assert _run(_world())["detail"]["identities_checked"] == 2390 and _run(_world())["detail"]["between_checked"] == 720 and _run(_world())["detail"]["months_checked"] == 120


def _detail(w):
    d = _run(w)["detail"]
    return d["largest_identity_gap_points"], d["largest_identity_gap_month"], d["largest_identity_gap_series"]


def test_each_identity_reports_the_largest_gap_it_finds_when_it_is_the_only_one_that_sees_it():
    d = _back(LAST, 40)
    w = _world()
    w[0]["firms.A.rate"][d] += 2 ** -7                                                                                        # the first identity only: the rate itself is off, none of its parts
    assert _detail(w) == (0.0078, _lab(d), "loans to firms")
    w = _world()
    w[0]["house.A.rate_cum"][d] += 2 ** -7
    w[0]["house.A.total_cum"][d] += 2 ** -7                                                                                   # the second only: the total is moved with it, so the sum of the two totals still holds
    assert _detail(w) == (0.0078, _lab(d), "house purchase loans")
    w = _world()
    w[0]["consumer.A.mix_cum"][d] += 2 ** -7
    w[0]["consumer.A.total_cum"][d] += 2 ** -7                                                                                # the third only
    assert _detail(w) == (0.0078, _lab(d), "consumer and other loans")
    w = _world()
    w[0]["firms_dep.A.total_cum"][d] += 2 ** -7                                                                               # the fourth only (an interior month, so the whole-window check does not see it)
    assert _detail(w) == (0.0078, _lab(d), "firms' deposits")
    w = _world()
    _ramp(w, "hh_dep", 2)                                                                                                     # the fifth only: every pair is off by 2 to the power -7 (the first identity sees that), the whole window by 2 to the power -6
    assert _detail(w) == (0.0156, _lab(LAST), "households' deposits")


def test_a_gap_that_rounds_to_zero_at_four_decimals_is_reported_as_none_not_as_a_month():
    w = _world()
    w[0]["firms.A.rate_step"][_back(LAST, 40)] += 2 ** -20                                                                    # 0.00000095: a gap, but 0.0 when shown to four decimals
    assert _detail(w) == (0.0, None, None)


def test_the_real_record_passes_every_check_and_is_pinned():
    assert _err(_real()) is None
    v = _real()[0]
    extremes = {}
    for sid in RATES:
        months = sorted(v[sid])
        ch = [(round(v[sid][y] - v[sid][x], 2), _lab(y)) for x, y in zip(months[-120:], months[-119:])]
        extremes[sid] = (min(ch)[0], max(ch)[0])
    assert max(abs(x) for lo, hi in extremes.values() for x in (lo, hi)) == 0.38                                              # the largest one-month move of any of the 19 rates in the window, far inside 1.5
    ranges = {kind: (min(min(v[sid].values()) for sid in v if sid.endswith("." + kind)), max(max(v[sid].values()) for sid in v if sid.endswith("." + kind))) for kind in KINDS}
    assert ranges == {"rate": (-0.07, 7.88), "rate_step": (-0.15, 0.31), "mix_step": (-0.02, 0.02), "rate_cum": (-3.91, 0.3), "mix_cum": (-0.21, 0.44), "total_cum": (-3.99, 0.42)}       # all 125 months of the saved responses (2016-05 to 2026-09); the whole record since 2003 also holds -0.50 (2009) and +1.62 for a running total


def test_the_limits_and_tolerances_are_the_ones_set_from_the_real_record():
    assert (S.RATE_LIMITS, S.STEP_LIMITS, S.CUM_LIMITS) == (RATE_LIMITS, STEP_LIMITS, CUM_LIMITS) and S.MONTH_MOVE == 1.5 and S.TOLERANCE == 0.015625
    assert (S.DEPTH, S.LAST_N, S.RATE_WINDOW, S.MIN_WINDOW, S.OVERDUE_AFTER_DAYS) == (120, 125, 120, 60, 75)
    assert (S.TTL, S.FAIL_TTL, S.TIMEOUT) == (21600.0, 120.0, 90.0)
    assert S.BASE == "https://data-api.ecb.europa.eu/service/data/MIR/" and S.NAMES == NAMES and S.SHORT == SHORT and S.PART_WORDS == PART_WORDS
    assert (S.RATE_UNIT, S.POINT_UNIT) == (RATE_U, POINT_U) and S.PARTS == PARTS and S.SPLIT == SPLIT and S.LOANS == LOANS and S.DEPOSITS == DEPOSITS and S.RATES == RATES
    assert S.BLOCKS == {b: (item, sector, LABEL[b]) for b, (item, sector) in (("firms", ("A20", "2240")), ("households", ("A20", "2250")), ("house", ("A22", "2250")), ("consumer", ("A25", "2250")), ("firms_dep", ("L22", "2240")), ("hh_dep", ("L22", "2250")))}
    assert S.KINDS == {"rate": "R", "rate_step": "I", "mix_step": "J", "rate_cum": "M", "mix_cum": "N", "total_cum": "O"}
    item = {"firms": ("A20", "2240"), "households": ("A20", "2250"), "house": ("A22", "2250"), "consumer": ("A25", "2250"), "firms_dep": ("L22", "2240"), "hh_dep": ("L22", "2250")}
    typ = {"rate": "R", "rate_step": "I", "mix_step": "J", "rate_cum": "M", "mix_cum": "N", "total_cum": "O"}
    keys = {}
    for b in BLOCKS:
        for k in (KINDS if b in SPLIT else ("rate",)):
            keys[f"{b}.A.{k}"] = (f"M.U2.B.{item[b][0]}.A.{typ[k]}.A.{item[b][1]}.EUR.O", RATE_U if k == "rate" else POINT_U)
        for p in PARTS[b]:
            keys[f"{b}.{p}.rate"] = (f"M.U2.B.{item[b][0]}.{p}.R.A.{item[b][1]}.EUR.O", RATE_U)
    assert S.SERIES == keys and len(keys) == 44 and tuple(S.SERIES) == IDS
    assert S.PAGE == "https://data-api.ecb.europa.eu/service/data/MIR/M.U2.B.A20.A.R.A.2240.EUR.O"
    assert S.SOURCE == "European Central Bank, ECB Data Portal: interest rates on the loans and deposits euro-area banks already have on their books, the outstanding amounts (MFI interest rate statistics, official, free public data)"
    assert S.BETWEEN == (("firms.A.rate", ("firms.F.rate", "firms.I.rate", "firms.J.rate")), ("households.A.rate", ("house.A.rate", "consumer.A.rate")), ("house.A.rate", ("house.F.rate", "house.I.rate", "house.J.rate")),
                         ("consumer.A.rate", ("consumer.F.rate", "consumer.I.rate", "consumer.J.rate")), ("firms_dep.A.rate", ("firms_dep.L.rate", "firms_dep.H.rate")), ("hh_dep.A.rate", ("hh_dep.L.rate", "hh_dep.H.rate")))
    head = lambda b: tuple(f"{b}.A.{k}" for k in KINDS)
    assert S.REQUESTS == (("M.U2.B.A20+A22+A25.A.R+I+J+M+N+O.A.2240+2250.EUR.O", head("firms") + ("households.A.rate",) + head("house") + head("consumer")),
                          ("M.U2.B.L22.A.R+I+J+M+N+O.A.2240+2250.EUR.O", head("firms_dep") + head("hh_dep")),
                          ("M.U2.B.A20+A22+A25.F+I+J.R.A.2240+2250.EUR.O", tuple(f"{b}.{p}.rate" for b in ("firms", "house", "consumer") for p in "FIJ")),
                          ("M.U2.B.L22.L+H.R.A.2240+2250.EUR.O", tuple(f"{b}.{p}.rate" for b in ("firms_dep", "hh_dep") for p in "LH")))


def test_the_four_requests_return_exactly_the_44_series_of_the_card_and_each_series_once():
    ids = [i for key, group in S.REQUESTS for i in group]
    assert len(ids) == 44 and sorted(ids) == sorted(IDS) and len(S.REQUESTS) == 4 and len(set(ids)) == 44
    assert all(sid in S.SERIES for sid in ids)


HEAD = "KEY,FREQ,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT,UNIT_MULT\n"
OK = "MIR.M.U2.B.A20.A.R.A.2240.EUR.O,M"


def test_the_real_layout_of_a_response_is_read():
    v, units, status = S.parse(F["raw_head"], ("firms.A.rate_step",))
    assert v == {"firms.A.rate_step": {date(2016, 5, 1): -0.02, date(2016, 6, 1): -0.04, date(2016, 7, 1): -0.03}} and units == {"firms.A.rate_step": POINT_U} and status == {"firms.A.rate_step": "A"}        # the header and the first three rows of the first response
    assert F["raw_head"].startswith("KEY,FREQ,REF_AREA,BS_REP_SECTOR,BS_ITEM,MATURITY_NOT_IRATE,DATA_TYPE_MIR,AMOUNT_CAT,BS_COUNT_SECTOR,CURRENCY_TRANS,IR_BUS_COV,TIME_PERIOD,OBS_VALUE,OBS_STATUS,")
    assert ",UNIT,UNIT_MULT" in F["raw_head"].split("\n")[0]


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_month_are_an_error():
    text = HEAD + f"{OK},2026-08,0.5,A,PCPA,0\n{OK},26-09,1,A,PCPA,0\n{OK},2026-9,1,A,PCPA,0\n{OK},2026-07,,M,PCPA,0\n{OK},2026-06,n/a,A,PCPA,0\n{OK},2026,1,A,PCPA,0\n{OK},2026-13,1,A,PCPA,0\n{OK},2026-00,1,A,PCPA,0\n"
    text += f"{OK},2026-Q3,1,A,PCPA,0\n{OK},2026-05-01,1,A,PCPA,0\n{OK}, 2026-04,1,A,PCPA,0\n{OK},2026-03x,1,A,PCPA,0\n{OK},2026-02,nan,A,PCPA,0\n{OK},2026-01,inf,A,PCPA,0\n"
    text += f"{OK},2026-03\n"                                                                                                     # a row cut short: no value at all, left out
    text += "MIR.M.U2.B.A20.A.R.A.2240.EUR.N,M,2026-08,0.9,A,PCPA,0\nMIR.Q.U2.B.A20.A.R.A.2240.EUR.O,Q,2026-08,0.8,A,PCPA,0\nMIR.M.U2.B.A20.A.R.A.2250.EUR.O,M,2026-08,0.7,A,PCPA,0\n"
    v, units, status = S.parse(text, ("firms.A.rate",))
    assert v == {"firms.A.rate": {date(2026, 8, 1): 0.5}} and units == {"firms.A.rate": RATE_U} and status == {"firms.A.rate": "A"}       # a month with no value, a year, bad months, nan, inf, new business, another frequency and another sector are all left out
    padded = HEAD + f"{OK},2026-08,0.5, P , PCPA , 0 \n"
    assert S.parse(padded, ("firms.A.rate",))[1] == {"firms.A.rate": RATE_U} and S.parse(padded, ("firms.A.rate",))[2] == {"firms.A.rate": "P"}          # spaces around a unit or a status are not a different one
    two = HEAD + f"{OK},2026-07,0.1,A,PCPA,0\n{OK},2026-09,0.3,P,PCPA,0\n{OK},2026-08,0.2,A,PCPA,0\n"
    assert S.parse(two, ("firms.A.rate",))[2] == {"firms.A.rate": "P"}                                                           # the status is the newest month's, whatever the order of the rows
    two = HEAD + f"{OK},2026-07,0.3,P,PCPA,0\n{OK},2026-08,0.1,A,PCPA,0\n"
    assert S.parse(two, ("firms.A.rate",))[2] == {"firms.A.rate": "A"}
    with pytest.raises(ValueError, match=r"firms.A.rate has two values for 2026-08"):
        S.parse(text + f"{OK},2026-08,0.1,A,PCPA,0\n", ("firms.A.rate",))
    with pytest.raises(ValueError, match=r"no values for house.A.rate"):
        S.parse(text, ("firms.A.rate", "house.A.rate"))
    with pytest.raises(ValueError, match=r"the source returned no values for house.A.rate, consumer.A.rate$"):
        S.parse(text, ("house.A.rate", "consumer.A.rate"))


def _text(ids, units=None):
    rows = []
    for sid in ids:
        d = F["series"][sid]
        unit = units.get(sid, d["unit"]) if units else d["unit"]
        last = len(d["months"]) - 1
        rows += [f"MIR.{S.SERIES[sid][0]},M,{m},{x!r},{d['status'][0] if i == last else 'A'},{unit[0]},{unit[1]}" for i, (m, x) in enumerate(zip(d["months"], d["values"]))]
    return HEAD + "\n".join(rows) + "\n"


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ids_of(path):
    for key, ids in S.REQUESTS:
        if path == "/service/data/MIR/" + key:
            return ids
    raise AssertionError(path)


def _handler(req, replace=None, units=None):
    ids = _ids_of(req.url.path)
    text = _text(ids, units if units and any(i in units for i in ids) else None)
    return httpx.Response(200, text=text.replace(*replace) if replace else text)


def test_overview_fetches_four_requests_and_caches():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = S.EuroStockRates(client=_transport(handler))
    r = asyncio.run(svc.overview(NOW))
    assert r["available"] and r["loans"][0]["rate_pct"] == 3.58 and len(seen) == 4 and r["source"].startswith("European Central Bank")
    assert (r["age_days"], r["freshness"], r["provisional"]) == (55, "CURRENT", True)
    later = asyncio.run(S.EuroStockRates(client=_transport(_handler)).overview(datetime(2026, 12, 31, 12, tzinfo=timezone.utc)))
    assert (later["age_days"], later["as_of"], later["freshness"]) == (92, "2026-12-31T12:00:00+00:00", "OVERDUE")              # the age is counted to the day given, not to the machine's
    base = "/service/data/MIR/"
    assert {req.url.path: req.url.params["lastNObservations"] for req in seen} == {base + key: "125" for key, ids in S.REQUESTS}
    assert all(req.url.params["format"] == "csvdata" for req in seen) and all(req.headers["user-agent"] == "ATLAS research terminal" for req in seen)
    assert all(req.headers["accept"] == "text/csv" for req in seen)
    assert all("%2B" not in str(req.url) for req in seen) and sum("+" in str(req.url) for req in seen) == 4                      # the + that joins the values of one dimension must reach the ECB as it is
    asyncio.run(svc.overview(NOW))
    assert len(seen) == 4


def test_the_client_the_provider_makes_waits_90_seconds_and_is_closed_afterwards(monkeypatch):
    real, made = httpx.AsyncClient, []

    def factory(**kw):
        made.append(kw)
        c = real(transport=httpx.MockTransport(_handler))
        made.append(c)
        return c

    given = real(transport=httpx.MockTransport(_handler))
    monkeypatch.setattr(S.httpx, "AsyncClient", factory)
    r = asyncio.run(S.EuroStockRates().overview(NOW))
    assert r["available"] is True and made[0] == {"timeout": 90.0} and made[1].is_closed is True
    asyncio.run(S.EuroStockRates(client=given).overview(NOW))
    assert given.is_closed is False and len(made) == 2                                                                           # a client that was given stays open, and none was made


def test_a_final_newest_month_for_every_rate_reaches_the_card():
    rows = []
    for sid in RATES:
        key = "MIR." + S.SERIES[sid][0]
        m, x = F["series"][sid]["months"][-1], F["series"][sid]["values"][-1]
        rows.append((f"{key},M,{m},{x!r},P,", f"{key},M,{m},{x!r},A,"))
    texts = "".join(_text(ids) for key, ids in S.REQUESTS)
    changed = [(old, new) for old, new in rows if old in texts]
    assert len(changed) == 19 and all(new not in texts for old, new in changed)                                                 # all nineteen rates are provisional in the real response

    def handler(req):
        t = _handler(req).text
        for old, new in changed:
            t = t.replace(old, new)
        return httpx.Response(200, text=t)
    r = asyncio.run(S.EuroStockRates(client=_transport(handler)).overview(NOW))
    assert r["available"] is True and r["provisional"] is False


@pytest.mark.parametrize("sid", ("firms.A.rate", "hh_dep.A.rate", "consumer.I.rate", "hh_dep.L.rate"))                                 # one rate from each of the four responses
def test_one_provisional_rate_in_any_of_the_four_responses_makes_the_card_say_so(sid):
    flips = []
    for other in RATES:
        if other != sid:
            key = "MIR." + S.SERIES[other][0]
            m, x = F["series"][other]["months"][-1], F["series"][other]["values"][-1]
            flips.append((f"{key},M,{m},{x!r},P,", f"{key},M,{m},{x!r},A,"))

    def handler(req):
        t = _handler(req).text
        for old, new in flips:
            t = t.replace(old, new)
        return httpx.Response(200, text=t)
    r = asyncio.run(S.EuroStockRates(client=_transport(handler)).overview(NOW))
    assert r["available"] is True and r["provisional"] is True


def test_an_unexpected_missing_key_reads_as_unavailable_not_as_a_crash(monkeypatch):
    def boom(*args):
        raise KeyError("firms")

    monkeypatch.setattr(S, "summarize", boom)
    r = asyncio.run(S.EuroStockRates(client=_transport(_handler)).overview(NOW))
    assert r["available"] is False and r["reason"].startswith("The euro-area rates on existing loans and deposits could not be read right now (") and "loans" not in r


def test_a_cached_answer_carries_the_time_of_the_call_that_got_it_from_the_cache():
    seen = []

    def handler(req):
        seen.append(req)
        return _handler(req)

    svc = S.EuroStockRates(client=_transport(handler))
    first = asyncio.run(svc.overview(NOW))
    later = NOW + timedelta(minutes=5)
    second = asyncio.run(svc.overview(later))
    assert len(seen) == 4 and first["as_of"] == NOW.isoformat() and second["as_of"] == later.isoformat() and second["loans"] == first["loans"]


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = types.SimpleNamespace(t=1000.0, monotonic=lambda: clock.t)
    monkeypatch.setattr(S, "time", clock)
    calls = {"n": 0, "ok": True}

    def handler(req):
        calls["n"] += 1
        return _handler(req) if calls["ok"] else httpx.Response(503)
    svc = S.EuroStockRates(client=_transport(handler))
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == 4
    clock.t += 6 * 3600 - 1
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == 4                                                                                                  # one second short of six hours: kept
    clock.t += 1
    calls["ok"] = False
    r = asyncio.run(svc.overview(NOW))
    assert calls["n"] > 4 and r["available"] is False                                                                       # six hours: asked again, and it failed
    n = calls["n"]
    clock.t += 119
    asyncio.run(svc.overview(NOW))
    assert calls["n"] == n                                                                                                  # the failure is kept for two minutes
    clock.t += 1
    calls["ok"] = True
    r = asyncio.run(svc.overview(NOW))
    assert calls["n"] > n and r["available"] is True                                                                        # and then asked again


def test_failure_says_so_and_shows_no_numbers():
    def handler(req):
        return httpx.Response(503)
    r = asyncio.run(S.EuroStockRates(client=_transport(handler)).overview(NOW))
    assert r["available"] is False and r["reason"] == "The euro-area rates on existing loans and deposits could not be read right now (the server had an error, HTTP 503)"
    assert "loans" not in r and "deposits" not in r and r["demo"] is False and r["as_of"] == NOW.isoformat()


def test_a_response_in_other_units_is_refused_and_shows_nothing():
    def handler(req):
        return _handler(req, units={"firms.A.rate": ("PCPA", "2")})
    r = asyncio.run(S.EuroStockRates(client=_transport(handler)).overview(NOW))
    assert r["available"] is False and r["reason"].startswith("The euro-area rates on existing loans and deposits could not be read right now (the data failed a check: the ECB reports the rate on loans to firms in other units") and "loans" not in r


@pytest.mark.parametrize("code, words", [(400, "the server answered HTTP 400"), (403, "the server refused the request, HTTP 403"), (404, "the data was not found there, HTTP 404"), (429, "the server is limiting requests, HTTP 429"), (500, "the server had an error, HTTP 500")])
def test_any_answer_but_200_is_a_failure_that_names_its_code(code, words):
    r = asyncio.run(S.EuroStockRates(client=_transport(lambda req: httpx.Response(code))).overview(NOW))
    assert r["available"] is False and r["reason"].endswith(f"({words})")


def test_a_dropped_connection_reads_plainly():
    def handler(req):
        raise httpx.ConnectError("")
    r = asyncio.run(S.EuroStockRates(client=_transport(handler)).overview(NOW))
    assert r["available"] is False and r["reason"].endswith("(the connection could not be made)") and fail_reason(httpx.ConnectError("")) == "the connection could not be made"


def test_a_failed_check_names_the_series_and_the_figure_first_so_the_message_is_not_clipped():
    w = _world()
    w[0]["consumer.A.rate_cum"][_back(LAST, 3)] = -10.5
    msg = _err(w)
    assert len(msg) <= 110 and dates_in_words(msg) == fail_reason(ValueError(msg))[len("the data failed a check: "):]                          # fail_reason keeps 110 characters of a check's message: none of ours is longer
    longest = max(len(NAMES[sid]) for sid in NAMES)
    assert longest + len(" moved by +1.60 points in 2026-09, more than 1.5") <= 110 and longest + len(" is -12.34 in 2026-09, outside -10 to 10 points") <= 110
    assert max(len(_a_msg(b, LAST, 0.05, 0.03, 0.031)) for b in SPLIT) <= 110 and max(len(_d_msg(b, LAST, 0.06, 0.09, -0.03, 0.031)) for b in SPLIT) <= 110
    assert max(len(_b_msg(b, LAST, 0.06, 0.09, 0.031)) for b in SPLIT) <= 110 and max(len(_e_msg(b, 3.72, 3.69, 0.031)) for b in SPLIT) <= 110
    assert max(len(_between_msg(b, LAST, 12.5, 0.031, 12.0, 12.4)) for b in BLOCKS) <= 110


def test_demo_mode_invents_nothing():
    d = asyncio.run(S.EuroStockRates(demo=True).overview(NOW))
    assert d["available"] is False and d["demo"] is True and d["reason"] == "Demo mode: the real euro-area rates on existing loans and deposits are not shown because made-up values would look real." and "loans" not in d


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-stock-rates")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True
