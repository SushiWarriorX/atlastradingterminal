"""Euro-area employment and productivity (ECB Data Portal, MNA dataflow, the euro area of 21 countries `I10`, seasonally and calendar adjusted): parsed from real responses (fetched 2026-11-18 14:33 UTC: the provider's four requests with 45 quarters each; the whole record, 126 quarters from 1995-Q1 for the 26 employment series and 127 for total employment and real GDP, was read before any limit was set). Every limit, tolerance and table is written out below as a literal, so that a changed limit in the module fails a test instead of moving the test with it, and each check is broken on its own in a world where every other check holds by construction."""
import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import euroemployment as S
from atlas_api.app import create_app
from atlas_api.failreason import fail_reason

F = json.loads((Path(__file__).parent / "fixtures" / "ecb_euro_employment.json").read_text())
TODAY = date(2026, 11, 18)
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)
JQ, BQ = "2026-Q3", "2026-Q2"                                          # the newest quarter of total employment (and of real GDP and of productivity per person) and of the breakdown (and of productivity per hour)
ACTS = ("A", "BTE", "F", "GTI", "J", "K", "L", "M_N", "OTQ", "RTU")
SECTOR = {"A": "agriculture and fishing", "BTE": "industry", "F": "construction", "GTI": "trade, transport and hospitality", "J": "information and communication", "K": "finance and insurance",
          "L": "real estate", "M_N": "professional and support services", "OTQ": "public services, education and health", "RTU": "arts, recreation and other services"}
PEOPLE = ["p_total"] + [f"p_{a}" for a in ACTS] + ["p_employees", "p_self"]
HOURS = ["h_total"] + [f"h_{a}" for a in ACTS] + ["h_employees", "h_self"]
PROD = ["prod_p_q", "prod_p_y", "prod_h_q", "prod_h_y"]
IDS = tuple(PEOPLE + HOURS + ["gdp"] + PROD)
BREAKDOWN = tuple(PEOPLE[1:] + HOURS)                                  # everything that comes with the breakdown, one quarter behind total employment
NAMES = {"p_total": "total employment", "h_total": "total hours worked", "p_employees": "employees", "p_self": "the self-employed", "h_employees": "hours worked by employees",
         "h_self": "hours worked by the self-employed", "gdp": "real GDP", "prod_p_q": "productivity per person, quarterly growth", "prod_p_y": "productivity per person, annual growth",
         "prod_h_q": "productivity per hour, quarterly growth", "prod_h_y": "productivity per hour, annual growth"}
NAMES.update({f"p_{a}": f"employment in {SECTOR[a]}" for a in ACTS})
NAMES.update({f"h_{a}": f"hours worked in {SECTOR[a]}" for a in ACTS})
PS, HW, EUR6, EUR0 = ("PS", "3"), ("HW", "3"), ("EUR", "6"), ("EUR", "0")
UNITS = {**{s: PS for s in PEOPLE}, **{s: HW for s in HOURS}, "gdp": EUR6, **{s: EUR0 for s in PROD}}
# the limits set from the whole real record, spelled out here
PERSONS_LIMITS, HOURS_LIMITS = (100000.0, 250000.0), (40000000.0, 100000000.0)
SECTOR_SHARE, SELF_SHARE, HOURS_PER_PERSON, JOBS_MOVE = (0.2, 40.0), (5.0, 45.0), (250.0, 500.0), (-10.0, 10.0)
PROD_LIMITS = {"prod_p_q": (-25.0, 25.0), "prod_p_y": (-30.0, 30.0), "prod_h_q": (-10.0, 10.0), "prod_h_y": (-15.0, 15.0)}
BASE_PEOPLE = dict(zip(ACTS, (5000.0, 24000.0, 11000.0, 42000.0, 5800.0, 4000.0, 1900.0, 24000.0, 44000.0, 11000.0)))      # thousands of persons, 172,700 in all


def _i(q):
    return int(q[:4]) * 4 + int(q[6]) - 1


def _l(i):
    return f"{i // 4}-Q{i % 4 + 1}"


def _persons(i, bi, trend=7.0, base=None):
    """The ten sectors' persons in quarter index i and their total, added up left to right as the module adds them."""
    parts = [(base or BASE_PEOPLE)[a] + trend * (i - bi) for a in ACTS]
    total = 0.0
    for x in parts:
        total += x
    return parts, total


def _world(jobs_end=JQ, break_end=BQ, extra=0, status=None, growth=1.0025, trend=7.0, hpp=388.0, base=None, bump=1.0005, hpp_trend=0.0):
    """The 31 series for the 45 quarters (plus `extra` older ones) ending on each group's newest quarter, where every check holds by construction: ten sectors that add up to the total (persons and hours), employees and self-employed that add up
    to the total, 388 hours per person a quarter, employees three quarters of the total, a real GDP level growing by the factor `growth` a quarter, and the ECB's productivity growth worked out from real GDP and employment as the ECB works it out. Sector persons are whole numbers of thousands, 388 hours a person, so every sum is exact in binary."""
    n = 45 + extra
    ji, bi = _i(jobs_end), _i(break_end)
    v = {s: {} for s in IDS}

    def total_p(i):                                                    # total persons: the sum of the sectors up to the breakdown's quarter, a little more in the quarters after it
        return _persons(min(i, bi), bi, trend, base)[1] * (bump ** max(0, i - bi))

    def hours_per_person(i):
        return hpp + hpp_trend * (i - bi)

    def total_h(i):
        parts = [x * hours_per_person(i) for x in _persons(i, bi, trend, base)[0]]
        t = 0.0
        for x in parts:
            t += x
        return t

    def gdp(i):
        return 3000000.0 * growth ** (i - (ji - n - 8))

    def prod(emp, i, back):
        return 100 * ((gdp(i) / gdp(i - back)) / (emp(i) / emp(i - back)) - 1)

    for i in range(bi - n + 1, bi + 1):
        q = _l(i)
        parts, tp = _persons(i, bi, trend, base)
        for a, x in zip(ACTS, parts):
            v[f"p_{a}"][q], v[f"h_{a}"][q] = x, x * hours_per_person(i)
        th = total_h(i)
        v["h_total"][q] = th
        v["p_employees"][q] = tp * 0.75                                # three quarters employees: whole numbers stay whole, so the parts add up to the total exactly
        v["p_self"][q] = tp - tp * 0.75
        v["h_employees"][q] = th * 0.75
        v["h_self"][q] = th - th * 0.75
    for i in range(ji - n + 1, ji + 1):
        q = _l(i)
        v["p_total"][q] = total_p(i)
        v["gdp"][q] = gdp(i)
        v["prod_p_q"][q], v["prod_p_y"][q] = prod(total_p, i, 1), prod(total_p, i, 4)
    for i in range(bi - n + 1, bi + 1):
        q = _l(i)
        v["prod_h_q"][q], v["prod_h_y"][q] = prod(total_h, i, 1), prod(total_h, i, 4)
    return v, dict(UNITS), {"p_total": "A"} if status is None else status


def _exact_world(jump="p"):
    """A world with binary-exact growth: employment and hours flat, real GDP flat except for one rise by the factor 1.0625 from the newest quarter of employment (jump "p") or of the breakdown (jump "h") on, so that the ECB's productivity
    growth there is exactly 6.25 (and exactly 0 before it) and a gap of exactly a tolerance can be made."""
    v, units, status = _world(trend=0.0)
    v["p_total"][JQ] = v["p_total"][BQ]                                # flat in the newest quarter too (the world's total grows by 0.05% in the quarter after the breakdown)
    end = JQ if jump == "p" else BQ
    for q in v["gdp"]:
        v["gdp"][q] = 3000000.0 * 1.0625 if _i(q) >= _i(end) else 3000000.0
    for s, emp, back in (("prod_p_q", "p_total", 1), ("prod_p_y", "p_total", 4), ("prod_h_q", "h_total", 1), ("prod_h_y", "h_total", 4)):
        for q in v[s]:
            b = _l(_i(q) - back)
            v[s][q] = 100 * ((v["gdp"][q] / v["gdp"][b]) / (v[emp][q] / v[emp][b]) - 1) if b in v["gdp"] and b in v[emp] else 0.0
    return v, units, status


