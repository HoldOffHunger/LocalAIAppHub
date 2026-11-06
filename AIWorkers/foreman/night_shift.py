import logging
import threading
from datetime import datetime, timedelta
from typing import Callable

from chat_hold import ChatHold
from chron_wait import ChronWait
from foreman_settings import ForemanSettings
from gpu_guard import GpuGuard
from presence import Presence
from worker_run import WorkerRun, twelve_hour

log = logging.getLogger("foreman")
QUICK = timedelta(minutes=2)  # a turn back this fast had nothing it could do (Wikipedia links on the Archive's 429): no more rounds for it
AWAY = 15 * 60  # seconds untouched before Ben counts as gone to bed, in the shift that runs until he wakes


class NightShift:
    """Watches the clock: while Ben's window is open, works the active tasks one after another, each at most once per window."""

    def __init__(self, settings: ForemanSettings, run: WorkerRun, guard: GpuGuard, launch: Callable[[set, datetime, datetime], int | None],
                 hold: ChatHold, poll_seconds: float = 20.0, chron: ChronWait | None = None, presence: Presence | None = None):
        self.settings = settings
        self.run = run
        self.guard = guard
        self.launch = launch  # starts the next task not in the set, for its share of now..ends; returns its id, or None when none is left
        self.hold = hold  # Ben chatting in Local Chat: nothing starts until the chat goes quiet
        self.chron = chron or ChronWait()  # the hub's Chron Jobs: nothing starts while a nightly job is due or running
        self.presence = presence or Presence()  # whether Ben is at the PC, for the shift that runs until he wakes
        self.slept = False  # Ben has been away long enough this window to count as asleep
        self.poll_seconds = poll_seconds
        self.closing = threading.Event()
        self.done_until: datetime | None = None  # Ben stopped this window's shift, or it ran out of tasks
        self.window: datetime | None = None
        self.worked: set[int] = set()  # tasks this round has already had a turn
        self.quick: set[int] = set()  # tasks whose turn this window came straight back: they sit out its later rounds
        self.turn: tuple[int, datetime] | None = None  # the shift's own turn in progress: which task, and when it started
        self.free_until: datetime | None = None  # free time Ben gave the workers, like Autonoma's: a window opened by hand
        self.rest_until: datetime | None = None  # the breather between two turns (Ben's setting): nothing starts before it
        self.note = ""  # why it's waiting, for the page

    def start(self) -> None:
        threading.Thread(target=self._watch, name="night-shift", daemon=True).start()

    def give_time(self, ends: datetime) -> bool:
        self.free_until, self.done_until, self.rest_until = ends, None, None  # Ben's hand on it: no waiting out a rest
        return self.tick()

    def window_end(self, now: datetime) -> datetime | None:
        # Free time wins while it lasts; otherwise it's the schedule's window, if one is open
        if self.free_until and now < self.free_until:
            return self.free_until
        self.free_until = None
        return self.settings.window_end(now)

    def tick(self, now: datetime | None = None) -> bool:
        now = now or datetime.now().astimezone()
        if self.hold.holding(now):
            self.note = "Paused: Ben is chatting."
            return False
        if self.run.overdue(now):
            name = self.run.task.name
            self.run.stop()
            self.note = f"Stopped {name}: it ran past its stop time of {twelve_hour(self.run.until)}."
            log.warning(self.note)
            with self.run.log_path.open("a", encoding="utf-8") as log_file:  # the page shows the log's tail, so say it there
                log_file.write(f"--- The Foreman {self.note[0].lower()}{self.note[1:]} ---\n")
            return False
        if self.turn and not self.run.running():
            task_id, began = self.turn
            self.turn = None
            if now - began < QUICK:
                self.quick.add(task_id)
            elif self.settings.rest_minutes():
                self.rest_until = now + timedelta(minutes=self.settings.rest_minutes())  # a turn that came straight back did no work to rest from
            log.info("task %s's turn ended after %s", task_id, str(now - began).split(".")[0])
        ends = self.window_end(now)
        if ends != self.window:
            self.window, self.worked, self.quick, self.slept = ends, set(), set(), False
        if ends is not None and ends != self.done_until and not self.free_until and self.settings.until_awake() and not self._asleep(now, ends):
            return False
        if ends is None or ends == self.done_until or self.run.running():
            self.note = "" if ends is None or self.run.running() else self.note
            if self.run.running():
                self.guard.desk_renew()  # the turn keeps its place at the desk while it works
            return False
        if self.rest_until and now < self.rest_until:
            self.note = f"Resting between jobs until {twelve_hour(self.rest_until.strftime('%H:%M'))}."
            return False
        if self.guard.autonoma_busy():
            self.note = "Waiting: Autonoma's model is on the GPU."
            return False
        job = self.chron.busy_job()  # asked before the desk, so a wait for the backup never holds a lease on the card
        if job:
            self.note = f"Waiting: Chron Jobs is running {job}."
            return False
        refusal = self.guard.desk_refusal()
        if refusal:
            self.note = f"Waiting: {refusal}."
            return False
        started = self.launch(self.worked, now, ends)
        if started is None and self.worked - self.quick:
            # Everyone has had a turn and there's time left: another round. On 31 Oct 2026 an hour's free time gave each of three
            # tasks twenty minutes, Wikipedia links came back in a second, and the shift sat idle for its last twenty minutes
            self.worked = set(self.quick)
            log.info("a new round, until %s; sitting out: %s", ends.strftime("%H:%M"), sorted(self.quick) or "nobody")
            started = self.launch(self.worked, now, ends)
        if started is None:
            self.done_until, self.note = ends, "The night shift has nothing left to do tonight."
            log.info("nothing left to do until %s (came straight back: %s)", ends.strftime("%H:%M"), sorted(self.quick) or "nobody")
            return False
        self.worked.add(started)
        self.turn = (started, now)
        self.note = ""
        log.info("started task %s, until %s", started, self.run.until or "done")
        return True

    def _asleep(self, now: datetime, ends: datetime) -> bool:
        # The shift that runs until Ben wakes: it starts once he's been away from the PC for AWAY, and the first touch of
        # the keyboard or mouse after that ends the night, stopping the shift's own turn (never a task he ran by hand).
        # Free time he gives by hand isn't asked about: he's at the PC when he gives it
        idle = self.presence.idle_seconds()
        if idle is None:
            self.note = "Waiting: Windows won't say whether Ben is at the PC."
            return False
        if idle >= AWAY:
            self.slept = True
            return True
        if not self.slept:
            self.note = f"Waiting: Ben is still at the PC. The night shift starts once he's been away {AWAY // 60} minutes."
            return False
        if self.turn and self.run.running():
            name = self.run.task.name
            self.run.stop()
            with self.run.log_path.open("a", encoding="utf-8") as log_file:
                log_file.write(f"--- The Foreman stopped {name}: Ben is up. ---\n")
        self.turn, self.done_until = None, ends
        self.note = f"Good morning! The night shift stopped at {now.strftime('%H:%M')}, when Ben came back to the PC."
        log.info("Ben is back at the PC; the night shift is done until %s", ends.strftime("%a %H:%M"))
        return False

    def _watch(self) -> None:
        while not self.closing.wait(self.poll_seconds):
            try:
                self.tick()
            except Exception:  # a bad tick must never stop the watching
                log.exception("night shift tick failed")
