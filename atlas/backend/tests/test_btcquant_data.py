"""btcquant data layer: parsing, complete-versus-incomplete candles on a UTC clock, validation (fatal and flagged), 4-hour candles from complete hours, storage, manifest, merging without overwriting,
paging, incremental update, and the refusal cases (HTTP 403 as with Binance here, rate limits, a failed validation that must save nothing)."""
import gzip
import json
from datetime import datetime, timezone

import httpx
import pytest

from atlas_api.btcquant import config as C
from atlas_api.btcquant import data as D

DAY, HOUR = C.DAY, C.HOUR
T0 = int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp())


def bar(t, o=100.0, h=105.0, l=95.0, c=101.0, v=10.0):
    return (t, o, h, l, c, v)


def days(n, start=T0):
    return [bar(start + i * DAY, o=100 + i, h=105 + i, l=95 + i, c=101 + i, v=10 + i) for i in range(n)]


# ---- parsing and the UTC clock ----

def test_coinbase_rows_become_candles_oldest_first_with_the_fields_in_the_right_order():
    rows = [[T0 + DAY, 90.0, 110.0, 100.0, 105.0, 7.0], [T0, 80.0, 100.0, 85.0, 95.0, 5.0]]      # newest first; [time, low, high, open, close, volume]
    assert D.parse_coinbase(rows) == [(T0, 85.0, 100.0, 80.0, 95.0, 5.0), (T0 + DAY, 100.0, 110.0, 90.0, 105.0, 7.0)]
    with pytest.raises(D.DataError, match="5 fields"):
        D.parse_coinbase([[T0, 1, 2, 3, 4]])


def test_a_candle_is_complete_exactly_when_its_open_plus_its_length_is_not_after_now():
    assert D.is_complete(T0, DAY, T0 + DAY) is True                                  # closes at 00:00 the next day, which is now
    assert D.is_complete(T0, DAY, T0 + DAY - 1) is False                             # one second early: still incomplete
    assert D.is_complete(T0, HOUR, T0 + HOUR) and not D.is_complete(T0, HOUR, T0 + HOUR - 1)


def test_the_candle_that_contains_now_is_never_used():
    cs = days(3)
    now = T0 + 2 * DAY + 15 * 60                                                      # 00:15 UTC on the third day, as in the scheduled run
    assert D.complete_only(cs, DAY, now) == cs[:2]


# ---- validation ----

def test_clean_data_passes_and_gaps_are_listed_not_filled():
    assert D.validate(days(5), DAY).ok
    cs = days(5)
    del cs[2:4]                                                                       # two missing days between day 1 and day 4
    rep = D.validate(cs, DAY)
    assert rep.ok and rep.gaps == [(T0 + DAY, T0 + 4 * DAY, 2)]


@pytest.mark.parametrize("mutate, text", [
    (lambda cs: cs.insert(2, cs[1]), "duplicate"),
    (lambda cs: cs.__setitem__(slice(1, 3), [cs[2], cs[1]]), "not in time order"),
    (lambda cs: cs.__setitem__(1, bar(T0 + DAY + 5)), "boundary"),
    (lambda cs: cs.__setitem__(1, bar(T0 + DAY, o=0.0, h=105.0, l=0.0, c=101.0)), "not above zero"),
    (lambda cs: cs.__setitem__(1, bar(T0 + DAY, o=100.0, h=100.5, l=95.0, c=101.0)), "inconsistent"),      # high below the close
    (lambda cs: cs.__setitem__(1, bar(T0 + DAY, o=100.0, h=105.0, l=100.5, c=101.0)), "inconsistent"),     # low above the open
    (lambda cs: cs.__setitem__(1, bar(T0 + DAY, v=-1.0)), "negative volume"),
])
def test_structural_problems_are_fatal(mutate, text):
    cs = days(4)
    mutate(cs)
    rep = D.validate(cs, DAY)
    assert not rep.ok and any(text in f for f in rep.fatal), rep.fatal


def test_a_huge_daily_move_is_flagged_for_review_but_does_not_stop_the_run():
    cs = days(3)
    cs[2] = bar(T0 + 2 * DAY, o=102.0, h=250.0, l=100.0, c=160.0)                    # +58% from the previous close of 102
    rep = D.validate(cs, DAY)
    assert rep.ok and any("+" in f and "check against another source" in f for f in rep.flags)
    assert D.validate(cs, DAY, flag_moves=False).flags == []


# ---- 4-hour candles ----

def hours(start, n):
    return [bar(start + i * HOUR, o=100 + i, h=110 + i, l=90 + i, c=101 + i, v=1.0) for i in range(n)]


