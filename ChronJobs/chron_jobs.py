# Chron Jobs: the jobs that run on their own at a set time each night, on http://127.0.0.1:8740
# start.bat runs this. Standard-library only, like the hub. The AI Workers' Foreman asks /api/busy before each turn,
# and starts nothing while a job is due or running.

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
JOBS_PATH = os.path.join(DATA_DIR, "jobs.json")
STATE_PATH = os.path.join(DATA_DIR, "state.json")
LOG_DIR = os.path.join(DATA_DIR, "logs")
PROGRESS_MARK = "PROGRESS "  # a job prints "PROGRESS 40 Version 3 of 5" to move its bar on the page; kept out of the log
PAGE_PATH = os.path.join(APP_DIR, "web", "index.html")
PORT = int(os.environ.get("CHRON_JOBS_PORT", "8740"))
POLL_SECONDS = 10


def today_at(clock, now):
    # "03:00" on now's own day
    return datetime.combine(now.date(), datetime.strptime(clock, "%H:%M").time(), now.tzinfo)


def parse_progress(line):
    # "PROGRESS 40 Version 3 of 5" -> {"percent": 40, "note": "Version 3 of 5"}; anything unreadable -> None
    number, _space, note = line[len(PROGRESS_MARK):].strip().partition(" ")
    try:
        return {"percent": max(0, min(100, round(float(number)))), "note": note.strip()}
    except ValueError:
        return None


class Scheduler:
    """Runs each job once a day at its time, one at a time. A job whose time passed while Chron Jobs was off runs as soon as
    it starts, so a night the PC slept through still gets its backup the next morning."""

    def __init__(self, jobs_path=JOBS_PATH, state_path=STATE_PATH, log_dir=LOG_DIR):
        self.jobs_path = jobs_path
        self.state_path = state_path
        self.log_dir = log_dir
        self.lock = threading.Lock()
        self.running = None  # the id of the job running now
        self.progress = None  # the running job's last {"percent", "note"}, if it reports any
        self.problem = ""  # why jobs.json can't be read, for the page
        self.jobs = []
        self.state = self._load(state_path, {})
        self.reload()

    def reload(self):
        # A typo in jobs.json keeps the last good list, as the hub does with its app list
        try:
            jobs = self._load(self.jobs_path, None)
            if not isinstance(jobs, list):
                raise ValueError("it should be a list, [ ... ]")
            for job in jobs:
                datetime.strptime(job["at"], "%H:%M")
            self.jobs, self.problem = jobs, ""
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.problem = "Can't read %s (%s); keeping the last good list." % (self.jobs_path, error)
        return self.jobs

    def due(self, job, now):
        # Its time today has come, and it hasn't started since
        slot = today_at(job["at"], now)
        started = self.state.get(job["id"], {}).get("started")
        return now >= slot and (not started or datetime.fromisoformat(started) < slot)

    def busy(self, now=None):
        # What the Foreman asks: the job running, or one due that's about to start. Due counts, because the workers' window
        # opens at 03:00 too, and a turn mustn't slip in during the seconds before the backup starts
        now = now or datetime.now().astimezone()
        with self.lock:
            if self.running:
                return self._title(self.running)
        for job in self.jobs:
            if self.due(job, now):
                return job["title"]
        return ""

    def next_run(self, job, now):
        slot = today_at(job["at"], now)
        return slot if self.due(job, now) or now < slot else slot + timedelta(days=1)

    def tick(self, now=None):
        now = now or datetime.now().astimezone()
        self.reload()
        for job in self.jobs:
            if self.due(job, now):
                self.run(job)

    def run(self, job):
        # One job at a time; a second Run press while one runs is refused rather than queued
        with self.lock:
            if self.running:
                return "%s is running" % self._title(self.running)
            self.running, self.progress = job["id"], None
        try:
            started = datetime.now().astimezone()
            self._record(job["id"], {"started": started.isoformat(timespec="seconds"), "finished": "", "ok": None, "summary": "Running…"})
            os.makedirs(self.log_dir, exist_ok=True)
            command = [sys.executable if part == "{python}" else part for part in job["command"]]
            with open(os.path.join(self.log_dir, job["id"] + ".log"), "a", encoding="utf-8") as log:
                log.write("\n=== %s, %s ===\n" % (job["title"], started.strftime("%Y-%m-%d %H:%M:%S")))
                log.flush()
                output, ok = self._follow(command, job.get("minutes", 30), log)
            lines = [line for line in output.splitlines() if line.strip()]
            self._record(job["id"], {"started": started.isoformat(timespec="seconds"),
                                     "finished": datetime.now().astimezone().isoformat(timespec="seconds"),
                                     "ok": ok, "summary": lines[-1] if lines else ("Done." if ok else "Failed, with nothing said.")})
            return ""
        finally:
            with self.lock:
                self.running, self.progress = None, None

    def _follow(self, command, minutes, log):
        # Runs the job, writing its output to the log as it comes (so the page's log is live) and taking its PROGRESS
        # lines for the bar. Stopped if it runs past its minutes
        try:
            process = subprocess.Popen(command, cwd=APP_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                       encoding="utf-8", errors="replace", env=dict(os.environ, PYTHONUNBUFFERED="1"))
        except OSError as error:
            message = "Couldn't run %s: %s\n" % (command, error)
            log.write(message)
            return message, False
        stopped = threading.Event()
        timer = threading.Timer(minutes * 60, lambda: (stopped.set(), process.kill()))
        timer.start()
        output = []
        try:
            for line in process.stdout:
                if line.startswith(PROGRESS_MARK):
                    self.progress = parse_progress(line) or self.progress
                    continue
                output.append(line)
                log.write(line)
                log.flush()
            process.wait()
        finally:
            timer.cancel()
        if stopped.is_set():
            message = "Stopped: it ran past its %d minutes.\n" % minutes
            log.write(message)
            output.append(message)
        return "".join(output), process.returncode == 0 and not stopped.is_set()

    def describe(self, now=None):
        now = now or datetime.now().astimezone()
        jobs = []
        for job in self.jobs:
            jobs.append({"id": job["id"], "title": job["title"], "description": job.get("description", ""), "at": job["at"],
                         "next": self.next_run(job, now).isoformat(timespec="minutes"), "running": self.running == job["id"],
                         "progress": self.progress if self.running == job["id"] else None,
                         "last": self.state.get(job["id"], {}), "log": self.log_tail(job["id"])})
        return {"jobs": jobs, "busy": self.busy(now), "problem": self.problem}

    def log_tail(self, job_id, lines=40):
        try:
            with open(os.path.join(self.log_dir, job_id + ".log"), encoding="utf-8") as handle:
                return "".join(handle.readlines()[-lines:])
        except OSError:
            return ""

    def _title(self, job_id):
        return next((job["title"] for job in self.jobs if job["id"] == job_id), job_id)

    def _record(self, job_id, entry):
        # Written whole and swapped in, so a crash mid-write never leaves a state file that forgets every job
        with self.lock:
            self.state[job_id] = entry
            os.makedirs(os.path.dirname(self.state_path), exist_ok=True)
            with open(self.state_path + ".tmp", "w", encoding="utf-8") as handle:
                json.dump(self.state, handle, indent=2)
            os.replace(self.state_path + ".tmp", self.state_path)

    @staticmethod
    def _load(path, fallback):
        if fallback is not None and not os.path.exists(path):
            return fallback
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def watch(self):
        while True:
            try:
                self.tick()
            except Exception as error:  # a bad tick must never stop the watching
                print("tick failed: %s" % error, flush=True)
            time.sleep(POLL_SECONDS)


