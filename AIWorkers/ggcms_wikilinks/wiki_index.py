import json
import re
import sqlite3
import unicodedata
import zlib
from datetime import datetime
from pathlib import Path

from url_tools import domain_key, domain_keys, wiki_url
from wiki_dumps import WikiDumps, row_values, table_rows

CHECKPOINT = 2_000_000  # lines between saves, so a scan stopped at the stop time loses at most a minute or two
DISAMBIGUATOR = re.compile(r"\s*\(([^()]*)\)$")
NOT_WORD = re.compile(r"[^\w\s]")


def title_key(title: str) -> tuple[str, str]:
    # A title as both sides can agree on: "The_Conquest_of_Bread_(book)" and "The Conquest of Bread" are the same key, with "book" aside
    text = unicodedata.normalize("NFKC", title.replace("_", " ")).strip()
    found = DISAMBIGUATOR.search(text)
    aside = found.group(1).lower() if found else ""
    base = NOT_WORD.sub(" ", DISAMBIGUATOR.sub("", text).lower())
    return " ".join(base.split()), aside


class WikiIndex:
    """What this task needs from Wikipedia's dumps, kept in SQLite: links into the domains it watches, and the articles they sit in or whose titles match ours."""

    def __init__(self, path: Path):
        self.connection = sqlite3.connect(path)
        self.connection.executescript(
            "CREATE TABLE IF NOT EXISTS links (page INTEGER, url TEXT, domain TEXT);"
            "CREATE INDEX IF NOT EXISTS links_page ON links (page);"
            "CREATE TABLE IF NOT EXISTS pages (id INTEGER PRIMARY KEY, title TEXT, redirect INTEGER, title_key TEXT, aside TEXT);"
            "CREATE INDEX IF NOT EXISTS pages_key ON pages (title_key);"
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);"
            "CREATE TABLE IF NOT EXISTS entries (id INTEGER PRIMARY KEY, title TEXT, link TEXT);"
            "CREATE TABLE IF NOT EXISTS texts (id INTEGER PRIMARY KEY, work INTEGER, author INTEGER, sources TEXT, domains TEXT, source_from TEXT, unknown TEXT, words BLOB);"
            "CREATE TABLE IF NOT EXISTS domains (domain TEXT PRIMARY KEY, state TEXT, why TEXT);")

    def save_ours(self, site, domain: str) -> None:
        # Our side, read from the site's dump once, so later turns needn't read 500 MB again
        with self.connection:
            self.connection.executemany("INSERT OR REPLACE INTO entries VALUES (?, ?, ?)",
                                        [(entry, title, site.link(domain, entry)) for entry, title in site.titles.items() if entry in site.publish])
            self.connection.executemany("INSERT OR REPLACE INTO texts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                                        [(text.entryid, text.work, text.author, json.dumps(text.sources), json.dumps(text.domains),
                                          text.source_from, json.dumps(text.unknown), zlib.compress(text.words.encode("utf-8")))
                                         for text in site.texts])
            self.set_meta("ours_done", 1)

    def entry(self, entry: int) -> tuple[str, str]:
        found = self.connection.execute("SELECT title, link FROM entries WHERE id = ?", (entry,)).fetchone()
        return found or ("", "")

    def texts(self) -> list[dict]:
        return [{"id": entry, "work": work, "author": author, "sources": json.loads(sources), "domains": json.loads(domains),
                 "source_from": source_from, "unknown": json.loads(unknown)}
                for entry, work, author, sources, domains, source_from, unknown in
                self.connection.execute("SELECT id, work, author, sources, domains, source_from, unknown FROM texts ORDER BY id")]

    def words(self, entry: int) -> str:
        found = self.connection.execute("SELECT words FROM texts WHERE id = ?", (entry,)).fetchone()
        return zlib.decompress(found[0]).decode("utf-8") if found else ""

    def domain_state(self, domain: str) -> tuple[str, str] | None:
        return self.connection.execute("SELECT state, why FROM domains WHERE domain = ?", (domain,)).fetchone()

    def set_domain_state(self, domain: str, state: str, why: str) -> None:
        with self.connection:
            self.connection.execute("INSERT OR REPLACE INTO domains VALUES (?, ?, ?)", (domain, state, why))

    def meta(self, key: str) -> str | None:
        row = self.connection.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value) -> None:
        self.connection.execute("INSERT OR REPLACE INTO meta VALUES (?, ?)", (key, str(value)))

    def scan_links(self, dumps: WikiDumps, domains: set[str], ends: datetime | None) -> bool:
        # A billion links, a pass of about an hour; only those into the watched domains (and their subdomains) are kept
        if self.meta("links_done"):
            return True
        keys = {domain_key(domain): domain for domain in domains}
        start, kept = int(self.meta("links_line") or 0), []
        print(f"reading Wikipedia's links into {len(domains)} domains" + (f", from line {start:,}" if start else ""), flush=True)
        number = start
        for number, line in table_rows(dumps.path("externallinks"), start):
            index_at = line.find(b",'") + 2
            index = line[index_at:line.find(b"'", index_at)]
            domain = next((keys[key] for key in domain_keys(index) if key in keys), None)
            if domain:
                page, index, path = row_values(line, 4)[1:]
                kept.append((int(page), wiki_url(index, path), domain))
            if number % CHECKPOINT == 0 and number > start:
                self._save_links(kept, number)
                kept = []
                if ends and datetime.now() >= ends:
                    print(f"  stopped at line {number:,}; the scan resumes there next turn", flush=True)
                    return False
        self._save_links(kept, number)
        with self.connection:
            self.set_meta("links_done", 1)
        return True

    def scan_pages(self, dumps: WikiDumps, titles: set[str], ends: datetime | None) -> bool:
        # Articles (namespace 0) that hold a kept link, or whose title matches one of ours; redirects count, the API follows them
        if self.meta("pages_done"):
            return True
        wanted = {page for (page,) in self.connection.execute("SELECT DISTINCT page FROM links")}
        start, kept = int(self.meta("pages_line") or 0), []
        print(f"reading Wikipedia's article titles for {len(wanted):,} linking pages and {len(titles):,} of our titles", flush=True)
        number = start
        for number, line in table_rows(dumps.path("page"), start):
            page, namespace, title, redirect = row_values(line, 4)
            if namespace == b"0":
                text = title.decode("utf-8", "replace")
                key, aside = title_key(text)
                if int(page) in wanted or key in titles:
                    kept.append((int(page), text.replace("_", " "), int(redirect), key, aside))
            if number % CHECKPOINT == 0 and number > start:
                self._save_pages(kept, number)
                kept = []
                if ends and datetime.now() >= ends:
                    print(f"  stopped at line {number:,}; the scan resumes there next turn", flush=True)
                    return False
        self._save_pages(kept, number)
        with self.connection:
            self.set_meta("pages_done", 1)
        return True

    def links(self) -> list[tuple[int, str, str, str]]:
        # (page id, article title, url, domain) for links in articles
        return self.connection.execute("SELECT links.page, pages.title, links.url, links.domain FROM links "
                                       "JOIN pages ON pages.id = links.page ORDER BY links.page").fetchall()

    def titled(self, key: str) -> list[tuple[int, str, int, str]]:
        return self.connection.execute("SELECT id, title, redirect, aside FROM pages WHERE title_key = ?", (key,)).fetchall()

    def page_links_to(self, page: int, domains: set[str]) -> bool:
        marks = ",".join("?" * len(domains))
        return bool(self.connection.execute(f"SELECT 1 FROM links WHERE page = ? AND domain IN ({marks}) LIMIT 1", (page, *domains)).fetchone())

    def _save_links(self, kept: list, line: int) -> None:
        with self.connection:
            self.connection.executemany("INSERT INTO links VALUES (?, ?, ?)", kept)
            self.set_meta("links_line", line + 1)

    def _save_pages(self, kept: list, line: int) -> None:
        with self.connection:
            self.connection.executemany("INSERT OR REPLACE INTO pages VALUES (?, ?, ?, ?, ?)", kept)
            self.set_meta("pages_line", line + 1)
