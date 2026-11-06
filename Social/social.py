# Social: Ben's "social tasks", a little at a time, on http://127.0.0.1:8750
# start.bat runs this. Standard-library only, like the hub. Each task is one AI Workers job whose finds Ben acts on by hand:
# Wikipedia typos, Wikipedia links to RevoltLib and to Marxists.org, and OCR misreadings for GGCMS's own misspelling lists.
# The workers find and a local model confirms; here Ben
# reads each one, makes the edit himself on Wikipedia, and marks it. Nothing here edits Wikipedia.

import json
import os
import sqlite3
import sys
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
MARKS_PATH = os.path.join(DATA_DIR, "marks.json")  # what Ben did with each find, and when
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
PAGE_PATH = os.path.join(APP_DIR, "web", "index.html")
WORKERS_DIR = os.environ.get("AI_WORKERS_DIR", r"E:\AIWorkers")
FOREMAN_DB = os.path.join(WORKERS_DIR, "data", "foreman.sqlite")
PORT = int(os.environ.get("SOCIAL_PORT", "8750"))
lock = threading.Lock()

# One card each. "done" is the mark that counts against the day's share, so the account reads as a person tidying, never a spree.
# A typo's marks keep their plain keys from before there were several jobs; a link's are kept as "<job>|<key>"
JOBS = [
    {"id": "typos", "title": "Wikipedia typos", "icon": "✏️", "kind": "wikipedia_typos", "target": "en.wikipedia",
     "also_targets": "doubled-%",  # the doubled-letter test hunts (doubled-ss…): what they find on Wikipedia is fixed the same way
     "finds": "task-%d.results.json", "per_day": 5, "done": "fixed", "marks": ["fixed", "not a typo"],
     "about": "Known misspellings in English Wikipedia's prose, confirmed by a local model. Read it in the article, fix it by hand, "
              "then mark it.",
     "missing": "Add a \"Wikipedia: known misspellings\" task in AI Workers (target en.wikipedia), and its finds appear here."},
    {"id": "revoltlib", "title": "Wikipedia links · RevoltLib", "icon": "🔗", "kind": "ggcms_wikilinks", "target": "revoltlib",
     "finds": "task-%d.results.jsonl", "per_day": 3, "done": "updated", "marks": ["updated", "asked on talk page", "not worth it"],
     "about": "Dead links Wikipedia could point at RevoltLib's copy, and articles about our works and authors with no link to us. "
              "Every edit discloses that you run the site; anything arguable goes on the talk page.",
     "missing": "Add a \"GGCMS: Wikipedia dead and missing links\" task in AI Workers (target revoltlib), and its finds appear here."},
    {"id": "marxists", "title": "Wikipedia links · Marxists.org", "icon": "📚", "kind": "mia_wikilinks", "target": "marxists.org",
     "also_targets": "marxists.org/%",  # one task per MIA author (marxists.org/archive/luxemburg…), all shown on this one card
     "finds": "task-%d.results.jsonl", "per_day": 3, "done": "updated", "marks": ["updated", "asked on talk page", "not worth it"],
     "about": "The same for the Marxists Internet Archive, for texts RevoltLib doesn't hold: anything on RevoltLib links there "
              "first.",
     "missing": "Add a \"Wikipedia: links to Marxists.org\" task in AI Workers (target marxists.org/archive/<author>), and its finds appear here."},
    {"id": "ocr", "title": "OCR misreadings", "icon": "🔍", "kind": "archive_ocr", "target": "archive.org",
     "finds": "task-%d.results.json", "per_day": 20, "done": "added to the list", "marks": ["added to the list", "not a misspelling"],
     "about": "Scanner misreadings (rn for m, li for h, the long s read as f) that recur across badly scanned Internet Archive "
              "texts, found from the Wikipedia typo hunter's own OCR-shaped finds. Candidates for GGCMS's misspelling lists: "
              "add the good ones by hand, then mark them.",
     "missing": "Add an \"Internet Archive: OCR misreadings\" task in AI Workers (target archive.org), and its finds appear here."},
]


def read_json(path, fallback):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return fallback


