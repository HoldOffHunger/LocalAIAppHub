import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from doubled import DoubledLetters  # noqa: E402
from run_doubled import judge_item  # noqa: E402


class Judge:
    """Rules as it's told; remembers what it was asked."""

    def __init__(self, english=True, real=()):
        self.english, self.real, self.asked = english, set(real), None

    def check(self, word, variants):
        self.asked = variants
        return {"meaning": "", "english_word": self.english,
                "variants": [{"variant": v, "real_word": v in self.real, "reason": "said so"} for v in variants]}


def letters(*real, listed=()):
    words = {"dessert": 300, "wordless": 100, "assess": 200, "princess": 500, "idless": 60}
    return DoubledLetters(words, set(words) | set(real), set(listed))


def verdicts(found):
    return {v["variant"]: v["verdict"] for v in found}


def test_a_dropped_letter_that_lands_on_a_real_word_is_thrown_out():
    assert verdicts(letters("desert").variants("dessert", "ss")) == {"desert": "real word", "desssert": "open"}


def test_every_pair_in_a_word_gets_its_own_slip():
    assert set(verdicts(letters().variants("assess", "ss"))) == {"asess", "asses", "asssess", "assesss"}


def test_a_real_word_plus_an_ending_counts_as_real():
    assert verdicts(letters("prince", "idle").variants("princess", "ss"))["princes"] == "real word (prince + ending)"
    assert verdicts(letters("idle").variants("idless", "ss"))["idles"] == "real word (idle + ending)"
    assert verdicts(letters("archer").variants("archeress", "ss"))["archeres"] == "open"  # archer takes s, not es
    assert verdicts(letters("mis").variants("missed", "ss"))["mised"] == "open"  # too short a stem to trust


def test_already_listed_slips_are_left_alone():
    assert verdicts(letters(listed={"wordles"}).variants("wordless", "ss"))["wordles"] == "already listed"


def test_most_used_words_come_first():
    items, about = letters().items("ss")
    assert [i["word"] for i in items] == ["princess", "dessert", "assess", "wordless", "idless"] and about["words"] == 5


def test_only_open_dropped_slips_go_to_the_judge():
    item = {"word": "dessert", "variants": letters("desert").variants("dessert", "ss")}
    judge = Judge()
    result = judge_item(judge, item)
    assert judge.asked == [] and verdicts(result["variants"]) == {"desert": "real word", "desssert": "misspelling"}


def test_a_spelling_only_webster_knows_goes_to_the_judge():
    found = DoubledLetters({"misspell": 138}, {"misspell"}, set(), {"misspell", "mispell"}).variants("misspell", "ss")
    assert verdicts(found)["mispell"] == "open (Webster only)"
    judge = Judge()
    assert verdicts(judge_item(judge, {"word": "misspell", "variants": found})["variants"])["mispell"] == "misspelling"
    assert judge.asked == ["mispell"]


def test_a_webster_word_with_nothing_to_ask_skips_the_model():
    item = {"word": "dessert", "in_webster": True, "variants": letters("desert").variants("dessert", "ss")}
    judge = Judge()
    assert judge_item(judge, item)["english_word"] and judge.asked is None


def test_the_judge_can_save_a_slip_the_dictionaries_missed():
    item = {"word": "wordless", "variants": letters().variants("wordless", "ss")}
    assert verdicts(judge_item(Judge(real={"wordles"}), item)["variants"])["wordles"] == "real word (judge)"
    assert verdicts(judge_item(Judge(), item)["variants"])["wordles"] == "misspelling"
