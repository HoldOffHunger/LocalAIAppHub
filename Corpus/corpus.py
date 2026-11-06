# Corpus: Ben's philosophy research library, on http://127.0.0.1:8760
# start.bat runs this. Standard library only, like the hub. One master list of works, each with every copy Ben has of it,
# physical, digital or on the web, so the same book in three formats is one work; what he's read; and where each work sits
# in his framework (framework.json): six realms by five phases. It reads his catalogues and never changes them.

import json
import os
import sqlite3
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from catalogue import books, evidence_lists, read_titles, web_note, work_key

APP = Path(__file__).resolve().parent
DATA = APP / "data"
DB_PATH = DATA / "corpus.sqlite"
FRAMEWORK = APP / "framework.json"
PAGE = APP / "web" / "index.html"
PORT = int(os.environ.get("CORPUS_PORT", "8760"))
# The catalogues of books Ben owns; the Bookstore, Bundles, Estate Giveaway and Sold lists are books for sale, not his shelves
OWNED_LISTS = [Path(r"E:\Books\Philosophy\New Library Books.rtf")]
# The books Ben has read, with full citations, and the evidence he found in each, kept in his research folder
READ_BOOKS = Path(r"E:\Books\Philosophy\Research\!!!Books")
READ_TITLES, EVIDENCE = READ_BOOKS / "Titles.rtf", READ_BOOKS / "Lists-Per-Title.rtf"
# What he read on the web: a note per text, "Notes, <Title>, <Author>.rtf", in Research\<subject>\Notes
WEB_NOTES = Path(r"E:\Books\Philosophy\Research")
STATUSES = ("unread", "reading", "read")
FORMATS = ("physical", "digital", "web")
lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS works (id INTEGER PRIMARY KEY, key TEXT UNIQUE, title TEXT, author TEXT, author_sort TEXT,
    year INTEGER, status TEXT DEFAULT 'unread', read_on TEXT DEFAULT '', notes TEXT DEFAULT '', realms TEXT DEFAULT '[]',
    phases TEXT DEFAULT '[]', added TEXT);
CREATE TABLE IF NOT EXISTS copies (id INTEGER PRIMARY KEY, work_id INTEGER REFERENCES works(id), format TEXT, place TEXT,
    detail TEXT DEFAULT '{}', key TEXT UNIQUE);