def _real():
    v = {sid: dict(zip(d["quarters"], d["values"])) for sid, d in F["series"].items()}
    return v, {sid: tuple(d["unit"]) for sid, d in F["series"].items()}, {"p_total": F["series"]["p_total"]["status"][-1]}


def _run(world, today=TODAY):
    return S.summarize(*world, today)


def _err(world, today=TODAY):
    """The refusal's text, or None when the world passes every check."""
    try:
        _run(world, today)
    except ValueError as e:
        return str(e)
    return None


def test_the_real_latest_jobs_recent_quarters_breakdown_sectors_and_productivity_by_hand():
    r = _run(_real())
    assert r["available"] is True and r["quarter"] == "2026-Q3" and r["age_days"] == 49 and r["freshness"] == "CURRENT" and r["provisional"] is False         # 2026-09-30 to 2026-11-18 is 49 days
    assert r["jobs"] == {"quarter": "2026-Q3", "persons": 176.5, "quarter_on_quarter": 0.01, "year_on_year": 0.35, "previous_quarter": "2026-Q2", "year_earlier": "2025-Q3"}
    assert [(x["quarter"], x["persons"], x["quarter_on_quarter"], x["year_on_year"]) for x in r["recent"]] == [("2026-Q3", 176.5, 0.01, 0.35), ("2026-Q2", 176.5, 0.12, 0.51), ("2026-Q1", 176.3, 0.08, 0.51),
                                                                                                          ("2025-Q4", 176.2, 0.13, 0.65), ("2025-Q3", 175.9, 0.17, 0.63), ("2025-Q2", 175.6, 0.13, 0.76)]
    b = r["breakdown"]
    assert (b["quarter"], b["persons"], b["hours"], b["hours_per_person"], b["hours_change_year"]) == ("2026-Q2", 176.5, 68.7, 389.0, 0.6)
    assert b["employees"] == {"persons": 151.6, "share": 85.9, "hours_share": 82.1} and b["self_employed"] == {"persons": 24.9, "share": 14.1, "hours_share": 17.9}
    assert [(x["id"], x["persons"], x["share"], x["change_year_thousands"], x["change_year"]) for x in b["sectors"]] == [
        ("OTQ", 44.4, 25.1, 507, 1.16), ("GTI", 43.0, 24.4, 209, 0.49), ("M_N", 25.1, 14.2, 202, 0.81), ("BTE", 24.3, 13.8, -107, -0.44), ("RTU", 11.5, 6.5, 53, 0.46), ("F", 11.4, 6.4, 158, 1.41),
        ("J", 5.9, 3.3, -103, -1.73), ("A", 5.1, 2.9, -101, -1.95), ("K", 4.1, 2.3, 57, 1.41), ("L", 1.9, 1.1, 14, 0.75)]
    assert [x["name"] for x in b["sectors"]] == [SECTOR[a] for a in ("OTQ", "GTI", "M_N", "BTE", "RTU", "F", "J", "A", "K", "L")]
    assert r["productivity"] == {"per_person": {"quarter": "2026-Q3", "quarter_on_quarter": 0.41, "year_on_year": 0.95}, "per_hour": {"quarter": "2026-Q2", "quarter_on_quarter": 0.52, "year_on_year": 0.59}}
    assert r["detail"] == {"quarters_checked": 45, "persons_quarters_checked": 44, "largest_persons_gap": 8.15e-10, "largest_hours_gap": 1.04e-07, "largest_productivity_gap": 0.0}
    assert r["checks"] == {"units_ok": True, "quarters_in_a_row": True, "range_ok": True, "jobs_move_ok": True, "activities_add_up_ok": True, "status_adds_up_ok": True, "productivity_follows_gdp_and_jobs_ok": True}
    assert r["source"].startswith("European Central Bank") and r["url"] == "https://data-api.ecb.europa.eu/service/data/MNA/Q.Y.I10.W2.S1.S1._Z.EMP._Z._T._Z.PS._Z.N"
    assert "not a market signal or a forecast" in r["note"] and "about 45 days" in r["note"] and "about 65 days" in r["note"]


def test_the_real_record_by_plain_python_outside_the_module():
    s = {k: dict(zip(d["quarters"], d["values"])) for k, d in F["series"].items()}
    assert (len(F["series"]), sorted({len(d["quarters"]) for d in F["series"].values()})) == (31, [45])
    assert max(s["p_total"], key=_i) == "2026-Q3" and max(s["p_A"], key=_i) == "2026-Q2" and max(s["h_total"], key=_i) == "2026-Q2" and max(s["prod_p_y"], key=_i) == "2026-Q3" and max(s["prod_h_y"], key=_i) == "2026-Q2"
    assert (s["p_total"]["2026-Q3"], s["p_total"]["2026-Q2"], s["h_total"]["2026-Q2"]) == (176547.095680786, 176535.707829202, 68669157.438049)
    r = _run(_real())
    assert r["jobs"]["quarter_on_quarter"] == round(100 * (176547.095680786 / 176535.707829202 - 1), 2)                       # 0.00645%, shown as 0.01
    assert r["jobs"]["year_on_year"] == round(100 * (s["p_total"]["2026-Q3"] / s["p_total"]["2025-Q3"] - 1), 2)
    assert r["breakdown"]["hours_per_person"] == round(68669157.438049 / 176535.707829202, 1)                                  # 388.98 hours a person in the quarter
    ten = sum(s[f"p_{a}"]["2026-Q2"] for a in ACTS)
    assert abs(ten - s["p_total"]["2026-Q2"]) < 1e-8 and abs(s["p_employees"]["2026-Q2"] + s["p_self"]["2026-Q2"] - s["p_total"]["2026-Q2"]) < 1e-8      # Eurostat's own sums hold to rounding noise
    assert round(sum(x["share"] for x in r["breakdown"]["sectors"]), 0) == 100.0
    # productivity per person is real GDP over persons, as the ECB works it out: q/q 0.41 = (3373329.42 / 3359...) / (176547.10 / 176535.71) - 1
    g = s["gdp"]
    assert round(100 * ((g["2026-Q3"] / g["2026-Q2"]) / (s["p_total"]["2026-Q3"] / s["p_total"]["2026-Q2"]) - 1), 2) == r["productivity"]["per_person"]["quarter_on_quarter"] == 0.41


def test_the_newest_value_is_provisional_only_when_the_source_says_so():
    assert _run(_world(status={"p_total": "A"}))["provisional"] is False
    assert _run(_world(status={"p_total": "P"}))["provisional"] is True
    assert _run(_world(status={"p_total": "E"}))["provisional"] is True
    assert _run(_world(status={}))["provisional"] is False                                                                      # a status that is not there is not a provisional one
    assert _run(_world(status={"p_total": ""}))["provisional"] is False


def test_overdue_after_135_days_from_the_end_of_the_newest_quarter_of_employment():
    end = date(2026, 9, 30)
    assert _run(_world(), end + timedelta(days=135))["freshness"] == "CURRENT" and _run(_world(), end + timedelta(days=135))["age_days"] == 135
    assert _run(_world(), end + timedelta(days=136))["freshness"] == "OVERDUE" and _run(_world(), end + timedelta(days=136))["age_days"] == 136
    assert _run(_world(), end)["age_days"] == 0 and _run(_world(), end)["freshness"] == "CURRENT"
    w = _world(jobs_end="2026-Q2", break_end="2026-Q2")                                                                         # the age is that of the quarter that total employment ends on, not of the breakdown
    assert _run(w, date(2026, 11, 18))["age_days"] == 141 and _run(w, date(2026, 11, 18))["freshness"] == "OVERDUE" and _run(w)["quarter"] == "2026-Q2"


def test_each_quarter_ends_on_its_own_last_day():
    for q, d in (("2026-Q1", date(2026, 3, 31)), ("2026-Q2", date(2026, 6, 30)), ("2026-Q3", date(2026, 9, 30)), ("2025-Q4", date(2025, 12, 31))):
        assert S._end(q) == d
        assert _run(_world(jobs_end=q, break_end=q), d)["age_days"] == 0


