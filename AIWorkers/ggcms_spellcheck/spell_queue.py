import json
import sqlite3
from pathlib import Path


class SpellQueue:
    """One task's pile: every text with words worth a look, and the verdict on each, so a run resumes where the last one stopped."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.executescript(
            "CREATE TABLE IF NOT EXISTS texts (id INTEGER PRIMARY KEY, entryid INTEGER, title TEXT, code TEXT, words TEXT, "
            "verdicts TEXT, checked_by TEXT, checked_at TEXT);"
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);")
        # A long text's verdicts so far, its first words in order: entry 7090's 4,255 words outlasted the 03:00-09:00 shift
        # three nights running and were thrown away each time, so a text is now judged and kept a part at a time
        if "partial" not in {row[1] for row in self.connection.execute("PRAGMA table_info(texts)")}:
            self.connection.execute("ALTER TABLE texts ADD COLUMN partial TEXT")

    def filled(self) -> bool:
        return self.meta("filled_from") is not None

    def fill(self, texts: list[dict], about: dict) -> None:
        with self.connection:
            self.connection.executemany("INSERT OR REPLACE INTO texts (id, entryid, title, code, words) VALUES (?, ?, ?, ?, ?)",
                                        [(t["id"], t["entryid"], t["title"], t["code"], json.dumps(t["words"], ensure_ascii=False))
                                         for t in texts])
            self.connection.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in about.items()])

    def refill_pending(self, texts: list[dict], about: dict) -> None:
        # A newer reader's pile, for the texts nobody has judged yet; judged texts keep their words and verdicts
        judged = {i for (i,) in self.connection.execute("SELECT id FROM texts WHERE verdicts IS NOT NULL OR partial IS NOT NULL")}
        with self.connection:
            self.connection.execute("DELETE FROM texts WHERE verdicts IS NULL AND partial IS NULL")
            self.connection.executemany("INSERT INTO texts (id, entryid, title, code, words) VALUES (?, ?, ?, ?, ?)",
                                        [(t["id"], t["entryid"], t["title"], t["code"], json.dumps(t["words"], ensure_ascii=False))
                                         for t in texts if t["id"] not in judged])
            self.connection.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                                        [(k, str(v)) for k, v in about.items() if k != "filled_from"])

    def meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def next(self, count: int) -> list[dict]:
        found = self.connection.execute(
            "SELECT id, entryid, title, code, words, partial FROM texts WHERE verdicts IS NULL ORDER BY id LIMIT ?", (count,)).fetchall()
        return [{"id": i, "entryid": e, "title": t, "code": c, "words": json.loads(w), "done": json.loads(d or "[]")}
                for i, e, t, c, w, d in found]

    def record(self, text_id: int, verdicts: list[dict], model: str, stamp: str) -> None:
        with self.connection:
            self.connection.execute("UPDATE texts SET verdicts = ?, checked_by = ?, checked_at = ? WHERE id = ?",
                                    (json.dumps(verdicts, ensure_ascii=False), model, stamp, text_id))

    def record_part(self, text: dict, verdicts: list[dict], model: str, stamp: str) -> None:
        # The next words of a text after the ones already done; the text is finished when they reach its last word
        text["done"] = text["done"] + verdicts
        if len(text["done"]) >= len(text["words"]):
            with self.connection:
                self.connection.execute("UPDATE texts SET partial = NULL WHERE id = ?", (text["id"],))
            self.record(text["id"], text["done"], model, stamp)
        else:
            with self.connection:
                self.connection.execute("UPDATE texts SET partial = ? WHERE id = ?", (json.dumps(text["done"], ensure_ascii=False), text["id"]))

    def typos(self) -> list[tuple[dict, dict]]:
        # Every word judged a typo, with the text it came from
        found = []
        for i, e, t, c, verdicts in self.connection.execute(
                "SELECT id, entryid, title, code, verdicts FROM texts WHERE verdicts LIKE '%\"typo\"%' ORDER BY entryid"):
            text = {"id": i, "entryid": e, "title": t, "code": c}
            found.extend((text, v) for v in json.loads(verdicts) if v["verdict"] == "typo")
        return found

    def counts(self) -> dict:
        done, total = self.connection.execute("SELECT COUNT(verdicts), COUNT(*) FROM texts").fetchone()
        words = self.connection.execute("SELECT COALESCE(SUM(json_array_length(words)), 0) FROM texts").fetchone()[0]
        return {"done": done, "total": total, "words to judge": words, "typos": len(self.typos()),
                "clean texts": int(self.meta("clean_texts") or 0)}
