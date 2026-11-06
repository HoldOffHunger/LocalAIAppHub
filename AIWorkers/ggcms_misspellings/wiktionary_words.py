import json
import re
import sqlite3
from pathlib import Path

DICTIONARIES = Path(r"E:\ModelWorkshop\dictionaries")
PLAIN = re.compile(r"[a-z]+(?:'[a-z]+)*")  # only the spellings the harvest can meet: lowercase, unaccented


class WiktionaryWords:
    """Every word and inflected form in the thirteen kaikki.org Wiktionaries, and which languages have it. A harvested
    "typo" that is a real word somewhere ("abbate", Italian for abbot) is a quotation, not a slip."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS words (word TEXT PRIMARY KEY, langs TEXT)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS built_from (file TEXT PRIMARY KEY, bytes INTEGER)")

    def build(self, folder: Path = DICTIONARIES, log=print) -> int:
        # Built once per set of dictionaries: on 26 Oct 2026, 11 of the 13 downloads were found cut short, so a dictionary
        # downloaded again (a new size) rebuilds the index rather than leaving it on the partial one
        files = sorted(folder.glob("*/kaikki.org-dictionary-*.jsonl"))
        sizes = {str(jsonl): jsonl.stat().st_size for jsonl in files}
        if sizes == dict(self.connection.execute("SELECT file, bytes FROM built_from")):
            return 0
        found: dict[str, set[str]] = {}
        for jsonl in files:
            language = jsonl.stem.removeprefix("kaikki.org-dictionary-")
            log(f"indexing {language}")
            for line in jsonl.open(encoding="utf-8"):
                try:
                    entry = json.loads(line)
                except ValueError:
                    log(f"  {language}: a broken line skipped (a cut-short download ends on one)")
                    continue
                for spelling in [entry.get("word", ""), *(form.get("form", "") for form in entry.get("forms", []))]:
                    spelling = spelling.lower()
                    if PLAIN.fullmatch(spelling):
                        found.setdefault(spelling, set()).add(language)
        with self.connection:
            self.connection.execute("DELETE FROM words")
            self.connection.execute("DELETE FROM built_from")
            self.connection.executemany("INSERT INTO words VALUES (?, ?)", ((w, ",".join(sorted(l))) for w, l in found.items()))
            self.connection.executemany("INSERT INTO built_from VALUES (?, ?)", sizes.items())
        return len(found)

    def languages(self, word: str) -> str:
        row = self.connection.execute("SELECT langs FROM words WHERE word = ?", (word.lower(),)).fetchone()
        return row[0] if row else ""
