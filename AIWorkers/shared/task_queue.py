import json
import sqlite3
from pathlib import Path


class TaskQueue:
    """A task's pile of items, each a JSON blob plus the verdict on it, so a run can stop anywhere and pick up where it left off."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.executescript(
            "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY, data TEXT, verdict TEXT, checked_by TEXT, checked_at TEXT);"
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);")

    def filled(self) -> bool:
        return self.meta("filled_from") is not None

    def fill(self, items: list[dict], about: dict) -> None:
        with self.connection:
            self.connection.executemany("INSERT OR REPLACE INTO items (id, data) VALUES (?, ?)",
                                        [(item["id"], json.dumps(item, ensure_ascii=False)) for item in items])
            self.connection.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in about.items()])

    def meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def next(self, count: int) -> list[dict]:
        return [json.loads(data) for (data,) in
                self.connection.execute("SELECT data FROM items WHERE verdict IS NULL ORDER BY id LIMIT ?", (count,))]

    def record(self, item_id: int, verdict: dict, model: str, stamp: str) -> None:
        with self.connection:
            self.connection.execute("UPDATE items SET verdict = ?, checked_by = ?, checked_at = ? WHERE id = ?",
                                    (json.dumps(verdict, ensure_ascii=False), model, stamp, item_id))

    def judged(self) -> list[tuple[dict, dict, str]]:
        return [(json.loads(d), json.loads(v), m) for d, v, m in
                self.connection.execute("SELECT data, verdict, checked_by FROM items WHERE verdict IS NOT NULL ORDER BY id")]

    def counts(self) -> dict:
        done, total = self.connection.execute("SELECT COUNT(verdict), COUNT(*) FROM items").fetchone()
        return {"done": done, "total": total}
