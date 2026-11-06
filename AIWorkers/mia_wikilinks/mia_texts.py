"""One MIA author's works, read from the local mirror fetch_mia.py made (E:\\mia\\site), never from the server.

Every MIA page's <title> reads "Author: Work (qualifier)": "Rosa Luxemburg: The Accumulation of Capital (Chap.5)". The work is
the part between, and a work's link is its folder's index.htm if it has one, otherwise its first page.
"""

import html
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

SITE = Path(r"E:\mia\site")
LISTING = Path(r"E:\mia\mia-files.txt")
BASE = "https://www.marxists.org/"
TITLE = re.compile(rb"<title[^>]*>(.*?)</title>", re.I | re.S)
TRAILING_ASIDE = re.compile(r"\s*\([^()]*\)\s*$")
LIBRARY = re.compile(r"\s*(?:internet archive|library|archive|reference archive)\s*$", re.I)
CHAPTER = re.compile(r"\s*[-–—:,]\s*(?:chapter|chap\.?|part|section|book|letter|appendix|preface|introduction)\b.*$", re.I)
NOT_WORKS = ("img/", "subject/", "images/", "pics/", "photo/", "sound/", "video/")
NOT_PAGES = ("index.htm", "404.htm", "404.html", "library.htm", "library.html")


@dataclass
class Work:
    title: str
    path: str  # under the web root, as marxists.org/<path>
    pages: list[str] = field(default_factory=list)

    @property
    def link(self) -> str:
        return BASE + self.path


@dataclass
class Author:
    folder: str  # "archive/luxemburg"
    name: str
    works: list[Work]

    @property
    def link(self) -> str:
        return f"{BASE}{self.folder}/index.htm"

    @property
    def surname(self) -> str:
        return self.name.split()[-1] if self.name else ""


def page_title(raw: bytes) -> str:
    found = TITLE.search(raw[:20000])
    if not found:
        return ""
    text = found.group(1).decode("utf-8", "replace") if b"charset=utf-8" in raw[:3000].lower() else found.group(1).decode("cp1252", "replace")
    return " ".join(html.unescape(text).replace("’", "'").split())


def work_title(title: str, name: str) -> str:
    # "Rosa Luxemburg: The Mass Strike (Chap.1)" -> "The Mass Strike"; asides come off one at a time ("(1903) (extract)")
    surname = name.split()[-1] if name else ""
    head = title.split(":", 1)[0] if ":" in title[:80] else ""
    if name and title.lower().startswith(name.lower() + ":"):
        while title.lower().startswith(name.lower() + ":"):  # "James Connolly: James Connolly: Labour in Irish History"
            title = title[len(name) + 1:].lstrip()
    elif head and surname and surname.lower() in head.lower() and len(head) < 80:
        title = title[len(head) + 1:].lstrip()  # "Nikolai Bukharin and Evgenii Preobrazhensky: The ABC of Communism"
    elif ":" in title[:40]:
        return ""  # another writer's page in this folder (an introduction, a review): not one of the author's works
    for _ in range(3):
        title = TRAILING_ASIDE.sub("", title)
    if surname:
        # "… by Nikolai Bukharin 1919", "… - Nikolai Bukharin - 1924", "… - Bukharin", "Soviets or Parliament 1919"
        names = re.escape(name) + "|" + re.escape(surname)
        title = re.sub(rf"\s*(?:,?\s*by|[-–—,])\s*(?:{names})\b.*$", "", title, flags=re.I)
        title = re.sub(rf"^(?:{names})\s*(?:\d{{4}})?$", "", title, flags=re.I)
    title = re.sub(r"\s+\d{4}$", "", title)
    title = CHAPTER.sub("", title)
    return title.strip(" -–—:")


def main_title(title: str) -> str:
    # "Historical Materialism - A System of Sociology" is also filed as "Historical Materialism"
    return re.split(r"\s+[-–—]\s+|:\s+", title, maxsplit=1)[0]


def read_author(folder: str, site: Path = SITE) -> Author:
    root = site / folder
    index = root / "index.htm"
    name = LIBRARY.sub("", page_title(index.read_bytes())) if index.exists() else folder.rsplit("/", 1)[-1].title()
    works: dict[str, Work] = {}
    fronts: dict[Path, str] = {}  # a book's folder -> its index page's title: every page in it is that book, whatever it's called
    for page in sorted(root.rglob("index.htm*")):
        dated = re.fullmatch(r"\d+s?|xx|misc|undated", page.parent.name.lower())  # a year's or month's index lists many works
        if page.parent != root and not dated and not page.name.endswith(".partial"):
            fronts[page.parent] = work_title(page_title(page.read_bytes()), name)
    for page in sorted(root.rglob("*.htm*")):
        relative = page.relative_to(root).as_posix()
        if page.name.endswith(".partial") or relative in NOT_PAGES or relative.startswith(NOT_WORKS):
            continue
        book = next((parent for parent in page.parents if parent in fronts and fronts[parent]), None)
        title = fronts[book] if book else work_title(page_title(page.read_bytes()), name)
        if len(title) < 3:
            continue
        path = f"{folder}/{relative}"
        work = works.setdefault(title.lower(), Work(title, path))
        work.pages.append(path)
        if PurePosixPath(path).name.lower() in ("index.htm", "index.html"):
            work.path = path  # the work's own front page beats its first chapter
    return Author(folder, name, list(works.values()))


def listed_paths(listing: Path = LISTING) -> set[str]:
    # Every path the server had when list_mia.py ran, lower-cased, and every folder above them
    have = set()
    for line in listing.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        path = line.split("\t", 2)[2].removesuffix(" (link)").lower()
        have.add(path)
        parts = path.split("/")
        have.update("/".join(parts[:count]) for count in range(1, len(parts)))
    return have
