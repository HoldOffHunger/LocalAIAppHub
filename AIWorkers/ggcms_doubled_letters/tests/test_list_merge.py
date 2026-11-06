import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "shared"))
import list_merge  # noqa: E402

PAGE = "<?php\n\tclass EnglishMisspellingsWords_B {\n\t\tpublic function EnglishMisspellingsWords() {\n\t\t\treturn [\n" \
       "\t\t\t\t'babble'=>[\n\t\t\t\t\t'bable',\n\t\t\t\t],\n" \
       "\t\t\t\t'beautiful'=>[\n\t\t\t\t\t'beatiful',\n\t\t\t\t],\n" \
       "\t\t\t];\r\n\t\t}\r\n\t}\r\n?>"


def lists(tmp_path, monkeypatch):
    folder = tmp_path / "EnglishMisspellings"
    folder.mkdir()
    (folder / "EnglishMisspellingsWords_B.php").write_bytes(PAGE.encode())
    for letter in ("0", "K"):
        (folder / f"EnglishMisspellingsWords_{letter}.php").write_bytes(PAGE.replace("_B", "_" + letter).encode())
    monkeypatch.setattr(list_merge, "WORDS", tmp_path)
    return folder


def test_a_slip_joins_its_words_block_or_starts_one_in_sorted_place(tmp_path, monkeypatch):
    folder = lists(tmp_path, monkeypatch)
    added = list_merge.merge({"beautyful": "beautiful", "beatiful": "beautiful", "bolth": "both", "bable": "babble",
                              "babbel": "babble"}, log=lambda line: None)
    page = (folder / "EnglishMisspellingsWords_B.php").read_bytes().decode()
    assert added == 3  # beatiful and bable were already there
    assert "'beautiful'=>[\n\t\t\t\t\t'beatiful',\n\t\t\t\t\t'beautyful',\n\t\t\t\t]," in page
    assert "'babble'=>[\n\t\t\t\t\t'bable',\n\t\t\t\t\t'babbel',\n\t\t\t\t]," in page
    assert page.index("'beautiful'") < page.index("'both'=>[") < page.index("\t\t\t];")


def test_quotes_are_escaped_and_odd_first_letters_go_to_zero(tmp_path, monkeypatch):
    folder = lists(tmp_path, monkeypatch)
    list_merge.merge({"kind've": "kind of", "3rd-degre": "3rd-degree"}, log=lambda line: None)
    # The page's tail is CRLF, so a block added there is CRLF too
    assert "'kind of'=>[\r\n\t\t\t\t\t'kind\\'ve',\r\n\t\t\t\t],\r\n" in (folder / "EnglishMisspellingsWords_K.php").read_bytes().decode()
    assert (folder / "EnglishMisspellingsWords_0.php").read_bytes() == PAGE.replace("_B", "_0").encode()  # code, not a list
