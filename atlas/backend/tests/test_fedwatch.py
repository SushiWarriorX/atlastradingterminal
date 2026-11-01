"""Fed Watch: calendar and timezones, decisions from the target range, classification and de-duplication, ICS parsing, release facts, partial failure."""
import asyncio
import pathlib
import re
import time
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from atlas_api import fedwatch as F
from atlas_api import macro as M
from atlas_api.app import create_app
from atlas_api.models import ProviderUnavailable
from atlas_api.news.parse import FeedError, RawItem

D = date
ORDER = re.compile(r"\b(buy|sell|short(?!-)|go long|enter|exit|stop[- ]loss|take[- ]profit|price target|you should|will (rise|fall|crash|rally))\b", re.I)


def run(c):
    return asyncio.run(c)


def days(start, values):
    return [(start + timedelta(days=i), v) for i, v in enumerate(values)]


def months(start, values):
    out, y, m = [], start.year, start.month
    for v in values:
        out.append((D(y, m, 1), v))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


# --- calendar and timezones ---------------------------------------------------------------------------------------------------------------
def test_announcement_times_follow_new_york_daylight_saving():
    assert F.et_to_utc(D(2026, 12, 9), "14:00").isoformat() == "2026-12-09T19:00:00+00:00"      # EST = UTC-5
    assert F.et_to_utc(D(2026, 6, 17), "14:00").isoformat() == "2026-06-17T18:00:00+00:00"      # EDT = UTC-4
    assert F.et_to_utc(D(2026, 12, 9), "14:30").hour == 19 and F.et_to_utc(D(2026, 12, 9), "14:30").minute == 30


def test_upcoming_events_are_future_sorted_and_flag_projection_meetings():
    now = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)
    ev = F.scheduled_events(now, 10)
    times = [e["at_utc"] for e in ev]
    assert times == sorted(times) and all(datetime.fromisoformat(t) > now for t in times) and all(e["kind"] == "scheduled" and e["link"] for e in ev)
    dec = next(e for e in ev if e["id"] == "statement-2026-12-09")
    assert dec["projections"] is True and "dot plot" in dec["title"]
    mins = next(e for e in ev if e["id"] == "minutes-2026-10-28")
    assert mins["at_utc"] == "2026-11-18T19:00:00+00:00"                                       # three weeks after the decision day


def test_meeting_table_is_well_formed():
    assert [e for _, e, _ in F.MEETINGS] == sorted(e for _, e, _ in F.MEETINGS)
    assert all(0 < (e - s).days <= 1 and e.weekday() < 5 for s, e, _ in F.MEETINGS)
    assert sum(1 for _, e, sep in F.MEETINGS if sep and e.year == 2026) == 4 and all(e.month in (3, 6, 9, 12) for _, e, sep in F.MEETINGS if sep)


# --- decisions ----------------------------------------------------------------------------------------------------------------------------
def ranges(changes):
    """Daily lower/upper series from 2026-01-01; changes = {date: (lo, hi)} effective from that date."""
    lo, hi, cur = [], [], (4.00, 4.25)
    for i in range(400):
        d = D(2026, 1, 1) + timedelta(days=i)
        cur = changes.get(d, cur)
        lo.append((d, cur[0]))
        hi.append((d, cur[1]))
    return lo, hi


def test_hold_cut_and_raise_are_computed_from_the_range_around_the_meeting():
    lo, hi = ranges({D(2026, 3, 19): (3.75, 4.00), D(2026, 9, 17): (4.00, 4.25)})            # cut after Mar 18, raise after Sep 16
    cut = F.decision(D(2026, 3, 18), lo, hi)
    assert cut["outcome"] == "cut" and cut["previous"]["upper"] == 4.25 and cut["new"]["upper"] == 4.00 and cut["change_bps"] == pytest.approx(-25.0)
    hold = F.decision(D(2026, 4, 29), lo, hi)
    assert hold["outcome"] == "held" and hold["change_bps"] == 0 and hold["announced_utc"].endswith("18:00:00+00:00")
    raised = F.decision(D(2026, 9, 16), lo, hi)
    assert raised["outcome"] == "raised" and raised["change_bps"] == pytest.approx(25.0) and raised["kind"] == "published_fact"


