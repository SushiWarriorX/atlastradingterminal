"""Deterministic, CONSERVATIVE symbol tagging of headlines.

Only unambiguous forms tag a symbol: a cashtag ($TSLA), an exchange-qualified ticker ((NASDAQ: TSLA)), or the words Bitcoin/BTC. A bare
uppercase word is never treated as a ticker (ALL, NOW, CAT, A, IT are all real tickers and ordinary words). Missing a tag is acceptable;
a wrong tag is not. A symbol-specific feed adds its own symbol explicitly (see service). Tags are NOT relevance or sentiment.
"""
from __future__ import annotations

import re

CASHTAG = re.compile(r"(?<![A-Za-z0-9$])\$([A-Z]{1,5})(?![A-Za-z0-9])")
EXCHANGE = re.compile(r"\((?:NASDAQ|NYSE|NYSE ARCA|NYSEARCA|NYSE American|AMEX|CBOE)\s*:\s*([A-Z]{1,5}(?:\.[A-Z])?)\)")
BITCOIN = re.compile(r"\b(?:Bitcoin|BTC)\b")


def tag(title: str, summary: str = "") -> list[str]:
    text = f"{title} {summary}"
    found: list[str] = []
    for rx in (CASHTAG, EXCHANGE):
        for m in rx.finditer(text):
            if m.group(1) not in found:
                found.append(m.group(1))
    if BITCOIN.search(title) and "BTC" not in found:     # headline only: a passing mention in a summary is not about Bitcoin
        found.append("BTC")
    return found[:6]
