"""Plain failure wording for every data provider ("could not be read right now (...)"): each kind of failure gets one plain sentence; a dropped connection no longer reads "(ConnectError: )";
no web address from the network layer is echoed; the codes and the failed checks that our own code raises keep their meaning; and no provider is allowed to go back to printing the raw exception."""
import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from atlas_api import claims as C
from atlas_api import gasoline as G
from atlas_api import oil as O
from atlas_api.failreason import MAX_TEXT, dates_in_words, fail_reason

REQ = httpx.Request("GET", "https://example.test/series?id=X&key=SECRET123")
SECRET = "https://secret.example/?key=SECRET123"
NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


@pytest.mark.parametrize("exc, expected", [
    (httpx.ConnectError(""), "the connection could not be made"),
    (httpx.ConnectError(SECRET), "the connection could not be made"),
    (httpx.ConnectTimeout(""), "the request timed out"),
    (httpx.ReadTimeout(""), "the request timed out"),
    (httpx.WriteTimeout(""), "the request timed out"),
    (httpx.PoolTimeout(""), "the request timed out"),
    (asyncio.TimeoutError(), "the request timed out"),
    (TimeoutError(), "the request timed out"),
    (httpx.ProxyError("403 Forbidden"), "the network proxy refused the connection"),
    (httpx.RemoteProtocolError("Server disconnected without sending a response."), "the server closed the connection without answering"),
    (httpx.ReadError(""), "the connection dropped"),
    (httpx.WriteError(""), "the connection dropped"),
    (httpx.CloseError(""), "the connection dropped"),
    (httpx.LocalProtocolError("x"), "the connection dropped"),
    (httpx.TooManyRedirects("x"), "the server redirected the request too many times"),
    (httpx.DecodingError("x"), "the answer could not be decoded"),
    (httpx.HTTPError("x"), "the request failed"),
    (httpx.HTTPStatusError("boom " + SECRET, request=REQ, response=httpx.Response(503, request=REQ)), "the server had an error, HTTP 503"),
    (json.JSONDecodeError("Expecting value", "", 0), "the answer was not valid JSON"),
    (KeyError("DCOILWTICO"), "the answer was not in the expected shape"),
    (IndexError("list index out of range"), "the answer was not in the expected shape"),
    (TypeError("x"), "the answer was not in the expected shape"),
    (AttributeError("x"), "the answer was not in the expected shape"),
])
def test_each_kind_of_failure_gets_one_plain_sentence(exc, expected):
    assert fail_reason(exc) == expected


@pytest.mark.parametrize("code, expected", [
    (301, "the server answered HTTP 301"), (401, "the server answered HTTP 401"), (418, "the server answered HTTP 418"),
    (403, "the server refused the request, HTTP 403"), (404, "the data was not found there, HTTP 404"), (429, "the server is limiting requests, HTTP 429"),
    (499, "the server answered HTTP 499"), (500, "the server had an error, HTTP 500"), (502, "the server had an error, HTTP 502"),
    (503, "the server had an error, HTTP 503"), (599, "the server had an error, HTTP 599"), (600, "the server answered HTTP 600"),
])
def test_the_http_code_our_providers_raise_keeps_its_number_and_gets_plain_words(code, expected):
    assert fail_reason(ValueError(f"HTTP {code}")) == expected


@pytest.mark.parametrize("message", ["HTTP 503 from the mirror", "http 503", "HTTP 50", "HTTP 5030", "the HTTP 503", "HTTP"])
def test_only_the_exact_status_marker_counts_as_a_status(message):
    assert fail_reason(ValueError(message)) == f"the data failed a check: {message}"


def test_a_failed_data_check_keeps_its_own_words():
    assert fail_reason(ValueError("gasoline moved more than 25% in a week")) == "the data failed a check: gasoline moved more than 25% in a week"
    assert fail_reason(ValueError("")) == "the data failed a check"
    assert fail_reason(ValueError("   \n  ")) == "the data failed a check"


def test_long_check_messages_are_cut_and_addresses_are_removed():
    long = "x" * 300
    r = fail_reason(ValueError(long))
    assert r == "the data failed a check: " + "x" * (MAX_TEXT - 1) + "…"
    exactly = "y" * MAX_TEXT
    assert fail_reason(ValueError(exactly)) == "the data failed a check: " + exactly                     # at the limit: untouched
    r = fail_reason(ValueError(f"bad answer from {SECRET} today"))
    assert "SECRET123" not in r and "https" not in r and r == "the data failed a check: bad answer from (link removed) today"
    assert fail_reason(ValueError("two\nlines   here")) == "the data failed a check: two lines here"


def test_an_unknown_error_names_its_class_and_never_ends_in_a_colon():
    assert fail_reason(RuntimeError("")) == "an unexpected error, RuntimeError"
    assert fail_reason(RuntimeError("boom  \n there")) == "an unexpected error, RuntimeError: boom there"
    assert fail_reason(OSError(SECRET)) == "an unexpected error, OSError: (link removed)"


