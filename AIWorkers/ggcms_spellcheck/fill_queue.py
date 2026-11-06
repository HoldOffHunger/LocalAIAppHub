import sys
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from spellchecker import SpellChecker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dump_tables import DumpTables  # noqa: E402
from ggcms_words import british_spellings, known_misspellings  # noqa: E402
from text_words import TextWords  # noqa: E402

ENGLISH = {"", "en", "eng", "english"}
COMMON_ACROSS = 3  # an unknown word used in this many texts is the site's vocabulary, not a typo


def gather(dump: Path, log=print) -> tuple[list[dict], dict]:
    """The mechanical pass: every English text's suspicious words, after the site's own vocabulary is taken out."""
    log(f"reading {dump}")
    entries, tags, bodies = {}, set(), []
    for table, row in DumpTables(dump).rows({"Entry", "Tag", "TextBody"}):
        if table == "Entry":
            entries[int(row["id"])] = (row["Title"], row["Code"], row["Publish"] == "1")
        elif table == "Tag":
            tags.update(row["Tag"].lower().split())  # Ben's own tags: names and terms he has already approved
        elif row.get("SpellCheckImmune") == "1":
            continue  # invented words on purpose (entry 7090's 4,255 coinages), ticked on modify.php
        elif (row.get("Language") or "").lower() in ENGLISH and row["Text"]:
            bodies.append((int(row["id"]), int(row["Entryid"]), row["Text"]))
    dictionary = SpellChecker(distance=1)
    # The lists pair some real words ("were" -> "where", "wine" -> "whine"): those only count as rare unknown words would
    known = {wrong: right for wrong, right in known_misspellings().items() if not dictionary.known([wrong])}
    reader = TextWords(dictionary, british_spellings() | tags, known)
    found, spread = [], Counter()
    for number, (body_id, entryid, markup) in enumerate(bodies, 1):
        title, code, published = entries.get(entryid, ("(missing entry)", "", False))
        if not published:
            continue
        words = reader.read(markup)
        spread.update(w for w, c in words.items() if not c.known and " " not in w)
        found.append({"id": body_id, "entryid": entryid, "title": title, "code": code, "words": words})
        if number % 1000 == 0:
            log(f"read {number} of {len(bodies)} texts")
    texts = []
    for text in found:
        keep = [_suggested(reader.dictionary, c) for w, c in text["words"].items() if c.known or spread[w] < COMMON_ACROSS]
        if keep := [asdict(c) for c in keep if c]:
            texts.append({**text, "words": keep})
    about = {"filled_from": str(dump), "texts_read": len(found), "clean_texts": len(found) - len(texts), "tags": len(tags),
             "site_vocabulary": sum(1 for w in spread if spread[w] >= COMMON_ACROSS)}
    return texts, about


def _suggested(dictionary: SpellChecker, candidate):
    # A word with no dictionary word one edit away is usually foreign or coined, not a slip of the finger
    if candidate.known or " " in candidate.word:  # a split already carries its joined word
        return candidate
    candidate.suggestion = dictionary.correction(candidate.word.lower()) or ""
    return candidate if candidate.suggestion and candidate.suggestion != candidate.word.lower() else None


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
    from dump_tables import newest_dump  # noqa: E402

    texts, about = gather(newest_dump(sys.argv[1] if len(sys.argv) > 1 else "revoltlib"))
    print(about)
    print("texts to judge:", len(texts), "words to judge:", sum(len(t["words"]) for t in texts),
          "known misspellings:", sum(1 for t in texts for w in t["words"] if w["known"]))
    for text in texts[:6]:
        print(text["entryid"], text["title"], [(w["word"], w["known"] or w["suggestion"]) for w in text["words"][:8]])