def test_decision_is_unavailable_without_data_on_both_sides():
    lo, hi = ranges({})
    assert F.decision(D(2025, 10, 28), lo, hi)["outcome"] is None                              # nothing before the meeting
    short = (lo[:100], hi[:100])
    assert F.decision(D(2026, 7, 29), *short)["outcome"] is None and "not available" in F.decision(D(2026, 7, 29), *short)["note"]


def test_decisions_lists_only_past_meetings_newest_first():
    lo, hi = ranges({})
    out = F.decisions(lo, hi, D(2026, 11, 1), 3)
    assert [d["meeting_end"] for d in out] == ["2026-10-28", "2026-09-16", "2026-07-29"]


# --- classification, speeches, de-duplication ------------------------------------------------------------------------------------------------
def item(title, link, day, summary="official text"):
    return RawItem(uid=link, title=title, link=link, summary=summary, published=datetime(2026, 10, day, 18, tzinfo=timezone.utc))


def test_classification_rules():
    c = F.classify
    assert c("Federal Reserve issues FOMC statement") == "statement" and c("Minutes of the Federal Open Market Committee, October 27-28") == "minutes"
    assert c("Implementation Note issued October 28, 2026") == "implementation"
    assert c("Federal Reserve Board announces plans for reducing the size of the balance sheet") == "balance_sheet"
    assert c("Federal Reserve Board announces extension of the Standing Repo facility") == "facility"
    assert c("Chair Powell's press conference") == "press_conference" and c("Summary of Economic Projections") == "projections"
    assert c("Federal Reserve Board announces approval of bank merger") is None
    assert c("Remarks on the economy", speech_feed=True) == "speech" and c("Remarks on the economy") is None


def test_significant_speeches_are_chair_and_vice_chair_only():
    assert F.significant_speech("Chair Powell, Economic Outlook") and F.significant_speech("Vice Chair Jefferson, Remarks")
    assert not F.significant_speech("Governor Waller, Remarks") and not F.significant_speech("Vice Chair for Supervision Bowman, Bank rules")


def test_communications_dedupe_across_feeds_and_keep_verbatim_text():
    a = [item("Federal Reserve issues FOMC statement", "https://f/a", 28, "The Committee decided to maintain the target range"), item("Approval of bank merger", "https://f/m", 27)]
    b = [item("Federal Reserve issues FOMC statement", "https://f/a", 28), item("Federal Reserve  issues FOMC statement!", "https://f/a2", 28)]          # same link, then same title+day
    c = [item("Governor Waller, Remarks", "https://f/s", 20), item("Chair Powell, Outlook", "https://f/p", 25)]
    out = F.communications([("monetary", False, a), ("all", False, b), ("speeches", True, c)])
    assert [x["type"] for x in out] == ["statement", "speech", "speech"] and out[0]["summary"] == "The Committee decided to maintain the target range"
    assert out[0]["why_it_matters"] and out[0]["kind"] == "published_fact" and out[1]["significant"] is True and out[2]["significant"] is False
    assert [x["published_utc"] for x in out] == sorted((x["published_utc"] for x in out), reverse=True)


# --- BLS calendar file ----------------------------------------------------------------------------------------------------------------------
ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261210T083000
SUMMARY:Consumer Price Index for November 2026
END:VEVENT
BEGIN:VEVENT
DTSTART:20261204T133000Z
SUMMARY:Employment Situation fo
 r November 2026
