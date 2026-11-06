import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS seeds (id INTEGER PRIMARY KEY, wrong TEXT UNIQUE, correct TEXT, shapes TEXT, source TEXT,
                                  total INTEGER, searched_at TEXT);
CREATE TABLE IF NOT EXISTS items (identifier TEXT PRIMARY KEY, title TEXT, year INTEGER, collection TEXT, file TEXT,
                                  snippet TEXT, state TEXT DEFAULT 'found', note TEXT, words INTEGER, nonwords INTEGER,
                                  mined_at TEXT);
CREATE TABLE IF NOT EXISTS item_seeds (identifier TEXT, seed_id INTEGER, UNIQUE (identifier, seed_id));
CREATE TABLE IF NOT EXISTS item_words (identifier TEXT, wrong TEXT, correct TEXT, shapes TEXT, strong INTEGER, count INTEGER,
                                       example TEXT, UNIQUE (identifier, wrong));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


class MineQueue:
    """The OCR seeds, the Archive items their searches turned up, and the non-words mined from each item's OCR.

    An item's badness is how many different seeds found it: one misreading is any old scan, several is a bad one."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)

    def meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def filled(self) -> bool:
        return self.meta("filled_from") is not None

    def fill(self, seeds: list[dict], about: dict) -> None:
        with self.connection:
            self.connection.executemany("INSERT OR IGNORE INTO seeds (wrong, correct, shapes, source) VALUES (?, ?, ?, ?)",
                                        [(s["wrong"], s["correct"], s["shapes"], s["source"]) for s in seeds])
            self.connection.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in about.items()])

    def next_seed(self) -> dict | None:
        # Wikipedia's own finds first, then GGCMS's list
        row = self.connection.execute("SELECT id, wrong, correct FROM seeds WHERE searched_at IS NULL "
                                      "ORDER BY source = 'GGCMS list', id LIMIT 1").fetchone()
        return dict(zip(("id", "wrong", "correct"), row)) if row else None

    def searched(self, seed: dict, total: int, hits: list[dict], stamp: str) -> None:
        with self.connection:
            for hit in hits:
                self.connection.execute("INSERT OR IGNORE INTO items (identifier, title, year, collection, file, snippet) "
                                        "VALUES (?, ?, ?, ?, ?, ?)", (hit["identifier"], hit["title"], hit["year"],
                                                                      hit["collection"], hit["file"], hit["snippet"]))
                self.connection.execute("INSERT OR IGNORE INTO item_seeds VALUES (?, ?)", (hit["identifier"], seed["id"]))
            self.connection.execute("UPDATE seeds SET total = ?, searched_at = ? WHERE id = ?", (total, stamp, seed["id"]))

    def worst_items(self, least_seeds: int, limit: int, state: str = "found") -> list[dict]:
        # A dropped fi or fl is how a born-digital PDF's text comes out, not a scanner's misreading: SEv3, found by seven
        # ligature seeds on 2 Nov 2026, was a 2020 book. So an item needs at least one other shape, and those rank it
        rows = self.connection.execute(
            "SELECT i.identifier, i.title, i.file, COUNT(*) AS seeds, "
            "SUM(instr(replace(d.shapes, '(ligature)', ''), '(') > 0) AS scanner "
            "FROM items i JOIN item_seeds s USING (identifier) JOIN seeds d ON d.id = s.seed_id "
            "WHERE i.state = ? GROUP BY i.identifier HAVING seeds >= ? AND scanner >= 1 "
            "ORDER BY scanner DESC, seeds DESC, i.identifier LIMIT ?", (state, least_seeds, limit)).fetchall()
        return [dict(zip(("identifier", "title", "file", "seeds"), row[:4])) for row in rows]

    def set_state(self, identifier: str, state: str, note: str = "") -> None:
        with self.connection:
            self.connection.execute("UPDATE items SET state = ?, note = ? WHERE identifier = ?", (state, note, identifier))

    def mined(self, identifier: str, result: dict, stamp: str) -> None:
        with self.connection:
            self.connection.executemany(
                "INSERT OR REPLACE INTO item_words VALUES (?, ?, ?, ?, ?, ?, ?)",
                [(identifier, wrong, entry["right"], entry["shapes"], int(entry["strong"]), entry["count"], entry.get("example", ""))
                 for wrong, entry in result["found"].items()])
            self.connection.execute("UPDATE items SET state = 'mined', note = '', words = ?, nonwords = ?, mined_at = ? "
                                    "WHERE identifier = ?", (result["words"], result["nonwords"], stamp, identifier))

    def candidates(self, least_items: int = 2) -> list[dict]:
        # A misreading that recurs across separately scanned texts is the scanner's habit, not one page's smudge
        rows = self.connection.execute(
            "SELECT wrong, correct, shapes, MAX(strong), COUNT(*) AS items, SUM(count) AS total, json_group_array(identifier) "
            "FROM item_words GROUP BY wrong, correct HAVING items >= ? ORDER BY MAX(strong) DESC, items DESC, total DESC, wrong",
            (least_items,)).fetchall()
        found = []
        for wrong, correct, shapes, strong, items, total, identifiers in rows:
            example, source = self.connection.execute(
                "SELECT example, identifier FROM item_words WHERE wrong = ? ORDER BY count DESC LIMIT 1", (wrong,)).fetchone()
            found.append({"wrong": wrong, "correct": correct, "shapes": shapes, "strong": bool(strong), "items": items,
                          "count": total, "identifiers": json.loads(identifiers), "example": example, "example_item": source})
        return found

    def items_waiting(self, state: str) -> list[dict]:
        rows = self.connection.execute("SELECT identifier, title, note FROM items WHERE state = ? ORDER BY identifier", (state,))
        return [dict(zip(("identifier", "title", "note"), row)) for row in rows]

    def counts(self, mine_cap: int) -> dict:
        seeds, searched = self.connection.execute("SELECT COUNT(*), COUNT(searched_at) FROM seeds").fetchone()
        items, mined, big = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(state = 'mined'), 0), COALESCE(SUM(state = 'too big'), 0) FROM items").fetchone()
        (candidates,) = self.connection.execute(
            "SELECT COUNT(*) FROM (SELECT wrong FROM item_words GROUP BY wrong HAVING COUNT(*) >= 2)").fetchone()
        return {"done": searched + mined, "total": seeds + mine_cap, "seeds searched": f"{searched}/{seeds}", "items found": items,
                "items mined": mined, "too big": big, "candidates": candidates}
