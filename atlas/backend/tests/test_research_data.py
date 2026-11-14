"""Research inputs that are not price (Fear & Greed history, hash-rate history): real trimmed responses as fixtures, hand-checked facts, each way a check can fail, the rule that a failing check returns nothing, and the live fetch with the network mocked. No network."""
import copy
import json
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

from atlas_api.btclab import research_data as R

FX = Path(__file__).parent / "fixtures"
FNG = json.loads((FX / "fng_slice.json").read_text())
HASH = json.loads((FX / "hashrate_slice.json").read_text())
NAS = json.loads((FX / "fred_nasdaq.json").read_text())
TODAY = date(2026, 11, 14)


def label(v):
    return "Extreme Fear" if v <= 25 else "Fear" if v <= 46 else "Neutral" if v <= 54 else "Greed" if v <= 75 else "Extreme Greed"


def synthetic_fng(n=1200, end=TODAY, skip=()):
    """An API-shaped payload (newest first), one row a day, labels from the real bands."""
    from datetime import datetime, timezone
    days = [end - timedelta(days=i) for i in range(n)]
    data = []
    for i, d in enumerate(days):
        if d in skip:
            continue
        v = (i * 7) % 96
        data.append({"value": str(v), "value_classification": label(v), "timestamp": str(int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()))})
    return {"name": "Fear and Greed Index", "data": data, "metadata": {"error": None}}


def real_2024_segment():
    daily, diff = R.parse_hashrate(HASH)
    return [(d, v) for d, v in daily if date(2024, 2, 20) <= d <= date(2024, 4, 30)], diff


# ---- Fear & Greed -----------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_fng_real_slice_parses_oldest_first_and_keeps_the_real_hole():
    rows = R.parse_fng(FNG)
    assert rows[0] == (date(2018, 2, 1), 30, "Fear") and rows[-1] == (date(2026, 11, 14), 13, "Extreme Fear")
    assert [r[0] for r in rows] == sorted(r[0] for r in rows) and len(rows) == 18
    days = {r[0] for r in rows}
    assert date(2024, 10, 25) in days and date(2024, 10, 27) in days and date(2024, 10, 26) not in days          # the real one-day hole is NOT filled
    assert (date(2024, 10, 25), date(2024, 10, 27), 1) in R.fng_gaps(rows)
    assert dict((d, v) for d, v, _ in rows)[date(2026, 11, 13)] == 20 and label(20) == "Extreme Fear"
    assert all(lab == label(v) for _, v, lab in rows)                                                              # the real labels follow the real bands


@pytest.mark.parametrize("change,why", [
    (lambda p: p["data"][3].__setitem__("value", "abc"), "invalid literal"),
    (lambda p: p["data"][3].__setitem__("value", "12.5"), "invalid literal"),
    (lambda p: p["data"][3].__setitem__("value", "101"), "outside 0 to 100"),
    (lambda p: p["data"][3].__setitem__("value", "-1"), "outside 0 to 100"),
    (lambda p: p["data"][3].__setitem__("timestamp", str(int(p["data"][3]["timestamp"]) + 3600)), "00:00 UTC"),
    (lambda p: p["data"][4].__setitem__("timestamp", p["data"][3]["timestamp"]), "appears twice"),
    (lambda p: p["data"][3].__setitem__("value_classification", ""), "label was missing"),
    (lambda p: p["data"][3].pop("value"), "unexpected"),
    (lambda p: p.__setitem__("data", []), "empty"),
    (lambda p: p.pop("data"), "unexpected"),
])
def test_fng_unreadable_data_raises(change, why):
    bad = copy.deepcopy(FNG)
    change(bad)
    with pytest.raises(ValueError, match=why):
        R.parse_fng(bad)
    for junk in (None, "text", [], {"data": None}):
        with pytest.raises(ValueError):
            R.parse_fng(junk)


def test_fng_checks_pass_a_good_series_and_name_each_failure():
    rows = R.parse_fng(synthetic_fng())
    assert R.check_fng(rows, TODAY) == []
    assert any("only 5 days" in p for p in R.check_fng(rows[:5], TODAY))
    swapped = [(d, 20, "Fear") if i == 600 else (d, v, lab) for i, (d, v, lab) in enumerate(rows)]            # a value of 20 labelled Fear while 20s are Extreme Fear elsewhere
    assert any("overlap" in p for p in R.check_fng(swapped, TODAY))
    holed = R.parse_fng(synthetic_fng(skip={TODAY - timedelta(days=k) for k in range(300, 310)}))
    assert any("a gap of 10 days" in p for p in R.check_fng(holed, TODAY))
    small = R.parse_fng(synthetic_fng(skip={TODAY - timedelta(days=k) for k in range(300, 303)}))               # a short hole is tolerated, as in the real history, and stays a hole
    assert R.check_fng(small, TODAY) == [] and R.fng_gaps(small)[0][2] == 3
    assert any("days old" in p for p in R.check_fng(rows, TODAY + timedelta(days=10)))
    real = R.check_fng(R.parse_fng(FNG), None, min_rows=10)
    assert any("a gap of" in p for p in real) and not any("overlap" in p for p in real)                        # the slice is full of holes (it is a slice), its labels are consistent