def test_the_year_on_year_changes_of_the_sectors_compare_with_the_same_quarter_a_year_earlier():
    r = _run(_world())["breakdown"]["sectors"]                                                                                  # every sector gains 7 thousand persons a quarter, so 28 thousand over four quarters
    assert {x["id"]: x["change_year_thousands"] for x in r} == {a: 28 for a in ACTS}
    assert {x["id"]: x["change_year"] for x in r} == {a: round(100 * (BASE_PEOPLE[a] / (BASE_PEOPLE[a] - 28.0) - 1), 2) for a in ACTS}
    assert next(x for x in r if x["id"] == "OTQ")["change_year"] == 0.06 and next(x for x in r if x["id"] == "L")["change_year"] == 1.5
    assert r[0]["id"] == "OTQ" and r[0]["persons"] == 44.0 and r[0]["share"] == 25.5 and r[0]["name"] == SECTOR["OTQ"]


def test_sectors_are_listed_by_size_and_equal_sizes_by_code():
    ids = [x["id"] for x in _run(_world(trend=0.0, base={a: 12000.0 for a in ACTS}))["breakdown"]["sectors"]]
    assert ids == sorted(ACTS)                                                                                                  # all ten equal: alphabetical


def test_every_figure_is_shown_to_the_decimals_the_card_prints():
    r = _run(_real())
    assert isinstance(r["jobs"]["persons"], float) and r["jobs"]["persons"] == round(r["jobs"]["persons"], 1)
    for x in r["recent"]:
        assert x["persons"] == round(x["persons"], 1) and x["quarter_on_quarter"] == round(x["quarter_on_quarter"], 2) and x["year_on_year"] == round(x["year_on_year"], 2)
    for x in r["breakdown"]["sectors"]:
        assert x["persons"] == round(x["persons"], 1) and x["share"] == round(x["share"], 1) and isinstance(x["change_year_thousands"], int) and x["change_year"] == round(x["change_year"], 2)
    assert r["breakdown"]["hours"] == round(r["breakdown"]["hours"], 1) and r["breakdown"]["hours_per_person"] == round(r["breakdown"]["hours_per_person"], 1)


def test_the_number_formats_of_the_refusal_messages():
    assert S._fmt(176547.09568) == "176,547.1" and S._fmt(68669157.438) == "68,669,157.4" and S._fmt(99999.5) == "99,999.5" and S._fmt(300000.0) == "300,000.0"
    assert S._lim(100000.0) == "100,000" and S._lim(0.2) == "0.2" and S._lim(40.0) == "40" and S._lim(-10.0) == "-10" and S._lim(100000000.0) == "100,000,000"


def test_a_series_in_other_units_than_the_ones_assumed_is_refused():
    for sid in IDS:
        v, units, status = _world()
        for wrong in (("PS", "0"), ("HW", "0"), ("EUR", "3"), ("XX", UNITS[sid][1]), ("", ""), ("PS", "6")):
            if wrong == UNITS[sid]:
                continue
            units = dict(UNITS)
            units[sid] = wrong
            assert _err((v, units, status)) == f"the ECB reports {NAMES[sid]} in other units than the card assumes", (sid, wrong)


def test_every_name_in_a_refusal_is_short_enough_for_the_card_to_show_the_number():
    v, units, status = _world()
    longest = max(len(f"the ECB reports {n} in other units than the card assumes") for n in NAMES.values())
    assert longest <= 110 and S.NAMES == NAMES                                                                                  # fail_reason clips a message at 110 characters
    for sid in IDS:
        assert len(fail_reason(ValueError(f"the ECB reports {NAMES[sid]} in other units than the card assumes"))) <= 150


def test_every_refusal_fits_the_110_characters_the_card_shows():
    """`fail_reason` clips a refusal at 110 characters: build every kind of refusal with the longest names and large figures and want at most 110 characters of each, so that the figure that failed is on the screen."""
    errs = []

    def refuse(change):
        v, units, status = _world()
        change(v, units)
        err = _err((v, units, status))
        assert err is not None
        errs.append(err)

    for sid in IDS:
        refuse(lambda v, u, sid=sid: u.update({sid: ("XX", "9")}))                                                              # the units refusal, for every series
        refuse(lambda v, u, sid=sid: v[sid].pop(_l(max(_i(q) for q in v[sid]) - 3)))                                            # a missing quarter, for every series
    refuse(lambda v, u: v["p_total"].update({BQ: 300000.0}))
    refuse(lambda v, u: v["h_total"].update({BQ: 100000000.5}))
    for a in ACTS:
        refuse(lambda v, u, a=a: v[f"p_{a}"].update({_l(_i(BQ) - 2): 90000.0}))                                                  # the share of each activity
    refuse(lambda v, u: v["p_self"].update({BQ: 90000.0}))
    refuse(lambda v, u: v["h_self"].update({BQ: 90000000.0}))
    refuse(lambda v, u: v["h_total"].update({BQ: v["p_total"][BQ] * 600.0}))
    refuse(lambda v, u: v["p_total"].update({JQ: v["p_total"][BQ] * 1.5}))
    for sid in PROD:
        refuse(lambda v, u, sid=sid: v[sid].update({BQ: -99.99}))
    refuse(lambda v, u: v["p_OTQ"].update({BQ: v["p_OTQ"][BQ] + 44000.0}))                                                      # the sums, with large gaps
    refuse(lambda v, u: v["h_OTQ"].update({BQ: v["h_OTQ"][BQ] + 98765432.1}))
    refuse(lambda v, u: v["p_employees"].update({BQ: v["p_employees"][BQ] + 44000.0}))
    refuse(lambda v, u: v["h_employees"].update({BQ: v["h_employees"][BQ] + 98765432.1}))
    for sid, end in (("prod_p_q", JQ), ("prod_p_y", JQ), ("prod_h_q", BQ), ("prod_h_y", BQ)):                                  # the relation, with a value inside its range
        refuse(lambda v, u, sid=sid, end=end: v[sid].update({_l(_i(end) - 6): v[sid][_l(_i(end) - 6)] + 1.5}))
    refuse(lambda v, u: v["prod_p_q"].pop(JQ))
    refuse(lambda v, u: v["prod_h_q"].pop(BQ))
    refuse(lambda v, u: v["h_A"].pop(BQ))
    assert len(errs) > 90 and max(len(e) for e in errs) <= 110, max(errs, key=len)


def test_series_ending_on_different_quarters_are_refused_and_so_are_employment_and_its_breakdown_too_far_apart():
    base = _world()
    for sid in BREAKDOWN:                                                                                                       # one breakdown series a quarter short
        v, units, status = _world()
        del v[sid][BQ]
        assert _err((v, units, status)) == "the employment breakdown series end on different quarters", sid
    v, units, status = _world(jobs_end=BQ, break_end=BQ)                                                                        # total employment level with its breakdown: fine
    assert _err((v, units, status)) is None
    assert _err(_world(jobs_end="2026-Q3", break_end="2026-Q2")) is None
    assert _err(_world(jobs_end="2026-Q4", break_end="2026-Q2")) == "total employment and its breakdown end more than a quarter apart"
    assert _err(_world(jobs_end="2026-Q1", break_end="2026-Q2")) == "total employment and its breakdown end more than a quarter apart"     # employment cannot be behind its breakdown


