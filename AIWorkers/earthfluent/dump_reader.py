import gzip
from dataclasses import dataclass
from pathlib import Path

from sql_values import SqlValues


@dataclass
class WordRow:
    """One translation to check, with everything a reviewer needs to judge its sense."""

    id: int  # EntryTranslation.id, the row a correction would update
    entryid: int
    permalink: int  # Assignment.id: the lesson context it was judged in
    lesson: str
    lang: str
    english: str
    current: str


class DumpReader:
    """Pulls one language's translations, their English words and their lessons out of an EarthFluent mysqldump (read-only)."""

    def __init__(self, dump: Path):
        self.dump = dump

    def rows(self, lang: str) -> list[WordRow]:
        titles, parents, translations = {}, {}, []
        for table, row in self._inserts():
            if table == "Entry":
                titles[int(row[0])] = row[1]
            elif table == "Assignment":
                parents.setdefault(int(row[2]), (int(row[0]), int(row[1])))  # child -> (assignment id, parent)
            elif table == "EntryTranslation" and row[5] == lang:
                translations.append(row)
        return [self._word(row, titles, parents, lang) for row in translations]

    def _word(self, row: list, titles: dict, parents: dict, lang: str) -> WordRow:
        entryid = int(row[6])
        permalink, parent = parents.get(entryid, (0, 0))
        return WordRow(int(row[0]), entryid, permalink, titles.get(parent, "(no lesson)"), lang, titles.get(entryid, "(missing entry)"), row[1])

    def _inserts(self):
        wanted = ("Entry", "Assignment", "EntryTranslation")
        with gzip.open(self.dump, "rt", encoding="utf-8", errors="replace") as dump:
            for line in dump:
                if line.startswith("INSERT INTO `"):
                    table = line[len("INSERT INTO `"):line.index("`", len("INSERT INTO `"))]
                    if table in wanted:
                        yield from ((table, row) for row in SqlValues(line).rows())
