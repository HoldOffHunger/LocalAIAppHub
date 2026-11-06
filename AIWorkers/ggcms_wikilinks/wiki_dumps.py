import gzip
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

import httpx

FOLDER = Path(__file__).resolve().parent.parent / "data" / "wikipedia"
CAP = 500 * 1000 ** 3  # Ben's cap for Wikipedia's files, 0.5 TB; the three tables this job reads are about 8 GB
FLOOR = 1000 ** 4  # and E: keeps at least a terabyte free whatever the cap says
BASE = "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-{}.sql.gz"
TABLES = ("externallinks", "page")  # redirects need no table: the API follows them
AGENT = {"User-Agent": "RevoltLibLinkFinder/1.0 (https://revoltlib.com/contact.php) httpx/0.28"}  # Wikimedia refuses a bot that gives no way to reach its owner
ESCAPES = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("0"): b"\0", ord("Z"): b"\x1a", ord("b"): b"\b"}


class WikiDumps:
    """English Wikipedia's link, page and redirect tables, downloaded once and kept under the cap; a download stopped at the stop time resumes."""

    def __init__(self, folder: Path = FOLDER, cap: int = CAP):
        self.folder = folder
        self.cap = cap
        self.folder.mkdir(parents=True, exist_ok=True)

    def path(self, table: str) -> Path:
        return self.folder / f"enwiki-{table}.sql.gz"

    def about(self) -> dict:
        found = self.folder / "dumps.json"
        return json.loads(found.read_text(encoding="utf-8")) if found.exists() else {}

    def ready(self) -> bool:
        return all(self.path(table).exists() for table in TABLES)

    def fetch(self, ends: datetime | None, refresh: bool = False) -> bool:
        # True when every table is here; a refresh fetches a table again only if Wikimedia has a newer one
        about = self.about()
        for table in TABLES:
            if self.path(table).exists() and not refresh:
                continue
            with httpx.Client(headers=AGENT, timeout=60, follow_redirects=True) as client:
                head = client.head(BASE.format(table))
                head.raise_for_status()
                size, stamp = int(head.headers["content-length"]), head.headers.get("last-modified", "")
                if self.path(table).exists() and about.get(table, {}).get("last_modified") == stamp:
                    continue
                self._room_for(size)
                print(f"downloading Wikipedia's {table} table ({size / 1000 ** 3:.1f} GB, {stamp})", flush=True)
                if not self._download(client, table, size, ends):
                    return False
            about[table] = {"last_modified": stamp, "bytes": size, "fetched": datetime.now().isoformat(timespec="seconds")}
            (self.folder / "dumps.json").write_text(json.dumps(about, indent=1), encoding="utf-8")
        return True

    def used(self) -> int:
        return sum(item.stat().st_size for item in self.folder.rglob("*") if item.is_file())

    def _room_for(self, size: int) -> None:
        if self.used() + size > self.cap:
            raise RuntimeError(f"Wikipedia's files would pass the {self.cap / 1000 ** 4:.1f} TB cap; clear {self.folder} first.")
        if shutil.disk_usage(self.folder).free - size < FLOOR:
            raise RuntimeError(f"Downloading would leave {self.folder.drive} with less than a terabyte free.")

    def _download(self, client: httpx.Client, table: str, size: int, ends: datetime | None) -> bool:
        final = self.path(table)
        part = final.with_name(final.name + ".part")
        have = part.stat().st_size if part.exists() else 0
        last = time.monotonic()
        with client.stream("GET", BASE.format(table), headers={"Range": f"bytes={have}-"} if have else {}) as reply, part.open("ab") as out:
            reply.raise_for_status()
            if have and reply.status_code != 206:
                out.truncate(0)  # the server ignored the range: start over rather than glue two files together
                have = 0
            for chunk in reply.iter_bytes(1 << 20):
                out.write(chunk)
                have += len(chunk)
                if time.monotonic() - last > 60:
                    print(f"  {have / size:.0%} of {table}", flush=True)
                    last = time.monotonic()
                if ends and datetime.now() >= ends:
                    print(f"  stopped at {have / size:.0%}; the download resumes next turn", flush=True)
                    return False
        if have != size:
            raise RuntimeError(f"{part.name} came to {have:,} bytes, not {size:,}; it resumes next turn.")
        part.replace(final)
        return True


def table_rows(path: Path, skip: int = 0):
    """(line number, row) for each row line of a Wikipedia table dump, which since 2024 puts one row on each line; the first `skip` aren't parsed."""
    with gzip.open(path, "rb") as dump:
        for number, line in enumerate(dump):
            if number >= skip and line.startswith(b"("):
                yield number, line


def row_values(line: bytes, count: int) -> list:
    # The first `count` values of one row line: ints stay bytes, strings come back unescaped; nothing past them is read
    values, at = [], 1
    while len(values) < count:
        if line[at] == 0x27:  # a quoted string
            out, at = bytearray(), at + 1
            while True:
                quote, slash = line.find(b"'", at), line.find(b"\\", at)
                if slash == -1 or quote < slash:
                    out += line[at:quote]
                    at = quote + 1
                    break
                out += line[at:slash]
                out += ESCAPES.get(line[slash + 1], line[slash + 1:slash + 2])
                at = slash + 2
            values.append(bytes(out))
        else:
            end = at
            while line[end] not in b",)":
                end += 1
            values.append(line[at:end])
            at = end
        at += 1  # the comma, or the closing bracket
    return values
