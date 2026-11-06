import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hunt_queue import HuntQueue  # noqa: E402
from typo_age import stood_since  # noqa: E402
from typo_judge import TypoJudge  # noqa: E402
from wiki_text import blank_markup, occurrences  # noqa: E402
from word_rules import WordRules  # noqa: E402


def words_found(text: str, wrong: str) -> list[str]:
    return [place["sentence"] for place in occurrences(text, wrong)]


def test_prose_is_found_with_its_sentence():
    text = "The band toured Europe. They recieved a gold disc in [[1999 in music|1999]]. Sales rose."
    assert words_found(text, "recieved") == ["They recieved a gold disc in 1999."]


def test_links_files_addresses_and_references_are_left_alone():
    # The live hits on 2 Nov 2026: a song title in a link, a file name, a URL and a ref name
    text = ('Aerosmith released "[[Lover Alot]]".\n'
            "[[File:Tsiolkovsky viewing letters he recieved.jpg|thumb|A [[letter]] archive]]\n"
            "Assets |url=https://www.nytimes.com/1981/unfrozen-assets-recieved-so-far.html\n"
            '<ref name="alot">{{cite web|title=Alot of fuss}}</ref> End.')
    assert words_found(text, "alot") == [] and words_found(text, "recieved") == []


def test_a_link_label_is_prose_but_its_target_is_not():
    assert words_found("He met [[Recieved Pronunciation|the speakers]] there.", "recieved") == []
    assert words_found("She [[Award|recieved]] it.", "recieved") == ["She recieved it."]


def test_a_links_trailing_letters_belong_to_the_link():
    # Denmark, 2 Nov 2026: "[[student exchange program]]mes" renders as "programmes", not a word "mes"
    assert words_found("Taught in [[doctorate]]s and [[student exchange program]]mes.", "mes") == []
    assert words_found("He [[Award|recieve]]d it.", "recieved") == ["He recieved it."]


def test_a_word_the_article_names_or_defines_is_marked():
    # Every exception Ben caught by 2 Nov 2026 that its sentence could show was the article naming the word itself
    named = lambda text, wrong: [place["named"] for place in occurrences(text, wrong)]
    assert named("* [[Golden perch]], an Australian fish, also called callop", "callop") == [True]
    assert named("'''Claping''' (pronounced \"clay-ping\") refers to hate crimes against the Amish.", "claping") == [True]
    assert named('Claping (pronounced "clay-ping") refers to hate crimes against the Amish.', "claping") == [True]
    assert named("The fish is known locally as \"callop\".", "callop") == [True]
    assert named("The shop sold alot of hats, and they recieved a gold disc.", "alot") == [False]
    assert named("They recieved (in 1902) a medal.", "recieved") == [False]
    assert named("Mining to produce [[wikt:culch|culch]], crushed shells.", "culch") == [True]
    assert named("Charged particles (Skt. ''bindu'', Tib. ''thig le''), and chakras.", "thig") == [True]
    assert named("A '''quadrupole''' or '''quadrapole''' is one of a sequence of configurations.", "quadrapole") == [True]
    assert named("</ref>\n\n'''Aditional sources'''\n\n* Browder, R. P.", "aditional") == [False]
    assert named("It went to [[Award|recieved]] status.", "recieved") == [False]
    assert named("The church recognized Russian jursidiction over Ukraine.", "jursidiction") == [False]
    assert named("From the Old French ''nonper'', not equal.", "nonper") == [True]


def test_nested_templates_come_apart():
    text = "{{Infobox person|name={{nowrap|Alot Smith}}|note=alot}}\nHe had alot of friends."
    assert words_found(text, "alot") == ["He had alot of friends."]


def test_a_quotations_bracketed_capital_is_not_a_misspelling():
    assert words_found('Paulson argues that "[w]hether change is called realignment" or (w)hether not.', "hether") == []


def test_sic_and_mid_sentence_capitals_are_skipped():
    assert words_found('He wrote "we recieved [sic] it" in 1902.', "recieved") == []
    assert words_found("The village of Alot lies east.", "alot") == []
    assert words_found("Alot of rain fell.", "alot") == ["Alot of rain fell."]


