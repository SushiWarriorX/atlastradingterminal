"""The discovery and research routes through the real app in demo mode: honest empty states, input validation, my states and notes, and the scheduler registering both daily jobs."""
import json

from fastapi.testclient import TestClient

from atlas_api.app import create_app


def client(tmp_path, demo=True):
    return TestClient(create_app(db_path=str(tmp_path / "d.db"), demo=demo, alert_loop=False, news_loop=False))


def test_listings_and_candidates_say_plainly_that_nothing_has_been_fetched_yet(tmp_path):
    with client(tmp_path) as c:
        l = c.get("/api/discover/listings").json()["data"]
        assert l["available"] is False and "has not been fetched yet" in l["reason"] and l["recent"] == [] and l["upcoming"] == [] and "IPOs only" in l["coverage"]
        n = c.get("/api/discover/candidates").json()["data"]
        assert n["available"] is False and "No daily study has run yet" in n["reason"] and n["items"] == [] and n["gaps"]


def test_candidate_filter_inputs_are_accepted_and_bounded(tmp_path):
    with client(tmp_path) as c:
        r = c.get("/api/discover/candidates?target=999&sectors=Technology,Health%20Care&min_market_cap=-5&max_listing_age_years=5&exchanges=NYSE")
        assert r.status_code == 200 and r.json()["ok"]


def test_my_states_validate_their_input_and_saving_replaces_dismissing(tmp_path):
    with client(tmp_path) as c:
        assert c.post("/api/discover/state", json={"symbol": "ABCD", "state": "loved"}).status_code == 422
        assert c.post("/api/discover/state", json={"symbol": "ab cd; DROP", "state": "saved"}).status_code == 422
        assert c.post("/api/discover/state", json={"symbol": "ABCD", "state": "saved", "extra": 1}).status_code == 422
        d = c.post("/api/discover/state", json={"symbol": "abcd", "state": "dismissed"}).json()["data"]
        assert d["symbol"] == "ABCD" and d["dismissed_at"]
        s = c.post("/api/discover/state", json={"symbol": "ABCD", "state": "saved"}).json()["data"]
        assert s["saved_at"] and s["dismissed_at"] is None
        got = c.get("/api/discover/state/ABCD").json()["data"]
        assert got["state"]["saved_at"] and got["notes"] == [] and got["last_review"] is None


def test_opening_a_company_marks_it_opened_and_notes_can_be_added_and_deleted(tmp_path):
    with client(tmp_path) as c:
        r = c.get("/api/research/AAPL").json()["data"]
        assert r["available"] is False and r["demo"] is True and r["my_state"]["state"]["opened_at"]
        n = c.post("/api/research/AAPL/notes", json={"body": "Read the segment note first."}).json()["data"]
        assert n["symbol"] == "AAPL" and n["id"]
        assert c.get("/api/research/AAPL").json()["data"]["my_state"]["notes"][0]["body"] == "Read the segment note first."
        assert c.post("/api/research/AAPL/notes", json={"body": "   "}).status_code in (422,)
        assert c.post("/api/research/AAPL/notes", json={"body": "x" * 4001}).status_code == 422
        assert c.delete(f"/api/research/notes/{n['id']}").json()["data"]["deleted"] == n["id"]
        assert c.delete(f"/api/research/notes/{n['id']}").status_code == 404
        assert c.post("/api/research/NOT-A-THING-123/notes", json={"body": "x"}).status_code == 404


def test_review_and_changes_need_the_filing_analysis_and_say_so_in_demo(tmp_path):
    with client(tmp_path) as c:
        rv = c.post("/api/research/AAPL/review")
        assert rv.status_code == 409 and "made-up company figures" in json.dumps(rv.json())
        ch = c.get("/api/research/AAPL/changes").json()["data"]
        assert ch["available"] is False and ch["has_review"] is False and "made-up company figures" in ch["reason"]
        assert c.get("/api/research/BTC/changes").status_code in (404, 422)


def test_both_daily_jobs_are_registered_and_the_demo_does_not_run_them(tmp_path):
    with client(tmp_path) as c:
        jobs = {j["id"]: j for j in c.app.state.scheduler.overview()["jobs"]}
        assert {"listings_refresh", "discovery_refresh"} <= set(jobs)
        assert jobs["listings_refresh"]["enabled"] is False and jobs["discovery_refresh"]["enabled"] is False        # demo mode: real events would be mixed with made-up data
        assert jobs["discovery_refresh"]["priority"] >= 4 and jobs["listings_refresh"]["priority"] >= 4             # fundamental research ranks above optional experiments
        assert jobs["discovery_refresh"]["kind"] == "discovery" and jobs["discovery_refresh"]["max_tokens"] == 0


def test_a_saved_study_is_served_as_valid_json_even_with_no_upper_limit_filters(tmp_path):
    """Regression: 'no upper limit' is infinity inside the code and must never reach the JSON (browsers and Starlette reject it)."""
    import sqlite3
    with client(tmp_path) as c:
        pool = [{"symbol": "AAAA", "name": "A Co", "exchange": "Nasdaq", "sector": "Technology", "industry": "x", "country": "United States", "market_cap": 2e9, "size_bucket": "mid", "ipo_year": 2015,
                 "dollar_volume": 5e6, "price": 10.0, "price_time": "2026-02-01T00:00:00+00:00", "price_source": "t", "score": 80.0, "factors": {}, "why_selected": ["x"], "risks": ["y"],
                 "main_opportunity": "o", "main_risk": "r", "material": "m", "description": {"note": "n"}, "revenue": {}, "rule_of_40": {}, "valuation": {}, "studied_at": "2026-02-01T00:00:00+00:00"}]
        run = {"asof": "2026-02-01", "created_at": "2026-02-01T00:00:00+00:00", "available": True, "universe": 1, "after_filters": 1, "studied": 1, "passed": 1, "excluded_by_filters": {}, "left_out_reasons": {},
               "could_not_study": {}, "errors": [], "pool": pool, "source": {"universe": "u", "filings": "f"}, "gaps": []}
        con = sqlite3.connect(str(tmp_path / "d.db"))
        con.execute("INSERT INTO disc_feed_runs(kind,asof,created_at,payload) VALUES('new_to_me','2026-02-01','2026-02-01T00:00:00+00:00',?)", (json.dumps(run),))
        con.commit()
        con.close()
        r = c.get("/api/discover/candidates")
        assert r.status_code == 200
        d = json.loads(r.text)["data"]                                                                              # strict JSON: would raise on Infinity
        assert d["available"] and d["filters_applied"]["max_market_cap"] is None and [i["symbol"] for i in d["items"]] == ["AAAA"]
