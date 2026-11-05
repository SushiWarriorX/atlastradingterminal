"""Macro brief: topic labelling, indicators with honest gaps, upcoming events, 'what matters today', and the route working without a FRED key."""
from datetime import date, datetime, timezone

from fastapi.testclient import TestClient

from atlas_api import macro_brief as B
from atlas_api.app import create_app

NOW = datetime(2026, 3, 17, 15, 0, tzinfo=timezone.utc)
ORDER_WORDS = ("buy now", "sell now", "price target", "you should", "guaranteed")


def facts():
    return {"facts": [
        {"id": "us10y", "label": "US 10-Year Treasury yield", "unit": "%", "value": 4.2, "obs_date": "2026-03-16", "series": "DGS10", "freshness": {"state": "CURRENT"},
         "changes": [{"label": "vs previous observation", "value": 3.0, "unit": "bps"}, {"label": "vs ~1 month earlier", "value": -12.0, "unit": "bps"}]},
        {"id": "core_cpi", "label": "Core CPI", "unit": "% year-over-year", "value": 3.1, "obs_date": "2026-02-01", "series": "CPILFESL", "freshness": {"state": "CURRENT"}, "changes": []},
        {"id": "fed", "label": "Fed funds target range", "unit": "%", "lower": 3.5, "upper": 3.75, "obs_date": "2026-03-16", "freshness": {"state": "CURRENT"}},
        {"id": "usd", "label": "Dollar", "error": "unavailable (DTWEXBGS: no data)"},
    ], "interpretations": [{"id": "inflation", "based_on": ["core_cpi"], "text": "Core CPI is 3.1% year-over-year.", "caveat": "One month is noisy."}]}


def fed():
    return {"releases": [{"id": "payrolls", "label": "Nonfarm payrolls", "unit": "thousand jobs", "value": 150.0, "obs_date": "2026-02-01", "freshness": {"state": "CURRENT"}, "changes": []}],
            "balance_sheet": None, "errors": ["BLS release calendar: unavailable"], "calendar": {"message": None},
            "upcoming": [{"title": "FOMC statement and rate decision", "at_utc": "2026-03-18T18:00:00+00:00", "source": "Fed FOMC calendar", "link": "https://fed.example"},
                         {"title": "Old", "at_utc": "2026-03-01T18:00:00+00:00"}],
            "release_schedule": [{"label": "CPI", "date": "2026-03-17", "at_utc": None}, {"label": "Employment report", "date": "2026-04-03", "at_utc": None}],
            "decisions": [{"outcome": "held", "meeting_end": "2026-01-28", "new": {"lower": 3.5, "upper": 3.75}, "source": "FRED"}]}


def test_topics_label_headlines_and_ignore_unrelated_ones():
    assert B.topic_of("Fed's Powell signals patience on rate cut") == "fed"
    assert B.topic_of("New sanctions hit oil exporters") == "geopolitics"
    assert B.topic_of("Lagarde says ECB will watch inflation") in ("central_banks", "inflation")
    assert B.topic_of("Celebrity chef opens restaurant") is None
    assert B.headline("Wire", "Celebrity chef opens restaurant", None, None) is None


def test_headlines_keep_the_title_verbatim_and_label_the_implication_as_an_interpretation():
    h = B.headline("Wire", "Treasury yields climb ahead of auction", "https://x.example", "2026-03-17T10:00:00+00:00")
    assert h["kind"] == "headline" and h["title"] == "Treasury yields climb ahead of auction" and h["feed"] == "Wire"
    assert "Interpretation" in h["implication_kind"]
    assert not any(w in h["implication"].lower() for w in ORDER_WORDS)


def test_indicators_have_dates_freshness_and_unavailable_ones_say_why():
    ind = {i["id"]: i for i in B.indicators(facts(), fed())}
    assert ind["us10y"]["value"] == 4.2 and ind["us10y"]["obs_date"] == "2026-03-16" and ind["us10y"]["freshness"] == "CURRENT"
    assert ind["us10y"]["change"]["label"].startswith("vs ~1 month")
    assert ind["fed"]["value"] == "3.50–3.75"
    assert ind["usd"]["available"] is False and "DTWEXBGS" in ind["usd"]["reason"]
    assert "payrolls" in ind
    assert list(ind)[0] == "fed"                     # fixed display order


def test_upcoming_is_future_only_sorted_and_sourced():
    ev = B.upcoming(fed(), date(2026, 3, 17))
    assert [e["date"] for e in ev] == ["2026-03-17", "2026-03-18", "2026-04-03"]
    assert all(e["source"] for e in ev)


def test_today_lists_near_events_as_facts_and_rule_notes_as_interpretations():
    out = B.build(facts(), fed(), [], NOW)
    kinds = {t["kind"] for t in out["today"]}
    assert kinds == {"fact", "interpretation"}
    titles = " ".join(t["title"] for t in out["today"])
    assert "CPI release today" in titles and "rates held" in titles
    assert not any(w in titles.lower() for w in ORDER_WORDS)
    assert out["errors"] == ["BLS release calendar: unavailable"]
    assert any("Consensus" in g for g in out["gaps"])


def test_build_dedupes_headlines_and_sorts_newest_first():
    st = [{"feed": "A", "title": "Fed holds rates", "link": None, "published": "2026-03-17T09:00:00+00:00"},
          {"feed": "B", "title": "fed holds rates", "link": None, "published": "2026-03-17T09:01:00+00:00"},
          {"feed": "A", "title": "Tariffs on steel announced", "link": None, "published": "2026-03-17T12:00:00+00:00"},
          {"feed": "A", "title": "Cat video goes viral", "link": None, "published": "2026-03-17T13:00:00+00:00"}]
    h = B.build(facts(), fed(), st, NOW)["headlines"]
    assert [x["title"] for x in h] == ["Tariffs on steel announced", "Fed holds rates"]


def test_route_works_in_demo_mode_without_fred_and_labels_it(tmp_path):
    with TestClient(create_app(db_path=str(tmp_path / "b.db"), demo=True, alert_loop=False, news_loop=False)) as c:
        r = c.get("/api/macro/brief")
        assert r.status_code == 200
        d = r.json()["data"]
        assert d["demo"] is True and d["indicators"] == [] and d["upcoming"] and d["gaps"]
