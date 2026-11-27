"""btcquant second-source check: the stored Coinbase daily Bitcoin candles against Hyperliquid's BTC perpetual daily candles (read-only; the real sample was fetched 2026-11-18 07:3x UTC: the venue's last 60 daily candles and the stored file's matching 59)."""
import gzip
import hashlib
import inspect
import json
import re
import subprocess
import sys
import time
import zlib
from pathlib import Path

import httpx
import pytest

from atlas_api.btcquant import crosscheck as X
from atlas_api.btcquant import data as D

DAY = 86400
T0 = 19_700 * DAY                                                      # a UTC midnight
F = json.loads((Path(__file__).parent / "fixtures" / "hyperliquid_btc_1d.json").read_text())
URL = "https://api.hyperliquid.xyz/info"


def candles(closes, start=0):
    return [(T0 + (start + i) * DAY, c, c, c, c, 1.0) for i, c in enumerate(closes)]


def test_the_closes_are_compared_day_by_day_and_the_numbers_are_the_ones_worked_out_by_hand():
    r = X.compare(candles([100.0, 200.0, 100.0, 200.0, 100.0]), candles([101.0, 200.0, 99.0, 202.0, 100.0]))        # differences +1, 0, -1, +1, 0 percent of the stored close
    assert (r["n_days"], r["only_in_stored"], r["only_in_other"]) == (5, 0, 0)
    assert (r["first_day"], r["last_day"]) == ("2023-12-09", "2023-12-13")                                            # day 19,700 since 1970 is 2023-12-09
    assert (r["median_abs_pct"], r["p99_abs_pct"], r["days_over_mid"], r["days_over_big"]) == (1.0, 1.0, 3, 0)
    assert r["largest"] == {"day": "2023-12-09", "diff_pct": 1.0}                                                      # the earliest of the three days that tie
    assert r["newest"] == {"day": "2023-12-13", "stored_close": 100.0, "other_close": 100.0, "diff_pct": 0.0}
    assert r["returns"]["pairs"] == 4 and r["returns"]["same_sign"] == 4 and r["returns"]["correlation"] == 0.99961
    assert r["flags"] == []


def test_a_day_in_only_one_file_is_counted_and_left_out_and_a_gap_breaks_the_returns():
    stored = candles([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])
    other = candles([100.0, 101.0]) + candles([103.0, 104.0, 105.0, 106.0, 107.0], start=3)                           # no day 2; two extra days, 6 and 7
    r = X.compare(stored, other)
    assert (r["n_days"], r["only_in_stored"], r["only_in_other"]) == (5, 1, 2)
    assert r["returns"]["pairs"] == 3                                                                                  # days 0-1, 3-4 and 4-5: the pairs around the missing day are not made


def test_closes_that_agree_give_a_correlation_of_one_and_a_flat_series_gives_none():
    same = X.compare(candles([100.0, 110.0, 99.0, 120.0]), candles([100.0, 110.0, 99.0, 120.0]))
    assert (same["median_abs_pct"], same["largest"]["diff_pct"], same["returns"]["same_sign"]) == (0.0, 0.0, 3) and same["returns"]["correlation"] == 1.0
    flat = X.compare(candles([100.0, 110.0, 99.0, 120.0]), candles([100.0] * 4))
    assert flat["returns"]["correlation"] is None and flat["returns"]["same_sign"] == 0                                   # a venue that never moves has no correlation and agrees on no sign


