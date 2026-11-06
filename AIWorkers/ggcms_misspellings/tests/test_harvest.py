import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import harvest as harvest_module  # noqa: E402
from run_harvest import judge_word  # noqa: E402
from wiktionary_words import WiktionaryWords  # noqa: E402


class Judge:
    """Says what it's told, one answer per sentence."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = 0

    def check(self, title, word):
        self.asked += 1
        return self.answers.pop(0)


def item(contexts=2, wiktionary=""):
    return {"word": "goverment", "suggestion": "government", "wiktionary": wiktionary,
            "contexts": [{"entryid": n, "title": f"Text {n}", "context": f"The goverment fell, said text {n}."} for n in range(contexts)]}


def test_a_typo_must_be_a_typo_in_both_sentences_with_one_fix():
    typo = {"verdict": "typo", "fix": "government", "reason": "slip"}
    assert judge_word(Judge(typo, typo), item())["verdict"] == "typo"
    assert judge_word(Judge(typo, {"verdict": "fine", "fix": "", "reason": "a name"}), item())["verdict"] == "fine"
    assert judge_word(Judge(typo, {**typo, "fix": "governments"}), item())["verdict"] == "fine"


def test_fine_in_the_first_sentence_needs_no_second_question():
    judge = Judge({"verdict": "fine", "fix": "", "reason": "real"})
    assert judge_word(judge, item())["verdict"] == "fine" and judge.asked == 1


def test_a_word_in_one_text_is_judged_on_its_one_sentence():
    judge = Judge({"verdict": "typo", "fix": "government", "reason": "slip"})
    assert judge_word(judge, item(contexts=1))["verdict"] == "typo" and judge.asked == 1


def test_wiktionary_words_and_their_forms_are_indexed_by_language(tmp_path):
    folder = tmp_path / "italian"
    folder.mkdir()
    entries = [{"word": "abbate", "forms": [{"form": "abbati"}]}, {"word": "Città"}]
    (folder / "kaikki.org-dictionary-Italian.jsonl").write_text("\n".join(json.dumps(e) for e in entries), encoding="utf-8")
    words = WiktionaryWords(tmp_path / "w.sqlite")
    assert words.build(tmp_path, log=lambda line: None) == 2  # città isn't plain ASCII, so it can't be a harvested word
    assert words.languages("abbati") == "Italian" and words.languages("teh") == ""


def test_long_foreign_words_are_dropped_and_short_ones_kept_as_evidence(tmp_path, monkeypatch):
    dump = tmp_path / "site.sql.gz"
    text = "<p>The abbate came. The goverment fell. It was teh end.</p><p>Then teh goverment again.</p>"
    sql = ("CREATE TABLE `Entry` (\n  `id` int,\n  `Title` text,\n  `Publish` int\n);\n"
           "INSERT INTO `Entry` VALUES (1,'One',1),(2,'Two',1);\n"
           "CREATE TABLE `TextBody` (\n  `id` int,\n  `Text` text,\n  `Language` text,\n  `Entryid` int\n);\n"
           f"INSERT INTO `TextBody` VALUES (1,'{text}','en',1),(2,'{text}','en',2);\n")
    with gzip.open(dump, "wt", encoding="utf-8") as handle:
        handle.write(sql)

    class Words:
        def languages(self, word):
            return {"abbate": "Italian", "teh": "Indonesian"}.get(word, "")

    monkeypatch.setattr(harvest_module, "known_misspellings", lambda: {})
    monkeypatch.setattr(harvest_module, "british_spellings", lambda: set())
    items, about = harvest_module.harvest(dump, Words(), log=lambda line: None)
    found = {i["word"]: i for i in items}
    assert "abbate" not in found and about["real_elsewhere"] == 1
    assert found["goverment"]["suggestion"] == "government" and found["goverment"]["texts"] == 2
    assert found["teh"]["wiktionary"] == "Indonesian"


def test_a_spellcheck_immune_text_is_not_read(tmp_path, monkeypatch):
    dump = tmp_path / "site.sql.gz"
    text = "<p>The goverment fell. It was the end.</p>"
    sql = ("CREATE TABLE `Entry` (\n  `id` int,\n  `Title` text,\n  `Publish` int\n);\n"
           "INSERT INTO `Entry` VALUES (1,'One',1),(2,'Two',1),(3,'Coined',1);\n"
           "CREATE TABLE `TextBody` (\n  `id` int,\n  `Text` text,\n  `Language` text,\n  `SpellCheckImmune` tinyint(1),\n  `Entryid` int\n);\n"
           f"INSERT INTO `TextBody` VALUES (1,'{text}','en',0,1),(2,'{text}','en',0,2),(3,'{text}','en',1,3);\n")
    with gzip.open(dump, "wt", encoding="utf-8") as handle:
        handle.write(sql)

    class Words:
        def languages(self, word):
            return ""

    monkeypatch.setattr(harvest_module, "known_misspellings", lambda: {})
    monkeypatch.setattr(harvest_module, "british_spellings", lambda: set())
    items, about = harvest_module.harvest(dump, Words(), log=lambda line: None)
    found = {i["word"]: i for i in items}
    assert found["goverment"]["texts"] == 2
    assert all(c["entryid"] != 3 for c in found["goverment"]["contexts"])


def test_halves_and_abbreviations_are_dropped_but_a_slip_at_a_line_end_is_kept():
    said = lambda *contexts: [{"entryid": 1, "title": "", "context": c} for c in contexts]  # noqa: E731
    assert harvest_module.shape("socio", said("the socio-political life", "socio- revolutionary")) == "half"
    assert harvest_module.shape("zation", said("join an organi- zation now", "the organi-zation")) == "half"
    assert harvest_module.shape("vol", said("see vol. 2", "in vol. 3", "vol. 9")) == "abbreviation"
    assert harvest_module.shape("eart", said("my eart.", "his eart.")) == ""  # two sentence ends are not an abbreviation
    assert harvest_module.shape("goverment", said("the goverment fell", "a goverment-run mill", "goverment men")) == ""
