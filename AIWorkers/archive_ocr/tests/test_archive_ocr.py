import json
import sqlite3
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from archive_client import ArchiveClient, ArchiveDown, TooBig, Unavailable  # noqa: E402
from mine_queue import MineQueue  # noqa: E402
from ocr_mining import Miner  # noqa: E402
from ocr_shapes import ocr_shaped, readings  # noqa: E402
from seeds import ocr_seeds  # noqa: E402

COMMON = {"the": 9000, "their": 800, "with": 900, "such": 500, "himself": 300, "modern": 200, "sufficiently": 120, "and": 9000,
          "government": 400, "large": 300, "afford": 90, "which": 900, "there": 900, "modem": 60}
frequency = lambda word: COMMON.get(word, 0)  # noqa: E731


def test_scanners_shapes_are_told_from_typing_slips():
    # Ben's examples, 2 Nov 2026, and the shapes the hunter's list already holds
    assert ocr_shaped("suftiently", "sufficiently").families == ["ligature"]
    assert ocr_shaped("modem", "modern").families == ["rn/m"]
    assert ocr_shaped("tlieir", "their").families == ["li/h"]
    assert ocr_shaped("himfelf", "himself").families == ["long s"]
    assert ocr_shaped("ancl", "and").families == ["cl/d"]
    assert ocr_shaped("ivith", "with").families == ["vv/w"]
    assert ocr_shaped("tbe", "the").strong is False  # one look-alike letter: a weak shape
    # People's slips: a doubled letter dropped, keys swapped, a vowel for a vowel, a forgotten double f
    for wrong, right in [("druming", "drumming"), ("eyars", "years"), ("tegether", "together"), ("oficial", "official")]:
        assert ocr_shaped(wrong, right) is None


def test_readings_never_reread_a_letter_and_put_fewest_swaps_first():
    found = readings("tlie")
    assert len(found[0].steps) == 1 and "the" in [r.word for r in found if len(r.steps) == 1]
    assert all(len(r.steps) <= 2 for r in found) and "tlie" not in [r.word for r in found]


def test_mining_keeps_ocr_shaped_nonwords_with_their_line():
    text = ("Tlie king and tlie queen gave tlieir word, fuch as it was, that tbe man\nwas fufficiently modem and himfelf "
            "ivith them; a gov-\nernment of iarge means could attord it. Qwzx is no word, nor is blorpt.")
    found = Miner(frequency, {"tlieir": "their"}).mine(text)["found"]
    assert found["tlie"]["right"] == "the" and found["tlie"]["count"] == 1  # "Tlie" is capitalised: left out
    assert found["fuch"]["right"] == "such" and found["himfelf"]["right"] == "himself"
    assert found["ivith"]["right"] == "with" and found["iarge"]["right"] == "large"
    assert found["tlieir"]["known"] == "their" and "tlieir word" in found["tlieir"]["example"]
    assert "modem" not in found and "tbe" not in found  # a real word, and too short to judge (under four letters)
    assert "government" not in found and "gov" not in found  # a line-break hyphen joins the word back up
    assert "blorpt" not in found and "qwzx" not in found  # no look-alike swap makes them a word


def test_the_queue_ranks_items_by_how_many_seeds_found_them(tmp_path):
    queue = MineQueue(tmp_path / "pile.sqlite")
    queue.fill([{"wrong": "tlieir", "correct": "their", "shapes": "li→h (li/h)", "source": "GGCMS list"},
                {"wrong": "suftiently", "correct": "sufficiently", "shapes": "ft→ffic (ligature)", "source": "Wikipedia find"}],
               {"filled_from": "test"})
    first = queue.next_seed()
    assert first["wrong"] == "suftiently"  # Wikipedia's own finds go first
    hit = lambda identifier: {"identifier": identifier, "title": identifier, "year": 1800, "collection": "", "file": "", "snippet": ""}
    queue.searched(first, 20, [hit("bad"), hit("fair")], "t")
    queue.searched(queue.next_seed(), 600000, [hit("bad"), hit("other")], "t")
    assert queue.next_seed() is None
    assert [item["identifier"] for item in queue.worst_items(2, 10)] == ["bad"]
    entry = {"right": "such", "shapes": "f→s (long s)", "strong": True, "count": 3, "example": "fuch as"}
    queue.mined("bad", {"words": 100, "nonwords": 9, "found": {"fuch": entry}}, "t")
    queue.mined("other", {"words": 100, "nonwords": 9, "found": {"fuch": {**entry, "count": 1}, "blah": {**entry, "right": "blab"}}}, "t")
    found = queue.candidates()
    assert [(c["wrong"], c["items"], c["count"], c["example_item"]) for c in found] == [("fuch", 2, 4, "bad")]  # one text: no
    assert queue.counts(60)["done"] == 4 and queue.worst_items(2, 10) == []


