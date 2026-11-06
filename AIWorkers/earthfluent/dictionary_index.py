import json
import sqlite3
from pathlib import Path

ARTICLES = ("il ", "lo ", "la ", "i ", "gli ", "le ", "un ", "uno ", "una ", "l'", "un'")


class DictionaryIndex:
    """A kaikki.org (Wiktionary) dump turned into a small SQLite lookup: word -> part of speech and English glosses."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS senses (word TEXT, pos TEXT, glosses TEXT)")
        self.connection.execute("CREATE INDEX IF NOT EXISTS by_word ON senses (word)")

    def build(self, jsonl: Path) -> int:
        # Run once per dictionary; lowercased so "Tacchino" in a title still finds "tacchino"
        if self.connection.execute("SELECT COUNT(*) FROM senses").fetchone()[0]:
            return 0
        rows = (self._row(json.loads(line)) for line in jsonl.open(encoding="utf-8"))
        with self.connection:
            self.connection.executemany("INSERT INTO senses VALUES (?, ?, ?)", (row for row in rows if row))
        return self.connection.execute("SELECT COUNT(*) FROM senses").fetchone()[0]

    def _row(self, entry: dict) -> tuple | None:
        glosses = [gloss for sense in entry.get("senses", []) for gloss in sense.get("glosses", [])[-1:]]
        if not glosses or "form of" in " ".join(glosses[:1]).lower():
            return None
        return entry["word"].lower(), entry.get("pos", ""), json.dumps(glosses[:8], ensure_ascii=False)

    def look_up(self, phrase: str) -> list[str]:
        # "Tacchino" or "il tacchino" -> ["noun: turkey (bird)", ...]
        word = phrase.strip().lower()
        for article in ARTICLES:
            if word.startswith(article) and len(word) > len(article) + 1:
                word = word[len(article):]
                break
        rows = self.connection.execute("SELECT pos, glosses FROM senses WHERE word = ?", (word,)).fetchall()
        return [f"{pos}: {'; '.join(json.loads(glosses))}" for pos, glosses in rows][:4]