def test_each_flag_speaks_only_past_its_threshold():
    stored, other = candles([128.0, 128.0, 128.0]), candles([129.0, 128.0, 129.0])                                      # +0.78125 percent: exact in binary, so a threshold can sit exactly on it
    assert X.compare(stored, other, warn_pct=0.78125)["flags"] == []
    r = X.compare(stored, other, warn_pct=0.78124)
    assert r["flags"] == ["the newest common candle (2023-12-11) differs by +0.78%, more than 0.78124%"]
    assert (X.compare(stored, other, mid_pct=0.78125)["days_over_mid"], X.compare(stored, other, mid_pct=0.78124)["days_over_mid"]) == (0, 2)
    assert (X.compare(stored, other, big_pct=0.78125)["days_over_big"], X.compare(stored, other, big_pct=0.78124)["days_over_big"]) == (0, 2)
    assert X.compare(stored, other, big_pct=0.78124)["flags"][0] == "2 day(s) differ by more than 0.78124%: look at them before trusting the file"
    low = X.compare(candles([100.0, 110.0, 99.0, 120.0, 90.0, 130.0]), candles([100.0, 90.0, 110.0, 100.0, 120.0, 100.0]))
    assert low["returns"]["correlation"] == -0.91225 and "the daily returns follow each other less closely than 0.99 (correlation -0.91225)" in low["flags"]
    lows = (candles([100.0, 110.0, 99.0, 120.0, 90.0, 130.0]), candles([100.0, 90.0, 110.0, 100.0, 120.0, 100.0]))
    assert X.compare(*lows, warn_pct=1000, big_pct=1000, min_correlation=-0.92)["flags"] == []                          # only the correlation is under test here
    assert X.compare(*lows, warn_pct=1000, big_pct=1000, min_correlation=-0.9)["flags"] == ["the daily returns follow each other less closely than -0.9 (correlation -0.91225)"]


def test_a_newest_candle_below_the_stored_close_is_flagged_too_and_with_its_sign():
    stored, other = candles([128.0, 128.0, 128.0]), candles([128.0, 128.0, 127.0])                                       # the newest day is -0.78125 percent: exact in binary
    assert X.compare(stored, other, warn_pct=0.78125)["flags"] == []
    assert X.compare(stored, other, warn_pct=0.78124)["flags"] == ["the newest common candle (2023-12-11) differs by -0.78%, more than 0.78124%"]


def test_a_correlation_exactly_at_the_limit_is_not_flagged():
    opposite = (candles([100.0, 200.0, 100.0, 200.0, 100.0]), candles([100.0, 50.0, 100.0, 50.0, 100.0]))               # returns +1, -0.5, +1, -0.5 against -0.5, +1, -0.5, +1: exactly opposite
    r = X.compare(*opposite, warn_pct=1e6, big_pct=1e6, min_correlation=-1.0)
    assert r["returns"]["correlation"] == -1.0 and r["flags"] == []
    assert X.compare(*opposite, warn_pct=1e6, big_pct=1e6, min_correlation=-0.99999)["flags"] == ["the daily returns follow each other less closely than -0.99999 (correlation -1)"]
    assert X.compare(*opposite, warn_pct=1e6, big_pct=1e6, min_correlation=1.0)["flags"] == ["the daily returns follow each other less closely than 1 (correlation -1)"]        # 1, not 1.0


def test_all_three_flags_at_the_default_limits_come_in_a_fixed_order():
    r = X.compare(candles([100.0, 110.0, 99.0, 120.0, 90.0, 130.0]), candles([100.0, 90.0, 110.0, 100.0, 120.0, 80.0]))
    assert r["flags"] == ["the newest common candle (2023-12-14) differs by -38.46%, more than 1%",
                          "5 day(s) differ by more than 2%: look at them before trusting the file",
                          "the daily returns follow each other less closely than 0.99 (correlation -0.9596)"]
    assert (r["days_over_mid"], r["days_over_big"], r["returns"]["same_sign"]) == (5, 5, 0)


def test_the_default_limits_are_the_table_and_the_result_carries_the_limits_it_used():
    assert X.LIMITS == {"mid_pct": 0.5, "big_pct": 2.0, "warn_pct": 1.0, "min_correlation": 0.99}
    sig = inspect.signature(X.compare).parameters
    assert {k: sig[k].default for k in X.LIMITS} == X.LIMITS
    a, b = candles([100.0, 101.0]), candles([100.0, 101.0])
    assert X.compare(a, b)["limits"] == X.LIMITS
    assert X.compare(a, b, mid_pct=0.1, big_pct=0.2, warn_pct=0.3, min_correlation=0.4)["limits"] == {"mid_pct": 0.1, "big_pct": 0.2, "warn_pct": 0.3, "min_correlation": 0.4}


