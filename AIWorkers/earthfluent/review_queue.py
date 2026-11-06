import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from dump_reader import WordRow


class ReviewQueue:
    """The pile of rows to check and every verdict so far, so a run can stop anywhere and pick up where it left off."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.execute("CREATE TABLE IF NOT EXISTS rows (id INTEGER PRIMARY KEY, lang TEXT, word TEXT, "
                                "verdict TEXT, checked_by TEXT, checked_at TEXT)")

    def fill(self, rows: list[WordRow]) -> int:
        with self.connection:
            self.connection.executemany("INSERT OR IGNORE INTO rows (id, lang, word) VALUES (?, ?, ?)",
                                        [(row.id, row.lang, json.dumps(asdict(row), ensure_ascii=False)) for row in rows])
        return self.connection.execute("SELECT COUNT(*) FROM rows").fetchone()[0]

    def next(self, lang: str, count: int, lesson_like: str = "%") -> list[WordRow]:
        found = self.connection.execute("SELECT word FROM rows WHERE lang = ? AND verdict IS NULL AND word LIKE ? ORDER BY id LIMIT ?",
                                        (lang, f'%"lesson": "{lesson_like}', count)).fetchall()
        return [WordRow(**json.loads(word)) for (word,) in found]

    def record(self, row: WordRow, verdict: dict, model: str, stamp: str) -> None:
        with self.connection:
            self.connection.execute("UPDATE rows SET verdict = ?, checked_by = ?, checked_at = ? WHERE id = ?",
                                    (json.dumps(verdict, ensure_ascii=False), model, stamp, row.id))

    def suspects(self, lang: str) -> list[tuple[WordRow, dict, str]]:
        found = self.connection.execute("SELECT word, verdict, checked_by FROM rows WHERE lang = ? AND verdict LIKE '%\"suspect\"%' ORDER BY id",
                                        (lang,)).fetchall()
        return [(WordRow(**json.loads(word)), json.loads(verdict), model) for word, verdict, model in found]

    def counts(self, lang: str) -> dict:
        done, left = (self.connection.execute(f"SELECT COUNT(*) FROM rows WHERE lang = ? AND verdict IS {kind} NULL", (lang,)).fetchone()[0]
                      for kind in ("NOT", ""))
        return {"checked": done, "left": left, "suspects": len(self.suspects(lang))}
