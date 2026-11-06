import re
import sys
from collections import defaultdict
from pathlib import Path

from spellchecker import SpellChecker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ggcms_spellcheck"))
from dump_tables import DumpTables  # noqa: E402
from fill_queue import ENGLISH  # noqa: E402
from ggcms_words import british_spellings, known_misspellings  # noqa: E402
from text_words import TextWords  # noqa: E402
from wiktionary_words import WiktionaryWords  # noqa: E402

CONTEXTS = 3  # sentences kept per word, each from a different text, for the judge and for Claude's confirmation
MIN_TEXTS = 2  # a slip in one text is that text's fix (the spellcheck's new-misspellings file has those); in two it's a habit
TAIL = 20  # judged first: a real slip recurs in a handful of texts; the head (hundreds of texts) is Latin, French and jargon
FOREIGN_DROP = 6  # a word this long that a Wiktionary has is a quotation; shorter ones collide with slips ("teh" is Indonesian)


def shape(word: str, contexts: list[dict]) -> str:
    """What the word's uses say it is before anyone judges it. On 26 Oct 2026 the head of RevoltLib's list was all halves
    ("socio" of socio-political, "zation" of a line-broken organi- zation) and abbreviations ("etc", "vol"), and gemma
    called socio a typo. A rule that a fixed neighbour marks a set phrase ("ipso facto") was tried and dropped: a fixed
    neighbour mostly means one text published three times, and it threw out satisfed, srategy and necassary."""
    uses = [(ctx[:m.start()], ctx[m.end():]) for ctx in (c["context"] for c in contexts)
            for m in re.finditer(r"(?<![A-Za-z'])" + re.escape(word) + r"(?![A-Za-z])", ctx, re.I)]
    if not uses:
        return ""
    if sum(bool(re.search(r"-\s?$", before) or re.match(r"\s?-", after)) for before, after in uses) * 2 > len(uses):
        return "half"
    if len(contexts) >= CONTEXTS and len(word) <= 5 and all(after.startswith(".") for _, after in uses):
        return "abbreviation"
    return ""


def harvest(dump: Path, words: WiktionaryWords, log=print) -> tuple[list[dict], dict]:
    """The mechanical pass: every unknown lowercase word on the site's published English texts, gathered across texts,
    each with a dictionary word one or two edits away. Words GGCMS's lists already have, and splits, are left out:
    splits are a text's own repair, not a misspelling to teach the lists."""
    log(f"reading {dump}")
    entries, tags, bodies = {}, set(), []
    for table, row in DumpTables(dump).rows({"Entry", "Tag", "TextBody"}):
        if table == "Entry":
            entries[int(row["id"])] = (row["Title"], row["Publish"] == "1")
        elif table == "Tag":
            tags.update(row["Tag"].lower().split())
        elif row.get("SpellCheckImmune") == "1":
            continue  # invented words on purpose, ticked on modify.php: not slips to teach the lists
        elif (row.get("Language") or "").lower() in ENGLISH and row["Text"]:
            bodies.append((int(row["Entryid"]), row["Text"]))
    near = SpellChecker(distance=2)
    known = known_misspellings()
    reader = TextWords(SpellChecker(distance=1), british_spellings() | tags, known)
    seen: dict[str, dict] = defaultdict(lambda: {"texts": 0, "count": 0, "contexts": []})
    texts = 0
    for number, (entryid, markup) in enumerate(bodies, 1):
        title, published = entries.get(entryid, ("", False))
        if not published:
            continue
        texts += 1
        for word, candidate in reader.read(markup).items():
            if candidate.known or " " in word:
                continue
            found = seen[word]
            found["texts"] += 1
            found["count"] += candidate.count
            if len(found["contexts"]) < CONTEXTS:
                found["contexts"].append({"entryid": entryid, "title": title, "context": candidate.context})
        if number % 2000 == 0:
            log(f"read {number} of {len(bodies)} texts, {len(seen)} unknown words so far")
    items, foreign, unsuggested, once, shapes = [], 0, 0, 0, {"half": 0, "abbreviation": 0}
    for word, found in seen.items():
        if found["texts"] < MIN_TEXTS:
            once += 1
            continue
        if kind := shape(word, found["contexts"]):
            shapes[kind] += 1
            continue
        langs = words.languages(word)
        if langs and len(word) >= FOREIGN_DROP:
            foreign += 1
            continue
        suggestion = reader.dictionary.correction(word) or ""  # one edit is quick; two only when one finds nothing
        if not suggestion or suggestion == word:
            suggestion = near.correction(word) or ""
        if not suggestion or suggestion == word:
            unsuggested += 1  # nothing real two edits away: coined, foreign or a name, not a slip
            continue
        items.append({"word": word, "suggestion": suggestion, "wiktionary": langs, **found})
    # The tail first, most texts first within it: on 26 Oct 2026 the head's three "typos" were versa, hoc and anigh, all wrong,
    # while militaty, migt and necassary sat in 2 and 3 texts
    items.sort(key=lambda item: (item["texts"] > TAIL, -item["texts"], -item["count"], item["word"]))
    for number, item in enumerate(items, 1):
        item["id"] = number
    about = {"filled_from": str(dump), "texts_read": texts, "unknown_words": len(seen), "in_one_text": once, "halves": shapes["half"],
             "abbreviations": shapes["abbreviation"], "real_elsewhere": foreign, "nothing_near": unsuggested, "candidates": len(items)}
    return items, about
