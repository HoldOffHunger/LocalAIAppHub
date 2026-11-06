import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from run_mia_links import folder_of, is_collection  # noqa: E402
from run_mia_subjects import SubjectBench, _pile, clean_title, names_for, read_collections, write_results  # noqa: E402
from task_queue import TaskQueue  # noqa: E402
from wiki_index import WikiIndex  # noqa: E402


def test_subject_targets_stay_in_their_section():
    assert folder_of("marxists.org/history/france") == "history/france"
    assert folder_of("marxists.org/history") == "history"
    assert folder_of("subject") == "subject"
    assert folder_of("kautsky") == "archive/kautsky"
    # the whole section is a collection target too, not an author called History
    assert all(is_collection(folder_of(target)) for target in ("marxists.org/history", "marxists.org/subject", "history/france"))
    assert not any(is_collection(folder_of(target)) for target in ("marxists.org/archive/kautsky", "kautsky", "historyx"))


def test_titles_and_names():
    assert clean_title("Red Front: Index | Encyclopedia of Anti-Revisionism On-Line") == "Red Front"
    assert clean_title("Charlotte Wilson, from Marxists.org") == "Charlotte Wilson"
    name, keys = names_for("history/etol/newspape/isj", "International Socialism (1st Series) 1958-1968")
    assert name == "International Socialism (1st Series) 1958-1968" and "international socialism" in keys
    _, keys = names_for("history/international/social-democracy", "History of the Second International")
    assert {"second international", "social democracy"} <= keys
    # a one-word folder name only counts when the index page gives no title
    assert "women" not in names_for("subject/women", "Women and Marxism")[1]
    assert names_for("history/usa/parties/cpusa", "")[1] == {"cpusa"}


def _mirror(tmp_path):
    site = tmp_path / "site"
    for folder, title in (("history/france/may-1968", "Paris May 1968"), ("history/france/stray", "A stray page")):
        (site / folder).mkdir(parents=True)
        (site / folder / "index.htm").write_bytes(f"<title>{title}</title><style>x</style><p>In Paris in May 1968, students rose.</p>".encode())
    listing = tmp_path / "listing.txt"
    rows = ["# header"] + [f"1\t2026-01-01\thistory/france/may-1968/{n}.htm" for n in range(4)] + ["1\t2026-01-01\thistory/france/stray/index.htm"]
    listing.write_text("\n".join(rows), encoding="utf-8")
    return site, listing


def test_collections_come_from_the_mirror(tmp_path):
    site, listing = _mirror(tmp_path)
    found = {each.folder: each for each in read_collections("history/france", listing, site)}
    assert "history/france/stray" not in found  # fewer than MIN_PAGES
    may = found["history/france/may-1968"]
    assert may.name == "Paris May 1968" and "may 1968" in may.keys and may.pages == 4
    assert may.opening.startswith("Paris May 1968 In Paris") and "x" not in may.opening.split()
    assert may.link == "https://www.marxists.org/history/france/may-1968/index.htm"


class FakeApi:
    def __init__(self, articles):
        self.found = articles

    def articles(self, titles):
        return {title: self.found[title] for title in titles if title in self.found}


class FakeJudge:
    model = "fake"

    def __init__(self):
        self.asked = []

    def about_collection(self, collection, article, opening):
        self.asked.append(article)
        same = article == "May 68"
        return {"same": same, "match": "same" if same else "different", "reason": "the same events"}


def test_pile_bench_and_results(tmp_path):
    site, listing = _mirror(tmp_path)
    collections = read_collections("history/france", listing, site)
    index = WikiIndex(tmp_path / "pile.wiki.sqlite")
    with index.connection:
        index.connection.executemany("INSERT INTO pages VALUES (?, ?, ?, ?, ?)", [
            (1, "May 1968", 1, "may 1968", ""), (2, "Paris May 1968", 1, "paris may 1968", ""),
            (3, "May 1968 (film)", 0, "may 1968", "film"), (4, "May 1968", 0, "may 1968", "linked"),
            (5, "May 1968 (Miró)", 0, "may 1968", "miró"), (6, "May 1968 (France)", 1, "may 1968", "france")])
        index.connection.execute("INSERT INTO links VALUES (4, 'https://www.marxists.org/history/france/may-1968/', 'marxists.org')")
    items = _pile(index, collections)
    # the film is dropped, and Miró's painting (an aside the collection's name doesn't share), and the article that links us
    assert sorted(item["page_id"] for item in items) == [1, 2, 6]

    queue = TaskQueue(tmp_path / "pile.sqlite")
    queue.fill(items, {"filled_from": "test", "links_from": "test"})
    bench = SubjectBench(collections, "", queue)
    unrest = {"title": "May 68", "text": "'''May 68''' was a period of unrest in France."}
    bench.judge, bench.api = FakeJudge(), FakeApi({  # both redirects land on one article; the third is a film about it
        "May 1968": unrest, "Paris May 1968": unrest,
        "May 1968 (France)": {"title": "Sous les pavés", "text": "'''Sous les pavés''' is a 1998 French documentary film about May 68."}})
    bench.batch(queue, queue.next(10), None)
    assert bench.judge.asked == ["May 68"]  # one judgement for both, and none for the film
    verdicts = {item["page_id"]: verdict for item, verdict, _ in queue.judged()}
    assert verdicts[6]["why"].startswith("the article is about a work") and verdicts[2]["repeat"]

    results = tmp_path / "results.txt"
    assert write_results(queue, results, "history/france") == 1
    text = results.read_text(encoding="utf-8")
    assert "[high] May 68" in text and "* [https://www.marxists.org/history/france/may-1968/index.htm Paris May 1968 archive]" in text
    assert '"kind": "subject"' in results.with_suffix(".jsonl").read_text(encoding="utf-8")