def read_lines(path):
    # A .jsonl file: one record a line; a half-written last line (the worker writing as we read) is skipped
    found = []
    try:
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                try:
                    found.append(json.loads(line))
                except ValueError:
                    pass
    except OSError:
        pass
    return found


def write_json(path, value):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporary = path + ".new"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=1)
    os.replace(temporary, path)


def tasks_for(job):
    # The Foreman's tasks for this job, read-only; each one's finds sit beside its results file
    try:
        connection = sqlite3.connect("file:%s?mode=ro" % FOREMAN_DB, uri=True)
        try:
            rows = connection.execute("SELECT id FROM tasks WHERE kind = ? AND (target = ? OR target LIKE ?) ORDER BY id",
                                      (job["kind"], job["target"], job.get("also_targets", job["target"]))).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return []
    return [os.path.join(WORKERS_DIR, "data", "tasks", job["finds"] % task_id) for (task_id,) in rows]


def mark_key(job, key):
    return key if job["id"] == "typos" else "%s|%s" % (job["id"], key)


def finds_of(job, paths):
    found, seen = [], set()
    for path in paths:
        records = read_json(path, []) if path.endswith(".json") else read_lines(path)
        for find in records:
            key = "%s:%s" % (find["page_id"], find["wrong"]) if job["id"] == "typos" else find.get("key", "")
            if key and key not in seen:
                seen.add(key)
                found.append({**find, "key": key})
    return found


def describe():
    marks = read_json(MARKS_PATH, {})
    settings = read_json(SETTINGS_PATH, {})
    today = datetime.now().date().isoformat()
    jobs = []
    for job in JOBS:
        paths = tasks_for(job)
        finds = finds_of(job, paths)
        for find in finds:
            mark = marks.get(mark_key(job, find["key"]), {})
            find.update(mark=mark.get("mark", ""), marked_at=mark.get("at", ""))
        done_today = sum(1 for key, mark in marks.items() if mark.get("mark") == job["done"] and mark.get("at", "").startswith(today)
                         and (("|" not in key) if job["id"] == "typos" else key.startswith(job["id"] + "|")))
        per_day = settings.get(job["id"] + "_a_day", settings.get("fixes_a_day", job["per_day"]) if job["id"] == "typos" else job["per_day"])
        jobs.append({"id": job["id"], "title": job["title"], "icon": job["icon"], "about": job["about"], "marks": job["marks"],
                     "done": job["done"], "per_day": per_day, "done_today": done_today, "finds": finds,
                     "problem": "" if paths else job["missing"],
                     # A typo younger than this is someone's work in progress: fixing it under them is poor manners
                     "hold_hours": settings.get("typo_hold_hours", 24)})
    return {"jobs": jobs}


def mark(job_id, key, value):
    job = next((job for job in JOBS if job["id"] == job_id), None)
    if job is None:
        raise ValueError("there's no job called %r" % job_id)
    if value and value not in job["marks"]:
        raise ValueError("%s's marks are %s" % (job["title"], ", ".join(job["marks"])))
    with lock:
        marks = read_json(MARKS_PATH, {})
        if value:
            marks[mark_key(job, key)] = {"mark": value, "at": datetime.now().astimezone().isoformat(timespec="seconds")}
        else:
            marks.pop(mark_key(job, key), None)  # undo
        write_json(MARKS_PATH, marks)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            with open(PAGE_PATH, "rb") as handle:
                self._send(200, handle.read(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            self._json(describe())
        else:
            self._send(404, b"not here", "text/plain")

    def do_POST(self):
        if self.path != "/api/mark":
            return self._send(404, b"not here", "text/plain")
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        except ValueError:
            return self._json({"problem": "that wasn't JSON"}, 400)
        if not isinstance(body.get("key"), str) or not isinstance(body.get("mark", ""), str):
            return self._json({"problem": "a mark needs a key, and a mark or nothing"}, 400)
        try:
            mark(body.get("job", "typos"), body["key"], body.get("mark", ""))
        except ValueError as problem:
            return self._json({"problem": str(problem)}, 400)
        self._json({"marked": body["key"]})

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
        pass


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    print("Social on http://127.0.0.1:%d/" % PORT, flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open("http://127.0.0.1:%d/" % PORT)
    server.serve_forever()


if __name__ == "__main__":
    main()