def test_quotations_and_italics_are_flagged_for_the_judge():
    [quoted] = occurrences('He said "we recieved nothing" at the time.', "recieved")
    [italic] = occurrences("Her novel ''Nothing alot'' sold well, and alot of people read it.", "alot")[:1]
    assert quoted["quoted"] and not quoted["italic"]
    assert italic["italic"]


def test_blanking_keeps_every_position():
    text = "a [[b|c]] {{d|{{e}}}} <ref>f</ref> https://g.example/h i"
    assert len(blank_markup(text)) == len(text)


def test_the_queue_goes_a_page_deeper_each_round(tmp_path):
    queue = HuntQueue(tmp_path / "pile.sqlite")
    queue.fill({"alot": "a lot", "recieved": "received"}, {"filled_from": "test"})
    first = queue.next_word()
    queue.visited(first, total=25, read=10)
    second = queue.next_word()
    assert second["wrong"] != first["wrong"] and second["offset"] == 0
    queue.visited(second, total=3, read=3)  # all its results read: finished
    again = queue.next_word()
    assert again["wrong"] == first["wrong"] and again["offset"] == 10 and again["round"] == 1
    queue.visited(again, total=25, read=10)
    queue.visited(queue.next_word(), total=25, read=5)
    assert queue.next_word() is None
    assert queue.counts()["finished"] == 2


def test_only_typos_are_listed_and_pages_are_not_judged_twice(tmp_path):
    queue = HuntQueue(tmp_path / "pile.sqlite")
    queue.fill({"alot": "a lot"}, {"filled_from": "test"})
    word = queue.next_word()
    place = {"word": "alot", "sentence": "He had alot.", "raw": "He had alot.", "quoted": False, "italic": False}
    queue.record(word, {"id": 1, "title": "A"}, place, {"verdict": "typo", "fix": "a lot", "reason": "slip"}, "m", "2026-11-02T20:00")
    queue.record(word, {"id": 2, "title": "B"}, place, {"verdict": "fine", "fix": "", "reason": "name"}, "m", "2026-11-02T20:01")
    assert [typo["title"] for typo in queue.typos()] == ["A"]
    assert queue.seen(word["id"], 2) and not queue.seen(word["id"], 3)


def test_the_learnt_rules_know_every_one():
    rules = WordRules()  # the real word_rules.json
    assert rules.fine_here("every one", "Every one in fifteen people throughout the country work in the tourism industry.")
    assert rules.fine_here("Every One", "He thanked every one of them.")
    assert not rules.fine_here("every one", "Every one came to the party.")
    assert "ratio" in rules.note("every one") and rules.note("recieved") == ""
    assert rules.fine_here("culch", "Byrd authorized fossil shell mining to produce culch, crushed shells used to form oyster beds.")
    assert rules.fine_here("thig", '"drops" or charged particles (Skt. bindu, Tib. thig le), and chakras ("wheels").')
    assert not rules.fine_here("thig", "It was the only thig he could think of.")
    assert rules.fine_here("strickly", "The single was released on Strickly FX in 2004.")
    assert not rules.fine_here("strickly", "Entry was strickly by invitation.")
    assert rules.fine_here("callop", "*, an Australian fish, also called callop")
    assert not rules.fine_here("callop", "She served seared callop with butter.")
    assert rules.fine_here("Claping", "===Claping===") and rules.fine_here("claping", "Claping")
    assert rules.fine_here("claping", 'Claping (pronounced "clay-ping") refers to hate crimes directed against Amish people.')
    assert not rules.fine_here("claping", "The crowd was claping loudly.")
    assert rules.fine_here("Boheman", "Boheman was arrested upon an attempt to recruit the monarch.")
    assert not rules.fine_here("boheman", "She lived a boheman life in Paris.")
    assert rules.fine_here("Varity", "Varity left Toronto and relocated its head office to Buffalo.") and rules.fine_here("Varity", "Varity")
    assert not rules.fine_here("varity", "The shop sold a varity of hats.")
    assert not rules.fine_here("Varity", "Varity of colour marks the breed.")


