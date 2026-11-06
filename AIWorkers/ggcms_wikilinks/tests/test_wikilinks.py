import gzip
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))

import run_wikilinks  # noqa: E402
from citations import find_citation, full_text_elsewhere, lead  # noqa: E402
from link_check import overlap  # noqa: E402
from our_texts import our_site, where_from  # noqa: E402
from url_tools import domain_keys, original, same_page, wiki_url  # noqa: E402
from wiki_dumps import WikiDumps, row_values  # noqa: E402
from wiki_index import WikiIndex, title_key  # noqa: E402

GGCMS_DUMP = """CREATE TABLE `Entry` (
  `id` int NOT NULL,
  `Title` varchar(255) NOT NULL,
  `Publish` tinyint(1) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
INSERT INTO `Entry` VALUES (1,'RevoltLib',1),(2,'Anarchism',1),(3,'The Conquest of Bread',1),(4,'Chapter 1',1),(5,'Peter Kropotkin',1),(6,'Draft',0);
CREATE TABLE `Assignment` (
  `id` int NOT NULL,
  `Parentid` int NOT NULL,
  `Childid` int NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
INSERT INTO `Assignment` VALUES (10,1,2),(11,2,3),(12,3,4),(13,2,5),(40,5,4),(14,3,6);
CREATE TABLE `Association` (
  `id` int NOT NULL,
  `Entryid` int NOT NULL,
  `ChosenEntryid` int NOT NULL,
  `Type` varchar(64) NOT NULL,
  `SubType` varchar(64) NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
INSERT INTO `Association` VALUES (1,3,5,'Role','Author');
CREATE TABLE `TextBody` (
  `id` int NOT NULL,
  `Text` mediumtext NOT NULL,
  `Source` varchar(512) NOT NULL,
  `Language` varchar(32) NOT NULL,
  `Entryid` int NOT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB;
INSERT INTO `TextBody` VALUES (1,'<p>The chapter text.</p>','https://web.archive.org/web/2009/http://www.oldsite.org/bread/ch1.html','en',4),(2,'<p>Book text.</p><p>Source: http://another.net/bread/</p>','','en',3),(3,'<p>A draft.</p>','http://x.org/','en',6);
"""


def write_gz(path: Path, text: str) -> Path:
    with gzip.open(path, "wt", encoding="utf-8") as out:
        out.write(text)
    return path


def test_urls_agree_however_they_are_spelled():
    assert same_page("http://www.OldSite.org/bread/index.html") == same_page("https://oldsite.org/bread/") == "oldsite.org/bread"
    assert original("https://web.archive.org/web/20090101000000/http://oldsite.org/a") == "http://oldsite.org/a"
    assert wiki_url(b"http://org.oldsite.www.", b"/bread/ch1.html") == "http://www.oldsite.org/bread/ch1.html"
    assert domain_keys(b"https://org.oldsite.www.")[:2] == [b"org.oldsite.", b"org.oldsite.www."]


def test_wikipedia_rows_are_one_a_line_with_escapes():
    assert row_values(b"(2,3850540,'http://edu.berkeley.www.','/it\\'s/'),\n", 4) == [b"2", b"3850540", b"http://edu.berkeley.www.", b"/it's/"]
    assert title_key("The_Conquest_of_Bread_(book)") == ("the conquest of bread", "book")
    assert title_key("What Is Property?") == ("what is property", "")


def test_our_side_uses_the_oldest_assignment_and_unwraps_archived_sources(tmp_path):
    site = our_site(write_gz(tmp_path / "revoltlib.sql.gz", GGCMS_DUMP))
    chapter = next(text for text in site.texts if text.entryid == 4)
    assert chapter.permalink == 12 and site.link("revoltlib.com", 4) == "https://revoltlib.com/?id=12"  # 12, not the later 40
    assert chapter.sources == ["http://www.oldsite.org/bread/ch1.html"] and chapter.source_from == "Source"
    assert chapter.work == 3 and chapter.author == 5
    book = next(text for text in site.texts if text.entryid == 3)
    assert book.sources == ["http://another.net/bread/"] and book.source_from == "body"
    assert 6 not in {text.entryid for text in site.texts}  # unpublished


