import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mia_texts import read_author, work_title  # noqa: E402
from run_mia_links import folder_of, keys_of  # noqa: E402


def test_work_title_strips_author_and_asides():
    assert work_title("Rosa Luxemburg: The Accumulation of Capital (Chap.5)", "Rosa Luxemburg") == "The Accumulation of Capital"
    assert work_title("Rosa Luxemburg: Marxist Theory and the Proletariat (1903) (extract)", "Rosa Luxemburg") == "Marxist Theory and the Proletariat"
    assert work_title("Rosa Luxemburg: Attrition or Struggle? (1910)", "Rosa Luxemburg") == "Attrition or Struggle?"


def test_another_writers_page_is_not_a_work():
    assert work_title("Paul Frölich: Introduction to the Junius Pamphlet", "Rosa Luxemburg") == ""


def test_targets_and_title_keys():
    assert folder_of("marxists.org/archive/luxemburg") == "archive/luxemburg"
    assert folder_of("https://www.marxists.org/archive/luxemburg/") == "archive/luxemburg"
    assert folder_of("luxemburg") == "archive/luxemburg"
    assert keys_of("The Junius Pamphlet") == {"the junius pamphlet", "junius pamphlet"}


def test_works_come_from_the_mirror(tmp_path):
    root = tmp_path / "archive" / "x"
    (root / "1913" / "book").mkdir(parents=True)
    (root / "index.htm").write_bytes(b"<title>Jo Writer Internet Archive</title>")
    (root / "1913" / "book" / "ch01.htm").write_bytes(b"<title>Jo Writer: A Book (Chap.1)</title>")
    (root / "1913" / "book" / "index.htm").write_bytes(b"<title>Jo Writer: A Book (1913)</title>")
    author = read_author("archive/x", tmp_path)
    assert author.name == "Jo Writer"
    assert [(work.title, work.path, len(work.pages)) for work in author.works] == [("A Book", "archive/x/1913/book/index.htm", 2)]
