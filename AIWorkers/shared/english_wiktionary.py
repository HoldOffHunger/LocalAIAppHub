import json
import re
import sqlite3
from pathlib import Path

DUMP = Path(r"E:\ModelWorkshop\dictionaries\english\raw-wiktextract-data.jsonl")  # kaikki.org's raw dump, every language, Jan 2026
INDEX = Path(__file__).resolve().parent.parent / "data" / "english-wiktionary.sqlite"
PLAIN = re.compile(r"[a-z]+(?:['-][a-z]+)*")
# Inflection tables carry their own labels as "forms"; these are headers, not words
NOT_FORMS = {"table-tags", "inflection-template", "class", "romanization"}


class EnglishWiktionary:
    """Every English word and inflected form in Wiktionary, kept apart from Wiktionary's own misspelling entries: it lists
    "recieve" as a misspelling of receive, and counting that as a real word would protect the very slips being hunted."""

    def __init__(self, path: Path = INDEX):
        self.connection = sqlite3.connect(path)
        self.connection.executescript(
            "CREATE TABLE IF NOT EXISTS words (word TEXT PRIMARY KEY);"
            "CREATE TABLE IF NOT EXISTS misspellings (word TEXT PRIMARY KEY, correct TEXT);"
            "CREATE TABLE IF NOT EXISTS built_from (file TEXT PRIMARY KEY, bytes INTEGER);")

    def build(self, dump: Path = DUMP, log=print) -> int:
        # The dump is 26 GB, so it's read once per download: a new size means a new download
        size = dump.stat().st_size
        if self.connection.execute("SELECT 1 FROM built_from WHERE file = ? AND bytes = ?", (str(dump), size)).fetchone():
            return 0
        words, misspelt = set(), {}
        with dump.open(encoding="utf-8") as lines:
            for n, line in enumerate(lines, 1):
                if n % 1_000_000 == 0:
                    log(f"  {n:,} entries read, {len(words):,} English words")
                if '"lang_code": "en"' not in line:  # cheaper than parsing the other languages' millions of entries
                    continue
                try:
                    entry = json.loads(line)
                except ValueError:
                    continue
                if entry.get("lang_code") != "en":
                    continue
                word = entry.get("word", "").lower()
                if not PLAIN.fullmatch(word):
                    continue
                senses = entry.get("senses", [])
                if senses and all("misspelling" in sense.get("tags", []) for sense in senses):
                    targets = [alt.get("word", "") for sense in senses for alt in sense.get("alt_of", []) + sense.get("form_of", [])]
                    misspelt.setdefault(word, targets[0] if targets else "")
                    continue
                words.add(word)
                for form in entry.get("forms", []):
                    spelling = form.get("form", "").lower()
                    if PLAIN.fullmatch(spelling) and not NOT_FORMS & set(form.get("tags", [])):
                        words.add(spelling)
        with self.connection:
            self.connection.execute("DELETE FROM words")
            self.connection.execute("DELETE FROM misspellings")
            self.connection.execute("DELETE FROM built_from")
            self.connection.executemany("INSERT INTO words VALUES (?)", ((w,) for w in words))
            self.connection.executemany("INSERT INTO misspellings VALUES (?, ?)",
                                        ((w, c) for w, c in misspelt.items() if w not in words))
            self.connection.execute("INSERT INTO built_from VALUES (?, ?)", (str(dump), size))
        return len(words)

    def words(self) -> set[str]:
        return {word for (word,) in self.connection.execute("SELECT word FROM words")}

    def misspellings(self) -> dict[str, str]:
        return dict(self.connection.execute("SELECT word, correct FROM misspellings"))


if __name__ == "__main__":
    index = EnglishWiktionary()
    print("built:", index.build(), "words;", len(index.misspellings()), "misspelling entries")
