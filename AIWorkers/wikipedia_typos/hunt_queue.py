import json
import random
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS words (id INTEGER PRIMARY KEY, wrong TEXT UNIQUE, correct TEXT, next_offset INTEGER DEFAULT 0,
                                  total INTEGER, round INTEGER DEFAULT 0, finished INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS hits (id INTEGER PRIMARY KEY, word_id INTEGER, page_id INTEGER, title TEXT, data TEXT, verdict TEXT,
                                 checked_by TEXT, checked_at TEXT, UNIQUE (word_id, page_id));
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS ages (word_id INTEGER, page_id INTEGER, since_rev INTEGER, typo_since TEXT, last_edit TEXT,
                                 gone INTEGER, dated_at TEXT, PRIMARY KEY (word_id, page_id));
"""
AGE_FIELDS = ("since_rev", "typo_since", "last_edit", "gone", "dated_at")


class HuntQueue:
    """The misspellings to look for, how deep into Wikipedia's results each has gone, and every hit with its verdict.

    Each visit to a word takes the next page of results; once every word has had its visit, a new round starts and
    each goes one page deeper. A word whose results have all been read is finished."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.executescript(SCHEMA)

    def filled(self) -> bool:
        return self.meta("filled_from") is not None

    def fill(self, misspellings: dict[str, str], about: dict, seed: int = 20261102, shuffle: bool = True) -> None:
        # Shuffled once, for good: the list is alphabetical, and "a a", "a bacteria"… first would be a dull first week.
        # A list already in a useful order (most used first) keeps it; words already in the pile keep their place either way
        pairs = list(misspellings.items())
        if shuffle:
            pairs.sort()
            random.Random(seed).shuffle(pairs)
        with self.connection:
            self.connection.executemany("INSERT OR IGNORE INTO words (wrong, correct) VALUES (?, ?)", pairs)
            self.connection.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", [(k, str(v)) for k, v in about.items()])

    def meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def next_word(self) -> dict | None:
        # The lowest round first: everything gets its visit before anything gets a second
        row = self.connection.execute("SELECT id, wrong, correct, next_offset, round FROM words WHERE finished = 0 "
                                      "ORDER BY round, id LIMIT 1").fetchone()
        return dict(zip(("id", "wrong", "correct", "offset", "round"), row)) if row else None

    def visited(self, word: dict, total: int, read: int) -> None:
        offset = word["offset"] + read
        with self.connection:
            self.connection.execute("UPDATE words SET next_offset = ?, total = ?, round = round + 1, finished = ? WHERE id = ?",
                                    (offset, total, int(read == 0 or offset >= total), word["id"]))

    def finish(self, word_id: int) -> None:
        # Read enough of this word's results, though more remain
        with self.connection:
            self.connection.execute("UPDATE words SET finished = 1 WHERE id = ?", (word_id,))

    def retire(self, words: set[str]) -> int:
        # Words found to be right after the pile was filled: never searched again
        with self.connection:
            return self.connection.executemany("UPDATE words SET finished = 1 WHERE wrong = ? AND finished = 0",
                                               [(word,) for word in words]).rowcount

    def seen(self, word_id: int, page_id: int) -> bool:
        return self.connection.execute("SELECT 1 FROM hits WHERE word_id = ? AND page_id = ?", (word_id, page_id)).fetchone() is not None

    def record(self, word: dict, page: dict, data: dict, verdict: dict, model: str, stamp: str) -> None:
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO hits (word_id, page_id, title, data, verdict, checked_by, checked_at) "
                                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                                    (word["id"], page["id"], page["title"], json.dumps(data, ensure_ascii=False),
                                     json.dumps(verdict, ensure_ascii=False), model, stamp))

    def typos(self) -> list[dict]:
        rows = self.connection.execute("SELECT w.wrong, w.correct, h.word_id, h.page_id, h.title, h.data, h.verdict, h.checked_by, "
                                       "h.checked_at, a.since_rev, a.typo_since, a.last_edit, a.gone, a.dated_at "
                                       "FROM hits h JOIN words w ON w.id = h.word_id LEFT JOIN ages a USING (word_id, page_id) "
                                       "ORDER BY h.checked_at DESC, h.id DESC")
        found = []
        for wrong, correct, word_id, page_id, title, data, verdict, checked_by, checked_at, *age in rows:
            verdict, data = json.loads(verdict), json.loads(data)
            if verdict.get("verdict") == "typo" and not data.get("quoted"):  # quoted finds from before quotations were skipped
                found.append({"wrong": wrong, "correct": correct, "word_id": word_id, "page_id": page_id, "title": title, **data,
                              "fix": verdict.get("fix", ""), "reason": verdict.get("reason", ""), "checked_by": checked_by,
                              "checked_at": checked_at, **dict(zip(AGE_FIELDS, age))})
        return found

    def undated(self) -> list[dict]:
        # Typos not yet given an age, oldest finds first
        return [typo for typo in reversed(self.typos()) if not typo["dated_at"]]

    def dated(self, typo: dict, age: dict, stamp: str) -> None:
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO ages VALUES (?, ?, ?, ?, ?, ?, ?)",
                                    (typo["word_id"], typo["page_id"], age["since_rev"], age["typo_since"], age["last_edit"],
                                     int(age["gone"]), stamp))

    def counts(self) -> dict:
        words, finished, visited = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(finished), 0), COALESCE(SUM(round > 0), 0) FROM words").fetchone()
        (rounds,) = self.connection.execute("SELECT COALESCE(MIN(round), 0) FROM words WHERE finished = 0").fetchone()
        hits, typos = self.connection.execute(
            "SELECT COUNT(*), COALESCE(SUM(json_extract(verdict, '$.verdict') = 'typo'), 0) FROM hits").fetchone()
        return {"done": visited, "total": words, "finished": finished, "round": rounds + 1, "pages read": hits, "typos": typos}