def test_a_run_never_takes_finds_away(tmp_path):
    # 4 Nov 2026: task 29's first run left 34 finds on Social; a collection run on the same pile must keep every one
    from run_mia_subjects import keep_earlier
    queue = TaskQueue(tmp_path / "task.sqlite")
    queue.fill([{"id": 1, "kind": "link", "page": "Chicanismo"}], {"filled_from": "history (author run)"})
    queue.record(1, {"result": "propose", "article": "Chicanismo", "link": "x"}, "code", "now")
    results = tmp_path / "task.results.txt"
    earlier = {"kind": "link", "key": "link:1:x", "article": "Chicanismo", "link": "x", "dead_url": "d"}
    results.with_suffix(".jsonl").write_text(json.dumps(earlier) + "\n", encoding="utf-8")
    keep_earlier(queue, results)
    write_results(queue, results, "history")
    write_results(queue, results, "history")  # and again, as every batch does
    kept = [json.loads(line) for line in results.with_suffix(".jsonl").read_text(encoding="utf-8").splitlines()]
    assert kept == [earlier]
    assert "Chicanismo" in results.read_text(encoding="utf-8")


def test_fill_adds_after_the_pile(tmp_path, monkeypatch):
    # 4 Nov 2026: fill called _pile with the pile's last id before _pile took one, and task 29 crashed after its title read
    import run_mia_subjects
    site, listing = _mirror(tmp_path)
    collections = read_collections("history/france", listing, site)
    index = WikiIndex(tmp_path / "task.wiki.sqlite")
    with index.connection:
        index.connection.execute("INSERT INTO pages VALUES (1, 'May 1968', 0, 'may 1968', '')")
        index.set_meta("links_done", 1)
        index.set_meta("pages_done", 1)
    monkeypatch.setattr(run_mia_subjects, "WikiDumps", lambda: None)
    queue = TaskQueue(tmp_path / "task.sqlite")
    queue.fill([{"id": 7, "kind": "link"}], {"filled_from": "earlier"})
    assert run_mia_subjects.fill(queue, index, collections, "history/france", None)
    assert [item["id"] for item in queue.next(10)] == [7, 8] and queue.meta("filled_from") == "earlier"


def test_wider_sources(tmp_path, monkeypatch):
    import run_mia_subjects
    from run_mia_subjects import front, history_keys, widen
    site, listing = _mirror(tmp_path)
    collections = read_collections("history/france", listing, site)
    may = next(each for each in collections if each.folder == "history/france/may-1968")
    assert "history of the may 1968" in history_keys(may) and "may 1968 history" in history_keys(may)
    assert front("history/france/may-1968").search("see marxists.org/history/france/may-1968/index.htm]")
    assert not front("history/france/may-1968").search("marxists.org/history/france/may-1968/1.htm")

    index = WikiIndex(tmp_path / "task.wiki.sqlite")
    base = "https://www.marxists.org/history/france/may-1968/"
    with index.connection:
        index.connection.executemany("INSERT INTO pages VALUES (?, ?, 0, ?, '')", [
            (10, "Situationist International", "situationist international"), (11, "Daniel Cohn-Bendit", "daniel cohn bendit"),
            (12, "Paris", "paris")])
        index.connection.executemany("INSERT INTO links VALUES (?, ?, 'marxists.org')", [
            (10, base + "0.htm"), (10, base + "1.htm"),  # two documents: offered the collection
            (11, base + "0.htm"),  # only one: not enough
            (12, base + "0.htm"), (12, base + "2.htm"), (12, base + "index.htm")])  # already links the collection
    variants = WikiIndex(tmp_path / "task.history-of.wiki.sqlite")
    with variants.connection:
        variants.connection.execute("INSERT INTO pages VALUES (20, 'History of May 1968', 1, 'history of may 1968', '')")
        variants.set_meta("pages_done", 1)
    loose = WikiIndex(tmp_path / "task.loose.wiki.sqlite")
    with loose.connection:  # what scan_loose keeps: the loose key in the title_key column
        loose.connection.executemany("INSERT INTO pages VALUES (?, ?, 0, ?, ?)", [
            (30, "1968 in Paris, May", "1968 may paris", ""), (31, "May 1968 (Miró)", "1968 may", "miró")])
        loose.set_meta("pages_done", 1)

    class Searcher:
        asked = []

        def _get(self, params):
            self.asked.append(params["srsearch"])
            return {"query": {"search": [{"pageid": 10, "title": "Situationist International"},  # already in the pile
                                         {"pageid": 40, "title": "Protests of 1968"}]}}

    monkeypatch.setattr(run_mia_subjects, "WikiDumps", lambda: None)
    monkeypatch.setattr(run_mia_subjects, "WikiApi", Searcher)
    queue = TaskQueue(tmp_path / "task.sqlite")
    queue.fill([{"id": 1, "kind": "subject", "page_id": 99, "folder": may.folder}], {"filled_from": "x", "collections_from": "x"})
    assert widen(queue, index, collections, "history/france", tmp_path / "task.sqlite", None)
    added = [(item["source"], item["page"], item["id"]) for item in queue.next(10)[1:]]
    assert added == [("cites", "Situationist International", 2), ("history of", "History of May 1968", 3),
                     ("loose", "1968 in Paris, May", 4), ("search", "Protests of 1968", 5)]
    assert Searcher.asked == ["Paris May 1968"]
    assert widen(queue, index, collections, "history/france", tmp_path / "task.sqlite", None)  # once each, never twice
    assert len(queue.next(10)) == 5 and Searcher.asked == ["Paris May 1968"]


