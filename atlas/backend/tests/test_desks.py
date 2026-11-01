import pytest

from atlas_api import commands


@pytest.mark.parametrize("text,view", [
    ("BTC", "btc"), ("BTC MTF", "btc"), ("AAPL", "equities"), ("SPY", "equities"), ("NVDA MTF", "equities"),
    ("SPX", "charts"), ("VIX", "charts"), ("SPX MTF", "charts"), ("US10Y", "charts"),
])
def test_each_instrument_lands_on_its_own_desk(text, view):
    c = commands.resolve(text)
    assert c.ok and c.view == view


def test_removed_sections_are_gone_from_the_command_surface():
    for text in ("MARKETS", "FUNDAMENTALS", "FA", "AAPL FA"):
        c = commands.resolve(text)
        assert not (c.ok and c.view in ("markets", "fundamentals")), text
    assert "markets" not in commands.VIEWS and "fundamentals" not in commands.VIEWS
