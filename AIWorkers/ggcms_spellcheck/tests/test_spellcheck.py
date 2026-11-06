import sys
from pathlib import Path

from spellchecker import SpellChecker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))

from dump_tables import SqlValues  # noqa: E402
from text_words import TextWords  # noqa: E402

DICTIONARY = SpellChecker(distance=1)


def words(markup: str, allowed=frozenset(), known=None) -> dict:
    return TextWords(DICTIONARY, set(allowed), known or {"teh": "the", "jos": "joss"}).read(markup)


def test_slips_are_found_and_counted():
    found = words("<p>The workers seized teh factory. The dstruction of the old order, the dstruction of the state.</p>")
    assert set(found) == {"teh", "dstruction"}
    assert found["teh"].known == "the" and found["dstruction"].count == 2
    assert found["dstruction"].context.startswith("The dstruction")


def test_names_foreign_words_and_addresses_are_left_alone():
    # Common short foreign words ("der") are the corpus filter's job: they're used in too many texts to be slips
    found = words("Kropotkin met Jos in Wales. Die Führungsrolle. See https://www.synaps.network/lpg?x=1 or mail ben@earthfluent.com")
    assert found == {}


def test_a_known_misspelling_opening_a_sentence_still_counts():
    assert "teh" in words("Teh strike began at dawn.")


def test_allowed_words_and_possessives_pass():
    assert words("The syndicalist's labour was colour.", allowed={"syndicalist", "labour", "colour"}) == {}


def test_dump_strings_keep_their_escapes():
    rows = list(SqlValues("INSERT INTO `TextBody` VALUES (1,'It\\'s a \\\"test\\\"\\nline',NULL),(2,'',5);").rows())
    assert rows == [["1", "It's a \"test\"\nline", None], ["2", "", "5"]]


def test_a_word_split_in_two_is_one_candidate_for_the_whole_span():
    found = words("National unity is the common inhe ritance of traditions. The Fennomanes obtained the recog nition by law.")
    assert set(found) == {"inhe ritance", "recog nition"}
    assert found["inhe ritance"].suggestion == "inheritance" and "inhe ritance" in found["inhe ritance"].context


def test_a_split_keeps_its_capital_and_two_real_words_are_left_alone():
    assert words("The Com mune fell.")["com mune"].suggestion == "Commune"
    assert words("He went an other way, in deed.") == {}


def test_old_english_and_plain_plurals_pass():
    text = ("Thou blanchest under thy visor. He sinketh. Rocks pil'd on rocks, the inexperienc'd hind. These animals frolick. "
            "Ye olde shoppe. The abolitions and the metalloids.")
    assert set(words(text)) <= {"shoppe"}


def test_an_old_ending_on_a_slip_is_still_a_slip():
    assert "hohest" in words("The hohest and purest part of the soul.")
    assert {"potatoe", "wents", "pts", "necessitys", "chamberes"} <= set(words("He ate a potatoe. It wents on. Ten pts. The necessitys of the chamberes."))


def test_old_verdicts_get_their_split_span_back():
    from refresh_queue import split_span
    assert split_span("inhe", "inheritance", "is the common inhe ritance of traditions") == "inhe ritance"
    assert split_span("mune", "Commune", "the spirit of the Com mune and") == "Com mune"
    assert split_span("teh", "the", "seized teh factory") == ""


class Screen:
    """Calls the words it's told typos, the rest fine, a minute each on the clock it's given."""

    def __init__(self, model, clock=None, typos=()):
        self.model, self.clock, self.typos, self.asked = model, clock, set(typos), 0

    def check(self, title, word):
        self.asked += 1
        if self.clock:
            self.clock.minutes += 1
        if word["word"] in self.typos:
            return {"verdict": "typo", "fix": "word", "reason": ""}
        return {"verdict": "fine", "fix": "", "reason": ""}

    def release(self):
        pass