def test_the_99th_percentile_is_the_nearest_rank_of_the_sorted_sizes():
    other = [1001.0] * 150
    other[10], other[20], other[30] = 1002.0, 1003.0, 1030.0                                                              # +0.2, +0.3 and +3 percent among 147 days of +0.1
    r = X.compare(candles([1000.0] * 150), candles(other))
    assert r["median_abs_pct"] == 0.1 and r["p99_abs_pct"] == 0.3                                                          # rank ceil(0.99 * 150) = 149 of 150
    assert r["largest"] == {"day": "2024-01-08", "diff_pct": 3.0} and (r["days_over_mid"], r["days_over_big"]) == (1, 1)    # day 30 since 2023-12-09
    assert r["flags"] == ["1 day(s) differ by more than 2%: look at them before trusting the file"]                         # one day is enough


def test_the_median_of_an_even_number_of_days_is_the_mean_of_the_middle_two():
    r = X.compare(candles([100.0] * 4), candles([101.0, 102.0, 103.0, 104.0]))                                             # differences +1, +2, +3 and +4 percent
    assert r["median_abs_pct"] == 2.5 and r["p99_abs_pct"] == 4.0


def test_candles_are_lined_up_by_utc_day_even_if_one_file_opens_them_late():
    for late_by in (3600, 82800):                                                                                           # 01:00 and 23:00 UTC
        late = [(t + late_by, *rest) for t, *rest in candles([100.0, 101.0, 102.0])]
        r = X.compare(candles([100.0, 101.0, 102.0]), late)
        assert (r["n_days"], r["only_in_stored"], r["only_in_other"], r["returns"]["pairs"]) == (3, 0, 0, 2)


def test_days_are_utc_days_whatever_the_machine_clock_says(monkeypatch):
    monkeypatch.setenv("TZ", "PST8")                                                                                         # eight hours behind UTC: day 19,700 at 00:00 UTC is 16:00 the day before there
    time.tzset()
    try:
        r = X.compare(candles([100.0, 101.0]), candles([100.0, 101.0]))
        assert (r["first_day"], r["last_day"]) == ("2023-12-09", "2023-12-10")
        assert X.compare(candles([128.0]), candles([127.0]), warn_pct=0.1)["flags"] == ["the newest common candle (2023-12-09) differs by -0.78%, more than 0.1%"]
    finally:
        monkeypatch.undo()
        time.tzset()


def test_one_pair_of_returns_has_no_correlation_and_a_day_without_a_move_in_both_files_agrees():
    one = X.compare(candles([100.0, 110.0]), candles([100.0, 111.0]))
    assert one["returns"] == {"pairs": 1, "correlation": None, "same_sign": 1} and one["flags"] == []
    assert X.compare(candles([100.0, 100.0, 110.0]), candles([100.0, 100.0, 111.0]))["returns"]["same_sign"] == 2          # no move in both counts as the same sign


def test_a_close_that_is_not_a_positive_number_is_left_out_and_flagged_instead_of_stopping_the_check():
    base = candles([100.0, 101.0, 102.0, 103.0])
    for bad in (0.0, -5.0, float("nan"), float("inf")):
        r = X.compare(candles([100.0, bad, 102.0, 103.0]), base)
        assert (r["n_days"], r["only_in_stored"], r["only_in_other"], r["bad_in_stored"], r["bad_at_venue"]) == (3, 0, 1, 1, 0)
        assert r["flags"] == ["1 close(s) in the stored file are not a positive number (the first on 2023-12-10): they are left out"] and r["returns"]["pairs"] == 1
    r = X.compare(base, candles([0.0, 101.0, -1.0, 103.0]))
    assert (r["n_days"], r["only_in_stored"], r["only_in_other"], r["bad_at_venue"]) == (2, 2, 0, 2)
    assert r["flags"] == ["2 close(s) at the venue are not a positive number (the first on 2023-12-09): they are left out"]
    newest_first = X.compare(list(reversed(candles([100.0, 0.0, 102.0, 0.0]))), base)                                          # bad days 3 and 1, in that order
    assert newest_first["flags"] == ["2 close(s) in the stored file are not a positive number (the first on 2023-12-10): they are left out"]
    both = X.compare(candles([0.0]), candles([0.0]))
    assert both["flags"] == ["1 close(s) in the stored file are not a positive number (the first on 2023-12-09): they are left out",
                             "1 close(s) at the venue are not a positive number (the first on 2023-12-09): they are left out", "no day is present in both files"]


