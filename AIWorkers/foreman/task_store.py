import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

EDITABLE = {"name", "notes", "active", "deployed"}
COLUMNS = "id, name, kind, target, active, notes, created, deployed"


@dataclass
class Task:
    """One job on the board: a kind of work (a worker folder) aimed at one target, like spellcheck × revoltlib."""

    id: int
    name: str
    kind: str  # the worker folder that does the work
    target: str  # the site or language it works on
    active: bool  # in the night shift's rotation
    notes: str
    created: str
    deployed: str = ""  # the day its results went live; a deployed task moves to Completed Jobs and leaves the night shift

    def as_dict(self) -> dict:
        return asdict(self)


class TaskStore:
    """Ben's tasks, kept in the Foreman's own SQLite file. Each task's work pile lives beside it, in data/tasks/."""

    def __init__(self, path: Path):
        self.folder = path.parent / "tasks"
        self.folder.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path, check_same_thread=False)
        self.connection.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, name TEXT, kind TEXT, target TEXT, "
                                "active INTEGER DEFAULT 1, notes TEXT DEFAULT '', created TEXT, deployed TEXT DEFAULT '')")
        if "deployed" not in {row[1] for row in self.connection.execute("PRAGMA table_info(tasks)")}:
            with self.connection:
                self.connection.execute("ALTER TABLE tasks ADD COLUMN deployed TEXT DEFAULT ''")

    def all(self) -> list[Task]:
        return [self._task(row) for row in self.connection.execute(f"SELECT {COLUMNS} FROM tasks ORDER BY id")]

    def get(self, task_id: int) -> Task:
        row = self.connection.execute(f"SELECT {COLUMNS} FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise LookupError(f"there's no task {task_id}")
        return self._task(row)

    def add(self, kind: str, target: str, name: str) -> Task:
        with self.connection:
            cursor = self.connection.execute("INSERT INTO tasks (id, name, kind, target, created) VALUES (?, ?, ?, ?, ?)",
                                             (self._next_id(), name, kind, target, datetime.now().astimezone().isoformat(timespec="seconds")))
        return self.get(cursor.lastrowid)

    def _next_id(self) -> int:
        # Never reuse a deleted task's id: its pile stays in data/tasks/, and a new task with that id would inherit it
        (highest,) = self.connection.execute("SELECT COALESCE(MAX(id), 0) FROM tasks").fetchone()
        piles = [int(number) for number in (path.name.split(".")[0].removeprefix("task-") for path in self.folder.glob("task-*"))
                 if number.isdigit()]
        return max([highest, *piles]) + 1

    def update(self, task_id: int, **fields) -> Task:
        self.get(task_id)
        for field, value in fields.items():
            if field not in EDITABLE:
                raise ValueError(f"a task's {field} can't be changed")
            with self.connection:
                self.connection.execute(f"UPDATE tasks SET {field} = ? WHERE id = ?", (value, task_id))
        return self.get(task_id)

    def delete(self, task_id: int) -> None:
        # The work pile stays in data/tasks/: deleting a card never throws away what the workers found
        self.get(task_id)
        with self.connection:
            self.connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    def paths(self, task: Task) -> dict:
        return {"queue": str(self.folder / f"task-{task.id}.sqlite"), "results": str(self.folder / f"task-{task.id}.results.txt")}

    @staticmethod
    def _task(row) -> Task:
        task_id, name, kind, target, active, notes, created, deployed = row
        return Task(task_id, name, kind, target, bool(active), notes or "", created or "", deployed or "")