# ---- hash rate --------------------------------------------------------------------------------------------------------------------------------------------------------------------
def test_hashrate_real_slice_parses_with_the_genesis_zeros_and_the_halving_day():
    daily, diff = R.parse_hashrate(HASH)
    assert daily[0][0] == date(2009, 1, 3) and daily[0][1] == pytest.approx(9273.3, abs=0.1)
    assert [v for d, v in daily if date(2009, 1, 4) <= d <= date(2009, 1, 9)] == [0.0] * 6                    # no block was mined in the first six days after the genesis block
    by = dict(daily)
    assert by[date(2024, 4, 20)] == pytest.approx(642.3e18, rel=0.001)                                           # the April 2024 halving day, as served
    assert diff[0] == (1231006505, 1.0) and [t for t, _ in diff] == sorted(t for t, _ in diff)
    assert daily[-1][0] == date(2026, 11, 14)


def test_hashrate_checks_pass_the_real_2024_slice_and_name_each_failure():
    seg, diff = real_2024_segment()
    assert len(seg) == 71 and R.check_hashrate(seg, diff) == [] and R.check_hashrate(seg, diff, date(2024, 5, 1)) == []
    assert any("days old" in p for p in R.check_hashrate(seg, diff, date(2024, 5, 10)))
    early, _ = R.parse_hashrate(HASH)
    assert R.check_hashrate(early[:12], diff) == []                                                              # the early zero days are real and tolerated
    gone = seg[:30] + seg[31:]
    assert any("a day is missing after" in p for p in R.check_hashrate(gone, diff))
    assert any("not in strictly increasing order" in p for p in R.check_hashrate(list(reversed(seg)), diff))
    spiked = [(d, v * 4 if i == 20 else v) for i, (d, v) in enumerate(seg)]
    assert any("moved more than 2.5x" in p for p in R.check_hashrate(spiked, diff))
    zero = [(d, 0.0 if i == 10 else v) for i, (d, v) in enumerate(seg)]
    assert any("non-positive" in p for p in R.check_hashrate(zero, diff))
    units = [(d, v * 1000) for d, v in seg]                                                                      # a whole series in the wrong unit: no daily jump, but it no longer follows the difficulty
    p = R.check_hashrate(units, diff)
    assert len(p) == 1 and "does not follow the difficulty in 2024" in p[0]


# ---- live fetch (network mocked) -------------------------------------------------------------------------------------------------------------------------------------------------
def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def plain(request):                                                                                              # the rule: a plain client, never a browser disguise
    assert "mozilla" not in request.headers.get("user-agent", "").lower()
    assert not any(h.lower().startswith(("sec-", "x-")) for h in request.headers)


def test_fetch_fng_good_and_failing_paths():
    def ok(request):
        plain(request)
        assert str(request.url) == R.FNG_URL
        return httpx.Response(200, json=synthetic_fng())
    res = R.fetch_fng(client(ok), TODAY)
    assert res["ok"] and res["problems"] == [] and len(res["rows"]) == 1200 and res["last"] == "2026-11-14" and res["gaps"] == []
    stale = R.fetch_fng(client(ok), TODAY + timedelta(days=30))
    assert stale["ok"] is False and stale["rows"] is None and any("days old" in p for p in stale["problems"]) and stale["last"] == "2026-11-14"      # a failing check shows nothing
    short = R.fetch_fng(client(lambda r: httpx.Response(200, json=synthetic_fng(50))), TODAY)
    assert short["ok"] is False and short["rows"] is None
    for handler in (lambda r: httpx.Response(500, text="boom"), lambda r: httpx.Response(403, text="no"), lambda r: httpx.Response(200, text="<html>not json</html>"),
                    lambda r: httpx.Response(200, json={"data": [{"value": "x"}]})):
        bad = R.fetch_fng(client(handler), TODAY)
        assert bad["ok"] is False and bad["rows"] is None and bad["problems"][0].startswith("unavailable")

    def slow(request):
        raise httpx.ReadTimeout("slow", request=request)
    assert R.fetch_fng(client(slow), TODAY)["problems"][0].startswith("unavailable: ReadTimeout")


def test_fetch_hashrate_good_and_failing_paths():
    seg, diff = real_2024_segment()
    from datetime import datetime, timezone
    payload = {"hashrates": [{"timestamp": int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp()), "avgHashrate": v} for d, v in seg],
               "difficulty": [{"time": t, "difficulty": x, "height": 0, "adjustment": 0} for t, x in diff]}

    def ok(request):
        plain(request)
        assert str(request.url) == R.HASHRATE_URL
        return httpx.Response(200, json=payload)
    res = R.fetch_hashrate(client(ok), date(2024, 5, 1))
    assert res["ok"] and len(res["daily"]) == 71 and res["first"] == "2024-02-20" and res["last"] == "2024-04-30" and len(res["difficulty"]) == len(diff)
    stale = R.fetch_hashrate(client(ok), date(2024, 6, 1))
    assert stale["ok"] is False and stale["daily"] is None and stale["difficulty"] is None
    holed = copy.deepcopy(payload)
    del holed["hashrates"][30]
    bad = R.fetch_hashrate(client(lambda r: httpx.Response(200, json=holed)), date(2024, 5, 1))
    assert bad["ok"] is False and bad["daily"] is None and any("a day is missing" in p for p in bad["problems"])
    down = R.fetch_hashrate(client(lambda r: httpx.Response(503, text="down")), date(2024, 5, 1))
    assert down["ok"] is False and down["problems"][0].startswith("unavailable") and down["daily"] is None