def test_the_largest_difference_is_the_largest_in_size_whatever_its_sign():
    r = X.compare(candles([100.0, 100.0, 100.0]), candles([100.0, 98.0, 100.5]))                                          # differences 0, -2.0 and +0.5 percent
    assert r["largest"] == {"day": "2023-12-10", "diff_pct": -2.0} and r["median_abs_pct"] == 0.5 and r["p99_abs_pct"] == 2.0
    assert r["days_over_mid"] == 1 and r["days_over_big"] == 0                                                           # 2.0 is not over 2.0


def test_nothing_in_common_says_so_and_has_no_numbers():
    for a, b, only in (([], [], (0, 0)), (candles([100.0, 101.0]), candles([100.0, 101.0], start=5), (2, 2)), (candles([100.0, 101.0, 102.0]), [], (3, 0))):
        r = X.compare(a, b)
        assert r["n_days"] == 0 and r["flags"] == ["no day is present in both files"]
        assert (r["only_in_stored"], r["only_in_other"], r["days_over_mid"], r["days_over_big"], r["bad_in_stored"], r["bad_at_venue"]) == (*only, 0, 0, 0, 0)
        assert all(r[k] is None for k in ("first_day", "last_day", "median_abs_pct", "p99_abs_pct", "largest", "newest", "returns"))
        assert "perpetual" in r["note"]


def test_the_note_says_a_perpetual_is_not_spot_and_what_the_check_is_for():
    note = X.compare(candles([100.0, 101.0]), candles([100.0, 101.0]))["note"]
    assert "perpetual future, not spot" in note and "WRONG" in note and "not a proof of either price" in note
    for phrase in ("small differences are normal", "larger ones on days of stress are expected", "a bad print, a shifted day, a missing day", "not for a tradable difference"):
        assert phrase in note
    assert X.VENUE == "Hyperliquid BTC perpetual (a perpetual future, not spot)"


def handler_for(rows, seen):
    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=rows)
    return handler


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_candle_snapshot_is_asked_for_and_only_complete_candles_come_back():
    seen = []
    start, end = F["stored"][0][0], 1795_000_000
    now_early = 1794_970_000                                                                                              # the venue's newest candle (open 2026-11-18 00:00 UTC) is still open
    c = client_for(handler_for(F["venue"], seen))
    out = X.fetch(c, start, end, now=now_early)
    req = seen[0]
    assert req.method == "POST" and str(req.url) == URL and req.headers["user-agent"] == "ATLAS research terminal"
    assert json.loads(req.content) == {"type": "candleSnapshot", "req": {"coin": "BTC", "interval": "1d", "startTime": start * 1000, "endTime": end * 1000}}
    assert len(out) == 59 and out[0][0] == 1789862400 and out[-1][0] == 1794873600                                        # 2026-09-20 to 2026-11-17: the open 2026-11-18 candle is dropped
    first = F["venue"][0]
    assert out[0] == (1789862400, float(first["o"]), float(first["h"]), float(first["l"]), float(first["c"]), float(first["v"]))
    assert len(X.fetch(client_for(handler_for(F["venue"], [])), start, end, now=1794960000 + DAY)) == 60                   # a day later it is complete


@pytest.mark.parametrize("handler, words", [
    (lambda req: httpx.Response(503), "answered HTTP 503"),
    (lambda req: httpx.Response(429), "answered HTTP 429"),
    (lambda req: httpx.Response(204), "answered HTTP 204"),
    (lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("")), "could not be reached (the request timed out)"),
    (lambda req: (_ for _ in ()).throw(httpx.ConnectError("")), "could not be reached (the connection could not be made)"),
    (lambda req: httpx.Response(200, json={"error": "x"}), "did not send a list of candles"),
    (lambda req: httpx.Response(200, text="not json at all"), "did not send a list of candles"),
    (lambda req: httpx.Response(200, json=[1]), "a candle Hyperliquid sent cannot be read"),
    (lambda req: httpx.Response(200, json=[{"t": 1, "o": "1", "h": "1", "l": "1", "v": "1"}]), "a candle Hyperliquid sent cannot be read"),
    (lambda req: httpx.Response(200, json=[{"t": 1, "o": "x", "h": "1", "l": "1", "c": "1", "v": "1"}]), "a candle Hyperliquid sent cannot be read"),
    (lambda req: httpx.Response(200, json=[F["venue"][0]] * 5000), "5,000 candles, the most one request gives"),
])
def test_a_failure_of_the_venue_is_said_in_plain_words(handler, words):
    with pytest.raises(X.CrosscheckError, match=re.escape(words)):
        X.fetch(client_for(handler), 0, 10, now=10**10)