def test_loose_names():
    from loose_names import acronym, aside_fits, comintern_party, loose_key
    assert loose_key("Communism in America") == loose_key("American Communism") == loose_key("American communists")
    assert loose_key("Communist Party of Australia") == loose_key("Australian Communist Party")
    assert loose_key("Socialist Party of the United States") == loose_key("American Socialist Party")
    assert loose_key("Russian Revolution") != loose_key("Soviet Revolution")  # Russia and the Soviet Union stay apart
    assert loose_key("List") == "list" and loose_key("Twists") == "twist"  # short words keep their ends
    assert aside_fits("UK", "Red Front history / erol / periodicals / britain / red front")
    assert not aside_fits("Carlyle", "The French Revolution history / france / revolution")
    assert acronym("cpgb") == "cpgb" and acronym("france") == "" and acronym("revolution") == ""
    assert comintern_party("history/international/comintern/sections/britain") == ["Communist Party of britain", "britain Communist Party"]
    assert comintern_party("history/international/comintern/sections/britain/ycl") == []


def test_hubs_and_one_collection_per_article(tmp_path, monkeypatch):
    import run_mia_subjects
    from run_mia_subjects import Collection, _citing
    hub = Collection("history/erol", "EROL", {"erol"}, 900, "index.htm", "")
    party = Collection("history/erol/poland", "Poland", {"poland"}, 5, "index.htm", "")
    other = Collection("history/erol/sri-lanka", "Sri Lanka", {"sri lanka"}, 5, "index.htm", "")
    monkeypatch.setattr(run_mia_subjects, "HUB", 2)  # EROL holds two collections here: a hub
    index = WikiIndex(tmp_path / "task.wiki.sqlite")
    base = "https://www.marxists.org/history/erol/"
    with index.connection:
        index.connection.executemany("INSERT INTO pages VALUES (?, ?, 0, ?, '')", [(1, "Polish party", "polish party"), (2, "Ceylon party", "ceylon party")])
        index.connection.executemany("INSERT INTO links VALUES (?, ?, 'marxists.org')", [
            (1, base + "poland/a.htm"), (1, base + "sri-lanka/b.htm"),  # spread across EROL: only the hub holds both
            (2, base + "sri-lanka/a.htm"), (2, base + "sri-lanka/b.htm")])
    items = _citing(index, [hub, party, other], 0, set())
    assert [(item["page"], item["folder"]) for item in items] == [("Ceylon party", "history/erol/sri-lanka")]

    queue = TaskQueue(tmp_path / "task.sqlite")
    queue.fill([{"id": 1, "kind": "subject", "page": "A", "page_id": 3, "folder": party.folder},
                {"id": 2, "kind": "subject", "page": "B", "page_id": 3, "folder": other.folder}], {"filled_from": "x"})
    bench = SubjectBench([party, other], "", queue)
    article = {"title": "Montoneros", "text": "'''Montoneros''' was a guerrilla organisation."}
    bench.judge, bench.api = FakeJudge(), FakeApi({"A": article, "B": article})
    bench.judge.about_collection = lambda collection, title, opening: {"same": True, "match": "same", "reason": "same"}
    bench.batch(queue, queue.next(10), None)
    verdicts = [verdict for _, verdict, _ in queue.judged()]
    assert verdicts[0]["result"] == "propose" and verdicts[1]["why"].startswith("the article already has a proposal: Poland")