def test_source_names_become_sites():
    assert where_from("TheAnarchistLibrary.org", "")[1:] == (["theanarchistlibrary.org"], "Source", [])
    assert where_from("Marxists.org & RevoltLib.com & AnarchyArchives", "")[1] == ["marxists.org", "revoltlib.com", "dwardmac.pitzer.edu"]
    assert where_from("University of Virginia Library", "")[1:] == ([], "Source", ["university of virginia library"])
    # with no Source, only a closing "Source:" line counts; a footnote's link is not where the text came from
    assert where_from("", "<p>See http://footnote.org/a for more.</p><p>Source: http://spunk.org/texts/x.html</p>")[:3] == \
        (["http://spunk.org/texts/x.html"], ["spunk.org"], "body")
    assert where_from("", "<p>See http://footnote.org/a for more.</p>") == ([], [], "", [])


ARTICLE = """'''''The Conquest of Bread''''' is an 1892 book by [[Peter Kropotkin]].{{Infobox book}}
== Reception ==
It was praised.<ref>{{cite web |url=http://oldsite.org/bread/ch1.html |title=Chapter 1 |url-status=dead}}</ref>
Also [http://www.another.net/bread/ the whole book]{{dead link|date=May 2020}} and http://third.org/x
<ref>{{cite web |url=http://kept.org/a |archive-url=https://web.archive.org/web/1/http://kept.org/a |title=A}}</ref>
== External links ==
* {{Gutenberg|no=23428}}
"""


def test_citations_are_found_with_their_marks_and_rewritten_with_our_link():
    cite = find_citation(ARTICLE, "https://www.oldsite.org/bread/ch1.html")
    assert cite.shape == "template" and cite.marked_dead and not cite.archived and cite.section == "Reception"
    assert cite.with_our_link("https://revoltlib.com/?id=12", "x", "RevoltLib") == \
        "{{cite web |url=https://revoltlib.com/?id=12 |title=Chapter 1 |via=RevoltLib}}"
    bracketed = find_citation(ARTICLE, "http://another.net/bread")
    assert bracketed.shape == "bracketed" and bracketed.marked_dead
    assert bracketed.with_our_link("https://revoltlib.com/?id=11", "http://www.another.net/bread/", "RevoltLib") == \
        "[https://revoltlib.com/?id=11 the whole book]"
    assert find_citation(ARTICLE, "http://third.org/x").shape == "bare"
    assert find_citation(ARTICLE, "http://kept.org/a").archived
    assert find_citation(ARTICLE, "http://nowhere.org/") is None
    assert full_text_elsewhere(ARTICLE) == ["{{Gutenberg}} template"]
    assert lead(ARTICLE) == "The Conquest of Bread is an 1892 book by Peter Kropotkin."


def test_overlap_counts_running_text_not_loose_words():
    ours = "the land belongs to all and the fruit of labour belongs to those who labour for it in common"
    assert overlap(ours, ours) == 1.0
    assert overlap("all labour belongs to the common land and fruit those who for it", ours) == 0.0


def test_the_scans_resume_and_the_pile_is_built(tmp_path, monkeypatch):
    dumps = WikiDumps(tmp_path / "wikipedia")
    links = ["INSERT INTO `externallinks` VALUES"] + [f"({n},999,'http://com.unrelated.','/{n}')," for n in range(5)] + [
        "(20,100,'http://org.oldsite.www.','/bread/ch1.html'),", "(21,101,'http://org.deadsite.','/old/text.html'),",
        "(22,102,'https://com.revoltlib.','/?id=11'),", "(23,103,'http://com.unrelated.','/x');"]
    write_gz(dumps.path("externallinks"), "\n".join(links) + "\n")
    pages = ["INSERT INTO `page` VALUES", "(100,0,'Bread_riots',0,0),", "(101,0,'Dead_things',0,0),", "(102,0,'Peter_Kropotkin',0,0),",
             "(103,0,'Unrelated',0,0),", "(104,0,'The_Conquest_of_Bread',0,0),", "(105,0,'The_Conquest_of_Bread_(film)',0,0),",
             "(106,1,'The_Conquest_of_Bread',0,0);"]
    write_gz(dumps.path("page"), "\n".join(pages) + "\n")
    index = WikiIndex(tmp_path / "task.wiki.sqlite")
    monkeypatch.setattr("wiki_index.CHECKPOINT", 2)
    assert index.scan_links(dumps, {"oldsite.org", "deadsite.org", "revoltlib.com"}, None)
    assert sorted(url for _, url, _ in index.connection.execute("SELECT * FROM links")) == [
        "http://deadsite.org/old/text.html", "http://www.oldsite.org/bread/ch1.html", "https://revoltlib.com/?id=11"]
    assert index.scan_pages(dumps, {"the conquest of bread", "peter kropotkin"}, None)
    index.save_ours(our_site(write_gz(tmp_path / "revoltlib.sql.gz", GGCMS_DUMP)), "revoltlib.com")
    index.set_domain_state("deadsite.org", "dead", "the domain no longer exists")
    texts = index.texts()
    works, authors = run_wikilinks._works_and_authors(index, texts)
    pile = run_wikilinks._pile(index, texts, works, authors, "revoltlib.com")
    assert [(item["kind"], item["page"]) for item in pile] == [
        ("link", "Bread riots"), ("near", "Dead things"), ("work", "The Conquest of Bread")]  # the film is left out, and Kropotkin already links us
    assert pile[0]["entry"] == 4 and [item["id"] for item in pile] == [1, 2, 3]


