"""The Macro cards that print their own `Check:` line (nine for the euro area: money, bank lending, consumer prices, unemployment, financial stress, bond yields, GDP, bank interest rates and employment; and US job openings and the US jobs report) say what their checks found once, in that line, with the card's own numbers. The API's `note` beside it says what the source is, how late it comes and that it is not a forecast, names the plain checks in one sentence and points to the Check line: it does not tell the same identities again (found 2026-11-18, reading the GDP card's screenshot: about 8 lines of small print said twice on each card)."""
import ast
import re
from pathlib import Path

import pytest

API = Path(__file__).parent.parent / "atlas_api"
COMPONENTS = Path(__file__).parent.parent.parent / "mobile" / "src" / "components"
CARDS = {"euromoney": "EuroMoneyCard.tsx", "eurolending": "EuroLendingCard.tsx", "eurohicp": "EuroInflationCard.tsx", "eurounemployment": "EuroUnemploymentCard.tsx",
         "eurostress": "EuroStressCard.tsx", "euroyields": "EuroYieldsCard.tsx", "eurogdp": "EuroGdpCard.tsx", "eurobankrates": "EuroBankRatesCard.tsx", "eurostockrates": "EuroStockRatesCard.tsx", "euroemployment": "EuroEmploymentCard.tsx", "jolts": "JoltsCard.tsx", "joltsindustries": "JoltsIndustriesCard.tsx", "usjobs": "UsJobsCard.tsx", "usgdp": "UsGdpCard.tsx", "ushousehold": "UsHouseholdCard.tsx", "usrealspending": "UsRealSpendingCard.tsx", "ustrade": "UsTradeCard.tsx", "joltsflows": "JoltsFlowsCard.tsx", "usinventories": "UsInventoriesCard.tsx", "usconsumercredit": "UsConsumerCreditCard.tsx"}
# sentences that belong to the Check line and must not come back in a note (each was in every note before)
REPEATED = ("not that the figures are right", "not that they are right", "which show the series belong together", "which shows the series belong together", "show the series belong together",
            "two checks that are", "one check that is", "three checks that are", "three checks held", "own arithmetic", "The ECB builds the totals")
PLAIN = {"euromoney": "Plain checks: the units are the ones assumed, no month is missing and no amount or growth rate is outside what the real record allows; the sums and the growth comparison are in the Check line.",
         "eurolending": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the growth rebuilt from the flows are in the Check line.",
         "eurohicp": "Plain checks: the units are the ones assumed, no month is missing and no rate or index is outside what the real record allows; the properties and Eurostat's own sums that held are in the Check line.",
         "eurounemployment": "Plain checks: the units are the ones assumed, no month is missing and no rate or number is outside what the real record allows; the properties and Eurostat's own sums that held are in the Check line.",
         "eurostress": "Plain checks: the units are the ones assumed and no hole is longer than 5 days; the ranges, the properties and the ECB's own sum that held are in the Check line.",
         "euroyields": "Plain checks: the units are the ones assumed and no hole is longer than 8 days; the ranges and the ECB's own sums that held are in the Check line.",
         "eurogdp": "Plain checks: the units are the ones assumed and no quarter is missing; the ranges and the source's own sums that held are in the Check line.",
         "eurobankrates": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the volume sums, the weighted-average identity and the bound on the composites are in the Check line.",
         "eurostockrates": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the ECB's rate and weight components and the totals inside their parts are in the Check line.",
         "euroemployment": "Plain checks: the units are the ones assumed and no quarter is missing; the ranges, the sums and the growth rebuilt from GDP and jobs are in the Check line.",
         "jolts": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the rates rebuilt from the levels are in the Check line.",
         "joltsindustries": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the parts inside their wholes are in the Check line.",
         "usjobs": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the rates rebuilt from the levels are in the Check line.",
         "usgdp": "Plain checks: the units are the ones assumed and no quarter is missing; the ranges, the sums and the contributions rebuilt from the parts are in the Check line.",
         "ushousehold": "Plain checks: the units are the ones assumed and no month or quarter is missing; the ranges, the sums and the comparison of the quarter with its months are in the Check line.",
         "usrealspending": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the monthly moves and the sum of real spending and prices against spending in dollars are in the Check line.",
         "ustrade": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the monthly moves and the six sums (each balance against its exports and imports, and the totals against goods plus services) are in the Check line.",
         "joltsflows": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the quits inside the separations are in the Check line.",
         "usinventories": "Plain checks: the units are the ones assumed and no month is missing; the ranges, the sums and the ratios rebuilt from the levels are in the Check line.",
         "usconsumercredit": "Plain checks: the units are the ones assumed and no month is missing; the ranges and the sum are in the Check line."}
LIMIT = 1100                                                                                                                  # characters: the longest note before was 1,824


def note_of(name):
    """The `note` of a provider's summary, read from its source: a plain string (no f-string), so that no number in it can change under the test."""
    tree = ast.parse((API / f"{name}.py").read_text(encoding="utf-8"))
    found = [v for n in ast.walk(tree) if isinstance(n, ast.Dict) for k, v in zip(n.keys, n.values) if isinstance(k, ast.Constant) and k.value == "note"]
    assert len(found) == 1 and isinstance(found[0], ast.Constant) and isinstance(found[0].value, str), name
    return found[0].value


@pytest.mark.parametrize("name", CARDS)
def test_a_note_does_not_say_its_checks_a_second_time(name):
    note = note_of(name)
    assert [p for p in REPEATED if p in note] == [], name
    assert "Checked:" not in note and "Checked " not in note, name


