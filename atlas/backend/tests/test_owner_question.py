"""The question for the owner that the Journey tab shows (`btcquant/owner_question.json`, read by `view.question`): a few plain sentences and the options, text only, written by the loop and answered in the chat. The file is strict so that a typo cannot put a half-built card in front of the owner: every limit below is a literal and is tested at both of its edges, and a file that cannot be used gives ONE plain sentence, never a crash and never a half card. Without a file there is nothing to show and nothing is said."""
import json
from pathlib import Path

import pytest

from atlas_api.btcquant import config as C
from atlas_api.btcquant import view as V

GOOD = {
    "asked_on": "2026-11-17",
    "title": "The Bitcoin research queue is on hold until you choose",
    "paragraphs": ["Three rule ideas are left to test.", "Nothing has been changed while this waits."],
    "options": [{"id": "3", "text": "Stop the daily queue.", "recommended": True}, {"id": "2", "text": "Add data.", "recommended": False}, {"id": "1", "text": "Lower the bar.", "recommended": False}],
    "how_to_answer": "Reply in the chat with 1, 2 or 3.",
}
M_JSON = "owner_question.json cannot be read as JSON, so the question is not shown."
M_OBJECT = "owner_question.json: it must hold one JSON object, so the question is not shown."
M_KEYS = "owner_question.json: it must have exactly the keys asked_on, title, paragraphs, options and how_to_answer, so the question is not shown."
M_DATE = "owner_question.json: asked_on must be a date like 2026-11-17, so the question is not shown."
M_TITLE = "owner_question.json: the title must be 1 to 90 characters, so the question is not shown."
M_PARAS = "owner_question.json: paragraphs must be 1 to 4 texts of 1 to 600 characters, so the question is not shown."
M_OPTIONS = ("owner_question.json: options must be 2 to 4 objects with exactly the keys id, text and recommended (an id of 1 to 3 characters, no two the same; a text of 1 to 400 characters; true or false; at most one true), "
             "so the question is not shown.")
M_HOW = "owner_question.json: how_to_answer must be 1 to 300 characters, so the question is not shown."


def write(tmp_path, obj):
    (tmp_path / "owner_question.json").write_text(obj if isinstance(obj, str) else json.dumps(obj), encoding="utf-8")
    return tmp_path


def changed(**kw):
    d = json.loads(json.dumps(GOOD))
    d.update(kw)
    return d


def option(**kw):
    o = {"id": "1", "text": "Lower the bar.", "recommended": False}
    o.update(kw)
    return o


def test_the_file_name_and_the_keys_are_the_ones_the_card_reads():
    assert V.QUESTION_FILE == "owner_question.json"
    assert V.QUESTION_KEYS == ("asked_on", "title", "paragraphs", "options", "how_to_answer") and V.OPTION_KEYS == ("id", "text", "recommended")


def test_without_a_file_there_is_nothing_to_show_and_nothing_to_say(tmp_path):
    assert V.question(tmp_path) == (None, None)


def test_a_sound_file_is_shown_as_it_was_written_in_its_own_order(tmp_path):
    q, problem = V.question(write(tmp_path, GOOD))
    assert problem is None and q == GOOD
    assert [o["id"] for o in q["options"]] == ["3", "2", "1"] and q["paragraphs"] == GOOD["paragraphs"]


def test_a_file_that_is_not_json_gives_one_sentence(tmp_path):
    for text in ("", "not json", "{", '{"asked_on": '):
        assert V.question(write(tmp_path, text)) == (None, M_JSON), text
    (tmp_path / "owner_question.json").write_bytes(b"\xff\xfe\x00")
    assert V.question(tmp_path) == (None, M_JSON)


def test_a_path_that_cannot_be_read_gives_the_same_one_sentence(tmp_path):
    (tmp_path / "owner_question.json").mkdir()                                                      # a folder with the file's name: reading it fails with an operating-system error
    assert V.question(tmp_path) == (None, M_JSON)


def test_text_that_is_not_plain_ascii_is_read_as_written(tmp_path):
    q = changed(title="Décision à prendre — 100 % sûr ?", paragraphs=["Un paragraphe avec « guillemets » et un tiret – long."])
    (tmp_path / "owner_question.json").write_text(json.dumps(q, ensure_ascii=False), encoding="utf-8")        # really UTF-8 on disk: json.dumps would otherwise escape it to ASCII
    assert (tmp_path / "owner_question.json").read_bytes() != json.dumps(q).encode() and V.question(tmp_path) == (q, None)


