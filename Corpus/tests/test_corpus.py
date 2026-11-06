import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import corpus  # noqa: E402
from catalogue import books, display_name, web_note, work_key  # noqa: E402

LIST = r"""{\rtf1\ansi\ansicpg1252\deff0{\fonttbl{\f0\fnil\fcharset0 Arial;}}
{\*\generator Riched20 10.0.19041}\viewkind4\uc1
\pard\ul\b\fs26 Angier, Natalie - Canon\ulnone\b0\par
"The Canon: A Whirligig Tour of the Beautiful Basics of Science," by Natalie Angier, published by Houghton Mifflin Company, 2007.\par
ISBN:  978-0-618-24295-5\par
Cover:  Hardcover\par
Weight:  X\par
\par
\ul\b Kropotkin, Peter - Conquest\par
TODO: SCAN\ulnone\b0\par
"The Conquest of Bread," by Peter Kropotkin, published by G. P. Putnam\rquote s Sons, 1906.\par
Pages:  298\par
}"""


def test_a_catalogue_reads_into_books():
    found = books(LIST)
    assert [(b["author"], b["title"], b["year"]) for b in found] == [
        ("Natalie Angier", "The Canon: A Whirligig Tour of the Beautiful Basics of Science", 2007),
        ("Peter Kropotkin", "The Conquest of Bread", 1906)]
    assert found[0]["fields"] == {"isbn": "978-0-618-24295-5", "cover": "Hardcover"}  # "Weight: X" is a blank
    assert found[1]["todo"] == ["TODO: SCAN"]


def test_a_web_note_names_its_text():
    note = r"{\rtf1\ansi\pard\f0\fs26 READ:  YES\par QUOTED:  YES\par}"
    assert web_note("Notes, A Hanging, Orwell.rtf", note) == {"title": "A Hanging", "author": "Orwell", "read": True}
    assert web_note("Notes, Anarchy, Order and Chaos, Malatesta.rtf", "READ:  NO")["title"] == "Anarchy, Order and Chaos"
    assert web_note("Some other file.rtf", note) is None


def test_one_work_however_its_copies_spell_it():
    assert display_name("Angier, Natalie") == "Natalie Angier" and display_name("Alkaloidal Clinic") == "Alkaloidal Clinic"
    assert work_key("The Conquest of Bread", "Peter Kropotkin") == work_key("Conquest of Bread: A Classic", "P. Kropotkin")
    assert work_key("The Conquest of Bread", "Peter Kropotkin") != work_key("Mutual Aid", "Peter Kropotkin")


READ = r"""{\rtf1\ansi
***\tab "Conquest of Bread," Peter Kropotkin\par
"The Conquest of Bread," by Peter Kropotkin, 1892.\par
}"""
EVIDENCE = r"""{\rtf1\ansi
\tab "Conquest of Bread," Peter Kropotkin\par
Worker Abuse\par
Anarchist Society\par
\tab "Mutual Aid," Peter Kropotkin\par
Animal Abuse\par
}"""


def test_read_books_are_marked_read_with_their_evidence(tmp_path, monkeypatch):
    listing = tmp_path / "Owned.rtf"
    listing.write_text(LIST, encoding="cp1252")
    (tmp_path / "Titles.rtf").write_text(READ, encoding="cp1252")
    (tmp_path / "Lists.rtf").write_text(EVIDENCE, encoding="cp1252")
    for name, value in (("DATA", tmp_path), ("DB_PATH", tmp_path / "corpus.sqlite"), ("OWNED_LISTS", [listing]),
                        ("READ_TITLES", tmp_path / "Titles.rtf"), ("EVIDENCE", tmp_path / "Lists.rtf")):
        monkeypatch.setattr(corpus, name, value)
    corpus.import_owned()
    corpus.import_read()
    works = {w["title"]: w for w in corpus.describe()["works"]}
    assert works["The Conquest of Bread"]["status"] == "read"  # the owned copy and the read one are the same work
    assert works["The Conquest of Bread"]["evidence"] == ["Worker Abuse", "Anarchist Society"]
    assert works["Mutual Aid"]["status"] == "read" and works["Mutual Aid"]["author"] == "Peter Kropotkin"  # only in the lists
    assert works["The Canon: A Whirligig Tour of the Beautiful Basics of Science"]["status"] == "unread"


def test_copies_in_three_formats_are_one_work(tmp_path, monkeypatch):
    listing = tmp_path / "Owned.rtf"
    listing.write_text(LIST, encoding="cp1252")
    monkeypatch.setattr(corpus, "DATA", tmp_path)
    monkeypatch.setattr(corpus, "DB_PATH", tmp_path / "corpus.sqlite")
    monkeypatch.setattr(corpus, "OWNED_LISTS", [listing])
    assert corpus.import_owned() == 2 and corpus.import_owned() == 0  # a second read adds nothing
    corpus.add_copy({"title": "The Conquest of Bread", "author": "Peter Kropotkin", "format": "web",
                     "place": "https://www.marxists.org/reference/archive/kropotkin-peter/1892/bread/"})
    corpus.add_copy({"title": "Conquest of Bread", "author": "Kropotkin", "format": "digital", "place": r"E:\Books\bread.pdf"})
    works = corpus.describe()["works"]
    bread = next(w for w in works if "Bread" in w["title"])
    assert len(works) == 2 and sorted(c["format"] for c in bread["copies"]) == ["digital", "physical", "web"]
    corpus.update_work(bread["id"], {"status": "read", "realms": ["economic", "nowhere"], "phases": ["principle", "society"]})
    bread = next(w for w in corpus.describe()["works"] if "Bread" in w["title"])
    assert bread["status"] == "read" and bread["read_on"] and bread["realms"] == ["economic"]
    assert bread["phases"] == ["principle", "society"]
