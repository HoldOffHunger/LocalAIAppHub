import json
import re
import subprocess
from pathlib import Path

MODIFY = "/usr/lib/ggcms/cli/scripts/internal/entries/modify_entry.php"


def wsl_path(path: Path) -> str:
    # E:\AIWorkers\x.json is /mnt/e/AIWorkers/x.json inside Fumiko's WSL
    resolved = Path(path).resolve()
    return f"/mnt/{resolved.drive[0].lower()}{resolved.as_posix()[2:]}"


class IntSite:
    """yallhearingthis.com on int: Fumiko's WSL copy of production. Reads with mysql, writes only through modify_entry.php,
    so every rule modify.php has (americanising, codes, dates, image sizes) runs exactly as it does for a person."""

    def __init__(self, records: Path, domain: str = "yallhearingthis.com", database: str = "yallhearingthis", user: str = "1"):
        self.records = records  # each posted record is kept as a file, so a run can be read back afterwards
        self.domain = domain
        self.database = database
        self.user = user  # holdoffhunger; the site has two administrators, so ADMIN is refused as ambiguous
        self.records.mkdir(parents=True, exist_ok=True)

    def query(self, sql: str) -> list[dict]:
        done = self._wsl(["mysql", "-B", "--default-character-set=utf8mb4", self.database, "-e", sql])
        lines = done.stdout.splitlines()
        if not lines:
            return []
        names = lines[0].split("\t")
        return [dict(zip(names, line.split("\t"))) for line in lines[1:]]

    def section_id(self, code: str) -> int:
        rows = self.query(f"SELECT e.id FROM Entry e JOIN Assignment a ON a.Childid = e.id "
                          f"WHERE e.Code = '{_sql(code)}' AND a.Parentid = (SELECT Parentid FROM Assignment WHERE Childid = 0 LIMIT 1)")
        if not rows:
            raise LookupError(f"there's no /{code}/ section on int; create it first")
        return int(rows[0]["id"])

    def child_id(self, section: int, code: str) -> int | None:
        rows = self.query(f"SELECT e.id FROM Entry e JOIN Assignment a ON a.Childid = e.id "
                          f"WHERE a.Parentid = {int(section)} AND e.Code = '{_sql(code)}'")
        return int(rows[0]["id"]) if rows else None

    def code_of(self, entry: int) -> str:
        rows = self.query(f"SELECT Code FROM Entry WHERE id = {int(entry)}")
        return rows[0]["Code"] if rows else ""

    def entry_with_link(self, url: str) -> int | None:
        # A show is known by its video, not its title: two shows can share a title, and a retitled video is the same show
        rows = self.query(f"SELECT Entryid FROM Link WHERE URL = '{_sql(url)}' LIMIT 1")
        return int(rows[0]["Entryid"]) if rows else None

    def save(self, parent_path: str, name: str, record: dict, apply: bool = True, action: str = "Save") -> dict:
        """Save adds a child under parent_path; Update edits the entry at parent_path itself, as the Edit form does.
        record is {"fields": {...}, "files": {...}, "clear": [...]} in modify.php's own field names."""
        path = self.records / f"{name}.json"
        files = {field: [wsl_path(Path(f)) if f else "" for f in paths] for field, paths in record.get("files", {}).items()}
        record = {**record, "files": files} if files else record  # PHP runs in WSL and reads /mnt/e/..., not E:\...
        path.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
        argv = ["php8.1", MODIFY, self.domain, f"--path={parent_path}", f"--user={self.user}", f"--fields-json={wsl_path(path)}", f"--action={action}"]
        done = self._wsl(argv + (["--apply"] if apply else []), timeout=600)
        status = re.search(r"^Status\s*:\s*(.*)$", done.stdout, re.M)
        refused = re.search(r"^Refused\s*:\s*(.*)$", done.stdout, re.M)
        text = status.group(1) if status else (refused.group(1) if refused else "")
        return {"ok": re.search(r"(Save|Update) successful", text) is not None or (not apply and "Dry run" in done.stdout),
                "status": re.sub(r"<[^>]+>", " ", text).strip()[:300], "output": done.stdout[-3000:], "record": str(path)}

    def _wsl(self, argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
        # --exec skips the shell, so a transcript's quotes and dollar signs reach PHP as they are
        return subprocess.run(["wsl", "-u", "root", "--exec", *argv], capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=timeout)


def _sql(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "''")