def test_no_failure_reads_empty_ends_in_a_colon_or_echoes_an_address():
    every = [httpx.ConnectError(""), httpx.ReadTimeout(""), httpx.ConnectError(SECRET), httpx.ProxyError(SECRET), httpx.RemoteProtocolError(SECRET), httpx.ReadError(SECRET),
             httpx.HTTPStatusError(SECRET, request=REQ, response=httpx.Response(500, request=REQ)), ValueError(SECRET), KeyError(SECRET), RuntimeError(SECRET), Exception("")]
    for e in every:
        r = fail_reason(e)
        assert r and not r.rstrip().endswith(":") and "SECRET123" not in r and "http://" not in r and "https://" not in r and "httpx" not in r, (e, r)


# ---- dates in a failed check are written in words (the phone shows this sentence and writes dates in words everywhere else) ----

MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"]


@pytest.mark.parametrize("n, name", list(enumerate(MONTHS, 1)))
def test_every_month_is_named_and_its_year_follows(n, name):
    assert dates_in_words(f"2026-{n:02d}") == f"{name} 2026"
    assert dates_in_words(f"1999-{n:02d}-28") == f"{name} 28, 1999"


@pytest.mark.parametrize("raw, words", [
    ("2026-09", "September 2026"), ("2026-11-23", "November 23, 2026"), ("2026-11-03", "November 3, 2026"), ("2026-11-10", "November 10, 2026"),
    ("2000-01", "January 2000"), ("1999-12", "December 1999"), ("2099-12-31", "December 31, 2099"), ("1900-01-01", "January 1, 1900"),
    ("2028-02-29", "February 29, 2028"), ("2026-02-28", "February 28, 2026"), ("2026-09-30", "September 30, 2026"), ("2026-12-31", "December 31, 2026"),
])
def test_an_iso_month_or_day_is_written_in_words(raw, words):
    assert dates_in_words(raw) == words
    assert dates_in_words(f"in {raw} and again {raw}.") == f"in {words} and again {words}."


@pytest.mark.parametrize("text", [
    "2026-13", "2026-00", "2026-09-31", "2026-02-29", "2026-09-00", "2026-09-32", "2026-04-31", "1899-12", "2100-01", "12026-09", "2026-091", "2026-09-011", "x2026-09", "2026-09x",
    "A-2026-09", "2026-09-", "-2026-09", "2026-9", "2026-9-1", "2026-09-1", "26-09-01", "2026/09/01", "2026-09-01T10:00", "2026-Q3", "JTS2000-12", "3.5-2026-09",
])
def test_a_token_that_is_not_a_real_date_is_left_as_it_is(text):
    assert dates_in_words(text) == text


def test_dates_next_to_punctuation_and_inside_longer_text_are_found():
    assert dates_in_words("from 2000-12 to 2026-09, 3.5 over 1.5 (2026-09).") == "from December 2000 to September 2026, 3.5 over 1.5 (September 2026)."
    assert dates_in_words("2026-09: 2026-10; 2026-11…") == "September 2026: October 2026; November 2026…"
    assert dates_in_words("on 2026-11-23, 2026-11-16 and 2026-11-09") == "on November 23, 2026, November 16, 2026 and November 9, 2026"
    assert dates_in_words("no dates here, 1,500 to 20,000 and 12.5%") == "no dates here, 1,500 to 20,000 and 12.5%"
    assert dates_in_words("") == ""


def test_a_day_is_read_with_its_month_and_a_month_alone_stays_a_month():
    assert dates_in_words("2026-09-01") == "September 1, 2026"                                        # not "September 2026-01"
    assert dates_in_words("2026-09 and 2026-09-01") == "September 2026 and September 1, 2026"


def test_a_failed_check_names_its_dates_in_words_and_changes_nothing_else():
    assert fail_reason(ValueError("private hires of 50,780 thousand in 2026-09 is outside 1,500 to 20,000")) == "the data failed a check: private hires of 50,780 thousand in September 2026 is outside 1,500 to 20,000"
    assert fail_reason(ValueError("there is no WTI crude price near 2026-11-23 to check the gasoline price against")) == "the data failed a check: there is no WTI crude price near November 23, 2026 to check the gasoline price against"
    assert fail_reason(ValueError("no change: 3.5 over 1.5")) == "the data failed a check: no change: 3.5 over 1.5"


def test_an_unexpected_error_names_its_dates_in_words_too():
    assert fail_reason(RuntimeError("bad month 2026-09")) == "an unexpected error, RuntimeError: bad month September 2026"
    assert fail_reason(RuntimeError("")) == "an unexpected error, RuntimeError"


