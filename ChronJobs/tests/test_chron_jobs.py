import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chron_jobs import Scheduler  # noqa: E402

LOCAL = datetime.now().astimezone().tzinfo
BACKUP = Path(__file__).resolve().parent.parent / "jobs" / "backup_memories.py"


def at(hour, minute=0, day=2):
    return datetime(2026, 11, day, hour, minute, tzinfo=LOCAL)


def scheduler(tmp_path, command=None, clock="03:00"):
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps([{"id": "j", "title": "The job", "at": clock,
                                 "command": command or ["{python}", "-c", "print('all done')"]}]), encoding="utf-8")
    return Scheduler(str(jobs), str(tmp_path / "state.json"), str(tmp_path / "logs"))


def test_a_job_is_due_from_its_time_until_it_has_run(tmp_path):
    chron = scheduler(tmp_path)
    assert chron.busy(at(2, 59)) == ""
    assert chron.busy(at(3, 0)) == "The job"  # due counts: the workers' window opens at 3 too
    chron.tick(at(3, 0))
    assert chron.state["j"]["ok"] and chron.state["j"]["summary"] == "all done"
    chron.state["j"]["started"] = at(3, 0).isoformat()  # as if it ran at 03:00 that night
    assert chron.busy(at(3, 1)) == ""
    assert chron.busy(at(3, 0, day=3)) == "The job"  # and again the next night


def test_a_night_slept_through_runs_when_chron_jobs_next_starts(tmp_path):
    chron = scheduler(tmp_path)
    chron.state["j"] = {"started": at(3, 0, day=1).isoformat()}
    assert chron.busy(at(9, 30)) == "The job"


def test_a_run_by_hand_before_three_still_runs_at_three(tmp_path):
    chron = scheduler(tmp_path)
    chron.state["j"] = {"started": at(1, 0).isoformat()}
    assert chron.busy(at(2, 0)) == "" and chron.busy(at(3, 0)) == "The job"


def test_a_failing_job_says_so_and_a_typo_keeps_the_last_good_list(tmp_path):
    chron = scheduler(tmp_path, ["{python}", "-c", "import sys; print('it broke'); sys.exit(3)"])
    chron.run(chron.jobs[0])
    assert chron.state["j"]["ok"] is False and chron.state["j"]["summary"] == "it broke"
    (tmp_path / "jobs.json").write_text("[{oops", encoding="utf-8")
    assert chron.reload()[0]["id"] == "j" and "Can't read" in chron.problem


def test_progress_lines_move_the_bar_and_stay_out_of_the_log(tmp_path):
    seen = []
    script = "import time; print('PROGRESS 40 Version 3 of 5', flush=True); time.sleep(1.5); print('painted')"
    chron = scheduler(tmp_path, ["{python}", "-c", script])
    worker = threading.Thread(target=chron.run, args=(chron.jobs[0],))
    worker.start()
    for _ in range(40):
        seen.append(chron.describe()["jobs"][0]["progress"])
        if seen[-1]:
            break
        time.sleep(0.05)
    worker.join()
    assert seen[-1] == {"percent": 40, "note": "Version 3 of 5"}
    assert chron.describe()["jobs"][0]["progress"] is None and chron.state["j"]["summary"] == "painted"
    assert "PROGRESS" not in (tmp_path / "logs" / "j.log").read_text(encoding="utf-8")


def test_a_job_past_its_minutes_is_stopped(tmp_path):
    chron = scheduler(tmp_path, ["{python}", "-c", "import time; time.sleep(30)"])
    chron.jobs[0]["minutes"] = 0.02
    chron.run(chron.jobs[0])
    assert chron.state["j"]["ok"] is False and "ran past" in chron.state["j"]["summary"]


def test_the_backup_makes_dated_snapshots_and_refuses_blank_files(tmp_path):
    source, to = tmp_path / ".claude", tmp_path / "backups"
    memory = source / "projects" / "E--Code" / "memory"
    memory.mkdir(parents=True)
    (memory / "MEMORY.md").write_text("- [A thing](a-thing.md)\n", encoding="utf-8")
    (memory / "a-thing.md").write_text("a fact\n", encoding="utf-8")
    (source / "CLAUDE.md").write_text("# Working with Ben\n", encoding="utf-8")
    (source / "projects" / "E--Code" / "transcript.jsonl").write_text("{}", encoding="utf-8")  # not a memory: left alone

    first = subprocess.run([sys.executable, str(BACKUP), "--source", str(source), "--to", str(to)], capture_output=True, text=True)
    assert first.returncode == 0, first.stdout + first.stderr
    snapshots = [path for path in to.iterdir()]
    assert len(snapshots) == 1 and not snapshots[0].name.endswith(".partial")
    assert (snapshots[0] / "projects" / "E--Code" / "memory" / "a-thing.md").read_text(encoding="utf-8") == "a fact\n"
    assert (snapshots[0] / "CLAUDE.md").exists() and not (snapshots[0] / "projects" / "E--Code" / "transcript.jsonl").exists()

    (memory / "a-thing.md").write_bytes(b"\0" * 300)  # what the shadow copy brought back on 1 Nov
    second = subprocess.run([sys.executable, str(BACKUP), "--source", str(source), "--to", str(to)], capture_output=True, text=True)
    assert second.returncode == 1 and "BLANK, left out: projects" in second.stdout
    assert len(list(to.iterdir())) == 2  # a second snapshot beside the first; the good one untouched
    assert (snapshots[0] / "projects" / "E--Code" / "memory" / "a-thing.md").read_text(encoding="utf-8") == "a fact\n"
