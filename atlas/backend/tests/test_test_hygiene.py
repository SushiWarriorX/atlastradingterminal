"""A test that cannot fail is not a test. Placeholders of this kind found their way into assertions three times (an `or True` that made an assertion pass whatever happened, a conditional on a constant, a string cut to nothing with `[:0]`), twice in tests written in a hurry and caught only by reading them before a breakage run. This file refuses them in every test file, so the next one fails here instead of passing in silence."""
import re
from pathlib import Path

TESTS = Path(__file__).parent
PATTERNS = (
    ("an assertion that ends in `or True`, which passes whatever happens", re.compile(r"\bor True\b")),
    ("a conditional on a constant (`if False else`), whose first branch never runs", re.compile(r"\bif False else\b")),
    ("an expression that falls back to `else True`, which passes whatever happens", re.compile(r"\belse True\b")),
    ("a string cut to nothing with `[:0]`", re.compile(r"\[:0\]")),
    ("`assert True`", re.compile(r"\bassert True\b")),
)


def findings(text: str) -> list[tuple[int, str]]:
    """(line number, what is wrong) for every line of `text` that holds one of the placeholders."""
    return [(n, what) for n, line in enumerate(text.split("\n"), 1) for what, pattern in PATTERNS if pattern.search(line)]


def test_no_test_holds_a_placeholder_that_makes_it_pass_whatever_happens():
    found = []
    for path in sorted(TESTS.glob("test_*.py")):
        if path.name != Path(__file__).name:                                                                   # this file spells the patterns out
            found += [f"{path.name}:{n}: {what}" for n, what in findings(path.read_text(encoding="utf-8"))]
    assert found == []


def test_the_patterns_find_what_they_are_meant_to_find_and_nothing_else():
    bad = "assert x or True\nassert y == 1 if False else True\nname = a[:0] + b\nassert True\nz = 5 if flag else True\nfine = 1\n"
    assert findings(bad) == [(1, PATTERNS[0][0]), (2, PATTERNS[1][0]), (2, PATTERNS[2][0]), (3, PATTERNS[3][0]), (4, PATTERNS[4][0]), (5, PATTERNS[2][0])]
    good = 'assert x or y\nassert "True" in text\nok = True if flag else False\nrows = a[:10]\nassert (x is True) == y\nvalue = 1 if flag else None\n'
    assert findings(good) == []
