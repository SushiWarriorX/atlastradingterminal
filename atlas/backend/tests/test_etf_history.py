"""ETF history from the Nasdaq feed: parsing, completeness, the total-return rebuild by hand, rolled and skipped dividends, checks and correlation. Real trimmed responses (fixture) plus synthetic hand-worked cases; no network."""
import json
from datetime import date
from pathlib import Path

import pytest

from atlas_api.btclab import etf_history as E

FX = json.loads((Path(__file__).parent / "fixtures" / "nasdaq_etf.json").read_text())


def _hist(rows, total=None):
    return {"data": {"totalRecords": len(rows) if total is None else total, "tradesTable": {"rows": rows}}}


def test_real_history_parses_oldest_first_and_matches_the_feeds_total():
    px = E.parse_history(FX["history_SPY"])
    assert len(px) == FX["history_SPY"]["data"]["totalRecords"] and px[0][0] < px[-1][0]
    assert px[-1][0] == date(2026, 11, 13) and all(c > 0 for _, c in px)
    assert E.checks(px)["ok"] is True


def test_incomplete_history_is_refused():
    rows = [{"date": "11/02/2026", "close": "$100.00"}, {"date": "11/03/2026", "close": "101.5"}]
    with pytest.raises(ValueError, match="incomplete"):
        E.parse_history(_hist(rows, total=3))
    with pytest.raises(ValueError, match="no price rows"):
        E.parse_history({"data": {"tradesTable": {"rows": []}}})


def test_bad_rows_are_refused_not_skipped():
    for rows in ([{"date": "11/02/2026", "close": "0"}], [{"date": "11/02/2026", "close": "abc"}], [{"date": "13/45/2026", "close": "1"}],
                 [{"date": "11/02/2026", "close": "1"}, {"date": "11/02/2026", "close": "2"}]):
        with pytest.raises(ValueError):
            E.parse_history(_hist(rows))


def test_real_dividends_parse_and_unavailable_is_none_not_empty():
    d = E.parse_dividends(FX["dividends_TLT"])
    assert len(d) == 5 and d == sorted(d) and d[-1][0] == date(2026, 11, 2) and d[-1][1] == pytest.approx(0.343177)
    assert E.parse_dividends(FX["dividends_SPY_unavailable"]) is None                      # 'not available' is not 'pays none'
    with pytest.raises(ValueError, match="unreviewed"):
        E.parse_dividends({"data": {"dividends": {"rows": [{"type": "Special Cash", "amount": "$1", "exOrEffDate": "01/02/2024"}]}}})


def test_total_return_by_hand():
    px = [(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 101.0), (date(2024, 1, 4), 100.0), (date(2024, 1, 5), 102.0)]
    tri, st = E.total_return_index(px, [(date(2024, 1, 4), 1.0)])
    assert [round(v, 6) for _, v in tri] == [1.0, 1.01, 1.01, round(1.01 * 102 / 100, 6)]          # day 3: (100+1)/101 = 1.0 exactly, then 102/100
    assert st == {"used": 1, "rolled": 0, "skipped_outside": 0}
    # no dividends: the series is just price over the first price
    assert [round(v, 4) for _, v in E.total_return_index(px, None)[0]] == [1.0, 1.01, 1.0, 1.02]


def test_dividend_on_a_non_trading_day_rolls_forward_and_outside_dividends_are_counted_not_used():
    px = [(date(2024, 1, 2), 100.0), (date(2024, 1, 5), 100.0), (date(2024, 1, 8), 100.0)]            # Jan 3 to 4 are not in the data
    tri, st = E.total_return_index(px, [(date(2024, 1, 3), 2.0), (date(2023, 12, 1), 5.0), (date(2025, 1, 1), 5.0), (date(2024, 1, 2), 9.0)])
    assert st == {"used": 1, "rolled": 1, "skipped_outside": 3}                                      # the dividend on the FIRST day cannot be reinvested (no earlier close) and is skipped
    assert [round(v, 4) for _, v in tri] == [1.0, 1.02, 1.02]


def test_checks_flag_a_gap_and_a_jump():
    ok = [(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 101.0)]
    assert E.checks(ok)["ok"] is True
    gap = [(date(2024, 1, 2), 100.0), (date(2024, 1, 20), 101.0)]
    assert E.checks(gap)["ok"] is False and E.checks(gap)["max_gap_days"] == 18
    jump = [(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 50.0)]
    assert E.checks(jump)["ok"] is False


def test_correlation_by_hand():
    a = {date(2024, 1, i): v for i, v in zip((2, 3, 4, 5), (1.0, 2.0, 3.0, 4.0))}
    b = {date(2024, 1, i): v for i, v in zip((2, 3, 4, 5), (2.0, 4.0, 6.0, 8.0))}
    r, n = E.correlation(a, b)
    assert r == pytest.approx(1.0) and n == 4
    c = {k: -v for k, v in b.items()}
    assert E.correlation(a, c)[0] == pytest.approx(-1.0)
    with pytest.raises(ValueError):
        E.correlation(a, {date(2024, 1, 2): 1.0})
    with pytest.raises(ValueError, match="constant"):
        E.correlation(a, {k: 1.0 for k in a})
    ch = E.daily_changes([(date(2024, 1, 2), 100.0), (date(2024, 1, 3), 110.0)])
    assert ch == {date(2024, 1, 3): pytest.approx(0.1)}