def test_the_note_reaches_the_judge():
    place = {"sentence": "Every one came.", "word": "Every one", "quoted": False, "italic": False}
    assert "past mistakes" in TypoJudge._question("A", "every one", "everyone", place, "Mind the ratios.")
    assert "past mistakes" not in TypoJudge._question("A", "recieved", "received", place)


def test_a_typo_inside_a_quotation_is_never_listed(tmp_path):
    queue = HuntQueue(tmp_path / "pile.sqlite")
    queue.fill({"melow": "mellow"}, {"filled_from": "test"})
    word = queue.next_word()
    place = {"word": "melow", "sentence": '"Linger" was "melow gold".', "raw": "", "quoted": True, "italic": False}
    queue.record(word, {"id": 1, "title": "A"}, place, {"verdict": "typo", "fix": "mellow", "reason": "slip"}, "m", "2026-11-02T20:00")
    assert queue.typos() == []


def tokens(text: str, origin: int = 100, back_in: dict | None = None) -> list[dict]:
    # WikiWho's shape: lowercased tokens with markup split off, each with the revision that added it and any re-addings
    back_in = back_in or {}
    return [{"str": word, "o_rev_id": origin + at, "in": back_in.get(at, [])} for at, word in enumerate(text.lower().split())]


def test_a_typo_is_dated_by_the_occurrence_its_wikitext_matches():
    # Flute, 3 Nov 2026: "sring" stood in a heading, a link and the prose; the find is the one in its prose
    current = tokens("=== sring === the [[ sring ]] was early . musicologist believes the sring to be the oldest")
    assert stood_since(current, "Sring", "a musicologist believes the sring to be the oldest flute") == 113
    assert stood_since(current, "sring", "=== Sring ===") == 101


def test_a_typo_put_back_has_stood_only_since_it_went_back():
    current = tokens("they recieved a medal", back_in={1: [500, 900]})
    assert stood_since(current, "recieved", "They recieved a medal") == 900


def test_a_phrase_has_stood_since_its_newest_word():
    current = tokens("some antiquarians suppose to have been", origin=10, back_in={3: [400]})
    assert stood_since(current, "suppose to", "antiquarians suppose to have been") == 400
    assert stood_since(tokens("they don ' t know", origin=10), "don't", "they don't know") == 13


def test_a_typo_already_fixed_has_no_age():
    assert stood_since(tokens("they received a medal"), "recieved", "They recieved a medal") is None


def test_ages_are_kept_with_their_typos(tmp_path):
    queue = HuntQueue(tmp_path / "pile.sqlite")
    queue.fill({"alot": "a lot"}, {"filled_from": "test"})
    word = queue.next_word()
    place = {"word": "alot", "sentence": "He had alot.", "raw": "He had alot.", "quoted": False, "italic": False}
    for page in (1, 2):
        queue.record(word, {"id": page, "title": "AB"[page - 1]}, place, {"verdict": "typo", "fix": "a lot", "reason": "slip"}, "m",
                     f"2026-11-02T20:0{page}")
    assert [typo["title"] for typo in queue.undated()] == ["A", "B"]
    [first, _] = queue.undated()
    queue.dated(first, {"since_rev": 7, "typo_since": "2019-05-01T10:00:00Z", "last_edit": "2026-10-01T09:00:00Z", "gone": False},
                "2026-11-03T01:00")
    assert [typo["title"] for typo in queue.undated()] == ["B"]
    dated = next(typo for typo in queue.typos() if typo["title"] == "A")
    assert dated["typo_since"] == "2019-05-01T10:00:00Z" and dated["since_rev"] == 7 and not dated["gone"]


def test_a_word_in_the_articles_own_title_is_its_subject():
    from run_hunt import in_title
    assert in_title("nicotini", "Nicotini") and in_title("callop", "Callop (fish)")
    assert not in_title("nicotini", "Nicotine replacement therapy")


