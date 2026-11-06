import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from task_store import Task
from worker_registry import Worker


OVERRUN_GRACE = timedelta(minutes=10)  # a worker finishing its last item gets this long past its stop time, then it's stopped


class WorkerRun:
    """The one task being worked right now, if any: started as its own process, logged to a file, stoppable."""

    def __init__(self, logs: Path):
        self.logs = logs
        self.logs.mkdir(parents=True, exist_ok=True)
        self.process: subprocess.Popen | None = None
        self.task: Task | None = None
        self.log_path: Path | None = None
        self.until = ""
        self.ends: datetime | None = None

    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def start(self, worker: Worker, task: Task, fill: dict, until: str, carry_on: bool = False) -> None:
        # carry_on: the same task restarted on a new stop time keeps writing to its log, so the page doesn't look like a fresh start
        if self.running():
            raise RuntimeError(f"{self.task.name} is already working")
        argv = worker.argv(worker.command, fill) + ([worker.until_flag, until] if worker.until_flag and until else [])
        if carry_on and self.task and self.task.id == task.id and self.log_path and self.log_path.exists():
            log = self.log_path.open("a", encoding="utf-8")
            log.write(f"--- stop time moved to {twelve_hour(until) if until else 'done'}: carrying on where it left off ---\n")
            log.flush()
        else:
            self.log_path = self.logs / f"task-{task.id}-{datetime.now():%Y-%m-%d_%H%M}.log"
            log = self.log_path.open("w", encoding="utf-8")
        flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        self.process = subprocess.Popen(argv, cwd=worker.folder, stdout=log, stderr=subprocess.STDOUT, creationflags=flags,
                                        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
        self.task, self.until = task, until
        self.ends = ends_at(until, datetime.now())

    def stop(self) -> None:
        if self.running():
            self.process.terminate()
            self.process.wait(timeout=20)

    def overdue(self, now: datetime) -> bool:
        # The workers' own clocks are the first line; this is the second, for a loop that forgot to look (26 Oct 2026)
        return self.running() and self.ends is not None and now.replace(tzinfo=None) >= self.ends + OVERRUN_GRACE

    def tail(self, lines: int = 40) -> list[str]:
        if not self.log_path or not self.log_path.exists():
            return []
        return self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:]

    def status(self) -> dict:
        return {"running": self.running(), "task": self.task.id if self.task else 0, "name": self.task.name if self.task else "",
                "until": self.until if self.running() else "", "log": self.log_path.name if self.log_path else ""}


def twelve_hour(until: str) -> str:
    # "19:37" is how the workers take it; Ben reads 7:37 PM
    return datetime.strptime(until, "%H:%M").strftime("%I:%M %p").lstrip("0")


def ends_at(until: str, started: datetime) -> datetime | None:
    # "06:00" given at 23:00 means tomorrow morning, as the workers read it
    if not until:
        return None
    ends = datetime.combine(started.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > started else ends + timedelta(days=1)
