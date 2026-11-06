import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dump_tables import DumpTables  # noqa: E402

from url_tools import host, original, urls_in  # noqa: E402

ENGLISH = {"", "en", "eng", "english"}
SOURCE_LINE = re.compile(r"^\W*(?:source|from|retrieved from|originally (?:published|from))\b", re.I)
TAG = re.compile(r"<[^>]+>")
SPLIT = re.compile(r"\s*(?:&|/|,|;|\band\b|\+)\s*", re.I)
DOMAIN = re.compile(r"^(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)+)$", re.I)
# Source names that aren't spelled as a domain; RevoltLib, 18 Oct 2026: 1,453 texts say Anarchy Archives
NAMED = {"anarchy archives": "dwardmac.pitzer.edu", "anarchyarchives": "dwardmac.pitzer.edu", "wikisource": "en.wikisource.org",
         "wikisource.org": "en.wikisource.org", "wikipedia": "en.wikipedia.org", "wikipedia.org": "en.wikipedia.org",
         "daily bleed": "recollectionbooks.com", "the daily bleed": "recollectionbooks.com"}


@dataclass
class OurText:
    """One published English text, with where it came from and the permalink a link to it should use."""

    entryid: int
    title: str
    permalink: int  # the entry's oldest Assignment id: GGCMS's ?id=, never the entry id
    work: int  # the book or article it belongs to (itself, if it is one)
    author: int  # the author's entry, or 0
    sources: list[str] = field(default_factory=list)  # page URLs, when the Source (or the body's closing line) gives one
    domains: list[str] = field(default_factory=list)  # the sites it came from, from URLs or from Source names like "Spunk.org"
    source_from: str = ""  # "Source", "body", or "" for a sourceless text
    unknown: list[str] = field(default_factory=list)  # Source names this couldn't turn into a site
    words: str = ""  # the plain text, for comparing with an archived copy


@dataclass
class OurSite:
    texts: list[OurText]
    titles: dict  # entry id -> title, for works and authors
    permalinks: dict  # entry id -> oldest Assignment id
    publish: set  # published entry ids

    def link(self, domain: str, entryid: int) -> str:
        # As entry-share.php's PermalinkURL() builds it
        return f"https://{domain}/?id={self.permalinks[entryid]}" if entryid in self.permalinks else ""


def our_site(dump: Path) -> OurSite:
    """Every published English text in a site's dump with its sources, works and authors (read-only)."""
    titles, publish, parent, permalinks, authors, bodies = {}, set(), {}, {}, {}, []
    for table, row in DumpTables(dump).rows({"Entry", "Assignment", "Association", "TextBody"}):
        if table == "Entry":
            titles[int(row["id"])] = row["Title"]
            if row["Publish"] == "1":
                publish.add(int(row["id"]))
        elif table == "Assignment":
            child = int(row["Childid"])
            if child not in permalinks or int(row["id"]) < permalinks[child]:  # oldest assignment wins (Ben, 29 Oct 2026)
                permalinks[child], parent[child] = int(row["id"]), int(row["Parentid"])
        elif table == "Association":
            if row["Type"] == "Role" and row["SubType"] == "Author":
                authors.setdefault(int(row["Entryid"]), int(row["ChosenEntryid"]))
        elif (row.get("Language") or "").lower() in ENGLISH and row["Text"].strip():
            bodies.append((int(row["Entryid"]), row["Text"], row.get("Source") or ""))
    texts = []
    for entryid, markup, source in bodies:
        if entryid not in publish or entryid not in permalinks:
            continue
        lineage = _lineage(entryid, parent)
        work = lineage[2] if len(lineage) > 2 else entryid  # site root, section, then the work
        sources, domains, source_from, unknown = where_from(source, markup)
        texts.append(OurText(entryid, titles.get(entryid, ""), permalinks[entryid], work,
                             next((authors[e] for e in (entryid, work) if e in authors), 0), sources, domains, source_from, unknown,
                             " ".join(TAG.sub(" ", markup).split())))
    return OurSite(texts, titles, permalinks, publish)


def where_from(source: str, markup: str) -> tuple[list[str], list[str], str, list[str]]:
    # TextBody.Source first: mostly a site's name ("TheAnarchistLibrary.org"), now and then a page's URL. Texts from before
    # the field had it in the body, in a closing "Source:" line; any other link in the body is a footnote, not where it came from.
    urls, domains, unknown = _unique(urls_in(source)), [], []
    for piece in SPLIT.split(URL_FREE.sub(" ", source)):
        piece = piece.strip(" .()[]\"'").lower()
        if not piece:
            continue
        named = NAMED.get(piece) or (DOMAIN.match(piece).group(1) if DOMAIN.match(piece) else None)
        (domains if named else unknown).append(named or piece)
    if source.strip():
        return urls, _unique_domains([host(url) for url in urls] + domains), "Source", unknown
    tail = TAG.sub(" ", markup[-4000:].replace("<br", "\n<br").replace("<p", "\n<p"))
    lines = [line.strip() for line in tail.splitlines() if SOURCE_LINE.match(line.strip()) and urls_in(line)]
    found = _unique([url for line in lines[-1:] for url in urls_in(line)])
    return found, _unique_domains([host(url) for url in found]), "body" if found else "", []


URL_FREE = re.compile(r"https?://\S+", re.I)


def _unique(urls: list[str]) -> list[str]:
    return list(dict.fromkeys(original(url) for url in urls if host(original(url))))


def _unique_domains(names: list[str]) -> list[str]:
    return list(dict.fromkeys(name[4:] if name.startswith("www.") else name for name in names if name))


def _lineage(entryid: int, parent: dict) -> list[int]:
    chain = [entryid]
    while chain[-1] in parent and len(chain) < 12:
        chain.append(parent[chain[-1]])
    return chain[::-1]