def test_productivity_must_end_where_its_employment_series_ends():
    v, units, status = _world()
    del v["prod_p_q"][JQ]
    assert _err((v, units, status)) == f"productivity per person ends on {BQ}, not on the newest quarter of employment ({JQ})"
    v, units, status = _world()
    del v["prod_p_y"][JQ]
    assert _err((v, units, status)) == f"productivity per person ends on {BQ}, not on the newest quarter of employment ({JQ})"
    v, units, status = _world()
    del v["prod_h_q"][BQ]
    assert _err((v, units, status)) == f"productivity per hour ends on {_l(_i(BQ) - 1)}, not on the newest quarter of the breakdown ({BQ})"
    v, units, status = _world()
    del v["prod_h_y"][BQ]
    assert _err((v, units, status)) == f"productivity per hour ends on {_l(_i(BQ) - 1)}, not on the newest quarter of the breakdown ({BQ})"
    v, units, status = _world()
    v["prod_p_q"]["2026-Q4"] = 0.1                                                                                              # one quarter ahead of employment
    assert _err((v, units, status)) == f"productivity per person ends on 2026-Q4, not on the newest quarter of employment ({JQ})"


def test_a_quarter_missing_in_the_last_45_is_refused_and_an_older_one_is_not():
    for sid in IDS:
        end = max(_i(q) for q in _world()[0][sid])
        for back, refused in ((1, True), (20, True), (44, True), (45, False), (50, False)):
            v, units, status = _world(extra=8)
            q = _l(end - back)
            del v[sid][q]
            err = _err((v, units, status))
            if refused:
                assert err == f"{NAMES[sid]} is missing for {q}", (sid, back, err)
            else:
                assert err is None, (sid, back, err)


def test_the_message_for_a_missing_quarter_names_the_series_and_the_quarter():
    v, units, status = _world()
    del v["p_OTQ"][_l(_i(BQ) - 3)]
    assert _err((v, units, status)) == f"employment in {SECTOR['OTQ']} is missing for {_l(_i(BQ) - 3)}"
    v, units, status = _world()
    del v["gdp"][_l(_i(JQ) - 2)]
    assert _err((v, units, status)) == f"real GDP is missing for {_l(_i(JQ) - 2)}"


@pytest.mark.parametrize("sid, lo, hi, end", [("p_total", 100000.0, 250000.0, JQ), ("h_total", 40000000.0, 100000000.0, BQ)])
def test_total_employment_and_total_hours_must_lie_inside_their_ranges_in_every_quarter_of_the_window(sid, lo, hi, end):
    name = NAMES[sid]
    for q_ in (end, _l(_i(end) - 20), _l(_i(end) - 44)):
        for value, ok in ((lo, True), (lo + 1.0, True), (hi - 1.0, True), (hi, True), (lo - 0.5, False), (hi + 0.5, False)):
            v, units, status = _world()
            v[sid][q_] = value
            err = _err((v, units, status))
            if ok:
                assert err is None or not err.startswith(f"{name} is "), (sid, q_, value, err)                                  # inside the range a later check may speak, never this one
            else:
                assert err is not None and err.startswith(f"{name} is ") and err.endswith(f" in {q_}, outside {S._lim(lo)} to {S._lim(hi)}"), (sid, q_, value, err)


def test_the_ranges_are_checked_before_the_sums_so_each_test_reaches_its_own():
    v, units, status = _world()
    v["p_total"][BQ] = 300000.0                                                                                                 # also breaks the sum of the ten sectors, but the range speaks first
    assert _err((v, units, status)).endswith("outside 100,000 to 250,000")


def test_the_jobs_move_by_up_to_10_percent_in_a_quarter():
    for ch, ok in ((9.99, True), (-9.99, True), (0.0, True), (10.01, False), (-10.01, False), (25.0, False)):                    # a percent bound cannot be hit exactly in floating point: probe either side
        v, units, status = _world(trend=0.0)
        v["p_total"][JQ] = v["p_total"][BQ] * (1 + ch / 100)                                                                     # the newest quarter has no breakdown, so only the move can notice
        err = _err((v, units, status))
        if ok:
            assert err is None or not err.startswith("employment moved by"), (ch, err)
        else:
            assert err == f"employment moved by {ch:+.2f}% in {JQ}, outside -10% to +10%", (ch, err)
    v, units, status = _world(trend=0.0)
    v["p_total"][_l(_i(BQ) - 6)] = v["p_total"][_l(_i(BQ) - 7)] * 0.8                                                           # an older quarter of the window counts too (and the move back, +25%, is the one named)
    assert _err((v, units, status)) == f"employment moved by -20.00% in {_l(_i(BQ) - 6)}, outside -10% to +10%"


def test_a_sector_may_be_between_a_fifth_of_a_percent_and_40_percent_of_employment():
    q = _l(_i(BQ) - 2)
    for sid, share, ok in (("p_L", 0.21, True), ("p_L", 0.19, False), ("p_OTQ", 39.99, True), ("p_OTQ", 40.01, False)):
        v, units, status = _world(trend=0.0)
        total = v["p_total"][q]
        v[sid][q] = total * share / 100                                                                                         # the breakdown no longer adds up, but the share check speaks first
        err = _err((v, units, status))
        if ok:
            assert err is None or not err.startswith(f"{NAMES[sid]} is "), (sid, share, err)
        else:
            assert err == f"{NAMES[sid]} is {share:.2f}% of employment in {q}, outside 0.2% to 40%", (sid, share, err)


def test_the_self_employed_may_be_between_5_and_45_percent_of_persons_and_of_hours():
    q = _l(_i(BQ) - 3)
    for sid, tot, share, ok in (("p_self", "p_total", 5.01, True), ("p_self", "p_total", 4.99, False), ("p_self", "p_total", 44.99, True), ("p_self", "p_total", 45.01, False),
                                ("h_self", "h_total", 5.01, True), ("h_self", "h_total", 4.99, False), ("h_self", "h_total", 44.99, True), ("h_self", "h_total", 45.01, False)):
        v, units, status = _world(trend=0.0)
        v[sid][q] = v[tot][q] * share / 100
        err = _err((v, units, status))
        what = "employment" if sid == "p_self" else "hours worked"
        if ok:
            assert err is None or not err.startswith(f"{NAMES[sid]} is "), (sid, share, err)
        else:
            assert err == f"{NAMES[sid]} is {share:.2f}% of {what} in {q}, outside 5% to 45%", (sid, share, err)


def test_hours_per_person_in_a_quarter_must_lie_between_250_and_500():
    q = _l(_i(BQ) - 4)
    for hpp, ok in ((250.0, True), (249.9, False), (500.0, True), (500.1, False)):
        v, units, status = _world()
        v["h_total"][q] = v["p_total"][q] * hpp
        err = _err((v, units, status))
        if ok:
            assert err is None or not err.startswith("hours per person are"), (hpp, err)
        else:
            assert err == f"hours per person are {hpp:.1f} in {q}, outside 250 to 500", (hpp, err)


@pytest.mark.parametrize("sid", PROD)
def test_productivity_growth_must_lie_inside_its_range_in_every_quarter_of_its_window(sid):
    lo, hi = PROD_LIMITS[sid]
    end = JQ if sid.startswith("prod_p") else BQ
    for q in (end, _l(_i(end) - 15), _l(_i(end) - 44)):
        for value, ok in ((lo, True), (hi, True), (lo + 0.01, True), (hi - 0.01, True), (lo - 0.01, False), (hi + 0.01, False)):
            v, units, status = _world()
            v[sid][q] = value
            err = _err((v, units, status))
            if ok:
                assert err is None or not err.startswith(f"{NAMES[sid]} is "), (sid, q, value, err)
            else:
                assert err == f"{NAMES[sid]} is {value:,.2f}% in {q}, outside {lo:g}% to {hi:g}%", (sid, q, value, err)


def _off_by(world, sid, q, gap):
    world[0][sid][q] += gap
    return world


def test_the_ten_sectors_must_add_up_to_total_employment_within_the_tolerance():
    q = BQ
    msg = lambda off: f"the ten activities do not add up to total employment in {q} (off by {off:+.6f} thousand persons)"
    w = _world(trend=0.0)
    assert _err(_off_by(w, "p_total", q, 2 ** -20)) is None                                                                     # exactly the tolerance: still fine
    assert _err(_off_by(_world(trend=0.0), "p_total", q, 2 ** -20 + 2 ** -34)) == msg(2 ** -20 + 2 ** -34)
    assert _err(_off_by(_world(trend=0.0), "p_total", q, -(2 ** -20 + 2 ** -34))) == msg(-(2 ** -20 + 2 ** -34))
    assert _err(_off_by(_world(trend=0.0), "p_total", _l(_i(q) - 30), 1.0)) == f"the ten activities do not add up to total employment in {_l(_i(q) - 30)} (off by +1.000000 thousand persons)"     # any quarter of the window
    for a in ACTS:                                                                                                              # every one of the ten sectors is part of the sum
        assert _err(_off_by(_world(trend=0.0), f"p_{a}", q, 5.0)) == msg(-5.0), a