def test_the_message_is_cut_first_and_its_dates_are_written_out_after_so_a_sentence_that_fits_is_never_cut_by_the_longer_wording():
    fits = "x" * 100 + " 2026-09"                                                                      # 108 characters: untouched by the cut, 7 longer in words
    assert len(fits) <= MAX_TEXT and fail_reason(ValueError(fits)) == "the data failed a check: " + "x" * 100 + " September 2026"
    at_limit = "y" * (MAX_TEXT - 8) + " 2026-09"                                                       # exactly 110
    assert len(at_limit) == MAX_TEXT and fail_reason(ValueError(at_limit)) == "the data failed a check: " + "y" * (MAX_TEXT - 8) + " September 2026"
    cut_inside = "x" * 106 + " 2026-09"                                                                # 114: the cut falls inside the date, which is then not a date
    assert fail_reason(ValueError(cut_inside)) == "the data failed a check: " + "x" * 106 + " 20…"
    whole = "x" * 90 + " 2026-09 " + "y" * 30                                                          # 129: the cut keeps the whole date, which is written out
    assert fail_reason(ValueError(whole)) == "the data failed a check: " + "x" * 90 + " September 2026 " + "y" * 10 + "…"


def test_an_unexpected_error_is_cut_first_and_its_dates_are_written_out_after():
    assert fail_reason(RuntimeError("x" * 100 + " 2026-09")) == "an unexpected error, RuntimeError: " + "x" * 100 + " September 2026"
    assert fail_reason(RuntimeError("x" * 106 + " 2026-09")) == "an unexpected error, RuntimeError: " + "x" * 106 + " 20…"


def test_an_http_address_is_removed_whether_it_is_secure_or_not():
    assert fail_reason(ValueError("bad answer from http://plain.example/x?k=1 today")) == "the data failed a check: bad answer from (link removed) today"


def test_the_status_marker_may_have_spaces_or_a_line_break_around_it():
    assert fail_reason(ValueError("  HTTP 503\n")) == "the server had an error, HTTP 503"


def test_the_cut_does_not_leave_a_space_in_front_of_the_ellipsis():
    assert fail_reason(ValueError("x" * (MAX_TEXT - 2) + " " + "z" * 10)) == "the data failed a check: " + "x" * (MAX_TEXT - 2) + "…"


def test_a_date_inside_a_removed_address_is_removed_with_it():
    assert fail_reason(ValueError("see https://example.test/2026-09/x for 2026-09")) == "the data failed a check: see (link removed) for September 2026"


def test_the_http_codes_and_the_other_plain_sentences_are_not_touched_by_the_dates():
    assert fail_reason(ValueError("HTTP 503")) == "the server had an error, HTTP 503"
    assert fail_reason(KeyError("2026-09")) == "the answer was not in the expected shape"
    assert fail_reason(httpx.ConnectError("2026-09")) == "the connection could not be made"


# ---- the providers actually use it (exact wording on the cards) ----

def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _boom(exc):
    def handler(req):
        raise exc
    return handler


@pytest.mark.parametrize("make, name", [(lambda c: O.OilPrices(client=c), "Oil prices"), (lambda c: G.GasolinePrices(client=c), "Gasoline prices"), (lambda c: C.JoblessClaims(client=c), "Jobless claims")])
def test_a_dropped_connection_reads_plainly_on_the_cards(make, name):
    r = asyncio.run(make(_client(_boom(httpx.ConnectError("")))).overview(NOW))
    assert r["available"] is False and r["reason"] == f"{name} could not be read right now (the connection could not be made)"
    r = asyncio.run(make(_client(_boom(httpx.ReadTimeout("")))).overview(NOW))
    assert r["reason"] == f"{name} could not be read right now (the request timed out)"
    r = asyncio.run(make(_client(lambda req: httpx.Response(503))).overview(NOW))
    assert r["reason"] == f"{name} could not be read right now (the server had an error, HTTP 503)"
    assert ": )" not in r["reason"] and "Error" not in r["reason"]


# ---- the guard: no provider may build its failure text from the raw exception again ----

ROOT = Path(__file__).resolve().parents[1] / "atlas_api"


def test_no_provider_prints_the_raw_exception_class_and_message():
    bad = [f"{p.name}:{n}" for p in sorted(ROOT.glob("*.py")) if p.name != "failreason.py" for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)   # failreason.py itself quotes the old pattern in its docstring
           if re.search(r"\{type\(e\)\.__name__\}: \{str\(e\)", line)]
    assert bad == [], f"use fail_reason(e) instead of the raw exception text in: {bad}"


def test_every_module_that_calls_fail_reason_imports_it():
    users = [p for p in sorted(ROOT.glob("*.py")) if p.name != "failreason.py" and "fail_reason(" in p.read_text(encoding="utf-8")]
    assert len(users) >= 25, [p.name for p in users]                                                          # the providers that used to print the raw exception
    missing = [p.name for p in users if not re.search(r"^from \.failreason import .*\bfail_reason\b", p.read_text(encoding="utf-8"), re.M)]
    assert missing == []