def long_text(tmp_path, count=600):
    from spell_queue import SpellQueue
    queue = SpellQueue(tmp_path / "pile.sqlite")
    queue.fill([{"id": 1, "entryid": 7090, "title": "Book 3, Chapter 3", "code": "",
                 "words": [{"word": f"wrd{n}", "context": "", "known": "", "suggestion": ""} for n in range(count)]},
                {"id": 2, "entryid": 7091, "title": "Book 3, Chapter 4", "code": "",
                 "words": [{"word": "teh", "context": "", "known": "", "suggestion": ""}]}], {"filled_from": "x"})
    return queue


def clock(monkeypatch):
    from datetime import datetime, timedelta
    import run_spellcheck

    class Clock(datetime):
        minutes = 0

        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 29, 3, 0) + timedelta(minutes=Clock.minutes)

    monkeypatch.setattr(run_spellcheck, "datetime", Clock)
    return Clock


def test_a_long_texts_part_goes_straight_to_the_judge_and_is_kept(tmp_path):
    import run_spellcheck
    queue = long_text(tmp_path)
    screen = Screen("mistral")
    run_spellcheck.batch_two_stage(queue, queue.next(2), screen, Screen("gemma"), None)
    assert screen.asked == run_spellcheck.PART  # one part, and not chapter 4 behind it: that waits for the next batch
    assert len(queue.next(1)[0]["done"]) == run_spellcheck.PART


def test_a_judge_out_of_clock_keeps_the_words_before_its_first_unchecked_typo(tmp_path, monkeypatch):
    from datetime import timedelta
    import run_spellcheck
    Clock = clock(monkeypatch)
    queue = long_text(tmp_path)
    typos = {"wrd10", "wrd20", "wrd30"}
    # One minute left when the judge starts, a minute a recheck: wrd10 is rechecked, wrd20 isn't
    ends = Clock.now() + timedelta(minutes=1)
    run_spellcheck.batch_two_stage(queue, queue.next(1), Screen("mistral", typos=typos), Screen("gemma", Clock, typos), ends)
    text, = queue.next(1)
    assert [v["word"] for v in text["done"]] == [f"wrd{n}" for n in range(20)]
    assert text["done"][10]["checked_by"] == "mistral > gemma"


def test_main_works_through_a_long_text_until_it_is_done(tmp_path, monkeypatch):
    import run_spellcheck
    queue = long_text(tmp_path)
    monkeypatch.setattr(run_spellcheck, "TypoCheck", lambda model, about: Screen(model))
    monkeypatch.setattr(run_spellcheck, "site_about", lambda target: "")
    monkeypatch.setattr(run_spellcheck, "write_results", lambda *a: 0)
    monkeypatch.setattr("sys.argv", ["run", "--queue", str(tmp_path / "pile.sqlite"), "--results", str(tmp_path / "r.txt"), "--limit", "5"])
    run_spellcheck.main()
    assert queue.next(5) == [] and queue.counts()["done"] == 2
    judged = queue.connection.execute("SELECT verdicts FROM texts WHERE id = 1").fetchone()[0]
    assert judged.count('"wrd') == 600 and '"wrd599"' in judged


def test_a_refresh_keeps_a_text_judged_part_way(tmp_path):
    from spell_queue import SpellQueue
    queue = long_text(tmp_path)
    text, = queue.next(1)
    queue.record_part(text, [{**w, "verdict": "fine"} for w in text["words"][:250]], "mistral", "now")
    queue.refill_pending([{"id": 1, "entryid": 7090, "title": "", "code": "", "words": []}], {})
    assert len(SpellQueue(tmp_path / "pile.sqlite").next(1)[0]["done"]) == 250


def test_a_part_longer_than_the_screeners_half_goes_to_the_judge_as_far_as_it_got(tmp_path, monkeypatch):
    from datetime import timedelta
    import run_spellcheck
    Clock = clock(monkeypatch)
    queue = long_text(tmp_path)
    # A 60-minute turn: the screener has 30 minutes, at a minute a word, so it screens 30 of the part's 250
    ends = Clock.now() + timedelta(minutes=60)
    run_spellcheck.batch_two_stage(queue, queue.next(2), Screen("mistral", Clock), Screen("gemma", Clock), ends)
    assert len(queue.next(1)[0]["done"]) == 30