END:VEVENT
BEGIN:VEVENT
DTSTART;VALUE=DATE:20261215
SUMMARY:Consumer Price Index (date only)
END:VEVENT
BEGIN:VEVENT
DTSTART:20261211T133000Z
SUMMARY:Producer Price Index
END:VEVENT
BEGIN:VEVENT
DTSTART:garbage
SUMMARY:Consumer Price Index broken
END:VEVENT
END:VCALENDAR
"""


def test_ics_parsing_handles_timezones_folded_lines_and_filters():
    ev = F.parse_ics(ICS)
    assert [(e["series"], e["date"]) for e in ev] == [("jobs", "2026-12-04"), ("cpi", "2026-12-10"), ("cpi", "2026-12-15")]
    assert ev[0]["name"] == "Employment Situation for November 2026" and ev[0]["at_utc"] == "2026-12-04T13:30:00+00:00"
    assert ev[1]["at_utc"] == "2026-12-10T13:30:00+00:00" and ev[2]["at_utc"] is None


# --- release facts ----------------------------------------------------------------------------------------------------------------------------
TODAY = D(2026, 11, 20)


def P(**over):
    base = {
        "CPIAUCSL": months(D(2025, 1, 1), [100 + i * 0.3 for i in range(17)]), "CPILFESL": months(D(2025, 1, 1), [100 + i * 0.25 for i in range(17)]),
        "PCEPI": months(D(2025, 1, 1), [100 + i * 0.2 for i in range(17)]), "PCEPILFE": months(D(2025, 1, 1), [100 + i * 0.2 for i in range(17)]),
        "PAYEMS": months(D(2026, 1, 1), [159000, 159100, 159250, 159300, 159500, 159560, 159700, 159850, 159900]),
        "UNRATE": months(D(2026, 1, 1), [4.0, 4.1, 4.1, 4.2, 4.3, 4.3, 4.4, 4.4, 4.5]),
        "A191RL1Q225SBEA": [(D(2026, 1, 1), 2.0), (D(2026, 4, 1), 1.0), (D(2026, 7, 1), 3.0)],
        "WALCL": days(D(2026, 6, 1), [7_000_000 - 1000 * i for i in range(150)]),
    }
    base.update(over)
    return base


def test_release_facts_have_values_units_dates_relevance_and_no_consensus():
    facts = {f["id"]: f for f in F.release_facts(P(), TODAY)}
    assert set(facts) == {"cpi", "core_cpi", "pce", "core_pce", "payrolls", "unemployment", "gdp"}
    assert facts["payrolls"]["value"] == 50 and "thousand jobs" in facts["payrolls"]["unit"] and facts["payrolls"]["obs_date"] == "2026-09-01"
    assert facts["unemployment"]["value"] == 4.5 and facts["unemployment"]["changes"][0]["value"] == pytest.approx(0.1)
    assert facts["gdp"]["value"] == 3.0 and facts["gdp"]["changes"][0]["value"] == pytest.approx(2.0) and facts["gdp"]["changes"][0]["ref_date"] == "2026-04-01"
    assert facts["core_pce"]["unit"] == "% year-over-year" and facts["cpi"]["freshness"]["state"] in ("CURRENT", "OVERDUE")
    for f in facts.values():
        assert f["relevance"] and "Consensus: not shown" in f["consensus_note"] and not ORDER.search(f["relevance"])


def test_payroll_change_needs_the_exact_previous_month():
    gap = [x for x in P()["PAYEMS"] if x[0] != D(2026, 8, 1)]
    f = {x["id"]: x for x in F.release_facts(P(PAYEMS=gap), TODAY)}["payrolls"]
    assert f["value"] is None and "missing" in f["note"]


def test_missing_series_gives_an_error_row_not_a_crash():
    facts = {f["id"]: f for f in F.release_facts(P(PAYEMS=None, PCEPI=None), TODAY)}
    assert "error" in facts["payrolls"] and "PAYEMS" in facts["payrolls"]["error"] and "error" in facts["pce"] and "value" in facts["cpi"]


def test_release_freshness_follows_each_publication_schedule():
    assert M.freshness("PAYEMS", TODAY - timedelta(days=45), TODAY)["state"] == "CURRENT" and M.freshness("PAYEMS", TODAY - timedelta(days=80), TODAY)["state"] == "OVERDUE"
    assert M.freshness("A191RL1Q225SBEA", TODAY - timedelta(days=120), TODAY)["state"] == "CURRENT" and M.freshness("A191RL1Q225SBEA", TODAY - timedelta(days=200), TODAY)["state"] == "OVERDUE"
    assert M.freshness("WALCL", TODAY - timedelta(days=9), TODAY)["state"] == "CURRENT" and M.freshness("WALCL", TODAY - timedelta(days=20), TODAY)["state"] == "OVERDUE"


def test_balance_sheet_trend_rule():
    shrink = F.balance_sheet_fact(days(D(2026, 6, 1), [7_000_000 - 2000 * i for i in range(150)]), D(2026, 10, 30))
    assert shrink["trend"] == "shrinking" and shrink["unit"] == "$ trillions" and shrink["value"] == pytest.approx((7_000_000 - 2000 * 149) / 1e6) and "13" in shrink["changes"][1]["label"]
    assert F.balance_sheet_fact(days(D(2026, 6, 1), [7_000_000 + 3000 * i for i in range(150)]), D(2026, 10, 30))["trend"] == "growing"
    assert F.balance_sheet_fact(days(D(2026, 6, 1), [7_000_000] * 150), D(2026, 10, 30))["trend"] == "roughly flat"
    short = F.balance_sheet_fact(days(D(2026, 10, 1), [7_000_000] * 5), D(2026, 10, 30))
    assert "trend" not in short and short["why_it_matters"]


def test_scenarios_cover_all_assets_conditionally_without_order_language():
    assert set(F.SCENARIOS) == {"raised", "cut", "held"}
    for o, a in F.SCENARIOS.items():
        assert set(a) == {"equities", "bonds", "dollar", "crypto"}
        assert all(not ORDER.search(t) and re.search(r"\b(can|may|often|tend|usually|depend)", t) for t in a.values()), o
    assert "not predictions" in F.SCENARIO_NOTE and "consensus" in F.SCENARIO_NOTE


# --- service ----------------------------------------------------------------------------------------------------------------------------------
def rss(*items):
    body = "".join(f"<item><title>{t}</title><link>{l}</link><pubDate>{d}</pubDate><description>{s}</description><guid>{l}</guid></item>" for t, l, d, s in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{body}</channel></rss>'.encode()


class FakeNews:
    def __init__(self, pages, fail=()):
        self.pages, self.fail, self.calls = pages, set(fail), []

    async def _get(self, url, etag, lm):
        self.calls.append(url)
        if url in self.fail:
            raise FeedError("HTTP 503")
        return 200, self.pages[url], {}


class FakeFred:
    def __init__(self, data, fail=()):
        self.data, self.fail, self.calls = data, set(fail), []

    async def series(self, inst, start=None):
        self.calls.append((inst.provider_symbol, start))
        if inst.provider_symbol in self.fail:
            raise ProviderUnavailable("fred", "HTTP 500")
        return [(datetime(d.year, d.month, d.day, tzinfo=timezone.utc), v) for d, v in self.data[inst.provider_symbol]]


def fred_data(today):
    lo, hi = ranges({D(2026, 9, 17): (3.75, 4.00)})
    return {**P(), "DFEDTARL": lo, "DFEDTARU": hi}


def news_pages():
    pub = "Wed, 28 Oct 2026 18:00:00 GMT"
    return {F.FEEDS[0][1]: rss(("Federal Reserve issues FOMC statement", "https://fed/a", pub, "The Committee decided to maintain the range")),
            F.FEEDS[1][1]: rss(("Federal Reserve issues FOMC statement", "https://fed/a", pub, "dup"), ("Approval of merger", "https://fed/m", pub, "x")),
            F.FEEDS[2][1]: rss(("Chair Powell, Outlook", "https://fed/s", "Tue, 27 Oct 2026 15:00:00 GMT", "speech text")),
            F.BLS_ICS: ICS.encode()}


NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def test_overview_assembles_all_sections_and_labels_kinds():
    svc = F.FedWatchService(FakeFred(fred_data(NOW.date())), FakeNews(news_pages()))
    o = run(svc.overview(NOW))
    assert o["errors"] == [] and [d["meeting_end"] for d in o["decisions"]][:2] == ["2026-10-28", "2026-09-16"] and o["decisions"][1]["outcome"] == "cut"
    assert [c["type"] for c in o["communications"]] == ["statement", "speech"] and all(c["kind"] == "published_fact" for c in o["communications"])
    assert o["upcoming"] and all(e["kind"] == "scheduled" for e in o["upcoming"]) and len(o["releases"]) == 7 and o["balance_sheet"]["series"] == "WALCL"
    assert [e["series"] for e in o["release_schedule"]] == ["jobs", "cpi", "cpi"] and "PCE and GDP release dates are not loaded" in o["schedule_note"]
    assert all(f["ok"] for f in o["feed_status"]) and "not predictions" in o["scenario_note"] and set(o["links"]) == {"fomc_calendar", "bls_schedule", "bea_schedule"}


def test_partial_failure_keeps_what_works_and_reports_the_rest():
    fred = FakeFred(fred_data(NOW.date()), fail=["PAYEMS", "WALCL"])
    news = FakeNews(news_pages(), fail=[F.FEEDS[1][1], F.BLS_ICS])
    o = run(F.FedWatchService(fred, news).overview(NOW))
    assert len(o["errors"]) == 4 and any("PAYEMS" in e for e in o["errors"]) and any("BLS" in e for e in o["errors"])
    assert "error" in o["balance_sheet"] and "error" in next(r for r in o["releases"] if r["id"] == "payrolls") and "value" in next(r for r in o["releases"] if r["id"] == "cpi")
    assert [s["ok"] for s in o["feed_status"]] == [True, False, True] and o["communications"] and o["release_schedule"] == [] and "could not be read" in o["schedule_note"]
    assert "://" not in " ".join(o["errors"])


def test_all_sources_failing_still_returns_the_calendar():
    o = run(F.FedWatchService(FakeFred({}, fail=F.FRED_IDS), FakeNews({}, fail=[u for _, u in F.FEEDS] + [F.BLS_ICS])).overview(NOW))
    assert o["upcoming"] and o["decisions"] == [] and o["decisions_error"] and o["communications"] == [] and o["balance_sheet"]["error"]


def test_success_is_cached_for_a_while():
    fred, news = FakeFred(fred_data(NOW.date())), FakeNews(news_pages())
    svc = F.FedWatchService(fred, news)
    run(svc.overview(NOW))
    n = len(fred.calls)
    o2 = run(svc.overview(NOW + timedelta(minutes=5)))
    assert len(fred.calls) == n and o2["upcoming"] and svc._cache[0] - time.monotonic() > F.FAIL_CACHE_SECONDS


def test_partial_failure_is_cached_briefly_with_errors_still_visible_then_retried():
    fred = FakeFred(fred_data(NOW.date()), fail=["WALCL"])
    news = FakeNews(news_pages(), fail=[F.FEEDS[1][1]])
    svc = F.FedWatchService(fred, news)
    first = run(svc.overview(NOW))
    f_calls, n_calls = len(fred.calls), len(news.calls)
    for _ in range(5):                                                                              # five more page loads
        again = run(svc.overview(NOW))
    assert len(fred.calls) == f_calls and len(news.calls) == n_calls                                # nothing refetched
    assert again["errors"] == first["errors"] and len(again["errors"]) == 2 and "error" in again["balance_sheet"]
    assert svc._cache[0] - time.monotonic() <= F.FAIL_CACHE_SECONDS
    svc._cache = (0.0, svc._cache[1])                                                               # the short cache expires
    run(svc.overview(NOW))
    assert len(fred.calls) > f_calls and len(news.calls) > n_calls


def test_a_failed_bls_calendar_is_reported_and_also_only_cached_briefly():
    svc = F.FedWatchService(FakeFred(fred_data(NOW.date())), FakeNews(news_pages(), fail=[F.BLS_ICS]))
    o = run(svc.overview(NOW))
    assert any("BLS release calendar" in e for e in o["errors"]) and "could not be read" in o["schedule_note"]
    assert svc._cache[0] - time.monotonic() <= F.FAIL_CACHE_SECONDS


def test_requests_use_a_start_date_and_only_the_planned_series():
    fred = FakeFred(fred_data(NOW.date()))
    run(F.FedWatchService(fred, FakeNews(news_pages())).overview(NOW))
    assert {s for s, _ in fred.calls} == set(F.FRED_IDS) and all(st is not None for _, st in fred.calls)


def test_demo_mode_shows_only_the_calendar_and_makes_no_requests():
    class Boom:
        async def series(self, *a, **k):
            raise AssertionError("network in demo")

        async def _get(self, *a, **k):
            raise AssertionError("network in demo")
    o = run(F.FedWatchService(Boom(), Boom(), demo=True).overview(NOW))
    assert o["demo"] and o["upcoming"] and o["communications"] == [] and o["releases"] == [] and "Demo mode" in o["notice"]


def test_demo_and_real_payloads_have_the_same_keys():
    class Boom:
        async def series(self, *a, **k):
            raise AssertionError("no network")
    demo = run(F.FedWatchService(Boom(), Boom(), demo=True).overview(NOW))
    real = run(F.FedWatchService(FakeFred(fred_data(NOW.date())), FakeNews(news_pages())).overview(NOW))
    assert set(real) - set(demo) == set() and set(demo) - set(real) == {"notice"}               # the screen can rely on every list being present


def test_api_routes(tmp_path):
    from atlas_api.providers.fred import FredProvider
    from atlas_api.providers.http import Http

    def h(req):
        sid = req.url.params["id"]
        pts = fred_data(NOW.date())[sid]
        return httpx.Response(200, text="observation_date,X\n" + "\n".join(f"{d},{v}" for d, v in pts))
    fred = FredProvider(Http("https://fred.test", "fred", min_interval=0, retries=1, client=httpx.AsyncClient(transport=httpx.MockTransport(h), base_url="https://fred.test")))
    net = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>not a feed</html>")))
    with TestClient(create_app(db_path=str(tmp_path / "f.db"), demo=False, providers={"fred": fred}, alert_loop=False, news_loop=False, news_client=net)) as c:
        d = c.get("/api/macro/fed").json()["data"]
        assert d["upcoming"] and len(d["releases"]) == 7 and d["decisions"] and all(not s["ok"] for s in d["feed_status"])
    with TestClient(create_app(db_path=str(tmp_path / "f2.db"), demo=True, alert_loop=False)) as c:
        assert c.get("/api/macro/fed").json()["data"]["demo"] is True
    with TestClient(create_app(db_path=str(tmp_path / "f3.db"), demo=False, providers={}, alert_loop=False)) as c:
        assert c.get("/api/macro/fed").status_code == 503


def test_fed_watch_writes_nothing_to_the_database(tmp_path):
    from atlas_api.db import DB
    db = DB(str(tmp_path / "w.db"))
    before = {t: db.q(f"SELECT * FROM {t}") for t in [r[0] for r in db.q("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]}
    run(F.FedWatchService(FakeFred(fred_data(NOW.date())), FakeNews(news_pages())).overview(NOW))
    assert {t: db.q(f"SELECT * FROM {t}") for t in before} == before


# --- review fixes: portable dates, schedule end, announcement vs effective dates ----------------------------------------------------------
def test_meeting_labels_are_portable_and_have_no_leading_zeros():
    assert F.meeting_label(D(2026, 10, 27), D(2026, 10, 28)) == "FOMC meeting Oct 27–28, 2026"
    assert F.meeting_label(D(2026, 3, 3), D(2026, 3, 4)) == "FOMC meeting Mar 3–4, 2026"
    assert F.meeting_label(D(2026, 6, 30), D(2026, 7, 1)) == "FOMC meeting Jun 30–Jul 1, 2026"
    labels = {e["meeting"] for e in F.scheduled_events(datetime(2024, 1, 1, tzinfo=timezone.utc), 100)}
    assert "FOMC meeting Jan 28–29, 2025" in labels and not any(re.search(r"\b0\d", x) for x in labels)


def test_no_platform_specific_strftime_codes_anywhere_in_the_backend():
    bad = []
    for f in pathlib.Path(F.__file__).parent.rglob("*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r"%-[a-zA-Z]|%#[a-zA-Z]|:%-[a-zA-Z]|:%#[a-zA-Z]", line):
                bad.append(f"{f.name}:{i}")
    assert bad == []                                                                                 # %-d / %#d work on only one operating system


def test_schedule_end_shows_needs_updating_and_never_invents_meetings():
    before = F.calendar_status(datetime(2026, 11, 1, tzinfo=timezone.utc))
    assert before["needs_update"] is False and before["message"] is None
    for when in (datetime(2026, 12, 9, 19, 1, tzinfo=timezone.utc), datetime(2026, 12, 20, tzinfo=timezone.utc), datetime(2027, 3, 1, tzinfo=timezone.utc)):
        c = F.calendar_status(when)                                                                 # right after the last decision, while minutes remain, and later
        assert c["needs_update"] is True and "Schedule needs updating" in c["message"] and c["link"] == F.LINKS["fomc_calendar"] and "Dec 9, 2026" in c["message"]
    last = max(e for _, e, _ in F.MEETINGS)
    late = F.scheduled_events(datetime(2027, 3, 1, tzinfo=timezone.utc))
    assert late == []                                                                               # nothing after the table, nothing made up
    ends = {datetime.fromisoformat(e["at_utc"]).date() for e in F.scheduled_events(datetime(2024, 1, 1, tzinfo=timezone.utc), 1000)}
    assert max(ends) <= last + timedelta(days=F.RULES["minutes_after_days"] + 1)


def test_overview_carries_the_calendar_status_even_with_no_future_meeting():
    svc = F.FedWatchService(FakeFred(fred_data(NOW.date())), FakeNews(news_pages()))
    o = run(svc.overview(datetime(2027, 3, 1, 12, tzinfo=timezone.utc)))
    assert o["upcoming"] == [] and o["calendar"]["needs_update"] is True and o["decisions"]
    assert run(F.FedWatchService(FakeFred(fred_data(NOW.date())), FakeNews(news_pages())).overview(NOW))["calendar"]["needs_update"] is False


def test_decision_announcement_is_kept_apart_from_the_fred_effective_date():
    lo, hi = ranges({D(2026, 3, 19): (3.75, 4.00)})
    cut = F.decision(D(2026, 3, 18), lo, hi)
    assert cut["announced_date"] == "2026-03-18" and cut["announced_utc"] == "2026-03-18T18:00:00+00:00"       # 2:00 pm EDT on the decision day
    assert cut["effective_obs_date"] == "2026-03-19" and cut["effective_obs_date"] != cut["announced_date"]
    assert cut["previous"]["obs_date"] == "2026-03-17" and cut["new"]["obs_date"] == "2026-03-19"
    assert "EFFECTIVE" in cut["date_note"] and "not the announcement time" in cut["date_note"]
    hold = F.decision(D(2026, 4, 29), lo, hi)
    assert hold["effective_obs_date"] is None and hold["announced_date"] == "2026-04-29"
    assert F.decision(D(2025, 10, 28), lo, hi).get("effective_obs_date") is None                  # unavailable decision: no dates implied