def test_the_ten_sectors_must_add_up_to_total_hours_within_the_tolerance():
    q = _l(_i(BQ) - 7)
    msg = lambda off: f"the ten activities do not add up to total hours in {q} (off by {off:+.6f} thousand hours)"
    assert _err(_off_by(_world(trend=0.0), "h_total", q, 2 ** -12)) is None
    assert _err(_off_by(_world(trend=0.0), "h_total", q, 2 ** -12 + 2 ** -25)) == msg(2 ** -12 + 2 ** -25)
    assert _err(_off_by(_world(trend=0.0), "h_total", q, -(2 ** -12 + 2 ** -25))) == msg(-(2 ** -12 + 2 ** -25))
    for a in ACTS:
        assert _err(_off_by(_world(trend=0.0), f"h_{a}", q, 5.0)) == msg(-5.0), a


def test_employees_and_the_self_employed_must_add_up_to_total_employment_and_hours_within_the_tolerance():
    q = _l(_i(BQ) - 9)
    mp = lambda off: f"employees and self-employed do not add up to employment in {q} (off by {off:+.6f} thousand persons)"       # the total minus the two parts
    mh = lambda off: f"employees and self-employed do not add up to hours in {q} (off by {off:+.6f} thousand hours)"
    assert _err(_off_by(_world(trend=0.0), "p_employees", q, 2 ** -20)) is None and _err(_off_by(_world(trend=0.0), "p_self", q, -(2 ** -20))) is None          # exactly the tolerance: still fine
    assert _err(_off_by(_world(trend=0.0), "h_employees", q, 2 ** -12)) is None and _err(_off_by(_world(trend=0.0), "h_self", q, -(2 ** -12))) is None
    assert _err(_off_by(_world(trend=0.0), "p_employees", q, 2 ** -20 + 2 ** -34)) == mp(-(2 ** -20 + 2 ** -34))
    assert _err(_off_by(_world(trend=0.0), "p_self", q, -(2 ** -20 + 2 ** -34))) == mp(2 ** -20 + 2 ** -34)
    assert _err(_off_by(_world(trend=0.0), "h_employees", q, 2 ** -12 + 2 ** -25)) == mh(-(2 ** -12 + 2 ** -25))
    assert _err(_off_by(_world(trend=0.0), "h_self", q, -(2 ** -12 + 2 ** -25))) == mh(2 ** -12 + 2 ** -25)
    assert _err(_off_by(_world(trend=0.0), "p_total", _l(_i(q) - 20), 3.0)).startswith("the ten activities do not add up")


def test_the_sums_are_checked_in_the_order_they_are_listed_so_each_test_above_reaches_its_own():
    v, units, status = _world(trend=0.0)
    q = BQ
    v["p_employees"][q] += 1.0                                                                                                  # breaks only the status sum of persons: the sector sum still holds
    assert _err((v, units, status)).startswith("employees and self-employed do not add up to employment")
    v, units, status = _world(trend=0.0)
    v["p_OTQ"][q] += 1.0
    v["h_employees"][q] += 1.0                                                                                                  # the sector sum of persons speaks before the status sum of hours
    assert _err((v, units, status)).startswith("the ten activities do not add up to total employment")
    v, units, status = _world(trend=0.0)
    v["h_OTQ"][q] += 1.0
    v["h_employees"][q] += 1.0
    assert _err((v, units, status)).startswith("the ten activities do not add up to total hours")


def test_the_persons_sums_cover_the_quarters_that_total_employment_has_and_the_hours_sums_all_45():
    r = _run(_world())
    assert r["detail"]["quarters_checked"] == 45 and r["detail"]["persons_quarters_checked"] == 44                              # total employment is a quarter ahead, so its oldest quarter has no breakdown, and the breakdown's oldest has no total
    r = _run(_world(jobs_end=BQ, break_end=BQ))
    assert r["detail"]["quarters_checked"] == 45 and r["detail"]["persons_quarters_checked"] == 45


@pytest.mark.parametrize("sid", PROD)
def test_productivity_growth_must_follow_real_gdp_and_employment_within_the_tolerance(sid):
    jump = "p" if sid.startswith("prod_p") else "h"
    end = JQ if jump == "p" else BQ
    kind = "quarterly" if sid.endswith("_q") else "annual"
    msg = lambda off: f"productivity per {'person' if jump == 'p' else 'hour'} is not real GDP over {'jobs' if jump == 'p' else 'hours'} in {end} ({kind}, off by {off:+.9f})"
    w = _exact_world(jump)
    assert _err(w) is None                                                                                                      # the exact world passes: productivity 6.25% from a 6.25% GDP rise over flat employment
    _off_by(w, sid, end, 2 ** -30)
    assert _err(w) is None                                                                                                      # a gap of exactly the tolerance is not refused
    w = _exact_world(jump)
    _off_by(w, sid, end, 2 ** -30 + 2 ** -40)
    assert _err(w) == msg(2 ** -30 + 2 ** -40)
    w = _exact_world(jump)
    _off_by(w, sid, end, -(2 ** -30 + 2 ** -40))
    assert _err(w) == msg(-(2 ** -30 + 2 ** -40))
    w = _exact_world(jump)
    q = _l(_i(end) - 12)                                                                                                        # any quarter of the window, not only the newest
    w[0][sid][q] += 0.01
    assert _err(w) == f"productivity per {'person' if jump == 'p' else 'hour'} is not real GDP over {'jobs' if jump == 'p' else 'hours'} in {q} ({kind}, off by +0.010000000)"


def test_the_productivity_check_skips_the_quarters_whose_earlier_level_is_not_in_the_window_and_needs_real_gdp_for_the_rest():
    v, units, status = _world()
    r = _run((v, units, status))
    assert r["detail"]["largest_productivity_gap"] == 0.0
    del v["gdp"][JQ]
    v["gdp"][_l(_i(JQ) - 45)] = 3000000.0                                                                                       # real GDP now has a full window ending a quarter earlier, so the missing newest quarter is the productivity check's to find
    assert _err((v, units, status)) == f"real GDP is missing for {JQ}"
    v, units, status = _world(extra=8)
    del v["gdp"][_l(_i(JQ) - 50)]                                                                                               # outside the 45-quarter window of real GDP: ignored
    assert _err((v, units, status)) is None


def test_the_largest_gaps_are_reported_rounded():
    v, units, status = _world(trend=0.0)
    v["p_total"][BQ] += 2 ** -21
    v["h_total"][BQ] += 2 ** -13
    r = _run((v, units, status))["detail"]
    assert r["largest_persons_gap"] == round(2 ** -21, 12) == 4.76837e-07 and r["largest_hours_gap"] == round(2 ** -13, 9) == 0.00012207
    v, units, status = _world()
    v["prod_p_q"][JQ] += 3e-10
    assert _run((v, units, status))["detail"]["largest_productivity_gap"] == round(3e-10, 12) == 3e-10


def test_the_real_record_passes_every_check_and_is_pinned():
    assert _err(_real()) is None
    v = _real()[0]
    q = sorted(v["p_total"], key=_i)
    mv = [100 * (v["p_total"][b] / v["p_total"][a] - 1) for a, b in zip(q, q[1:])]
    assert (round(min(mv), 3), round(max(mv), 3)) == (-2.835, 1.128)                                                            # the real jobs extremes in the fetched window (2020-Q2 and 2021-Q3) are inside the bound of 10%
    sh = [100 * v[f"p_{a}"][x] / v["p_total"][x] for a in ACTS for x in v["p_A"] if x in v["p_total"]]
    assert (round(min(sh), 2), round(max(sh), 2)) == (0.97, 25.13)
    hp = [v["h_total"][x] / v["p_total"][x] for x in v["h_total"] if x in v["p_total"]]
    assert (round(min(hp), 2), round(max(hp), 2)) == (335.7, 396.25)
    assert (round(min(v["prod_p_q"].values()), 3), round(max(v["prod_p_q"].values()), 3)) == (-8.563, 10.383)
    assert (round(min(v["prod_h_y"].values()), 3), round(max(v["prod_h_y"].values()), 3)) == (-1.763, 3.545)


