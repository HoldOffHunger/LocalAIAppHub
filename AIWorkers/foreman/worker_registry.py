import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

DUMPS = Path(r"E:\Code\DB-Backups")

@dataclass
class Worker:
    """One kind of work the Foreman can hand out, described by its folder's worker.json."""

    name: str  # the folder name, and the task's kind
    folder: Path
    title: str
    description: str
    command: list[str]
    until_flag: str = ""
    stats: list[str] | None = None
    results: str = ""
    targets: list[str] = field(default_factory=list)  # what a task of this kind can aim at: sites, or languages

    def argv(self, parts: list[str], fill: dict | None = None) -> list[str]:
        # {python} is this venv; {target}, {queue} and {results} come from the task
        values = {"python": str(Path(sys.executable)), **(fill or {})}
        return [part.format(**values) if "{" in part else part for part in parts]

    def results_path(self, fill: dict | None = None) -> Path | None:
        if not self.results:
            return None
        path = Path(self.results.format(**(fill or {})))
        return path if path.is_absolute() else self.folder / path

    def summary(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description, "targets": self.targets}


def dumped_sites(dumps: Path = DUMPS) -> list[str]:
    # Every GGCMS site with a dump on disk; they all share one schema, so any of them can be a target
    return sorted({path.name.removesuffix(".sql.gz") for path in dumps.glob("20??-??-??/*.sql.gz")} - {"clonefrom"})


class WorkerRegistry:
    """Finds every worker under the AIWorkers root: drop in a folder with a worker.json and it appears."""

    def __init__(self, root: Path, sites=dumped_sites):
        self.root = root
        self.sites = sites

    def all(self) -> list[Worker]:
        found = []
        for spec in sorted(self.root.glob("*/worker.json")):
            data = json.loads(spec.read_text(encoding="utf-8"))
            if data.get("targets") == "sites":  # "any site with a dump" rather than a fixed list
                data["targets"] = self.sites()
            found.append(Worker(name=spec.parent.name, folder=spec.parent, **data))
        return found

    def get(self, name: str) -> Worker:
        for worker in self.all():
            if worker.name == name:
                return worker
        raise LookupError(f"there's no worker called {name!r}")