class FakeApi:
    def __init__(self, articles):
        self.pages = articles

    def articles(self, titles):
        return {title: {"id": 1, "title": title, "text": self.pages[title]} for title in titles if title in self.pages}


class FakeCheck:
    def __init__(self, archived_text):
        self.text = archived_text
        self.rested = False

    def resting(self):
        return self.rested

    def archive_refused(self):
        self.rested = True
        return 300.0

    def check(self, url):
        return {"state": "dead", "why": "the domain no longer exists", "text": ""}

    def archived(self, url):
        return {"url": f"https://web.archive.org/web/2009/{url}", "timestamp": "2009"}

    def archived_text(self, snapshot):
        return self.text


def test_the_workbench_proposes_edits_and_writes_them_out(tmp_path, monkeypatch):
    index = WikiIndex(tmp_path / "task.wiki.sqlite")
    chapter = "<p>" + " ".join(f"word{n}" for n in range(200)) + "</p>"
    dump = GGCMS_DUMP.replace("'<p>The chapter text.</p>'", f"'{chapter}'")
    index.save_ours(our_site(write_gz(tmp_path / "revoltlib.sql.gz", dump)), "revoltlib.com")
    index.set_domain_state("oldsite.org", "dead", "the domain no longer exists")
    bench = run_wikilinks.Workbench(index, "revoltlib", "")
    bench.api = FakeApi({"Bread riots": ARTICLE, "The Conquest of Bread": ARTICLE})
    bench.check = FakeCheck(" ".join(f"word{n}" for n in range(150)))
    queue = run_wikilinks.TaskQueue(tmp_path / "task.sqlite")
    queue.fill([{"id": 1, "kind": "link", "page": "Bread riots", "url": "http://oldsite.org/bread/ch1.html", "entry": 4, "source_from": "Source"},
                {"id": 2, "kind": "near", "page": "Bread riots", "url": "http://oldsite.org/bread/ch1.html", "domain": "oldsite.org"},
                {"id": 3, "kind": "work", "page": "The Conquest of Bread", "entry": 3, "title": "The Conquest of Bread", "aside": "book"}],
               {"filled_from": "test"})
    bench.batch(queue, queue.next(10), None)
    verdicts = {item["id"]: verdict for item, verdict, _ in queue.judged()}
    assert verdicts[1]["result"] == "propose" and verdicts[1]["confidence"] == "high" and verdicts[1]["link"] == "https://revoltlib.com/?id=12"
    assert verdicts[2]["entry"] == 4 and verdicts[2]["why"].startswith("100%")
    assert verdicts[3]["result"] == "propose" and verdicts[3]["elsewhere"] == ["{{Gutenberg}} template"]  # titled a book, names Kropotkin: no judge needed
    results = tmp_path / "task.results.txt"
    assert run_wikilinks.write_results(queue, index, results, "revoltlib") == 3
    page = results.read_text(encoding="utf-8")
    assert "DEAD LINKS WIKIPEDIA HAS MARKED (2)" in page and "replace with: {{cite web |url=https://revoltlib.com/?id=12" in page
    assert "* [https://revoltlib.com/?id=11 Full text of ''The Conquest of Bread''] at RevoltLib" in page