def test_the_limits_and_tolerances_are_the_ones_set_from_the_real_record():
    assert (S.PERSONS_LIMITS, S.HOURS_LIMITS, S.SECTOR_SHARE, S.SELF_SHARE, S.HOURS_PER_PERSON, S.JOBS_MOVE) == (PERSONS_LIMITS, HOURS_LIMITS, SECTOR_SHARE, SELF_SHARE, HOURS_PER_PERSON, JOBS_MOVE)
    assert S.PROD_LIMITS == PROD_LIMITS
    assert (S.PERSONS_TOLERANCE, S.HOURS_TOLERANCE, S.PRODUCTIVITY_TOLERANCE) == (2 ** -20, 2 ** -12, 2 ** -30) == (0.00000095367431640625, 0.000244140625, 9.313225746154785e-10)
    assert (S.LAST_N, S.OVERDUE_AFTER_DAYS, S.RECENT_QUARTERS, S.TIMEOUT) == (45, 135, 6, 90.0)
    assert (S.TTL, S.FAIL_TTL) == (21600.0, 120.0)
    assert S.BASE == "https://data-api.ecb.europa.eu/service/data/MNA/" and S.NAMES == NAMES and S.SECTOR == SECTOR and S.ACTS == ACTS
    assert S.PAGE == "https://data-api.ecb.europa.eu/service/data/MNA/Q.Y.I10.W2.S1.S1._Z.EMP._Z._T._Z.PS._Z.N"
    assert S.SOURCE == ("European Central Bank, euro-area employment, hours worked and labour productivity (Eurostat quarterly national accounts, ESA 2010, euro area of 21 countries, seasonally and calendar adjusted), "
                        "as published on the ECB Data Portal (official, free public data)")


def test_the_tables_of_series_and_requests_are_the_ones_the_real_fixture_was_fetched_with():
    assert tuple(S.SERIES) == IDS and len(IDS) == 31
    for sid in IDS:
        key, unit = S.SERIES[sid]
        assert "MNA." + key == F["series"][sid]["key"] and tuple(F["series"][sid]["unit"]) == unit == UNITS[sid], sid
    assert S.SERIES["p_total"] == ("Q.Y.I10.W2.S1.S1._Z.EMP._Z._T._Z.PS._Z.N", PS) and S.SERIES["h_OTQ"] == ("Q.Y.I10.W2.S1.S1._Z.EMP._Z.OTQ._Z.HW._Z.N", HW)
    assert S.SERIES["p_employees"][0] == "Q.Y.I10.W2.S1.S1._Z.SAL._Z._T._Z.PS._Z.N" and S.SERIES["h_self"][0] == "Q.Y.I10.W2.S1.S1._Z.SELF._Z._T._Z.HW._Z.N"
    assert S.SERIES["gdp"] == ("Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N", EUR6)
    assert S.SERIES["prod_p_q"] == ("Q.Y.I10.W0.S1.S1._Z.LPR_PS._Z._T._Z.EUR.LR.G1", EUR0) and S.SERIES["prod_h_y"] == ("Q.Y.I10.W0.S1.S1._Z.LPR_HW._Z._T._Z.EUR.LR.GY", EUR0)
    assert [k for k, ids in S.REQUESTS] == ["Q.Y.I10.W2.S1.S1._Z.EMP._Z._T+A+BTE+F+GTI+J+K+L+M_N+OTQ+RTU._Z.PS+HW._Z.N", "Q.Y.I10.W2.S1.S1._Z.SAL+SELF._Z._T._Z.PS+HW._Z.N",
                                           "Q.Y.I10.W2.S1.S1.B.B1GQ._Z._Z._Z.EUR.LR.N", "Q.Y.I10.W0.S1.S1._Z.LPR_PS+LPR_HW._Z._T._Z.EUR.LR.G1+GY"]
    assert sorted(s for k, ids in S.REQUESTS for s in ids) == sorted(IDS) and len([s for k, ids in S.REQUESTS for s in ids]) == 31      # every series is asked for once
    assert S.BREAKDOWN == BREAKDOWN and S.STATUS_IDS == ("p_employees", "p_self", "h_employees", "h_self")
    assert S.REQUESTS[0][1] == tuple(PEOPLE[:-2] + HOURS[:-2]) and S.REQUESTS[1][1] == ("p_employees", "p_self", "h_employees", "h_self") and S.REQUESTS[2][1] == ("gdp",) and S.REQUESTS[3][1] == tuple(PROD)


def test_the_headline_is_read_at_the_newest_quarter_of_employment_and_the_breakdown_at_its_own():
    r = _run(_world(bump=1.05))                                                                                                 # total employment 5% higher in the quarter after the breakdown
    assert r["jobs"]["persons"] == 181.3 and r["jobs"]["quarter_on_quarter"] == 5.0 and r["quarter"] == JQ
    b = r["breakdown"]
    assert b["persons"] == 172.7 and next(x for x in b["sectors"] if x["id"] == "OTQ")["share"] == 25.5 and b["employees"]["share"] == 75.0 and b["self_employed"]["share"] == 25.0
    assert [(x["quarter"], x["persons"]) for x in r["recent"]][:2] == [(JQ, 181.3), (BQ, 172.7)]


def test_the_hours_a_person_works_and_the_change_in_hours_keep_their_decimals():
    assert _run(_world(hpp=388.5))["breakdown"]["hours_per_person"] == 388.5
    assert _run(_world())["breakdown"]["hours_change_year"] == round(100 * (172700.0 / (172700.0 - 280.0) - 1), 2) == 0.16      # four quarters earlier every sector had 28 thousand fewer persons


def test_productivity_per_hour_is_its_own_series_not_productivity_per_person():
    r = _run(_world(hpp_trend=0.5))["productivity"]                                                                             # the hours a person works rise by half an hour a quarter
    persons = lambda k: sum(BASE_PEOPLE[a] + 7.0 * k for a in ACTS)
    hours = lambda k: persons(k) * (388.0 + 0.5 * k)
    assert r["per_person"]["quarter_on_quarter"] == round(100 * (1.0025 / 1.0005 - 1), 2) == 0.2
    assert r["per_hour"]["quarter_on_quarter"] == round(100 * (1.0025 / (hours(0) / hours(-1)) - 1), 2) == 0.08
    assert r["per_hour"]["year_on_year"] == round(100 * ((1.0025 ** 4) / (hours(0) / hours(-4)) - 1), 2)


def test_the_exact_edge_of_a_share_is_inside_its_range_and_a_little_beyond_it_is_not():
    q = _l(_i(BQ) - 2)
    ten = {a: 10000.0 for a in ACTS}                                                                                            # ten sectors of 10%, 100,000 persons and 410 hours a person: 0.2%, 40%, 5% and 45% are exact here

    def world():
        return _world(trend=0.0, hpp=410.0, base=ten)
    for a in ACTS:
        for value, share, ok in ((200.0, 0.2, True), (199.0, 0.2, False), (40000.0, 40.0, True), (40001.0, 40.0, False)):
            v, units, status = world()
            v[f"p_{a}"][q] = value
            err = _err((v, units, status))
            if ok:
                assert err is None or not err.startswith(f"{NAMES['p_' + a]} is "), (a, value, err)                              # the sums speak next
            else:
                assert err == f"{NAMES['p_' + a]} is {100 * value / 100000.0:.2f}% of employment in {q}, outside 0.2% to 40%", (a, value, err)
    for sid, tot, vals in (("p_self", "p_total", ((5000.0, True), (4900.0, False), (45000.0, True), (45100.0, False))), ("h_self", "h_total", ((2050000.0, True), (2000000.0, False), (18450000.0, True), (18500000.0, False)))):
        for value, ok in vals:
            v, units, status = world()
            v[sid][q] = value
            err = _err((v, units, status))
            what = "employment" if sid == "p_self" else "hours worked"
            if ok:
                assert err is None or not err.startswith(f"{NAMES[sid]} is "), (sid, value, err)
            else:
                assert err == f"{NAMES[sid]} is {100 * value / v[tot][q]:.2f}% of {what} in {q}, outside 5% to 45%", (sid, value, err)


