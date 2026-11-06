import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "jobs"))

from paint_scene import BOOK_PATH, load, order, pair_id, prompt_for, style_for  # noqa: E402

BOOK = load(BOOK_PATH, None)


def test_every_race_gets_every_subject_once():
    pairs = [pair_id(race, subject) for _index, race, subject in order(BOOK)]
    assert len(pairs) == len(set(pairs)) == len(BOOK["folk"]) * len(BOOK["subjects"])


def test_neighbouring_nights_change_race_and_subject():
    lined_up = order(BOOK)
    for (_i, race_a, subject_a), (_j, race_b, subject_b) in zip(lined_up, lined_up[1:]):
        assert race_a != race_b and subject_a["id"] != subject_b["id"]


def test_every_night_gets_its_versions_in_different_styles():
    for index, _race, _subject in order(BOOK):
        styles = [style_for(index, version, BOOK["styles"]) for version in range(1, BOOK["versions"] + 1)]
        assert len(set(styles)) == BOOK["versions"]


def test_every_race_has_a_look_and_buildings_and_every_prompt_fills_in():
    assert set(BOOK["folk"]) == set(BOOK["architecture"])
    assert len({subject["id"] for subject in BOOK["subjects"]}) == len(BOOK["subjects"])
    for _index, race, subject in order(BOOK):
        prompt = prompt_for(race, subject, BOOK, BOOK["styles"][0])
        assert "{" not in prompt and prompt[0].isupper() and prompt.endswith(BOOK["finish"])