def test_four_hour_candles_are_built_only_from_four_complete_aligned_hours():
    base = T0                                                                          # 00:00 UTC
    hs = hours(base, 8)
    out = D.resample_4h(hs)
    assert out == [(base, 100.0, 113.0, 90.0, 104.0, 4.0), (base + 4 * HOUR, 104.0, 117.0, 94.0, 108.0, 4.0)]      # open of the first hour, highest high, lowest low, close of the last hour, summed volume
    assert D.resample_4h(hs[:7]) == out[:1]                                            # the second 4-hour candle has only three hours
    assert D.resample_4h(hs[1:]) == [out[1]]                                           # starts at 01:00: the first group is incomplete and the hours are aligned to 00/04/08...
    gap = hs[:2] + hs[3:]                                                              # 02:00 missing
    assert D.resample_4h(gap) == [out[1]]
    assert D.resample_4h(hs, now=base + 7 * HOUR + 30 * 60) == out[:1]                 # the last hour is not complete yet at 07:30


# ---- storage and the manifest ----

def test_csv_roundtrip_is_exact_and_the_gz_bytes_do_not_depend_on_when_they_were_written(tmp_path):
    cs = [bar(T0, 0.1 + 0.2, 105.123456789, 95.5, 101.0, 12.000000000001), bar(T0 + DAY)]
    assert D.from_csv_bytes(D.to_csv_bytes(cs)) == cs
    a, b = tmp_path / "a.csv.gz", tmp_path / "b.csv.gz"
    D.save(a, cs)
    D.save(b, cs)
    assert a.read_bytes() == b.read_bytes() and D.load(a) == cs
    assert gzip.decompress(a.read_bytes()) == D.to_csv_bytes(cs)
    D.save(tmp_path / "c.csv", cs)
    assert D.load(tmp_path / "c.csv") == cs and D.load(tmp_path / "missing.csv") == []
    with pytest.raises(D.DataError, match="header"):
        D.from_csv_bytes(b"a,b\n1,2\n")


def test_the_manifest_changes_when_any_candle_changes_and_reports_gaps():
    cs = days(5)
    m = D.manifest(cs, DAY, "2024-01-06T00:15:00Z")
    assert m["count"] == 5 and m["first"] == "2024-01-01T00:00:00Z" and m["last"] == "2024-01-05T00:00:00Z" and m["gap_count"] == 0 and m["fatal"] == []
    cs2 = list(cs)
    cs2[3] = bar(cs[3][0], c=cs[3][4] + 0.01)
    assert D.manifest(cs2, DAY)["sha256"] != m["sha256"] and D.manifest(cs, DAY)["sha256"] == m["sha256"]
    del cs[2]
    assert D.manifest(cs, DAY)["gaps"] == [{"from": "2024-01-02T00:00:00Z", "to": "2024-01-04T00:00:00Z", "missing": 1}]


def test_merging_adds_new_candles_but_never_overwrites_and_reports_a_revision():
    stored = days(3)
    fresh = [stored[2], bar(T0 + 3 * DAY)]                                             # one identical, one new
    merged, rev = D.merge(stored, fresh)
    assert [c[0] for c in merged] == [T0 + i * DAY for i in range(4)] and rev == []
    revised = bar(T0 + DAY, o=stored[1][1], h=stored[1][2], l=stored[1][3], c=stored[1][4] * 1.05, v=stored[1][5])    # the provider now shows a close 5% different
    merged, rev = D.merge(stored, [revised])
    assert merged[1] == stored[1] and len(rev) == 1 and "kept the stored copy" in rev[0]
    noise = bar(T0 + DAY, o=stored[1][1], h=stored[1][2], l=stored[1][3], c=stored[1][4] * 1.0001, v=stored[1][5])        # 0.01%: not a revision
    assert D.merge(stored, [noise])[1] == []


# ---- the downloader and the incremental update ----

