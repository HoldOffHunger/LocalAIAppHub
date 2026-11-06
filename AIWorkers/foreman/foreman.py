import json
import logging
import secrets
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

from chat_hold import ChatHold
from foreman_settings import ForemanSettings
from gpu_guard import GpuGuard
from night_shift import NightShift
from task_store import Task, TaskStore
from worker_registry import WorkerRegistry
from worker_run import WorkerRun, ends_at

log = logging.getLogger("foreman")
CHAT_NOTE = "Paused: Ben is chatting."
SHORTEST_TURN = timedelta(minutes=15)  # less than this, and loading the models is most of the turn
LONGEST_TURN_ASLEEP = timedelta(hours=1)  # until Ben wakes, nobody knows how long the night is: turns of an hour, round after round
LONGEST_CHAT_HOLD = 120  # minutes; a chat that asks for more is asking for something else
LAST_START = timedelta(minutes=2)  # with less left than this, a stop time written to the minute could already be past


class Foreman:
    """Everything the page needs: the tasks and how far along each is, the schedule, the run in progress and what each task found."""

    def __init__(self, root: Path):
        self.root = root
        self.token = secrets.token_urlsafe(32)
        self.registry = WorkerRegistry(root)
        self.settings = ForemanSettings(root / "data" / "foreman.json")
        self.tasks = TaskStore(root / "data" / "foreman.sqlite")
        self.run = WorkerRun(root / "data" / "logs")
        self.hold = ChatHold(self._resume)
        self.shift = NightShift(self.settings, self.run, GpuGuard(), self._launch_next, self.hold)
        self.progress_cache: dict[int, tuple[float, dict]] = {}
        self._adopt_old_driver()

    def add_task(self, kind: str, target: str, name: str) -> Task:
        worker = self.registry.get(kind)
        if worker.targets and target not in worker.targets:
            raise ValueError(f"{worker.title} works on {', '.join(worker.targets)}, not {target!r}.")
        return self.tasks.add(kind, target, name.strip() or f"{worker.title} · {target}")

    def run_now(self, task_id: int, minutes: int = 0, until: str = "") -> None:
        # "Give it an hour" becomes a stop time; neither means work until the pile is done
        self.hold.clear()
        if minutes:
            until = (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M")
        elif until:
            datetime.strptime(until, "%H:%M")
        self._start(self.tasks.get(task_id), until)
        log.info("Ben ran task %s by hand, until %s", task_id, until or "done")
        self.shift.free_until = None
        self.shift.done_until = self.shift.window_end(datetime.now().astimezone())  # Ben's hand on it: the shift stands aside this window

    def give_time(self, minutes: int) -> None:
        # "Give the workers an hour": the night shift's rotation, starting now
        if minutes < 1:
            raise ValueError("Give them at least a minute.")
        self.hold.clear()
        if self.run.running():
            raise RuntimeError(f"{self.run.task.name} is already working; stop it first.")
        log.info("Ben gave the workers %s minutes", minutes)
        if not self.shift.give_time(datetime.now().astimezone() + timedelta(minutes=minutes)):
            raise RuntimeError(self.shift.note or "There's nothing for them to do: every active task is finished.")

    def stop(self) -> None:
        log.info("Ben stopped the workers")
        self.hold.clear()
        self.run.stop()
        self.shift.done_until = self.shift.window_end(datetime.now().astimezone())  # stopping it early won't restart it this window
        self.shift.free_until = None

    def hold_for_chat(self, minutes: int) -> None:
        # Local Chat asks before each reply: the worker steps aside, and the shift waits until the chat goes quiet
        if not 1 <= minutes <= LONGEST_CHAT_HOLD:
            raise ValueError(f"Hold for 1 to {LONGEST_CHAT_HOLD} minutes.")
        log.info("Local Chat holds the card for %s minutes", minutes)
        self.hold.hold(minutes, self.run, datetime.now().astimezone())
        self.shift.note = CHAT_NOTE

    def stretch(self, minutes: int) -> None:
        # "Actually, give it two hours": the free time and the running task's stop time both move by the same amount. A worker
        # reads its stop time once and plans its turn around it, so it restarts on the new one and picks up where it left off.
        delta = timedelta(minutes=minutes)
        log.info("Ben moved the stop time by %s minutes", minutes)
        free, run_end, held_end = self._stop_times()
        free, run_end, held_end = [end + delta if end else None for end in (free, run_end, held_end)]
        if not (free or run_end or held_end):
            raise RuntimeError("Nothing is working to a stop time right now.")
        now = datetime.now()
        for end in (free, run_end, held_end):
            if end and end.replace(tzinfo=None) - now < timedelta(minutes=1):
                raise ValueError("That stop time has already gone by.")
            if end and end.replace(tzinfo=None) - now >= timedelta(hours=24):
                raise ValueError("A stop time can be at most a day away.")
        if free:
            self.shift.free_until = self.shift.window = free  # the same window, only longer: tasks that had their turn keep it
        if held_end:
            self.hold.task_until = held_end.strftime("%H:%M")
        if run_end:
            # The same turn, only longer: its log carries on, and its model stays on the card rather than reloading
            task = self.run.task
            self.run.stop()
            self.run.start(self.registry.get(task.kind), task, self._fill(task), run_end.strftime("%H:%M"), carry_on=True)

    def _stop_times(self) -> tuple:
        # When the free time ends, when the running task stops, and when the task the chat stepped aside would have stopped
        hold = self.hold
        held = ends_at(hold.task_until, hold.stopped_at.replace(tzinfo=None)) if hold.task and hold.task_until else None
        return self.shift.free_until, self.run.ends if self.run.running() else None, held

    def _latest_stop(self) -> str:
        # What the page's stop-time box starts from; "" when nothing is working to a stop time
        ends = [end.replace(tzinfo=None) for end in self._stop_times() if end]
        return max(ends).isoformat(timespec="minutes") if ends else ""

    def end_chat_hold(self) -> None:
        # Ben kicked Chat off the card from the hub: the workers needn't wait out the quiet time
        self.hold.end()
        if self.shift.note == CHAT_NOTE:
            self.shift.note = ""

    def state(self) -> dict:
        return {"tasks": [{**task.as_dict(), "progress": self._progress(task)} for task in self.tasks.all()],
                "kinds": [worker.summary() for worker in self.registry.all()],
                "schedule": self.settings.data["schedule"], "run": self.run.status(), "log": self.run.tail(), "waiting": self.shift.note,
                "free_until": self.shift.free_until.strftime("%H:%M") if self.shift.free_until else "",
                "ends_at": self._latest_stop(), "rest_minutes": self.settings.rest_minutes(),
                "rotation": {"worked": sorted(self.shift.worked), "quick": sorted(self.shift.quick)}}

    def results(self, task_id: int) -> str:
        task = self.tasks.get(task_id)
        path = self.registry.get(task.kind).results_path(self._fill(task))
        return path.read_text(encoding="utf-8")[-200_000:] if path and path.exists() else "(no results yet)"

    def _start(self, task: Task, until: str) -> None:
        self.shift.guard.clear_card()  # each turn starts with the whole card, whatever the last task left loaded
        self.run.start(self.registry.get(task.kind), task, self._fill(task), until)
        self.progress_cache.pop(task.id, None)

    def _resume(self, task: Task, until: str) -> None:
        # The task the chat stopped goes back to work with its old stop time, unless Ben deleted it or something else is working
        try:
            task = self.tasks.get(task.id)
        except LookupError:
            return
        if not self.run.running():
            self._start(task, until)

    def _launch_next(self, worked: set, now: datetime, ends: datetime) -> int | None:
        # The night shift's pick: the first active task that hasn't had its turn this window and still has work left.
        # It gets its share of what's left of the window, not all of it: a long pile at the top of the board (RevoltLib's
        # 14,000 quotes) took every window whole, and the cards below it never had a turn.
        waiting = [task for task in self.tasks.all()
                   if task.active and not task.deployed and task.id not in worked and not self._progress(task, fresh=True).get("complete")]
        if not waiting:
            return None
        share = max((ends - now) / len(waiting), SHORTEST_TURN)
        if self.settings.until_awake() and not self.shift.free_until:
            share = min(share, LONGEST_TURN_ASLEEP)
        stop = min(now + share, ends)
        if stop - now < LAST_START:
            # On 2 Nov 2026 a new round began 27 seconds before free time ended at 14:13:47. Its stop time went out as "14:13",
            # already past, so the worker and the overrun check both read it as tomorrow's 14:13, and it worked on all afternoon
            return None
        self._start(waiting[0], stop.strftime("%H:%M"))
        return waiting[0].id

    def _fill(self, task: Task) -> dict:
        return {"target": task.target, **self.tasks.paths(task)}

    def _progress(self, task: Task, fresh: bool = False) -> dict:
        # Each task reports itself, at most every 20 seconds; a broken stats script shouldn't break the page
        cached = self.progress_cache.get(task.id)
        if cached and not fresh and time.time() - cached[0] < 20:
            return cached[1]
        self.progress_cache[task.id] = (time.time(), _counted(self._ask_progress(task)))
        return self.progress_cache[task.id][1]

    def _ask_progress(self, task: Task) -> dict:
        try:
            worker = self.registry.get(task.kind)
        except LookupError:
            return {"error": f"the {task.kind} worker folder is missing"}
        if not worker.stats:
            return {}
        try:
            out = subprocess.run(worker.argv(worker.stats, self._fill(task)), cwd=worker.folder, capture_output=True, text=True,
                                 timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return json.loads(out.stdout.strip().splitlines()[-1])
        except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
            return {"error": "couldn't read progress"}

    def _adopt_old_driver(self) -> None:
        # The first Foreman had one worker in the driver's seat; it becomes the first task card
        driver = self.settings.data.pop("driver", "")
        if driver and not self.tasks.all():
            worker = self.registry.get(driver)
            self.tasks.add(driver, worker.targets[0] if worker.targets else "", worker.title)
        self.settings.save()


def _counted(progress: dict) -> dict:
    # Workers report done and total; the first worker said checked and left, which means the same
    if "done" not in progress and "checked" in progress and "left" in progress:
        progress = {**progress, "done": progress["checked"], "total": progress["checked"] + progress["left"]}
    if "done" in progress and "total" in progress:
        progress["percent"] = round(100 * progress["done"] / progress["total"], 1) if progress["total"] else 0
        progress["complete"] = progress["total"] > 0 and progress["done"] >= progress["total"]
    return progress