def test_front_pages_and_robot_refusals_are_not_dead_copies(tmp_path):
    # kaya.com, 2 Nov 2026: a publisher's home page that turned the robot away, offered as a dead copy of a book
    class Refusing(FakeCheck):
        def check(self, url):
            return {"state": "unsure", "why": "the site answered 403 (it may just refuse robots)", "text": ""}
    index = WikiIndex(tmp_path / "task.wiki.sqlite")
    index.save_ours(our_site(write_gz(tmp_path / "revoltlib.sql.gz", GGCMS_DUMP)), "revoltlib.com")
    bench = run_wikilinks.Workbench(index, "revoltlib", "")
    bench.api, bench.check = FakeApi({"Bread riots": ARTICLE}), Refusing("")
    queue = run_wikilinks.TaskQueue(tmp_path / "task.sqlite")
    queue.fill([{"id": 1, "kind": "link", "page": "Bread riots", "url": "http://www.another.net/", "entry": 4, "source_from": "Source"},
                {"id": 2, "kind": "link", "page": "Bread riots", "url": "http://oldsite.org/bread/ch1.html", "entry": 4, "source_from": "Source"}],
               {"filled_from": "test"})
    bench.batch(queue, queue.next(10), None)
    verdicts = {item["id"]: verdict for item, verdict, _ in queue.judged()}
    assert verdicts[1]["result"] == "skip" and "front page" in verdicts[1]["why"]
    assert verdicts[2]["result"] == "skip" and "may still work" in verdicts[2]["why"]
    # and a proposal made before the rule existed is withdrawn when the results are written
    old = {"result": "propose", "dead": "unsure", "replacement": "[http://kaya.com Kaya]", "as_written": "[http://kaya.com Kaya]"}
    assert run_wikilinks._withdrawn({"kind": "link", "url": "http://kaya.com/"}, old)


def test_an_archive_outage_leaves_its_items_in_the_pile_and_the_rest_carry_on(tmp_path):
    class Down(FakeCheck):
        asked = 0

        def archived(self, url):
            Down.asked += 1
            raise run_wikilinks.ArchiveDown("the Internet Archive answered 429")
    index = WikiIndex(tmp_path / "task.wiki.sqlite")
    index.set_domain_state("oldsite.org", "dead", "gone")
    bench = run_wikilinks.Workbench(index, "revoltlib", "")
    bench.api, bench.check = FakeApi({"Bread riots": ARTICLE}), Down("")
    queue = run_wikilinks.TaskQueue(tmp_path / "task.sqlite")
    queue.fill([{"id": 1, "kind": "near", "page": "Bread riots", "url": "http://oldsite.org/bread/ch1.html", "domain": "oldsite.org"},
                {"id": 2, "kind": "near", "page": "Bread riots", "url": "http://oldsite.org/bread/ch2.html", "domain": "oldsite.org"},
                {"id": 3, "kind": "link", "page": "Bread riots", "url": "http://elsewhere.org/gone.html", "entry": 4, "source_from": "Source"}],
               {"filled_from": "test"})
    bench.batch(queue, queue.next(10), None)
    assert Down.asked == 1  # the second Archive item waits without asking
    assert queue.counts() == {"done": 1, "total": 3} and [item["id"] for item in queue.next(10)] == [1, 2]


def test_the_archived_copy_comes_from_the_cdx_index():
    # archive.org/wayback/available refused us for days (4 Nov 2026); CDX's newest good capture is the copy now
    import httpx
    from link_check import LinkCheck

    def answer(request):
        if "nothing" in str(request.url):
            return httpx.Response(200, text="")
        return httpx.Response(200, json=[["timestamp", "original"], ["20010101000000", "http://a.org/x"], ["20050101000000", "http://a.org/x"]])

    check = LinkCheck(httpx.Client(transport=httpx.MockTransport(answer)))
    check.asked["archive.org"] = -1e9  # no politeness pause in a test
    assert check.archived("http://a.org/x") == {"url": "https://web.archive.org/web/20050101000000/http://a.org/x", "timestamp": "20050101000000"}
    check.asked["archive.org"] = -1e9
    assert check.archived("http://nothing.org/") is None
