import gzip
import re
from pathlib import Path

DUMPS = Path(r"E:\Code\DB-Backups")
COLUMN = re.compile(r"^\s+`([^`]+)`")
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "0": "\0", "Z": "\x1a", "b": "\b"}


def newest_dump(site: str) -> Path:
    # The dated backup folders sort by name; the newest one holding <site>.sql.gz wins
    found = sorted(DUMPS.glob(f"20??-??-??/{site}.sql.gz"))
    if not found:
        raise FileNotFoundError(f"there's no {site}.sql.gz under {DUMPS}\\<date>\\")
    return found[-1]


class DumpTables:
    """Reads chosen tables' rows out of a GGCMS mysqldump as dicts, by the column names in the dump's own CREATE TABLE (read-only)."""

    def __init__(self, dump: Path):
        self.dump = dump

    def rows(self, wanted: set[str]):
        columns, building = {}, None
        with gzip.open(self.dump, "rt", encoding="utf-8", errors="replace") as dump:
            for line in dump:
                if line.startswith("CREATE TABLE `"):
                    building = line.split("`")[1]
                    columns[building] = []
                elif building and (match := COLUMN.match(line)) and not line.lstrip().startswith(("PRIMARY", "KEY", "UNIQUE", "FULLTEXT")):
                    columns[building].append(match.group(1))
                elif line.startswith(")"):
                    building = None
                elif line.startswith("INSERT INTO `"):
                    table = line.split("`")[1]
                    if table in wanted:
                        for values in SqlValues(line).rows():
                            yield table, dict(zip(columns[table], values))


class SqlValues:
    """Reads the rows out of one mysqldump INSERT line, honouring quotes and backslash escapes; strings are cut a run at a time."""

    def __init__(self, line: str):
        self.line = line
        self.at = line.index(" VALUES ") + len(" VALUES ")

    def rows(self):
        while self.at < len(self.line) and self.line[self.at] == "(":
            self.at += 1
            yield self._row()
            self.at += 1  # the comma between rows, or the closing semicolon

    def _row(self) -> list:
        values = []
        while True:
            values.append(self._value())
            closing = self.line[self.at]
            self.at += 1
            if closing == ")":
                return values

    def _value(self):
        if self.line[self.at] == "'":
            return self._string()
        end = self.at
        while self.line[end] not in ",)":
            end += 1
        raw, self.at = self.line[self.at:end], end
        return None if raw == "NULL" else raw

    def _string(self) -> str:
        out, line, at = [], self.line, self.at + 1
        while True:
            quote, slash = line.find("'", at), line.find("\\", at)
            if slash == -1 or quote < slash:
                out.append(line[at:quote])
                self.at = quote + 1
                return "".join(out)
            out.append(line[at:slash])
            out.append(ESCAPES.get(line[slash + 1], line[slash + 1]))
            at = slash + 2
