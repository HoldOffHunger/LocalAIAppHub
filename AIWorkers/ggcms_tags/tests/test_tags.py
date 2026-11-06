import shutil
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from keywords import ignore_words, list_keywords, words  # noqa: E402
from run_tags import kept  # noqa: E402

SPEECH = ("The union met on Tuesday. The union voted to strike, and the Industrial Workers of the World sent word: "
          "the Industrial Workers of the World stand with you. Bring ham sandwiches! “Solidarity forever,” the union sang. "
          "To-day the strike holds; the strike is strong, and the union is strong.")


def test_cleanup_matches_the_page():
    assert words("“Hello,” to-day — it’s (fine).") == ["hello", "today", "—", "it's", "fine"]


def test_phrases_come_first_longest_down_then_single_words_by_count():
    found = [keyword for keyword, _ in list_keywords(SPEECH, ignore_words())]
    assert found.index("industrial workers of the world") < found.index("union")
    assert found[-1] != "union" and "the" not in found and "ham" in found  # ham is ListKeywords' to offer, the model's to strike


def test_the_model_only_removes():
    item = {"candidates": ["union", "strike", "ham", "solidarity"]}
    assert kept(item, {"struck": [2]}) == ["union", "strike", "solidarity"]


def test_edge_articles_are_trimmed_and_the_twins_merged():
    item = {"candidates": ["the one-armed prisoner", "right and left", "one-armed prisoner", "a cornbread tom the", "the", "ham"]}
    assert kept(item, {"struck": [5]}) == ["one-armed prisoner", "right and left", "cornbread tom"]


@pytest.mark.skipif(not shutil.which("node"), reason="needs node to run the page's own script")
def test_the_port_matches_list_find_keywords_js():
    page = subprocess.run(["node", str(HERE / "listkeywords_parity.js")], input=SPEECH, capture_output=True, text=True, encoding="utf-8", check=True)
    expected = [line for line in page.stdout.split("\n") if line]
    assert [keyword for keyword, _ in list_keywords(SPEECH, ignore_words())] == expected