def test_the_oldest_quarter_of_the_breakdown_is_judged_too_even_though_total_employment_does_not_have_it():
    q0 = _l(_i(BQ) - 44)
    v, units, status = _world()
    v["h_self"][q0] = v["h_total"][q0] * 0.04
    assert _err((v, units, status)) == f"{NAMES['h_self']} is 4.00% of hours worked in {q0}, outside 5% to 45%"
    v, units, status = _world()
    v["h_OTQ"][q0] += 5.0
    assert _err((v, units, status)) == f"the ten activities do not add up to total hours in {q0} (off by -5.000000 thousand hours)"
    v, units, status = _world()
    v["h_employees"][q0] += 5.0
    assert _err((v, units, status)) == f"employees and self-employed do not add up to hours in {q0} (off by -5.000000 thousand hours)"


def test_the_oldest_move_of_total_employment_is_judged_too():
    a, b = _l(_i(JQ) - 44), _l(_i(JQ) - 43)
    v, units, status = _world()
    v["p_total"][b] = v["p_total"][a] * 0.8
    assert _err((v, units, status)) == f"employment moved by -20.00% in {b}, outside -10% to +10%"


def test_the_largest_gap_reported_is_the_larger_of_what_either_sum_was_off_by():
    for sid, gap, key, digits in (("p_OTQ", 2 ** -22, "largest_persons_gap", 12), ("p_employees", 2 ** -22, "largest_persons_gap", 12), ("h_OTQ", 2 ** -14, "largest_hours_gap", 9), ("h_employees", 2 ** -14, "largest_hours_gap", 9)):
        v, units, status = _world(trend=0.0)
        v[sid][BQ] += gap                                                                                                       # only one of the two sums is off, and the other holds exactly
        assert _run((v, units, status))["detail"][key] == round(gap, digits), sid


def test_a_client_made_here_waits_90_seconds_and_is_closed(monkeypatch):
    seen = {"closed": False}

    class Fake:
        def __init__(self, **kw):
            seen["timeout"] = kw.get("timeout")

        async def get(self, url, params=None, headers=None):
            for key, ids in S.REQUESTS:
                if url == S.BASE + key:
                    return httpx.Response(200, text=_text(ids))
            raise AssertionError(url)

        async def aclose(self):
            seen["closed"] = True

    monkeypatch.setattr(S.httpx, "AsyncClient", Fake)
    r = asyncio.run(S.EuroEmployment().overview(NOW))
    assert r["available"] is True and seen["timeout"] == 90.0 and seen["closed"] is True


def test_an_answer_from_the_cache_carries_the_time_of_the_question_and_the_age_the_time_of_the_question_gives():
    async def go():
        async with _transport(_handler) as c:
            e = S.EuroEmployment(client=c)
            a = await e.overview(NOW)
            b = await e.overview(NOW + timedelta(hours=1))
            return a, b

    a, b = asyncio.run(go())
    assert a["as_of"] == NOW.isoformat() and b["as_of"] == (NOW + timedelta(hours=1)).isoformat() and b["jobs"] == a["jobs"]
    late = asyncio.run(S.EuroEmployment(client=_transport(_handler)).overview(datetime(2027, 3, 1, 12, tzinfo=timezone.utc)))
    assert late["age_days"] == 152 and late["freshness"] == "OVERDUE"                                                           # 2026-09-30 to 2027-03-01, by the date of the question and not by the clock of the machine


@pytest.mark.parametrize("code", [301, 400, 403, 404, 429])
def test_any_answer_but_200_is_a_failure_that_says_which(code):
    async def go():
        async with _transport(lambda req: httpx.Response(code, text="x")) as c:
            return await S.EuroEmployment(client=c).overview(NOW)

    r = asyncio.run(go())
    assert r["available"] is False and r["reason"] == f"The euro-area employment could not be read right now ({fail_reason(ValueError(f'HTTP {code}'))})"


def test_the_request_asks_for_csv():
    seen = []

    def handler(req):
        seen.append(req.headers["accept"])
        return _handler(req)

    async def go():
        async with _transport(handler) as c:
            return await S.EuroEmployment(client=c).overview(NOW)

    assert asyncio.run(go())["available"] is True and seen == ["text/csv"] * 4


def test_a_refusal_for_a_total_shows_the_value_that_was_refused():
    for sid, value, shown in (("p_total", 250000.5, "250,000.5"), ("p_total", 99999.5, "99,999.5"), ("h_total", 100000000.5, "100,000,000.5"), ("h_total", 39999999.5, "39,999,999.5")):
        v, units, status = _world()
        v[sid][BQ if sid == "h_total" else JQ] = value
        end = BQ if sid == "h_total" else JQ
        lo, hi = ("100,000", "250,000") if sid == "p_total" else ("40,000,000", "100,000,000")
        assert _err((v, units, status)) == f"{NAMES[sid]} is {shown} in {end}, outside {lo} to {hi}"


HEAD = "KEY,TIME_PERIOD,OBS_VALUE,OBS_STATUS,UNIT_MEASURE,UNIT_MULT\n"
OK = "MNA.Q.Y.I10.W2.S1.S1._Z.EMP._Z._T._Z.PS._Z.N"


def test_the_real_layout_of_a_response_is_read():
    sid = next(s for s, d in F["series"].items() if d["key"] == F["raw_head_key"])
    v, units, status = S.parse(F["raw_head"], (sid,))
    assert list(v[sid]) == F["series"][sid]["quarters"][:2] and list(v[sid].values()) == F["series"][sid]["values"][:2]
    assert units == {sid: tuple(F["series"][sid]["unit"])} and status == {sid: "A"}
    assert F["raw_head"].startswith("KEY,FREQ,ADJUSTMENT,REF_AREA,COUNTERPART_AREA,REF_SECTOR,COUNTERPART_SECTOR,ACCOUNTING_ENTRY,STO,INSTR_ASSET,ACTIVITY,EXPENDITURE,UNIT_MEASURE,PRICES,TRANSFORMATION,TIME_PERIOD,OBS_VALUE,OBS_STATUS,")


