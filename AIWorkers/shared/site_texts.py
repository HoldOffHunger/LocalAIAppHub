import html
import re
from dataclasses import dataclass, field
from pathlib import Path

from dump_tables import DumpTables

ENGLISH = {"", "en", "eng", "english"}
BLOCK = re.compile(r"</?(?:p|div|br|li|h\d|blockquote|tr|td)[^>]*>", re.I)
TAG = re.compile(r"<[^>]+>")


@dataclass
class SiteText:
    """One published English text on a GGCMS site, with where it sits: its work, its author, and the records it already has."""

    entryid: int
    title: str
    work: str  # the top entry under the site's section: the book or article
    author: str
    markup: str
    has: set = field(default_factory=set)  # child record types the entry already holds: Quote, Description, Tag…

    def paragraphs(self) -> list[str]:
        text = html.unescape(TAG.sub(" ", BLOCK.sub("\n", self.markup)))
        return [re.sub(r"\s+", " ", line).strip() for line in text.split("\n") if line.strip()]

    def source(self) -> str:
        # Ben's house style for a quote's source: '"Work," by Author'
        return f"\"{self.work},\" by {self.author}" if self.author else ""  # a page with no author on record (a biography) has no work to cite


def site_texts(dump: Path, children=("Quote", "Description", "Tag", "EventDate")) -> list[SiteText]:
    """Every published English text in a site's dump, read once (read-only)."""
    entries, parent, authors, bodies, has = {}, {}, {}, [], {}
    for table, row in DumpTables(dump).rows({"Entry", "Assignment", "Association", "TextBody", *children}):
        if table == "Entry":
            entries[int(row["id"])] = (row["Title"], row["Publish"] == "1")
        elif table == "Assignment":
            parent.setdefault(int(row["Childid"]), int(row["Parentid"]))
        elif table == "Association":
            if row["Type"] == "Role" and row["SubType"] == "Author":
                authors.setdefault(int(row["Entryid"]), int(row["ChosenEntryid"]))
        elif table == "TextBody":
            if (row.get("Language") or "").lower() in ENGLISH and row["Text"].strip():
                bodies.append((int(row["Entryid"]), row["Text"]))
        else:
            has.setdefault(int(row["Entryid"]), set()).add(table)
    found = []
    for entryid, markup in bodies:
        title, published = entries.get(entryid, ("", False))
        if not published:
            continue
        lineage = _lineage(entryid, parent)
        work = lineage[2] if len(lineage) > 2 else entryid  # site root, section, then the work
        author = next((authors[e] for e in (entryid, work) if e in authors), None)
        found.append(SiteText(entryid, title, entries.get(work, (title,))[0], entries.get(author, ("",))[0] if author else "",
                              markup, has.get(entryid, set())))
    return found


def _lineage(entryid: int, parent: dict) -> list[int]:
    chain = [entryid]
    while chain[-1] in parent and len(chain) < 12:
        chain.append(parent[chain[-1]])
    return chain[::-1]