@pytest.mark.parametrize("name", CARDS)
def test_a_note_names_the_plain_checks_in_one_sentence_and_points_to_the_check_line(name):
    note = note_of(name)
    assert PLAIN[name] in note and note.count("Plain checks:") == 1 and note.count("the Check line") == 1, name


@pytest.mark.parametrize("name", CARDS)
def test_a_note_still_says_what_already_happened_and_is_no_forecast(name):
    note = note_of(name)
    assert re.search(r"This describes [a-z ]+ that already happened: it is not a market signal or a forecast\.$", note) or note.endswith("This describes what already happened: it is not a market signal or a forecast."), name


@pytest.mark.parametrize("name", CARDS)
def test_a_note_is_at_most_1100_characters(name):
    assert len(note_of(name)) <= LIMIT, (name, len(note_of(name)))


@pytest.mark.parametrize("name, card", CARDS.items())
def test_the_card_prints_the_check_line_and_says_it_does_not_prove_the_figures(name, card):
    path = COMPONENTS / card
    if not path.exists():
        pytest.skip("the phone app is not in this checkout")
    text = path.read_text(encoding="utf-8")
    for m in re.finditer(r'from "\.\./lib/(\w+)"', text):                                                                     # a card may keep its wording in a pure helper of the phone app (a unit test covers it there)
        helper = COMPONENTS.parent / "lib" / f"{m.group(1)}.ts"
        if helper.exists():
            text += helper.read_text(encoding="utf-8")
    assert "Check:" in text and re.search(r"not that (the figures|they) are right", text), card                              # the sentence taken out of the note must live on the card


def test_the_notes_keep_what_only_they_say_about_their_source():
    assert "The newest month is provisional and is revised later" in note_of("euromoney") and "The newest month is provisional and is revised later" in note_of("eurolending") and "The newest month is provisional and is revised later" in note_of("eurobankrates")
    assert "flash" in note_of("eurohicp") and "fixed composition" in note_of("eurounemployment") and "changing composition" in note_of("eurostress") and "fitted curve, not a market quote" in note_of("euroyields")
    assert "stopped at Q1 2026" in note_of("eurogdp") and "about 45 days" in note_of("eurogdp") and "about 65 days" in note_of("eurogdp") and "NEW loans and pay on NEW deposits" in note_of("eurobankrates")
    assert "about 45 days" in note_of("euroemployment") and "about 65 days" in note_of("euroemployment") and "usually one quarter behind" in note_of("euroemployment") and "real GDP divided by the persons employed or by the hours they worked" in note_of("euroemployment")
    assert "last business day of the month" in note_of("jolts") and "removed without filling positions" in note_of("jolts") and "payroll employment plus openings" in note_of("jolts") and "preliminary" in note_of("jolts") and "household survey" in note_of("jolts")
    assert "already have on their books" in note_of("eurostockrates") and "An old loan keeps its rate until it is repaid or reset" in note_of("eurostockrates") and "rate component and a weight component" in note_of("eurostockrates") and "The newest month is provisional and is revised later" in note_of("eurostockrates")
    assert "job openings by industry" in note_of("joltsindustries") and "worked out by subtraction and marked as such" in note_of("joltsindustries") and "Smaller samples make industry figures noisier" in note_of("joltsindustries") and "preliminary" in note_of("joltsindustries")
    assert "do not agree month to month" in note_of("usjobs") and "not looking is not unemployed" in note_of("usjobs") and "revised in later releases" in note_of("usjobs") and "private and government" in note_of("usjobs")
    assert "chained 2017 dollars" in note_of("usrealspending") and "taken out" in note_of("usrealspending") and "more or fewer goods and services bought" in note_of("usrealspending") and "revised in later releases" in note_of("usrealspending") and "not a market signal or a forecast" in note_of("usrealspending")
    assert "balance-of-payments basis" in note_of("ustrade") and "A negative balance is a deficit" in note_of("ustrade") and "Goods are physical products" in note_of("ustrade") and "revised in later releases" in note_of("ustrade") and "not a market signal or a forecast" in note_of("ustrade")
    assert "Hires are all additions to the payroll" in note_of("joltsflows") and "the net of a month is hires minus total separations" in note_of("joltsflows") and "only for total nonfarm, the private sector and government" in note_of("joltsflows") and "worked out by subtraction and marked as such" in note_of("joltsflows") and "not a market signal or a forecast" in note_of("joltsflows")
    assert "on the last day of the month" in note_of("usinventories") and "the number of months of sales the shelves hold" in note_of("usinventories") and "not corrected for price changes" in note_of("usinventories") and "goods are piling up faster than they sell" in note_of("usinventories") and "not a market signal or a forecast" in note_of("usinventories")
    assert "owed at the end of the month" in note_of("usconsumercredit") and "mostly credit cards" in note_of("usconsumercredit") and "mortgages, home-equity loans" in note_of("usconsumercredit") and "does not say whether the loans are being repaid" in note_of("usconsumercredit") and "revised from time to time" in note_of("usconsumercredit") and "not a market signal or a forecast" in note_of("usconsumercredit")
    assert "disposable income" in note_of("ushousehold") and "found by subtraction" in note_of("ushousehold") and "not adjusted for inflation" in note_of("ushousehold") and "from the GDP release" in note_of("ushousehold") and "revised in later releases" in note_of("ushousehold")
    assert "counted by what it was spent on" in note_of("usgdp") and "below zero when the country buys more from abroad than it sells" in note_of("usgdp") and "prices held fixed" in note_of("usgdp") and "revised in later releases" in note_of("usgdp")