@pytest.mark.parametrize("text", ("[]", "[1, 2]", '"a string"', "42", "null", "true"))
def test_json_that_is_not_one_object_gives_one_sentence(tmp_path, text):
    assert V.question(write(tmp_path, text)) == (None, M_OBJECT)


def test_the_keys_must_be_exactly_the_five_none_missing_and_none_extra(tmp_path):
    for key in GOOD:
        d = {k: v for k, v in GOOD.items() if k != key}
        assert V.question(write(tmp_path, d)) == (None, M_KEYS), key
    assert V.question(write(tmp_path, {**GOOD, "extra": "x"})) == (None, M_KEYS)
    assert V.question(write(tmp_path, {})) == (None, M_KEYS)


@pytest.mark.parametrize("value, ok", (("2026-11-17", True), ("2024-02-29", True), ("2026-02-28", True), ("2026-02-29", False), ("2026-13-01", False), ("2026-11-31", False), ("17 Nov 2026", False),
                                       ("2026-11-17T00:00:00Z", False), ("2026-1-7", False), ("", False), (20261117, False), (None, False)))
def test_asked_on_must_be_a_real_date_written_year_month_day(tmp_path, value, ok):
    got = V.question(write(tmp_path, changed(asked_on=value)))
    assert got == ((changed(asked_on=value), None) if ok else (None, M_DATE))


def test_the_title_is_1_to_90_characters_and_not_blank(tmp_path):
    for title in ("a", "a" * 90, " a "):
        assert V.question(write(tmp_path, changed(title=title)))[1] is None, title
    for title in ("", "   ", "a" * 91, None, 5, ["a"]):
        assert V.question(write(tmp_path, changed(title=title))) == (None, M_TITLE), title


def test_the_limit_counts_the_characters_as_written_spaces_included(tmp_path):
    assert V.question(write(tmp_path, changed(title="  " + "a" * 88)))[1] is None                  # 90 characters with two spaces in front
    assert V.question(write(tmp_path, changed(title="a" * 90 + "  "))) == (None, M_TITLE)          # 92: the spaces count
    assert V.question(write(tmp_path, changed(paragraphs=["a" * 599 + " "])))[1] is None
    assert V.question(write(tmp_path, changed(paragraphs=["a" * 600 + " "]))) == (None, M_PARAS)
    assert V.question(write(tmp_path, changed(how_to_answer="a" * 300 + " "))) == (None, M_HOW)


def test_there_are_1_to_4_paragraphs_of_1_to_600_characters_each(tmp_path):
    for paragraphs in (["a"], ["a" * 600], ["a"] * 4, ["a" * 600] * 4):
        assert V.question(write(tmp_path, changed(paragraphs=paragraphs)))[1] is None, len(paragraphs)
    for paragraphs in ([], ["a"] * 5, ["a" * 601], ["a", "a" * 601], ["a" * 601, "a"], ["a", ""], ["", "a"], ["a", "   "], ["   ", "a"], ["a", 5], [5, "a"], ["a", None], [None, "a"], ["a", "a" * 601, "a"], "a paragraph", None, {"a": "b"}):
        assert V.question(write(tmp_path, changed(paragraphs=paragraphs))) == (None, M_PARAS), paragraphs


def test_there_are_2_to_4_options_and_the_first_or_last_may_be_the_one_that_breaks_it(tmp_path):
    two = [option(id="1"), option(id="2")]
    four = [option(id="1"), option(id="2"), option(id="3"), option(id="4")]
    for options in (two, four):
        assert V.question(write(tmp_path, changed(options=options)))[1] is None, len(options)
    for options in ([], [option()], [option(id=str(i)) for i in range(5)], "options", None, {"id": "1"}, [option(id="1"), "text"], [option(id="1"), None], ["text", option(id="1")]):
        assert V.question(write(tmp_path, changed(options=options))) == (None, M_OPTIONS), options