def test_without_a_now_the_machine_clock_decides_which_candles_are_complete(monkeypatch):
    c, start, end = client_for(handler_for(F["venue"], [])), F["stored"][0][0], 1795_000_000
    monkeypatch.setattr(X.D, "now_utc", lambda: 1794970000)                                                               # the venue's candle of 18 Nov is still open
    assert len(X.fetch(c, start, end)) == 59
    monkeypatch.setattr(X.D, "now_utc", lambda: 1794960000 + DAY)                                                         # a day later it is complete
    assert len(X.fetch(c, start, end)) == 60


def test_an_empty_answer_is_no_candles_and_one_row_short_of_the_limit_is_still_read():
    assert X.fetch(client_for(handler_for([], [])), 0, 10, now=10**10) == []
    rows = [{**F["venue"][0], "t": F["venue"][0]["t"] + i * 86_400_000} for i in range(4999)]
    out = X.fetch(client_for(handler_for(rows, [])), 0, 10, now=10**10)
    assert len(out) == 4999 and all(type(c[0]) is int for c in out) and out[1][0] - out[0][0] == DAY                          # whole seconds, not 1000 times too many or a float


def test_the_client_the_command_makes_waits_30_seconds():
    c = X._client()
    try:
        assert c.timeout == httpx.Timeout(30)
    finally:
        c.close()


def stored_file(tmp_path, rows=None):
    p = tmp_path / "btcusd_1d.csv"
    D.save(p, [tuple(c) for c in (rows if rows is not None else F["stored"])])
    return p


def test_a_run_reads_the_stored_file_asks_the_venue_for_its_range_and_writes_nothing(tmp_path):
    p = stored_file(tmp_path)
    before = (hashlib.sha256(p.read_bytes()).hexdigest(), sorted(x.name for x in tmp_path.iterdir()), p.stat().st_mtime_ns)
    seen = []
    r = X.check(p, client_for(handler_for(F["venue"], seen)), now=1794970000)
    assert json.loads(seen[0].content)["req"]["startTime"] == F["stored"][0][0] * 1000 and json.loads(seen[0].content)["req"]["endTime"] == 1794970000 * 1000
    assert r["n_days"] == 59 and r["stored_file"] == str(p) and r["venue"].startswith("Hyperliquid BTC perpetual")
    assert (hashlib.sha256(p.read_bytes()).hexdigest(), sorted(x.name for x in tmp_path.iterdir()), p.stat().st_mtime_ns) == before          # not a byte, not a file, not a timestamp changed


def test_a_client_that_was_given_stays_open_and_one_the_command_made_is_closed(tmp_path, monkeypatch):
    p = stored_file(tmp_path)
    given = client_for(handler_for(F["venue"], []))
    X.check(p, given, now=1794970000)
    assert given.is_closed is False                                                                                       # the caller's client is the caller's to close
    made = []
    monkeypatch.setattr(X, "_client", lambda: made.append(client_for(handler_for(F["venue"], []))) or made[-1])
    X.check(p, now=1794970000)
    assert len(made) == 1 and made[0].is_closed is True


def test_the_given_clock_decides_which_venue_candles_are_complete_not_the_machine(tmp_path):
    p, c = stored_file(tmp_path), client_for(handler_for(F["venue"], []))
    assert X.check(p, c, now=1794970000)["only_in_other"] == 0                                                            # 2026-11-18 02:46 UTC: the venue's candle of that day is still open
    assert X.check(p, c, now=4_000_000_000)["only_in_other"] == 1                                                         # in the year 2096 it is complete
    past = X.check(p, c, now=1794873600 + 3600)                                                                           # 2026-11-17 01:00 UTC: the venue's 17 Nov candle is still open
    assert (past["n_days"], past["only_in_stored"]) == (58, 1)


