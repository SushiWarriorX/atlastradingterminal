"""One plain-words reason for a failed fetch or a failed data check, shared by every data provider's "could not be read right now (...)" line.

Why this exists: the providers used to write f"{type(e).__name__}: {str(e)[:80]}". That shows "(ConnectError: )" when the exception carries no message (a dropped connection usually carries none), names library classes a beginner cannot act on, and can echo a request address. Here every network failure becomes one plain sentence that names no library, no address and no raw exception text. The failures our own code raises keep their own plain wording: "HTTP 503" becomes "the server had an error, HTTP 503" (the code stays, for anyone who wants to look it up), and a data check that did not pass says "the data failed a check: <what failed>".
Nothing here retries or hides anything: a failure still shows nothing but this sentence.
"""
from __future__ import annotations

import json
import re

import httpx

_STATUS = re.compile(r"^HTTP (\d{3})$")
_LINK = re.compile(r"https?://\S+")
MAX_TEXT = 110


def _status_words(code: int) -> str:
    if code == 403:
        return f"the server refused the request, HTTP {code}"
    if code == 404:
        return f"the data was not found there, HTTP {code}"
    if code == 429:
        return f"the server is limiting requests, HTTP {code}"
    if 500 <= code <= 599:
        return f"the server had an error, HTTP {code}"
    return f"the server answered HTTP {code}"


def _clean(text: str) -> str:
    """One line, no web addresses, at most MAX_TEXT characters."""
    text = _LINK.sub("(link removed)", " ".join(str(text).split()))
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 1].rstrip() + "…"


def fail_reason(e: BaseException) -> str:
    """The reason for a failure as a sentence that fits inside "(...)": never empty, never ends in a colon, never names a library, never echoes an address from the network layer."""
    if isinstance(e, (httpx.TimeoutException, TimeoutError)):         # on Python 3.11+ (the project's minimum) asyncio.TimeoutError is TimeoutError
        return "the request timed out"
    if isinstance(e, httpx.ProxyError):
        return "the network proxy refused the connection"
    if isinstance(e, httpx.ConnectError):
        return "the connection could not be made"
    if isinstance(e, httpx.RemoteProtocolError):
        return "the server closed the connection without answering"
    if isinstance(e, httpx.HTTPStatusError):
        return _status_words(e.response.status_code)
    if isinstance(e, httpx.TooManyRedirects):
        return "the server redirected the request too many times"
    if isinstance(e, httpx.DecodingError):
        return "the answer could not be decoded"
    if isinstance(e, httpx.TransportError):           # reads, writes and anything else that broke the connection part-way
        return "the connection dropped"
    if isinstance(e, httpx.HTTPError):
        return "the request failed"
    if isinstance(e, json.JSONDecodeError):           # before ValueError: it is one
        return "the answer was not valid JSON"
    if isinstance(e, ValueError):                     # what our own code raises: a bad HTTP status, or a data check that did not pass
        m = _STATUS.match(str(e).strip())
        if m:
            return _status_words(int(m.group(1)))
        msg = _clean(str(e))
        return f"the data failed a check: {msg}" if msg else "the data failed a check"
    if isinstance(e, (KeyError, IndexError, TypeError, AttributeError)):
        return "the answer was not in the expected shape"
    msg = _clean(str(e))
    return f"an unexpected error, {type(e).__name__}" + (f": {msg}" if msg else "")
