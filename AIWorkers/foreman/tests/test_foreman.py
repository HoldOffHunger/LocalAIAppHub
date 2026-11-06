import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from foreman import Foreman, _counted  # noqa: E402
from foreman_settings import ForemanSettings  # noqa: E402
from worker_registry import WorkerRegistry  # noqa: E402
from worker_run import WorkerRun  # noqa: E402

LOCAL = datetime.now().astimezone().tzinfo


class Guard:
    def __init__(self, busy=False, refusal=""):
        self.busy = busy
        self.refusal = refusal  # what the hub's GPU desk says; "" gives the workers the card
        self.renewed = 0

    def autonoma_busy(self):
        return self.busy

    def desk_refusal(self, minutes=5):
        return self.refusal

    def desk_renew(self, minutes=2):
        self.renewed += 1

    def clear_card(self):
        self.cleared = True


@pytest.fixture(autouse=True)
def card_untouched(monkeypatch):
    # The tests must never unload the real models on Fumiko's card, nor take the card at the real hub's GPU desk
    monkeypatch.setattr("gpu_guard.GpuGuard.clear_card", lambda self: None)
    monkeypatch.setattr("gpu_guard.GpuGuard.desk_refusal", lambda self, minutes=5: "")
    monkeypatch.setattr("gpu_guard.GpuGuard.desk_renew", lambda self, minutes=2: None)
    monkeypatch.setattr("chron_wait.ChronWait.busy_job", lambda self: "")  # nor ask the real Chron Jobs, which is busy at 3 AM


class Chron:
    def __init__(self, job=""):
        self.job = job  # what Chron Jobs says is due or running; "" lets the shift start

    def busy_job(self):
        return self.job


@pytest.fixture
def root(tmp_path):
    # A pretend worker that prints its arguments and finishes, and reports progress from a file
    folder = tmp_path / "echo"
    folder.mkdir()
    (tmp_path / "data").mkdir()
    (folder / "echo.py").write_text("import sys; print('working', sys.argv[1:])", encoding="utf-8")
    (folder / "stats.py").write_text("import sys, pathlib; p = pathlib.Path(sys.argv[1] + '.done');"
                                     "print('{\"done\": %d, \"total\": 10}' % (10 if p.exists() else 3))", encoding="utf-8")
    (folder / "worker.json").write_text(json.dumps({"title": "Echo", "description": "Says what it was told.", "targets": ["a", "b"],
                                                     "command": ["{python}", "echo.py", "--on", "{target}"], "until_flag": "--until",
                                                     "stats": ["{python}", "stats.py", "{queue}"]}), encoding="utf-8")
    return tmp_path


def at(hour, minute=0, day=13):
    return datetime(2026, 10, day, hour, minute, tzinfo=LOCAL)


def test_a_window_across_midnight_belongs_to_the_day_it_starts(tmp_path):
    settings = ForemanSettings(tmp_path / "foreman.json")
    settings.set_schedule(True, "23:00", "02:00", [0])  # Monday nights
    assert settings.window_end(at(23, 30, day=12)) == at(2, day=13)  # 12 Oct 2026 is a Monday
    assert settings.window_end(at(1, 0, day=13)) == at(2, day=13)
    assert settings.window_end(at(23, 30, day=13)) is None  # Tuesday isn't ticked


def test_tasks_are_a_kind_aimed_at_a_target(root):
    foreman = Foreman(root)
    task = foreman.add_task("echo", "b", "")
    assert task.name == "Echo · b" and task.active
    with pytest.raises(ValueError):
        foreman.add_task("echo", "nowhere", "")
    with pytest.raises(LookupError):
        foreman.add_task("nobody", "a", "")
    foreman.tasks.update(task.id, name="Renamed", active=False)
    assert foreman.tasks.get(task.id).name == "Renamed" and not foreman.tasks.get(task.id).active
    with pytest.raises(ValueError):
        foreman.tasks.update(task.id, kind="other")


def test_a_deleted_tasks_id_is_never_reused(root):
    foreman = Foreman(root)
    foreman.add_task("echo", "b", "")
    last = foreman.add_task("echo", "b", "")
    Path(foreman.tasks.paths(last)["queue"]).write_text("its pile")  # what the workers found outlives the card
    foreman.tasks.delete(last.id)
    assert foreman.add_task("echo", "b", "").id == last.id + 1