def test_seeds_come_from_the_hunters_finds_and_list_read_only(tmp_path):
    path = tmp_path / "task-21.sqlite"
    hunter = sqlite3.connect(path)
    hunter.executescript("CREATE TABLE words (id INTEGER PRIMARY KEY, wrong TEXT, correct TEXT);"
                         "CREATE TABLE hits (id INTEGER PRIMARY KEY, word_id INTEGER, verdict TEXT, checked_at TEXT);")
    hunter.executemany("INSERT INTO words VALUES (?, ?, ?)", [(1, "suftiently", "sufficiently"), (2, "druming", "drumming"),
                                                               (3, "govemment", "government"), (4, "modem", "modern"),
                                                               (5, "chruch", "church"), (6, "unfiled", "unfilled")])
    typo = lambda reason: json.dumps({"verdict": "typo", "fix": "", "reason": reason})
    hunter.executemany("INSERT INTO hits (word_id, verdict, checked_at) VALUES (?, ?, ?)",
                       [(1, typo("ffi read as ft"), "a"), (2, typo("a missing m"), "b"), (5, typo("an OCR error in a scan"), "c")])
    hunter.commit()
    hunter.close()
    seeds = {seed["wrong"]: seed for seed in ocr_seeds(path, frequency)}
    assert set(seeds) == {"suftiently", "govemment", "chruch"}  # druming is a typist's; modem is a real word; unfiled half i/l
    assert seeds["suftiently"]["source"] == "Wikipedia find" and seeds["govemment"]["source"] == "GGCMS list"
    assert seeds["chruch"]["shapes"] == "the judge said OCR"


def fake_archive(handler) -> ArchiveClient:
    return ArchiveClient(httpx.Client(transport=httpx.MockTransport(handler)), pause=0)


def test_the_client_reads_full_text_hits_and_refuses_big_texts():
    def handler(request: httpx.Request) -> httpx.Response:
        if "page_production" in request.url.path:
            assert request.url.params["service_backend"] == "fts" and request.url.params["page_type"] == "search_results"
            return httpx.Response(200, json={"response": {"header": {"succeeded": True}, "body": {"hits": {"total": 20, "hits": [
                {"fields": {"identifier": "bim_x", "title": "The Great Duty", "year": 1741, "collection": ["ecco"],
                            "file_basename": "bim_x"}, "highlight": {"text": ["all {{{suftiently}}} iarge"]}}]}}}})
        if "/metadata/" in request.url.path:
            return httpx.Response(200, json={"result": [{"name": "bim_x_djvu.txt", "size": "4000000"}, {"name": "bim_x.pdf"}]})
        raise AssertionError(request.url)

    archive = fake_archive(handler)
    total, hits = archive.full_text("suftiently")
    assert total == 20 and hits[0]["identifier"] == "bim_x" and "iarge" in hits[0]["snippet"]
    name, size = archive.ocr_text_file("bim_x", "bim_x")
    with pytest.raises(TooBig):
        archive.ocr_text("bim_x", name, size)


def test_a_refusal_ends_the_turn_rather_than_being_taken_for_no_hits():
    archive = fake_archive(lambda request: httpx.Response(429))
    with pytest.raises(ArchiveDown):
        archive.full_text("tlieir")
    failing = fake_archive(lambda request: httpx.Response(200, json={"response": {"header": {"succeeded": False},
                                                                                  "error": {"message": "HTTP 503"}}}))
    with pytest.raises(ArchiveDown):
        failing.full_text("tlieir")


def test_a_lending_library_book_is_skipped_not_taken_for_the_archive_refusing():
    # 2 Nov 2026: The Jews of Baltimore answered 401, and ended the whole first turn
    for status in (401, 500):
        with pytest.raises(Unavailable):
            fake_archive(lambda request: httpx.Response(status)).ocr_text("JudaicaFrankfurt-English", "Blum_djvu.txt", 1000)
    with pytest.raises(ArchiveDown):
        fake_archive(lambda request: httpx.Response(503)).ocr_text("JudaicaFrankfurt-English", "Blum_djvu.txt", 1000)


def test_an_item_only_ligature_seeds_found_is_a_pdf_not_a_bad_scan(tmp_path):
    queue = MineQueue(tmp_path / "pile.sqlite")
    queue.fill([{"wrong": w, "correct": r, "shapes": f, "source": "GGCMS list"} for w, r, f in
                [("identifed", "identified", "f→fi (ligature)"), ("confict", "conflict", "f→fl (ligature)"),
                 ("tlieir", "their", "li→h (li/h)")]], {"filled_from": "test"})
    hit = lambda identifier: {"identifier": identifier, "title": "", "year": None, "collection": "", "file": "", "snippet": ""}
    for seed, items in zip(range(3), (["SEv3", "scan"], ["SEv3", "scan"], ["scan"])):
        queue.searched(queue.next_seed(), 1, [hit(i) for i in items], "t")
    assert [item["identifier"] for item in queue.worst_items(2, 10)] == ["scan"]