def make_client(log, status=200, flaky=0):
    def handler(req):
        p = req.url.params
        log.append(dict(p))
        if status != 200:
            return httpx.Response(status)
        if flaky and len([x for x in log if x]) <= flaky:
            return httpx.Response(429)
        g = int(p["granularity"])
        a = int(datetime.fromisoformat(p["start"].replace("Z", "+00:00")).timestamp())
        b = int(datetime.fromisoformat(p["end"].replace("Z", "+00:00")).timestamp())
        rows = [[t, 95.0 + (t // g) % 50, 105.0 + (t // g) % 50, 100.0 + (t // g) % 50, 101.0 + (t // g) % 50, 10.0] for t in range(a, b + 1, g)]
        return httpx.Response(200, json=list(reversed(rows)))
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_the_downloader_pages_300_candles_at_a_time_and_returns_them_in_order():
    log = []
    got = D.Downloader(make_client(log), sleep=0).fetch(DAY, T0, T0 + 699 * DAY)
    assert len(got) == 700 and [c[0] for c in got] == [T0 + i * DAY for i in range(700)] and len(log) == 3
    assert [x["granularity"] for x in log] == ["86400"] * 3 and log[0]["start"] == "2024-01-01T00:00:00Z"
    assert D.validate(got, DAY).ok


def test_http_403_like_binance_here_is_a_plain_data_error(tmp_path):
    with pytest.raises(D.DataError, match="HTTP 403"):
        D.Downloader(make_client([], status=403), sleep=0).fetch(DAY, T0, T0 + DAY)


def test_a_rate_limit_is_retried_and_then_given_up(monkeypatch):
    monkeypatch.setattr(D.time, "sleep", lambda s: None)
    assert len(D.Downloader(make_client([], flaky=2), sleep=0).fetch(DAY, T0, T0 + 2 * DAY)) == 3
    with pytest.raises(D.DataError, match="rate-limiting"):
        D.Downloader(make_client([], flaky=99), sleep=0).fetch(DAY, T0, T0 + 2 * DAY)


def test_update_downloads_only_what_is_missing_stores_complete_candles_only_and_is_repeatable(tmp_path):
    path = tmp_path / "d.csv"
    log = []
    dl = D.Downloader(make_client(log), sleep=0)
    now = T0 + 10 * DAY + 15 * 60                                                       # 00:15 UTC on day 10: day 10 has just begun
    m = D.update(path, DAY, now=now, downloader=dl, start=T0)
    assert m["count"] == 10 and m["last"] == "2024-01-10T00:00:00Z" and m["added"] == 10 and m["fatal"] == []      # days 0 to 9 are complete; day 10 is not stored
    assert [c[0] for c in D.load(path)][-1] == T0 + 9 * DAY
    sha = m["sha256"]
    log.clear()
    m2 = D.update(path, DAY, now=now, downloader=dl, start=T0)                          # nothing new: no fetch needed beyond the next candle, which is incomplete
    assert m2["added"] == 0 and m2["sha256"] == sha
    m3 = D.update(path, DAY, now=T0 + 12 * DAY + 15 * 60, downloader=dl, start=T0)    # two more days complete
    assert m3["added"] == 2 and m3["count"] == 12 and log[0]["start"] == "2024-01-11T00:00:00Z"


def test_a_failed_validation_stops_the_run_and_saves_nothing(tmp_path):
    path = tmp_path / "d.csv"
    D.save(path, days(3))
    before = path.read_bytes()

    class Bad(D.Downloader):
        def fetch(self, interval, start, end):
            return [bar(start, o=100.0, h=90.0, l=95.0, c=101.0)]                      # a high below the open: impossible
    with pytest.raises(D.DataError, match="failed validation"):
        D.update(path, DAY, now=T0 + 10 * DAY, downloader=Bad(), start=T0)
    assert path.read_bytes() == before


def test_an_unreachable_provider_leaves_the_stored_file_untouched(tmp_path):
    path = tmp_path / "d.csv"
    D.save(path, days(3))
    before = path.read_bytes()
    with pytest.raises(D.DataError, match="HTTP 403"):
        D.update(path, DAY, now=T0 + 10 * DAY, downloader=D.Downloader(make_client([], status=403), sleep=0), start=T0)
    assert path.read_bytes() == before


def test_a_manifest_is_recorded_per_file_and_one_does_not_erase_the_other(tmp_path):
    path = tmp_path / "manifest.json"
    D.record_manifest("1d", {"count": 3, "sha256": "aa"}, path)
    D.record_manifest("1h", {"count": 5, "sha256": "bb"}, path)
    D.record_manifest("1d", {"count": 4, "sha256": "cc"}, path)                 # the newer daily manifest replaces the older one
    got = json.loads(path.read_text())
    assert got == {"1d": {"count": 4, "sha256": "cc"}, "1h": {"count": 5, "sha256": "bb"}}


def test_a_damaged_manifest_file_is_replaced_not_trusted(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{not json", encoding="utf-8")
    D.record_manifest("1d", {"count": 1}, path)
    assert json.loads(path.read_text()) == {"1d": {"count": 1}}
    path.write_text("[1, 2, 3]", encoding="utf-8")                              # valid JSON but not a mapping
    D.record_manifest("1h", {"count": 2}, path)
    assert json.loads(path.read_text()) == {"1h": {"count": 2}}