"""


def connect():
    DATA.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    columns = {row["name"] for row in connection.execute("PRAGMA table_info(works)")}
    if "evidence" not in columns:  # what Ben found in the book, from Lists-Per-Title (2 Nov 2026)
        connection.execute("ALTER TABLE works ADD COLUMN evidence TEXT DEFAULT '[]'")
    return connection


def surname_first(author):
    # "Chris Guillebeau" → "Guillebeau, Chris", for sorting; joint and corporate authors sort as written
    words = author.split()
    return author if len(words) < 2 or " and " in author or "," in author else f"{words[-1]}, {' '.join(words[:-1])}"


def now():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def work_for(connection, title, author, author_sort="", year=None):
    # The work this copy belongs to: found by its key, or made
    key = work_key(title, author)
    row = connection.execute("SELECT id FROM works WHERE key = ?", (key,)).fetchone()
    if row:
        return row["id"]
    cursor = connection.execute("INSERT INTO works (key, title, author, author_sort, year, added) VALUES (?, ?, ?, ?, ?, ?)",
                                (key, title, author, author_sort or author, year, now()))
    return cursor.lastrowid


def import_owned():
    # Every book in the owned catalogues becomes a physical copy; run again, it only adds what's new
    added = 0
    with lock, connect() as connection:
        for path in OWNED_LISTS:
            if not path.exists():
                continue
            for book in books(path.read_text(encoding="cp1252", errors="replace")):
                key = f"physical:{path.name}:{book['author_sort']} - {book['short']}"
                if connection.execute("SELECT 1 FROM copies WHERE key = ?", (key,)).fetchone():
                    continue
                work = work_for(connection, book["title"], book["author"], book["author_sort"], book["year"])
                detail = {**book["fields"], "citation": book["citation"], "todo": book["todo"]}
                connection.execute("INSERT INTO copies (work_id, format, place, detail, key) VALUES (?, 'physical', ?, ?, ?)",
                                   (work, path.name, json.dumps(detail, ensure_ascii=False), key))
                added += 1
    return added


def import_read():
    # The books Ben has read: each is marked read (never un-marked), and its evidence list is his file's, refreshed each time
    if not READ_TITLES.exists():
        return 0
    titles = read_titles(READ_TITLES.read_text(encoding="cp1252", errors="replace"))
    lists = evidence_lists(EVIDENCE.read_text(encoding="cp1252", errors="replace")) if EVIDENCE.exists() else {}
    known = {title["header"] for title in titles}
    # A book with an evidence list but no line in Titles was read too; it has only its short title and author
    titles += [{"header": header, "short": header.split('," ')[0].strip('"'), "author": header.split('," ', 1)[-1],
                "title": header.split('," ')[0].strip('"'), "year": None, "citation": ""} for header in lists if header not in known]
    added = 0
    with lock, connect() as connection:
        for title in titles:
            work = work_for(connection, title["title"], title["author"], surname_first(title["author"]), title["year"])
            key = f"read:{READ_TITLES.name}:{title['header']}"
            if not connection.execute("SELECT 1 FROM copies WHERE key = ?", (key,)).fetchone():
                detail = {"citation": title["citation"]} if title["citation"] else {}
                connection.execute("INSERT INTO copies (work_id, format, place, detail, key) VALUES (?, 'physical', ?, ?, ?)",
                                   (work, "read, in Titles.rtf", json.dumps(detail, ensure_ascii=False), key))
                added += 1
            connection.execute("UPDATE works SET status = 'read' WHERE id = ? AND status = 'unread'", (work,))
            if title["header"] in lists:
                connection.execute("UPDATE works SET evidence = ? WHERE id = ?",
                                   (json.dumps(lists[title["header"]], ensure_ascii=False), work))
    return added


def import_web_notes():
    # Each note is a web copy of its work, marked read when the note says so
    added = 0
    notes = [path for folder in WEB_NOTES.glob("*/Notes") for path in folder.glob("*.rtf")] if WEB_NOTES.exists() else []
    with lock, connect() as connection:
        for path in notes:
            key = f"web:{path.parent.parent.name}/{path.name}"
            if connection.execute("SELECT 1 FROM copies WHERE key = ?", (key,)).fetchone():
                continue
            note = web_note(path.name, path.read_text(encoding="cp1252", errors="replace"))
            if not note:
                continue
            work = work_for(connection, note["title"], note["author"])
            connection.execute("INSERT INTO copies (work_id, format, place, detail, key) VALUES (?, 'web', ?, '{}', ?)",
                               (work, f"notes in Research\\{path.parent.parent.name}\\Notes", key))
            if note["read"]:
                connection.execute("UPDATE works SET status = 'read' WHERE id = ? AND status = 'unread'", (work,))
            added += 1
    return added


def add_copy(body):
    title, author, fmt, place = (str(body.get(k, "")).strip() for k in ("title", "author", "format", "place"))
    if not title or fmt not in FORMATS:
        raise ValueError("A copy needs a title and a format: physical, digital or web.")
    with lock, connect() as connection:
        work = work_for(connection, title, author or "Unknown", year=body.get("year") or None)
        key = f"{fmt}:{place or title}:{work}"
        connection.execute("INSERT OR IGNORE INTO copies (work_id, format, place, detail, key) VALUES (?, ?, ?, '{}', ?)",
                           (work, fmt, place, key))
    return work


def update_work(work_id, body):
    framework = json.loads(FRAMEWORK.read_text(encoding="utf-8"))
    realms = {r["id"] for r in framework["realms"]}
    phases = {p["id"] for p in framework["phases"]}
    changes = {}
    if "status" in body:
        if body["status"] not in STATUSES:
            raise ValueError("Status is unread, reading or read.")
        changes["status"] = body["status"]
        if body["status"] == "read":
            changes["read_on"] = datetime.now().date().isoformat()
    if "notes" in body:
        changes["notes"] = str(body["notes"])[:20000]
    if "realms" in body:
        changes["realms"] = json.dumps([r for r in body["realms"] if r in realms])
    if "phases" in body:
        changes["phases"] = json.dumps([p for p in body["phases"] if p in phases])
    if not changes:
        return
    with lock, connect() as connection:
        connection.execute(f"UPDATE works SET {', '.join(k + ' = ?' for k in changes)} WHERE id = ?", (*changes.values(), work_id))


def describe():
    with connect() as connection:
        works = [dict(row) for row in connection.execute("SELECT * FROM works ORDER BY author_sort COLLATE NOCASE, title")]
        copies = {}
        for row in connection.execute("SELECT * FROM copies"):
            copies.setdefault(row["work_id"], []).append({"format": row["format"], "place": row["place"],
                                                          "detail": json.loads(row["detail"])})
    for work in works:
        work["realms"], work["phases"] = json.loads(work["realms"]), json.loads(work["phases"])
        work["evidence"] = json.loads(work.get("evidence") or "[]")
        work["copies"] = copies.get(work["id"], [])
        del work["key"]
    return {"framework": json.loads(FRAMEWORK.read_text(encoding="utf-8")), "works": works,
            "lists": [str(path) for path in OWNED_LISTS + [READ_TITLES, EVIDENCE]]}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(describe())
        else:
            self._send(404, b"not here", "text/plain")

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if self.path == "/api/import":
                return self._json({"added": import_owned() + import_read() + import_web_notes()})
            if self.path == "/api/copies":
                return self._json({"work": add_copy(body)})
            if self.path.startswith("/api/works/"):
                update_work(int(self.path.rsplit("/", 1)[1]), body)
                return self._json({"ok": True})
        except (ValueError, KeyError) as problem:
            return self._json({"problem": str(problem)}, 400)
        self._send(404, b"not here", "text/plain")

    def _json(self, value, status=200):
        self._send(status, json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def main():
    print(f"Corpus: {import_owned()} new books from the catalogues, {import_read()} from the read list, "
          f"{import_web_notes()} web notes", flush=True)
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print(f"Corpus on http://127.0.0.1:{PORT}/", flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"http://127.0.0.1:{PORT}/")
    server.serve_forever()


if __name__ == "__main__":
    main()