# ---- equity index closes (the equity-trend experiment) --------------------------------------------------------------------------------------------------------------------------
def test_index_real_slices_parse_skip_closed_days_and_keep_the_real_gap():
    s = R.parse_index(NAS["sept2001"], "NASDAQCOM")
    assert len(s) == 10 and s[0] == (date(2001, 9, 5), 1759.01) and s[-1] == (date(2001, 9, 24), 1499.4)
    days = {d for d, _ in s}
    assert date(2001, 9, 11) not in days and date(2001, 9, 14) not in days                              # the market was closed: left out, never filled
    assert (date(2001, 9, 17) - date(2001, 9, 10)).days == 7                                              # the real closure is a 7-day gap between closes
    r = R.parse_index(NAS["recent"], "NASDAQCOM")
    assert len(r) == 58 and r[0] == (date(2026, 8, 25), 26151.3) and r[-1] == (date(2026, 11, 13), 25136.27)
    with pytest.raises(ValueError):
        R.parse_index("observation_date,OTHER\n2026-11-13,1\n", "NASDAQCOM")
    with pytest.raises(ValueError):
        R.parse_index("observation_date,NASDAQCOM\n2026-11-13,abc\n", "NASDAQCOM")


def test_index_checks_pass_real_data_and_name_each_failure():
    sept = R.parse_index(NAS["sept2001"], "NASDAQCOM")
    assert R.check_index(sept, None, min_rows=5) == []                                                    # the real 7-day closure is exactly inside the limit
    widened = [(d + timedelta(days=1) if d >= date(2001, 9, 17) else d, v) for d, v in sept]
    assert any("a gap of 8 days after 2001-09-10" in p for p in R.check_index(widened, None, min_rows=5))
    assert any("only 10 closes (need 250)" in p for p in R.check_index(sept, None))
    d0 = date(2026, 1, 5)
    pair = lambda a, b: [(d0, a), (d0 + timedelta(days=1), b)]                                            # noqa: E731
    assert R.check_index(pair(100.0, 125.0), None, min_rows=2) == [] and R.check_index(pair(100.0, 75.0), None, min_rows=2) == []     # exactly 25% either way is allowed
    assert any("more than 25%" in p for p in R.check_index(pair(100.0, 126.0), None, min_rows=2))
    assert any("more than 25%" in p for p in R.check_index(pair(100.0, 74.0), None, min_rows=2))
    assert any("outside 10 to 1e+06" in p for p in R.check_index(pair(5.0, 5.1), None, min_rows=2))
    assert any("outside 10 to 1e+06" in p for p in R.check_index(pair(100.0, 2_000_000.0), None, min_rows=2))
    last = date(2026, 11, 13)
    recent = R.parse_index(NAS["recent"], "NASDAQCOM")
    assert R.check_index(recent, last + timedelta(days=7), min_rows=5) == []                              # 7 days old is allowed (a long weekend plus a holiday) ...
    assert any("8 days old" in p for p in R.check_index(recent, last + timedelta(days=8), min_rows=5))    # ... 8 is not


def test_fetch_index_good_and_failing_paths():
    seen = []

    def ok(request):
        seen.append(request)
        plain(request)
        return httpx.Response(200, text=NAS["recent"])
    res = R.fetch_index("NASDAQCOM", client(ok), date(2026, 11, 14), min_rows=5)
    assert res["ok"] and res["problems"] == [] and len(res["rows"]) == 58 and res["first"] == "2026-08-25" and res["last"] == "2026-11-13"
    assert seen[0].url.params["id"] == "NASDAQCOM" and "cosd" in seen[0].url.params                      # the download is limited to what is needed
    stale = R.fetch_index("NASDAQCOM", client(ok), date(2026, 12, 15), min_rows=5)
    assert stale["ok"] is False and stale["rows"] is None and any("days old" in p for p in stale["problems"])                    # a failing check shows nothing
    short = R.fetch_index("NASDAQCOM", client(ok), date(2026, 11, 14))
    assert short["ok"] is False and short["rows"] is None and any("only 58 closes" in p for p in short["problems"])
    for handler in (lambda r: httpx.Response(500, text="boom"), lambda r: httpx.Response(403, text="no"), lambda r: httpx.Response(200, text="<html>not a csv</html>"),
                    lambda r: httpx.Response(200, text="observation_date,NASDAQCOM\n")):
        bad = R.fetch_index("NASDAQCOM", client(handler), date(2026, 11, 14), min_rows=5)
        assert bad["ok"] is False and bad["rows"] is None and bad["problems"][0].startswith("unavailable")

