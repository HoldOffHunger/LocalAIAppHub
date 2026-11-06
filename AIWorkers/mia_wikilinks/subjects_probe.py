"""Prototype: which of MIA's history/ subject folders share a name with a Wikipedia article, and does that article link them?

Reads folder names from MIA's listing (so it works before the mirror has history/), plus each folder's index.htm title where
the mirror already has one. Writes a TSV for a person to read; no model, no live checks, no edits.

    python subjects_probe.py --out E:/mia/subjects-probe.tsv
"""

import argparse
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "ggcms_wikilinks"))

from wiki_dumps import WikiDumps  # noqa: E402
from wiki_index import WikiIndex, title_key  # noqa: E402

from mia_texts import LISTING, SITE, page_title  # noqa: E402
from run_mia_links import _borrow_links  # noqa: E402

SECTIONS = ("history/",)
NOISE = re.compile(r"^(?:\d+s?|no\d+|v\d+|vol\d+|issue\d*|index|subject|subject-indexes|pubs|periodicals|newspape|document|"
                   r"writers|archive|images?|img|pics|pdf|works|misc|xx|undated|people|events|government|sections)$", re.I)
TITLE_TAIL = re.compile(r"\s*(?:[|:–—-]\s*)?(?:marxists internet archive|mia|encyclopedia of trotskyism on-line|etol|"
                        r"encyclopedia of anti-revisionism on-line|erol|history archive|archive|index)\s*$", re.I)


def folders(listing: Path, sections: tuple[str, ...] = SECTIONS) -> dict[str, int]:
    # every folder under the watched sections, with how many pages sit under it
    pages = defaultdict(int)
    for line in listing.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        path = line.split("\t", 2)[2].removesuffix(" (link)")
        if not path.startswith(sections) or not re.search(r"\.html?$", path, re.I):
            continue
        parts = path.split("/")[:-1]
        for count in range(2, len(parts) + 1):
            pages["/".join(parts[:count])] += 1
    return pages


def names_of(folder: str) -> set[str]:
    # "history/france/paris-commune" -> "paris commune"; the mirror's own index title when it has one
    names = set()
    slug = folder.rsplit("/", 1)[-1]
    if not NOISE.match(slug):
        words = re.sub(r"[-_.]+", " ", slug).strip()
        if len(words.split()) >= 2:
            names.add(words)
    index = SITE / folder / "index.htm"
    if index.exists():
        title = TITLE_TAIL.sub("", page_title(index.read_bytes()))
        for _ in range(2):
            title = TITLE_TAIL.sub("", title)
        if 2 <= len(title.split()) <= 8:
            names.add(title)
    return {key for key in (title_key(name)[0] for name in names) if key}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", default=str(HERE.parent / "data" / "tasks" / "subjects-probe.wiki.sqlite"))
    parser.add_argument("--out", required=True)
    parser.add_argument("--sections", default="history/", help="comma-separated MIA folders, e.g. subject/,history/")
    args = parser.parse_args()

    sections = tuple(part.strip().rstrip("/") + "/" for part in args.sections.split(","))
    sizes = folders(LISTING, sections)
    by_key = defaultdict(list)
    for folder in sizes:
        for key in names_of(folder):
            by_key[key].append(folder)
    print(f"{len(sizes):,} folders under {', '.join(sections)}; {len(by_key):,} candidate titles", flush=True)

    index = WikiIndex(Path(args.index))
    if not index.meta("links_done"):
        _borrow_links(index)
    if not index.scan_pages(WikiDumps(), set(by_key), None):
        sys.exit("page scan stopped early")

    rows = []
    for key, homes in by_key.items():
        for page, title, redirect, aside in index.titled(key):
            if aside and "disambiguation" in aside:
                continue
            links = [url for (url,) in index.connection.execute(
                "SELECT url FROM links WHERE page = ? AND domain = 'marxists.org'", (page,))]
            for folder in homes:
                here = any(f"marxists.org/{folder}".lower() in url.lower() for url in links)
                rows.append((title, "redirect" if redirect else "article", folder, sizes[folder],
                             "links this folder" if here else f"links MIA {len(links)}x" if links else "no MIA link"))
    rows.sort(key=lambda row: (row[4] != "no MIA link", row[4].startswith("links this"), -row[3]))
    with open(args.out, "w", encoding="utf-8") as out:
        out.write("article\tkind\tmia folder\tmia pages\tstate\n")
        out.writelines("\t".join(map(str, row)) + "\n" for row in rows)
    states = defaultdict(int)
    for row in rows:
        states[row[4] if not row[4].startswith("links MIA") else "links MIA elsewhere"] += 1
    print(f"{len(rows):,} matches: {dict(states)}; written to {args.out}", flush=True)


if __name__ == "__main__":
    main()