def test_without_a_file_given_the_daily_file_of_the_data_module_is_read(tmp_path, monkeypatch):
    p = stored_file(tmp_path)
    monkeypatch.setattr(D, "daily_path", lambda: p)
    r = X.check(None, client_for(handler_for(F["venue"], [])), now=1794970000)
    assert r["stored_file"] == str(p) and r["n_days"] == 59
    assert X.check("", client_for(handler_for(F["venue"], [])), now=1794970000)["stored_file"] == str(p)                    # an empty --file is no file given


def test_the_client_the_command_made_is_closed_when_the_venue_fails_too(tmp_path, monkeypatch):
    made = []
    monkeypatch.setattr(X, "_client", lambda: made.append(client_for(lambda req: httpx.Response(503))) or made[-1])
    with pytest.raises(X.CrosscheckError, match="answered HTTP 503"):
        X.check(stored_file(tmp_path), now=1794970000)
    assert len(made) == 1 and made[0].is_closed is True


@pytest.mark.parametrize("make", [
    lambda p: p.write_text("time,price\n1,2\n"),
    lambda p: p.write_text(",".join(D.HEADER) + "\n1,2,3\n"),
    lambda p: p.write_text(",".join(D.HEADER) + "\n1,x,3,4,5,6\n"),
    lambda p: p.write_bytes(b"\xff\xfe\x00"),
])
def test_a_stored_file_that_cannot_be_read_is_said_in_words(tmp_path, make):
    p = tmp_path / "a.csv"
    make(p)
    with pytest.raises(X.CrosscheckError, match=r"^the stored file cannot be read: (the candle file has an unexpected header|a row or the file itself is damaged)$"):
        X.check(p, client_for(handler_for([], [])), now=10**10)


@pytest.mark.parametrize("raw", [b"not gzip at all", gzip.compress(b"x" * 400, mtime=0)[:20], gzip.compress(b"x" * 400, mtime=0)[:10] + b"\xff" * 8 + gzip.compress(b"x" * 400, mtime=0)[18:]])
def test_a_damaged_compressed_file_and_a_folder_are_said_in_words(tmp_path, raw):
    p = tmp_path / "a.csv.gz"
    p.write_bytes(raw)
    for path in (p, tmp_path):
        with pytest.raises(X.CrosscheckError, match="^the stored file cannot be read: a row or the file itself is damaged$"):
            X.check(path, client_for(handler_for([], [])), now=10**10)


