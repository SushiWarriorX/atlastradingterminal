"""NY Fed SOFR: parsed from a real response (fetched 2026-11-08), staleness, failure labelled and never guessed, demo invents nothing, appears in the macro brief."""
import asyncio
from datetime import date

import httpx

from atlas_api import macro_brief as MB
from atlas_api.nyfed import NyFedSofr, parse

REAL = {"refRates": [
    {"effectiveDate": "2026-11-05", "type": "SOFR", "percentRate": 3.92, "percentPercentile1": 3.85, "percentPercentile25": 3.90, "percentPercentile75": 3.97, "percentPercentile99": 4.00, "volumeInBillions": 3256, "revisionIndicator": ""},
    {"effectiveDate": "2026-11-04", "type": "SOFR", "percentRate": 3.94, "percentPercentile1": 3.86, "percentPercentile25": 3.93, "percentPercentile75": 4.00, "percentPercentile99": 4.02, "volumeInBillions": 3207, "revisionIndicator": ""},
    {"effectiveDate": "2026-11-03", "type": "SOFR", "percentRate": 3.97, "percentPercentile1": 3.88, "percentPercentile25": 3.95, "percentPercentile75": 4.03, "percentPercentile99": 4.05, "volumeInBillions": 3260, "revisionIndicator": ""}]}
TODAY = date(2026, 11, 8)


def test_latest_rate_date_and_daily_change_come_from_the_data():
    f = parse(REAL, TODAY)
    assert f["value"] == 3.92 and f["unit"] == "%" and f["obs_date"] == "2026-11-05" and f["freshness"]["state"] == "CURRENT"
    assert f["changes"][0]["value"] == -0.02 and f["changes"][0]["ref_date"] == "2026-11-04" and f["percentiles"]["99"] == 4.00


def test_an_old_reading_is_overdue_not_current():
    assert parse(REAL, date(2026, 11, 20))["freshness"]["state"] == "OVERDUE"


def test_bad_rows_are_dropped_and_no_rows_raises():
    assert parse({"refRates": [{"type": "SOFR", "effectiveDate": "x", "percentRate": "?"}, {"type": "EFFR", "effectiveDate": "2026-11-05", "percentRate": 3.9}, REAL["refRates"][0]]}, TODAY)["value"] == 3.92
    try:
        parse({"refRates": []}, TODAY)
        assert False
    except ValueError:
        pass


def go(handler, demo=False):
    return asyncio.run(NyFedSofr(httpx.AsyncClient(transport=httpx.MockTransport(handler)), demo).fact(TODAY))


def test_failure_gives_an_error_row_with_no_value():
    for h in (lambda r: httpx.Response(503), lambda r: httpx.Response(200, json={"refRates": []}), lambda r: (_ for _ in ()).throw(httpx.ConnectError("x"))):
        f = go(h)
        assert "error" in f and "value" not in f and "NY Fed" in f["error"]


def test_demo_mode_invents_nothing():
    f = go(lambda r: httpx.Response(200, json=REAL), demo=True)
    assert "error" in f and "value" not in f


def test_it_is_in_the_macro_brief_indicator_order_next_to_the_fed_rate():
    assert MB.INDICATOR_ORDER.index("sofr") == MB.INDICATOR_ORDER.index("fed") + 1
    out = MB.indicators({"facts": []}, {"releases": [parse(REAL, TODAY)]})
    s = next(i for i in out if i["id"] == "sofr")
    assert s["available"] and s["value"] == 3.92 and s["obs_date"] == "2026-11-05" and s["change"]["value"] == -0.02
