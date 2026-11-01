import pytest

from atlas_api import commands


@pytest.mark.parametrize("text,view", [
    ("BTC", "btc"), ("BTC MTF", "btc"), ("AAPL", "equities"), ("SPY", "equities"), ("NVDA MTF", "equities"),
    ("SPX", "overview"), ("VIX", "overview"), ("SPX MTF", "overview"), ("US10Y", "overview"), ("AAPL CHART", "equities"), ("BTC CHART", "btc"),
])
def test_each_instrument_lands_on_its_own_desk(text, view):
    c = commands.resolve(text)
    assert c.ok and c.view == view


def test_removed_sections_are_gone_from_the_command_surface():
    for text in ("MARKETS", "FUNDAMENTALS", "FA", "AAPL FA"):
        c = commands.resolve(text)
        assert not (c.ok and c.view in ("markets", "fundamentals")), text
    assert "markets" not in commands.VIEWS and "fundamentals" not in commands.VIEWS


@pytest.mark.parametrize("text", ["CHARTS", "PORT", "PORTFOLIO", "RISK", "ALERTS", "ALERT BTC ABOVE 70000", "BUY AAPL 10", "SELL BTC 0.1 STOP 68000", "IDEAS", "BUY", "ALERT"])
def test_removed_sections_give_a_clear_message_not_a_fake_ticker(text):
    c = commands.resolve(text)
    assert not c.ok and "removed from ATLAS" in c.error and c.view is None


def test_removed_sections_are_not_views_or_suggestions():
    for v in ("portfolio", "risk", "alerts", "ideas", "charts", "ai"):
        assert v not in commands.VIEWS
    assert not any(w in commands.ALL_WORDS for w in ("BUY", "SELL", "ALERT", "PORT", "RISK"))


def test_ai_and_compare_commands_open_the_overview_panels_with_their_parameters():
    brief = commands.resolve("AI BTC")
    assert brief.ok and brief.view == "overview" and brief.params == {"brief": True} and brief.instrument_ids
    ask = commands.resolve("why is bitcoin moving today and what changed")
    assert ask.ok and ask.view == "overview" and ask.params["ask"].startswith("why is bitcoin")
    cmp = commands.resolve("COMPARE BTC QQQ")
    assert cmp.ok and cmp.view == "overview" and len(cmp.params["compare"]) == 2
    assert commands.resolve("AI").view == "overview"