def test_a_fix_must_be_a_spelling_of_the_word_not_another_word():
    from run_hunt import another_word
    assert another_word("kaber", "kabar", "charlock")
    assert not another_word("kaber", "kabar", "kabar")
    assert not another_word("nicotini", "nicotine", "nicotine")
    assert not another_word("alot", "a lot", "a lot") and not another_word("recieve", "receive", "")


def test_a_phrase_fix_may_name_only_the_word_that_changes():
    from run_hunt import another_word
    assert not another_word("had came", "had come", "come") and not another_word("it's zenith", "its zenith", "its")
    assert another_word("florescence", "fluorescence", "flourishing")


def test_a_doubled_target_hunts_the_doubled_letter_workers_kept_slips(tmp_path):
    import sqlite3
    from doubled_pairs import doubled_pairs
    from task_queue import TaskQueue
    with sqlite3.connect(tmp_path / "foreman.sqlite") as foreman:
        foreman.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, kind TEXT, target TEXT)")
        foreman.execute("INSERT INTO tasks VALUES (23, 'ggcms_doubled_letters', 'ss'), (24, 'ggcms_doubled_letters', 'll')")
    (tmp_path / "tasks").mkdir()
    pile = TaskQueue(tmp_path / "tasks" / "task-23.sqlite")
    pile.fill([{"id": 1, "word": "calmness"}, {"id": 2, "word": "agassiz"}], {"filled_from": "test"})
    pile.record(1, {"english_word": True, "variants": [{"variant": "calmnes", "verdict": "misspelling"},
                                                       {"variant": "calmes", "verdict": "real word"}]}, "m", "now")
    pile.record(2, {"english_word": False, "variants": [{"variant": "agasiz", "verdict": "misspelling"}]}, "m", "now")
    pile.connection.close()
    assert doubled_pairs("ss", tmp_path) == {"calmnes": "calmness"} and doubled_pairs("tt", tmp_path) == {}


def test_the_pair_report_doubts_a_slip_the_judge_keeps_calling_right(tmp_path):
    from doubled_pairs import write_pair_report
    queue = HuntQueue(tmp_path / "hunt.sqlite")
    queue.fill({"calmnes": "calmness", "bosing": "bossing"}, {"filled_from": "test"}, shuffle=False)
    words = {row[1]: {"id": row[0], "wrong": row[1], "correct": row[2], "offset": 0, "round": 0}
             for row in queue.connection.execute("SELECT id, wrong, correct FROM words")}
    for page, (wrong, verdict) in enumerate([("calmnes", "typo"), ("bosing", "fine"), ("bosing", "fine")]):
        queue.record(words[wrong], {"id": page, "title": f"Page {page}"}, {}, {"verdict": verdict}, "m", "now")
    for word in words.values():
        queue.visited(word, 5, 2)
    assert write_pair_report(queue.connection, tmp_path / "report.txt", "ss") == 1
    report = (tmp_path / "report.txt").read_text(encoding="utf-8")
    assert report.index("bosing") < report.index("Confirmed") < report.index("calmnes")


def test_a_word_in_capitals_is_an_acronym():
    from run_hunt import acronym
    assert acronym("ASSS") and acronym("CSAD") and not acronym("Asss") and not acronym("asss") and not acronym("I")


def test_bold_or_italics_inside_a_word_do_not_split_it():
    assert words_found(": Out of the '''mock'''ing'''bird's''' throat, the '''mu'''sical '''shu'''ttle", "ttle") == []
    assert words_found("the '''shu'''ttle", "shu") == []
    assert len(words_found("the ''ttle'' word", "ttle")) == 1  # italics round a whole word still leave it a word


def test_an_old_find_split_by_markup_is_recognised_from_its_wikitext():
    from wiki_text import split_by_markup
    assert split_by_markup("ttle", "the '''mus'''ical '''shu'''ttle [2 dactyls") and split_by_markup("eached", "''Couch Potato r''eached no. 4")
    assert not split_by_markup("ttle", "a ''ttle'' word")