def test_the_header_message_is_the_one_the_data_module_gives(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("time,price\n1,2\n")
    with pytest.raises(X.CrosscheckError) as e:
        X.check(p, client_for(handler_for([], [])), now=10**10)
    assert str(e.value) == "the stored file cannot be read: the candle file has an unexpected header"


def test_a_missing_or_empty_stored_file_is_said_plainly(tmp_path):
    with pytest.raises(X.CrosscheckError, match="no stored candles at"):
        X.check(tmp_path / "nothing.csv", client_for(handler_for([], [])), now=10**10)
    with pytest.raises(X.CrosscheckError, match="no stored candles at"):
        X.check(stored_file(tmp_path, rows=[]), client_for(handler_for([], [])), now=10**10)


def test_the_real_candles_of_both_venues_agree_as_worked_out_in_plain_python():
    start, end = F["stored"][0][0], 1795_000_000
    other = X.fetch(client_for(handler_for(F["venue"], [])), start, end, now=1794970000)
    r = X.compare([tuple(c) for c in F["stored"]], other)
    assert (r["n_days"], r["only_in_stored"], r["only_in_other"], r["first_day"], r["last_day"]) == (59, 0, 0, "2026-09-20", "2026-11-17")
    assert (r["median_abs_pct"], r["p99_abs_pct"], r["days_over_mid"], r["days_over_big"]) == (0.069, 0.214, 0, 0)
    assert r["largest"] == {"day": "2026-10-29", "diff_pct": 0.214}
    assert r["returns"] == {"pairs": 58, "correlation": 0.99982, "same_sign": 57}
    assert r["newest"] == {"day": "2026-11-17", "stored_close": 64873.18, "other_close": 64922.0, "diff_pct": 0.075}
    assert r["flags"] == []


def test_the_summary_is_plain_and_the_command_never_fails_the_run_over_a_flag(tmp_path, capsys, monkeypatch):
    p = stored_file(tmp_path)
    monkeypatch.setattr(X, "_client", lambda: client_for(handler_for(F["venue"], [])))
    monkeypatch.setattr(X.D, "now_utc", lambda: 1794970000)
    assert X.main(["--file", str(p)]) == 0
    text = capsys.readouterr().out
    assert text == "\n".join([
        "Second-source check of the stored Bitcoin daily candles (read-only: nothing is written)",
        f"Stored file: {p}; other venue: Hyperliquid BTC perpetual (a perpetual future, not spot)",
        "59 days in both files, 2026-09-20 to 2026-11-17 (0 only in the stored file, 0 only at the venue).",
        "Close difference (venue against stored): median 0.069%, 99% of days within 0.214%, largest +0.214% on 2026-10-29; 0 days over 0.5%, 0 over 2%.",
        "Daily returns: 58 pairs, correlation 0.99982, same sign on 57.",
        "Newest common candle 2026-11-17: stored 64873.18, venue 64922.0 (+0.075%).",
        "No flags.",
        X.NOTE]) + "\n"
    assert X.main(["--file", str(p), "--warn-pct", "0.05"]) == 0                                                           # a flag is printed, not an error
    assert "FLAG: the newest common candle (2026-11-17) differs by +0.08%, more than 0.05%" in capsys.readouterr().out


def test_every_limit_can_be_set_on_the_command_line(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(X, "_client", lambda: client_for(handler_for(F["venue"], [])))
    monkeypatch.setattr(X.D, "now_utc", lambda: 1794970000)
    assert X.main(["--file", str(stored_file(tmp_path)), "--mid-pct", "0.1", "--big-pct", "0.2", "--warn-pct", "0.07", "--min-correlation", "0.9999"]) == 0
    lines = capsys.readouterr().out.split("\n")
    assert "18 days over 0.1%, 2 over 0.2%." in lines[3]                                                                      # 18 of the 59 days differ by more than 0.1%, 2 by more than 0.2%
    assert lines[6:9] == ["FLAG: the newest common candle (2026-11-17) differs by +0.08%, more than 0.07%",
                          "FLAG: 2 day(s) differ by more than 0.2%: look at them before trusting the file",
                          "FLAG: the daily returns follow each other less closely than 0.9999 (correlation 0.99982)"]


def test_the_summary_counts_the_days_in_one_file_only_on_the_right_side():
    r = X.compare(candles([100.0, 101.0, 102.0, 103.0]), candles([100.0, 101.0]) + candles([105.0], start=5))                  # days 2 and 3 only in the stored file, day 5 only at the venue
    text = X.describe({**r, "stored_file": "a.csv", "venue": X.VENUE})
    assert "2 days in both files, 2023-12-09 to 2023-12-10 (2 only in the stored file, 1 only at the venue)." in text


def test_the_summary_of_a_run_with_nothing_in_common_and_with_a_flat_venue():
    empty = X.describe({**X.compare([], []), "stored_file": "a.csv", "venue": X.VENUE}).split("\n")
    assert empty[0].startswith("Second-source check of the stored Bitcoin daily candles") and empty[1] == f"Stored file: a.csv; other venue: {X.VENUE}"
    assert empty[2] == "FLAG: no day is present in both files" and len(empty) == 4 and "days in both files" not in "\n".join(empty)
    flat = X.describe({**X.compare(candles([100.0, 110.0, 99.0, 120.0]), candles([100.0] * 4)), "stored_file": "a.csv", "venue": X.VENUE})
    assert "Daily returns: 3 pairs, correlation n/a, same sign on 0." in flat and "largest -16.667% on 2023-12-12" in flat           # 100 against 120 on the last day is the largest, and it is below the stored close


def test_a_failure_prints_the_reason_and_exits_with_two(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(X, "_client", lambda: client_for(lambda req: httpx.Response(503)))
    assert X.main(["--file", str(stored_file(tmp_path))]) == 2
    assert capsys.readouterr().out == "The check could not be made: Hyperliquid answered HTTP 503\n"


def test_the_module_runs_as_a_command_and_exits_with_two_when_the_file_is_missing(tmp_path):
    missing = tmp_path / "none.csv"
    r = subprocess.run([sys.executable, "-m", "atlas_api.btcquant.crosscheck", "--file", str(missing)], cwd=Path(__file__).parent.parent, capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and r.stdout == f"The check could not be made: no stored candles at {missing}\n"
