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
from atlas_api.failreason import MAX_TEXT, fail_reason

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