def test_the_shift_works_each_active_unfinished_task_once_per_window(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard(busy=True)
    foreman.settings.set_schedule(True, "03:00", "06:00", list(range(7)))
    first, paused, finished, second = (foreman.add_task("echo", t, n) for t, n in (("a", "1"), ("a", "2"), ("a", "3"), ("b", "4")))
    foreman.tasks.update(paused.id, active=False)
    Path(foreman.tasks.paths(finished)["queue"] + ".done").write_text("", encoding="utf-8")
    assert not foreman.shift.tick(at(3, 5)) and "Autonoma" in foreman.shift.note
    foreman.shift.guard.busy = False
    assert foreman.shift.tick(at(3, 6)) and foreman.run.task.id == first.id
    foreman.run.process.wait(timeout=30)
    assert "working ['--on', 'a', '--until', '04:33']" in "\n".join(foreman.run.tail())  # half of 03:06-06:00: two tasks want it
    assert foreman.shift.tick(at(3, 7)) and foreman.run.task.id == second.id  # skips the paused and the finished
    foreman.run.process.wait(timeout=30)
    assert not foreman.shift.tick(at(3, 8)) and "nothing left" in foreman.shift.note
    assert foreman.shift.tick(at(3, 8, day=14))  # a new night, a new round


def test_free_time_works_the_rotation_now_and_stop_ends_it(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    first, second = foreman.add_task("echo", "a", "1"), foreman.add_task("echo", "b", "2")
    foreman.give_time(60)
    assert foreman.run.task.id == first.id and foreman.state()["free_until"]
    foreman.run.process.wait(timeout=30)
    assert foreman.shift.tick() and foreman.run.task.id == second.id  # the first finished early; the next takes its turn
    foreman.stop()
    assert not foreman.state()["free_until"] and not foreman.shift.tick()
    with pytest.raises(ValueError):
        foreman.give_time(0)


def test_each_task_gets_its_share_of_the_window_not_all_of_it(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    foreman.settings.set_schedule(True, "03:00", "04:00", list(range(7)))
    foreman.settings.set_rest(0)  # about the turns' shares, not the rest between them
    for target in ("a", "b", "a"):
        foreman.add_task("echo", target, "")
    assert foreman.shift.tick(at(3, 0))
    foreman.run.process.wait(timeout=30)
    assert "'--until', '03:20'" in "\n".join(foreman.run.tail())  # a third of the hour each
    foreman.shift.worked = set(task.id for task in foreman.tasks.all()[:2])
    assert foreman.shift.tick(at(3, 50))
    foreman.run.process.wait(timeout=30)
    assert "'--until', '04:00'" in "\n".join(foreman.run.tail())  # never past the window, even for the shortest turn


def test_targets_can_be_every_site_with_a_dump(root):
    spec = root / "echo" / "worker.json"
    spec.write_text(json.dumps({**json.loads(spec.read_text(encoding="utf-8")), "targets": "sites"}), encoding="utf-8")
    assert WorkerRegistry(root, sites=lambda: ["earthfluent", "revoltlib"]).get("echo").targets == ["earthfluent", "revoltlib"]


def test_run_now_gives_a_task_a_stop_time(root):
    foreman = Foreman(root)
    task = foreman.add_task("echo", "a", "")
    foreman.run_now(task.id, minutes=60)
    foreman.run.process.wait(timeout=30)
    assert "--until" in "\n".join(foreman.run.tail())
    progress = foreman.state()["tasks"][0]["progress"]
    assert progress["percent"] == 30.0 and not progress["complete"]


def test_the_old_driver_becomes_the_first_task(root):
    (root / "data" / "foreman.json").write_text(json.dumps({"driver": "echo", "schedule": {"enabled": False, "start": "03:00",
                                                                                            "end": "06:00", "days": [0]}}), encoding="utf-8")
    foreman = Foreman(root)
    assert [(t.kind, t.target) for t in foreman.tasks.all()] == [("echo", "a")]
    assert "driver" not in json.loads((root / "data" / "foreman.json").read_text(encoding="utf-8"))


def test_checked_and_left_count_as_done_and_total():
    assert _counted({"checked": 5, "left": 15})["percent"] == 25.0
    assert _counted({"done": 0, "total": 0})["complete"] is False


def test_only_one_task_at_a_time(root):
    foreman = Foreman(root)
    task = foreman.add_task("echo", "a", "")
    (root / "echo" / "echo.py").write_text("import time; time.sleep(5)", encoding="utf-8")
    run = WorkerRun(root / "logs")
    worker = WorkerRegistry(root).get("echo")
    run.start(worker, task, {"target": "a"}, "")
    with pytest.raises(RuntimeError):
        run.start(worker, task, {"target": "a"}, "")
    run.stop()
    assert not run.running()


def test_a_chat_steps_the_worker_aside_and_it_comes_back_when_the_chat_goes_quiet(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    (root / "echo" / "echo.py").write_text("import sys, time; print('working', sys.argv[1:], flush=True); time.sleep(30)", encoding="utf-8")
    task = foreman.add_task("echo", "a", "")
    foreman.run_now(task.id, minutes=600)
    foreman.hold_for_chat(5)
    assert not foreman.run.running() and "chatting" in foreman.state()["waiting"]
    assert not foreman.shift.tick()  # still warm: nothing starts
    later = datetime.now().astimezone() + timedelta(minutes=6)
    foreman.shift.tick(later)
    assert foreman.run.running() and foreman.run.task.id == task.id and foreman.run.until
    foreman.run.stop()


def test_the_shift_waits_while_the_gpu_desk_gives_the_card_to_someone_else(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard(refusal="Images has the GPU")
    foreman.settings.set_schedule(True, "03:00", "06:00", list(range(7)))
    (root / "echo" / "echo.py").write_text("import time; time.sleep(30)", encoding="utf-8")
    foreman.add_task("echo", "a", "")
    assert not foreman.shift.tick(at(3, 5)) and foreman.shift.note == "Waiting: Images has the GPU."
    foreman.shift.guard.refusal = ""
    assert foreman.shift.tick(at(3, 6)) and foreman.run.running()
    foreman.shift.tick(at(3, 7))
    assert foreman.shift.guard.renewed == 1  # a working turn keeps its place at the desk
    foreman.run.stop()


def test_the_shift_waits_for_chron_jobs_and_never_takes_the_card_meanwhile(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard(refusal="")
    foreman.shift.chron = Chron("Back up Claude's memories")
    foreman.settings.set_schedule(True, "03:00", "06:00", list(range(7)))
    (root / "echo" / "echo.py").write_text("import time; time.sleep(30)", encoding="utf-8")
    foreman.add_task("echo", "a", "")
    desk_asked = []
    foreman.shift.guard.desk_refusal = lambda minutes=5: desk_asked.append(minutes) or ""
    assert not foreman.shift.tick(at(3, 0)) and foreman.shift.note == "Waiting: Chron Jobs is running Back up Claude's memories."
    assert not desk_asked and not foreman.run.running()
    foreman.shift.chron.job = ""
    assert foreman.shift.tick(at(3, 1)) and foreman.run.running()
    foreman.run.stop()


class Presence:
    def __init__(self, idle=None):
        self.idle = idle  # seconds since Ben last touched the keyboard or mouse; None when Windows won't say

    def idle_seconds(self):
        return self.idle


def test_until_ben_wakes_the_window_runs_to_the_next_nights_start(tmp_path):
    settings = ForemanSettings(tmp_path / "foreman.json")
    settings.set_schedule(True, "03:00", "09:00", list(range(7)), "until_awake")
    assert settings.window_end(at(11, 0)) == at(3, day=14)  # long past 9 AM, still open
    assert settings.window_end(at(2, 59)) == at(3, day=13)  # yesterday's night, until tonight's begins
    with pytest.raises(ValueError):
        settings.set_schedule(True, "03:00", "09:00", [0], "whenever")
    (tmp_path / "old.json").write_text(json.dumps({"schedule": {"enabled": True, "start": "03:00", "end": "09:00", "days": [1]}}))
    assert not ForemanSettings(tmp_path / "old.json").until_awake()  # a schedule from before the modes is a window


def test_until_ben_wakes_it_starts_once_he_is_away_and_his_first_touch_ends_the_night(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    foreman.shift.presence = Presence(idle=60)
    foreman.settings.set_schedule(True, "03:00", "09:00", list(range(7)), "until_awake")
    (root / "echo" / "echo.py").write_text("import sys, time; print('working', sys.argv[1:], flush=True); time.sleep(30)", encoding="utf-8")
    foreman.add_task("echo", "a", "")
    assert not foreman.shift.tick(at(3, 0)) and "still at the PC" in foreman.shift.note  # up late: it waits for bed
    foreman.shift.presence.idle = 20 * 60
    assert foreman.shift.tick(at(3, 10)) and foreman.run.running()
    for _ in range(100):
        if "working" in "\n".join(foreman.run.tail()):
            break
        time.sleep(0.1)
    assert "'--until', '04:10'" in "\n".join(foreman.run.tail())  # an hour's turn: nobody knows how long the night is
    foreman.shift.presence.idle = 5
    assert not foreman.shift.tick(at(9, 40)) and not foreman.run.running() and "Good morning" in foreman.shift.note
    foreman.shift.presence.idle = 20 * 60
    assert not foreman.shift.tick(at(10, 30))  # gone again later in the day: the night is over until tomorrow's 3 AM
    assert foreman.shift.tick(at(3, 5, day=14)) and foreman.run.running()
    foreman.run.stop()


def test_until_ben_wakes_never_guesses_when_windows_wont_say(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    foreman.shift.presence = Presence(idle=None)
    foreman.settings.set_schedule(True, "03:00", "09:00", list(range(7)), "until_awake")
    foreman.add_task("echo", "a", "")
    assert not foreman.shift.tick(at(3, 0)) and "won't say" in foreman.shift.note


def test_a_shorter_hold_never_cuts_a_longer_one_short(root):
    foreman = Foreman(root)
    foreman.hold_for_chat(20)  # Images drawing a long clip, say
    foreman.hold_for_chat(5)  # then a chat message
    assert foreman.shift.hold.holding(datetime.now().astimezone() + timedelta(minutes=10))


def test_a_task_held_past_its_stop_time_stays_stopped(root):
    foreman = Foreman(root)
    (root / "echo" / "echo.py").write_text("import time; time.sleep(30)", encoding="utf-8")
    task = foreman.add_task("echo", "a", "")
    foreman.run_now(task.id, minutes=2)
    foreman.hold_for_chat(5)
    assert not foreman.shift.hold.holding(datetime.now().astimezone() + timedelta(minutes=6))
    assert not foreman.run.running()


def test_kicking_chat_off_brings_the_held_task_straight_back(root):
    foreman = Foreman(root)
    (root / "echo" / "echo.py").write_text("import time; time.sleep(30)", encoding="utf-8")
    task = foreman.add_task("echo", "a", "")
    foreman.run_now(task.id)
    foreman.hold_for_chat(5)
    assert not foreman.run.running()
    foreman.end_chat_hold()
    assert not foreman.shift.hold.holding(datetime.now().astimezone())
    assert foreman.run.running() and foreman.run.task.id == task.id
    foreman.run.stop()


def test_stretching_free_time_moves_the_running_task_with_it(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    (root / "echo" / "echo.py").write_text("import time; time.sleep(30)", encoding="utf-8")
    task = foreman.add_task("echo", "a", "")
    foreman.give_time(60)
    free, ends, log = foreman.shift.free_until, foreman.run.ends, foreman.run.log_path
    foreman.stretch(30)
    assert foreman.run.log_path == log and "carrying on where it left off" in log.read_text(encoding="utf-8")
    assert foreman.shift.free_until == free + timedelta(minutes=30)
    assert foreman.run.running() and foreman.run.task.id == task.id and foreman.run.ends == ends + timedelta(minutes=30)
    assert foreman.state()["ends_at"]
    with pytest.raises(ValueError):
        foreman.stretch(-200)  # already gone by
    with pytest.raises(ValueError):
        foreman.stretch(24 * 60)
    foreman.run.stop()


def test_stretching_reaches_a_task_the_chat_stepped_aside(root):
    foreman = Foreman(root)
    (root / "echo" / "echo.py").write_text("import time; time.sleep(30)", encoding="utf-8")
    task = foreman.add_task("echo", "a", "")
    foreman.run_now(task.id, minutes=30)
    old = foreman.run.until
    foreman.hold_for_chat(5)
    foreman.stretch(60)
    assert foreman.hold.task_until == (datetime.strptime(old, "%H:%M") + timedelta(minutes=60)).strftime("%H:%M")
    foreman.run.stop()


def test_nothing_to_stretch_says_so(root):
    with pytest.raises(RuntimeError):
        Foreman(root).stretch(10)


def test_bens_own_stop_cancels_the_chat_hold(root):
    foreman = Foreman(root)
    (root / "echo" / "echo.py").write_text("import time; time.sleep(30)", encoding="utf-8")
    task = foreman.add_task("echo", "a", "")
    foreman.run_now(task.id)
    foreman.hold_for_chat(5)
    foreman.stop()
    assert not foreman.shift.hold.holding(datetime.now().astimezone() + timedelta(minutes=6))
    assert not foreman.run.running()
    with pytest.raises(ValueError):
        foreman.hold_for_chat(0)


def test_a_worker_that_overruns_its_stop_time_is_stopped(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    (root / "echo" / "echo.py").write_text("import time; time.sleep(30)", encoding="utf-8")
    task = foreman.add_task("echo", "a", "")
    foreman.run_now(task.id, minutes=5)
    foreman.shift.tick(datetime.now().astimezone() + timedelta(minutes=10))
    assert foreman.run.running()  # inside the grace
    foreman.shift.tick(datetime.now().astimezone() + timedelta(minutes=16))
    assert not foreman.run.running() and "past its stop time" in foreman.run.tail()[-1]


def test_a_deployed_task_leaves_the_night_shift(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    shipped = foreman.add_task("echo", "a", "")
    foreman.tasks.update(shipped.id, deployed="2026-10-26")
    assert foreman.tasks.get(shipped.id).deployed == "2026-10-26"
    assert foreman._launch_next(set(), at(3), at(9)) is None


def test_no_turn_starts_in_the_last_seconds_of_a_window(root):
    # A stop time of "14:13" given at 14:13:20 reads as tomorrow's 14:13
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    foreman.add_task("echo", "a", "")
    assert foreman._launch_next(set(), at(14, 13) + timedelta(seconds=20), at(14, 13) + timedelta(seconds=47)) is None
    assert not foreman.run.running()


def test_time_left_after_everyone_has_had_a_turn_starts_another_round_without_the_quick_quitters(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    foreman.settings.set_schedule(True, "03:00", "06:00", list(range(7)))
    foreman.settings.set_rest(0)  # about the turns' shares, not the rest between them
    worker, quitter = foreman.add_task("echo", "a", "spellcheck"), foreman.add_task("echo", "b", "wikipedia links")
    assert foreman.shift.tick(at(3, 0)) and foreman.run.task.id == worker.id
    foreman.run.process.wait(timeout=30)
    assert foreman.shift.tick(at(4, 30)) and foreman.run.task.id == quitter.id  # the spellcheck worked its ninety minutes
    foreman.run.process.wait(timeout=30)
    assert foreman.shift.tick(at(4, 31)) and foreman.run.task.id == worker.id  # links came straight back: the spellcheck goes again
    foreman.run.process.wait(timeout=30)
    assert "'--until', '06:00'" in "\n".join(foreman.run.tail())  # alone in its round, it gets the rest of the window
    assert foreman.shift.tick(at(5, 0)) and foreman.run.task.id == worker.id  # and another, while it keeps using its turns
    foreman.run.process.wait(timeout=30)
    assert not foreman.shift.tick(at(5, 1)) and "nothing left" in foreman.shift.note  # until it too comes straight back


def test_the_shift_rests_between_jobs_but_not_after_a_turn_that_came_straight_back(root):
    foreman = Foreman(root)
    foreman.shift.guard = Guard()
    foreman.settings.set_schedule(True, "03:00", "06:00", list(range(7)))
    assert foreman.settings.rest_minutes() == 5  # Ben's setting, 4 Nov 2026
    first, second, third = (foreman.add_task("echo", t, n) for t, n in (("a", "1"), ("b", "2"), ("a", "3")))
    assert foreman.shift.tick(at(3, 0)) and foreman.run.task.id == first.id
    foreman.run.process.wait(timeout=30)
    assert not foreman.shift.tick(at(3, 20)) and "Resting between jobs until 3:25 AM" in foreman.shift.note
    assert foreman.shift.tick(at(3, 25)) and foreman.run.task.id == second.id
    foreman.run.process.wait(timeout=30)
    assert foreman.shift.tick(at(3, 26)) and foreman.run.task.id == third.id  # the second came straight back: no rest after it
    with pytest.raises(ValueError):
        foreman.settings.set_rest(-1)
    foreman.settings.set_rest(0)
    assert ForemanSettings(root / "data" / "foreman.json").rest_minutes() == 0