scheduler = None


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(PAGE_PATH, "rb") as handle:
                self._send(200, handle.read(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(scheduler.describe())
        elif self.path == "/api/busy":
            job = scheduler.busy()
            self._json({"busy": bool(job), "job": job})
        else:
            self._send(404, b"not here", "text/plain")

    def do_POST(self):
        if self.path != "/api/run":
            return self._send(404, b"not here", "text/plain")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self._json({"problem": "that wasn't JSON"}, 400)
        job = next((job for job in scheduler.reload() if job["id"] == body.get("id")), None)
        if not job:
            return self._json({"problem": "no job called %s" % body.get("id")}, 404)
        if scheduler.running:
            return self._json({"problem": "%s is running" % scheduler.busy()}, 409)
        threading.Thread(target=scheduler.run, args=(job,), daemon=True).start()
        self._json({"started": job["id"]})

    def _json(self, value, status=200):
        self._send(status, json.dumps(value).encode(), "application/json; charset=utf-8")

    def _send(self, status, body, content_type):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass  # the Foreman asks /api/busy every 20 seconds; the window stays for what matters


def main():
    global scheduler
    scheduler = Scheduler()
    if scheduler.problem:
        print(scheduler.problem, flush=True)
    for job in scheduler.jobs:
        print("  %-28s at %s" % (job["title"], job["at"]), flush=True)
    threading.Thread(target=scheduler.watch, name="chron-watch", daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Chron Jobs on http://127.0.0.1:%d/" % PORT, flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open("http://127.0.0.1:%d/" % PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