def test_values_that_are_missing_or_not_numbers_are_skipped_never_filled_and_two_values_for_a_quarter_are_an_error():
    text = HEAD + f"{OK},2026-Q2,5.5,A,PS,3\n{OK},26-Q3,1,A,PS,3\n{OK},202-Q3,1,A,PS,3\n{OK},2026-Q1,,M,PS,3\n{OK},2025-Q4,n/a,A,PS,3\n{OK},2025,1,A,PS,3\n{OK},2025-Q5,1,A,PS,3\n{OK},2025-Q0,1,A,PS,3\n{OK},2025-q3,1,A,PS,3\n{OK},2025-Q03,1,A,PS,3\n{OK},2025Q3,1,A,PS,3\n{OK},2025-Q3x,1,A,PS,3\n{OK},2025-09,1,A,PS,3\n"
    text += f"{OK},2025-Q2,nan,A,PS,3\n{OK},2025-Q1,inf,A,PS,3\nMNA.Q.Y.I9.W2.S1.S1._Z.EMP._Z._T._Z.PS._Z.N,2026-Q2,0.9,A,PS,3\nMNA.A.Y.I10.W2.S1.S1._Z.EMP._Z._T._Z.PS._Z.N,2026,0.8,A,PS,3\nMNA.Q.Y.I10.W2.S1.S1._Z.SAL._Z._T._Z.PS._Z.N,2026-Q2,0.7,A,PS,3\n"
    text += f"{OK},2025-Q3\n"                                                                                                   # a row cut short: its value is missing altogether
    v, units, status = S.parse(text, ("p_total",))
    assert v == {"p_total": {"2026-Q2": 5.5}} and units == {"p_total": PS} and status == {"p_total": "A"}                         # a quarter with no value, a year, bad quarters, nan, inf, the 20-country area, another frequency and another series are all left out
    padded = HEAD + f"{OK},2026-Q2,5.5, P , PS , 3 \n"
    assert S.parse(padded, ("p_total",))[1] == {"p_total": PS} and S.parse(padded, ("p_total",))[2] == {"p_total": "P"}
    two = HEAD + f"{OK},2026-Q1,0.1,A,PS,3\n{OK},2026-Q3,0.3,P,PS,3\n{OK},2026-Q2,0.2,A,PS,3\n"
    assert S.parse(two, ("p_total",))[2] == {"p_total": "P"}                                                                    # the status is the newest quarter's, whatever the order of the rows
    two = HEAD + f"{OK},2025-Q4,0.3,P,PS,3\n{OK},2026-Q1,0.1,A,PS,3\n"
    assert S.parse(two, ("p_total",))[2] == {"p_total": "A"}
    with pytest.raises(ValueError, match=r"p_total has two values for 2026-Q2"):
        S.parse(text + f"{OK},2026-Q2,0.1,A,PS,3\n", ("p_total",))
    with pytest.raises(ValueError, match=r"no values for h_total"):
        S.parse(text, ("p_total", "h_total"))
    with pytest.raises(ValueError, match=r"the source returned no values for h_total, gdp$"):
        S.parse(text, ("h_total", "gdp"))


def _text(ids, units=None):
    rows = []
    for sid in ids:
        d = F["series"][sid]
        unit = units.get(sid, d["unit"]) if units else d["unit"]
        rows += [f"MNA.{S.SERIES[sid][0]},{q},{x!r},{st},{unit[0]},{unit[1]}" for q, x, st in zip(d["quarters"], d["values"], d["status"])]
    return HEAD + "\n".join(rows) + "\n"


def _transport(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _ids_of(path):
    for key, ids in S.REQUESTS:
        if path == "/service/data/MNA/" + key:
            return ids
    raise AssertionError(path)


def _handler(req, replace=None, units=None):
    ids = _ids_of(req.url.path)
    text = _text(ids, units if units and any(i in units for i in ids) else None)
    return httpx.Response(200, text=text.replace(*replace) if replace else text)


def test_overview_fetches_four_requests_and_caches():
    seen = []

    def handler(req):
        seen.append((req.url.path, dict(req.url.params), req.headers["user-agent"]))
        return _handler(req)

    async def go():
        async with _transport(handler) as c:
            e = S.EuroEmployment(client=c)
            a = await e.overview(NOW)
            b = await e.overview(NOW)
            return a, b

    a, b = asyncio.run(go())
    assert a["available"] is True and a["quarter"] == "2026-Q3" and a["demo"] is False and b["available"] is True
    assert len(seen) == 4                                                                                                       # the second call is answered from the cache
    assert sorted(p for p, _, _ in seen) == sorted("/service/data/MNA/" + k for k, _ in S.REQUESTS)
    assert all(q == {"lastNObservations": "45", "format": "csvdata"} for _, q, _ in seen) and all(ua == "ATLAS research terminal" for _, _, ua in seen)
    assert a["jobs"]["persons"] == 176.5 and a["breakdown"]["persons"] == 176.5 and a["as_of"] == NOW.isoformat()


def test_a_provisional_newest_total_reaches_the_card():
    def handler(req):
        return _handler(req, replace=("2026-Q3,176547.095680786,A", "2026-Q3,176547.095680786,P"))

    async def go():
        async with _transport(handler) as c:
            return await S.EuroEmployment(client=c).overview(NOW)

    assert asyncio.run(go())["provisional"] is True


def test_an_unexpected_missing_key_reads_as_unavailable_not_as_a_crash(monkeypatch):
    def broken(text, ids):
        raise KeyError("x")
    monkeypatch.setattr(S, "parse", broken)

    async def go():
        async with _transport(_handler) as c:
            return await S.EuroEmployment(client=c).overview(NOW)

    r = asyncio.run(go())
    assert r["available"] is False and "could not be read right now" in r["reason"]


def test_a_success_is_kept_for_six_hours_and_a_failure_for_two_minutes(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(S.time, "monotonic", lambda: clock[0])
    calls = []
    ok = [False]

    def handler(req):
        calls.append(req.url.path)
        return _handler(req) if ok[0] else httpx.Response(503, text="no")

    async def go():
        async with _transport(handler) as c:
            e = S.EuroEmployment(client=c)
            r1 = await e.overview(NOW)
            n1 = len(calls)
            clock[0] += 119.0
            r2 = await e.overview(NOW)
            n2 = len(calls)
            clock[0] += 2.0
            ok[0] = True
            r3 = await e.overview(NOW)
            n3 = len(calls)
            clock[0] += 21599.0
            r4 = await e.overview(NOW)
            n4 = len(calls)
            clock[0] += 2.0
            r5 = await e.overview(NOW)
            return r1, n1, r2, n2, r3, n3, r4, n4, r5, len(calls)

    r1, n1, r2, n2, r3, n3, r4, n4, r5, n5 = asyncio.run(go())
    assert r1["available"] is False and r2["available"] is False and n2 == n1                                                   # the failure is remembered for 120 seconds
    assert r3["available"] is True and n3 > n2 and r4["available"] is True and n4 == n3 and r5["available"] is True and n5 > n4   # the success for six hours


def test_failure_says_so_and_shows_no_numbers():
    async def go():
        async with _transport(lambda req: httpx.Response(500, text="x")) as c:
            return await S.EuroEmployment(client=c).overview(NOW)

    r = asyncio.run(go())
    assert r["available"] is False and r["reason"].startswith("The euro-area employment could not be read right now (") and "jobs" not in r and "breakdown" not in r


def test_a_response_in_other_units_is_refused_and_shows_nothing():
    async def go():
        async with _transport(lambda req: _handler(req, units={"p_total": ("PS", "0")})) as c:
            return await S.EuroEmployment(client=c).overview(NOW)

    r = asyncio.run(go())
    assert r["available"] is False and "other units" in r["reason"] and "jobs" not in r


def test_a_dropped_connection_reads_plainly():
    def handler(req):
        raise httpx.ConnectError("boom", request=req)

    async def go():
        async with _transport(handler) as c:
            return await S.EuroEmployment(client=c).overview(NOW)

    r = asyncio.run(go())
    assert r["available"] is False and "ConnectError" not in r["reason"] and "boom" not in r["reason"]


def test_a_refusal_names_what_failed_within_the_clipped_message():
    def handler(req):
        return _handler(req, replace=("2026-Q2,44357.970540782,A", "2026-Q2,44358.970540782,A"))

    async def go():
        async with _transport(handler) as c:
            return await S.EuroEmployment(client=c).overview(NOW)

    r = asyncio.run(go())
    want = fail_reason(ValueError("the ten activities do not add up to total employment in 2026-Q2 (off by -1.000000 thousand persons)"))
    assert r["available"] is False and r["reason"] == f"The euro-area employment could not be read right now ({want})" and "-1.000000" in r["reason"]


def test_demo_mode_invents_nothing():
    r = asyncio.run(S.EuroEmployment(demo=True).overview(NOW))
    assert r["available"] is False and r["demo"] is True and "made-up" in r["reason"] and "jobs" not in r


def test_route_is_served_and_labelled(tmp_path):
    app = create_app(db_path=str(tmp_path / "a.db"), demo=True, alert_loop=False, news_loop=False)
    with TestClient(app) as c:
        r = c.get("/api/macro/euro-employment")
        assert r.status_code == 200 and r.json()["data"]["available"] is False and r.json()["data"]["demo"] is True and "as_of" in r.json()["data"]