def test_each_option_has_exactly_the_three_keys(tmp_path):
    for key in ("id", "text", "recommended"):
        o = {k: v for k, v in option().items() if k != key}
        assert V.question(write(tmp_path, changed(options=[option(id="2"), o]))) == (None, M_OPTIONS), key
    assert V.question(write(tmp_path, changed(options=[option(id="2"), {**option(), "extra": 1}]))) == (None, M_OPTIONS)


def test_an_option_id_is_1_to_3_characters_and_no_two_options_share_one(tmp_path):
    for oid in ("a", "abc", "12"):
        assert V.question(write(tmp_path, changed(options=[option(id="9"), option(id=oid)])))[1] is None, oid
    for oid in ("", "abcd", 1, None, ["1"]):
        assert V.question(write(tmp_path, changed(options=[option(id="9"), option(id=oid)]))) == (None, M_OPTIONS), oid
    assert V.question(write(tmp_path, changed(options=[option(id="1"), option(id="2"), option(id="1")]))) == (None, M_OPTIONS)
    assert V.question(write(tmp_path, changed(options=[option(id="1"), option(id="1")]))) == (None, M_OPTIONS)


def test_an_option_text_is_1_to_400_characters(tmp_path):
    for text in ("a", "a" * 400):
        assert V.question(write(tmp_path, changed(options=[option(id="2"), option(text=text)])))[1] is None, len(text)
    for text in ("", "   ", "a" * 401, None, 5):
        assert V.question(write(tmp_path, changed(options=[option(id="2"), option(text=text)]))) == (None, M_OPTIONS), text


def test_recommended_is_true_or_false_and_at_most_one_option_has_it(tmp_path):
    for flags in ((False, False), (True, False), (False, True), (False, False, True, False)):
        options = [option(id=str(i + 1), recommended=f) for i, f in enumerate(flags)]
        assert V.question(write(tmp_path, changed(options=options)))[1] is None, flags
    for flags in ((True, True), (True, False, True), (True, True, True, True)):
        options = [option(id=str(i + 1), recommended=f) for i, f in enumerate(flags)]
        assert V.question(write(tmp_path, changed(options=options))) == (None, M_OPTIONS), flags
    for value in (1, 0, "yes", "true", None, [True]):
        assert V.question(write(tmp_path, changed(options=[option(id="2"), option(recommended=value)]))) == (None, M_OPTIONS), value


def test_how_to_answer_is_1_to_300_characters(tmp_path):
    for text in ("a", "a" * 300):
        assert V.question(write(tmp_path, changed(how_to_answer=text)))[1] is None, len(text)
    for text in ("", "   ", "a" * 301, None, 5):
        assert V.question(write(tmp_path, changed(how_to_answer=text))) == (None, M_HOW), text


def test_every_problem_is_one_plain_sentence_that_names_the_file_and_says_the_question_is_not_shown(tmp_path):
    for m in (M_JSON, M_OBJECT, M_KEYS, M_DATE, M_TITLE, M_PARAS, M_OPTIONS, M_HOW):
        assert m.startswith("owner_question.json") and m.endswith(", so the question is not shown.") and "\n" not in m


def test_the_first_thing_wrong_is_the_one_named_in_the_order_the_file_is_read(tmp_path):
    bad = changed(asked_on="x", title="", paragraphs=[], options=[], how_to_answer="")
    assert V.question(write(tmp_path, bad)) == (None, M_DATE)
    bad = changed(title="", paragraphs=[], options=[], how_to_answer="")
    assert V.question(write(tmp_path, bad)) == (None, M_TITLE)
    bad = changed(paragraphs=[], options=[], how_to_answer="")
    assert V.question(write(tmp_path, bad)) == (None, M_PARAS)
    bad = changed(options=[], how_to_answer="")
    assert V.question(write(tmp_path, bad)) == (None, M_OPTIONS)


def test_the_default_place_is_the_btcquant_folder_and_a_missing_root_means_no_file(tmp_path):
    assert V.question(tmp_path / "nowhere") == (None, None)
    got = V.question()                                                                              # the real folder: no argument means C.ROOT
    assert got == V.question(C.ROOT)


def test_the_file_in_the_repo_is_sound_if_it_is_there():
    path = Path(C.ROOT) / "owner_question.json"
    if not path.exists():
        pytest.skip("no question is waiting for the owner")
    q, problem = V.question(C.ROOT)
    assert problem is None and q is not None and len(q["options"]) >= 2
