import threading
from datetime import datetime, timedelta
from typing import Callable

from task_store import Task
from worker_run import WorkerRun


class ChatHold:
    """Ben is chatting, so the card is his: the running task steps aside, and goes back to work once the chat has been quiet a while."""

    def __init__(self, resume: Callable[[Task, str], None]):
        self.resume = resume  # restarts the stepped-aside task with the stop time it had
        self.lock = threading.Lock()
        self.until: datetime | None = None
        self.task: Task | None = None
        self.task_until = ""
        self.stopped_at: datetime | None = None

    def hold(self, minutes: int, run: WorkerRun, now: datetime) -> None:
        # Each chat message pushes the quiet time out again; only the first one has a worker to stop. Holds come from
        # Chat and from the hub's GPU desk on behalf of Images, so a shorter one never cuts a longer one short.
        with self.lock:
            if run.running() and self.task is None:
                self.task, self.task_until, self.stopped_at = run.task, run.until, now
                run.stop()
            self.until = max(self.until or now, now + timedelta(minutes=minutes))

    def holding(self, now: datetime) -> bool:
        # True while the chat is warm; the first call after it cools sends the stepped-aside task back to work
        with self.lock:
            if self.until and now < self.until:
                return True
            task, task_until, stopped_at = self.task, self.task_until, self.stopped_at
            self.until, self.task = None, None
        if task and not _past(task_until, stopped_at, now):
            self.resume(task, task_until)
        return False

    def end(self) -> None:
        # The hub's "kick chat off the GPU": the chat counts as quiet now, so the next tick sends the stepped-aside task back
        with self.lock:
            self.until = None

    def clear(self) -> None:
        # Ben's own hand on the Foreman (run, free time, stop) overrides the hold, and nothing comes back on its own
        with self.lock:
            self.until, self.task = None, None


def _past(until: str, stopped_at: datetime, now: datetime) -> bool:
    # A task told to stop at 04:30 that was held past 04:30 has had its turn
    if not until:
        return False
    stop = datetime.combine(stopped_at.date(), datetime.strptime(until, "%H:%M").time(), stopped_at.tzinfo)
    stop += timedelta(days=1) if stop <= stopped_at else timedelta()
    return now >= stop
