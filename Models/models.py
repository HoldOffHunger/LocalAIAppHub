# Models: every AI model on Ben's machine, by kind, with who made it, where it lives and how big it is, on
# http://127.0.0.1:8800 and the 🧠 Models entry in the App Hub. start.bat runs this. Standard library only, like the hub.
# It reads model folders and never changes them; the one thing it writes is data\sweep.json, the last drive sweep.

import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import known
import scan

APP = Path(__file__).resolve().parent
DATA = APP / "data"
SWEEP_PATH = DATA / "sweep.json"
PAGE = APP / "web" / "index.html"
PORT = int(os.environ.get("MODELS_PORT", "8800"))

lock = threading.Lock()
state = {"models": [], "scanned_at": "", "scanning": False, "sweep": {"running": False, "folder": "", "folders": 0,
                                                                     "found": 0, "drives": [], "finished": ""}}


def load_sweep():
    try:
        return json.loads(SWEEP_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"found": [], "finished": "", "drives": []}


def rescan():
    with lock:
        if state["scanning"]:
            return
        state["scanning"] = True
    try:
        models = scan.catalogue(load_sweep().get("found", []))
    finally:
        with lock:
            state["scanning"] = False
    with lock:
        state["models"] = models
        state["scanned_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")


def sweep():
    # Every drive, every folder but Windows' own and the homes (E:\AIModels, E:\ModelWorkshop): slow (minutes on the 20 TB array), so it runs on its
    # own thread and is saved, and the page is built from the saved one until the next sweep
    sweep_state = state["sweep"]
    found, drives = [], scan.drives()
    sweep_state.update(running=True, folders=0, found=0, drives=drives)

    def progress(folder):
        sweep_state["folder"] = folder
        sweep_state["folders"] += 1

    try:
        for drive in drives:
            found.extend(scan.walk_for_models(drive, scan.SWEEP_SMALLEST, skip_roots=scan.HOMES, progress=progress))
            sweep_state["found"] = len(found)
        finished = datetime.now().strftime("%Y-%m-%d %H:%M")
        DATA.mkdir(exist_ok=True)
        SWEEP_PATH.write_text(json.dumps({"finished": finished, "drives": drives, "found": found}, indent=1), encoding="utf-8")
        sweep_state["finished"] = finished
    finally:
        sweep_state.update(running=False, folder="")
    rescan()


def summary(models):
    # Disk use counts a file once even when several Ollama models share it
    seen, disk = set(), 0
    for model in models:
        if model["files"] and model["source"] == "Ollama":
            for file in model["files"]:
                if file["path"] not in seen:
                    seen.add(file["path"])
                    disk += file["size"]
        else:
            disk += model["size"]
    return {"count": len(models), "disk": disk, "outside": sum(1 for model in models if model["straggler"]),
            "outside_size": sum(model["size"] for model in models if model["straggler"])}


def known_path(path):
    # Only a folder the page is showing can be opened in Explorer
    with lock:
        return any(model["path"] == path or any(file["path"] == path for file in model["files"]) for model in state["models"])


class Handler(BaseHTTPRequestHandler):
    server_version = "Models/1.0"

    def log_message(self, format_string, *args):
        pass

    def send_json(self, value, status=200):
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            content = PAGE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
        elif path == "/api/models":
            with lock:
                models = list(state["models"])
                body = {"models": models, "kinds": [{"id": k, "title": t, "icon": i} for k, t, i in known.KINDS],
                        "summary": summary(models), "scanned_at": state["scanned_at"], "scanning": state["scanning"],
                        "root": " and ".join(str(home) for home in scan.HOMES), "sweep": dict(state["sweep"]),
                        "last_sweep": load_sweep().get("finished", "")}
            self.send_json(body)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/rescan":
            threading.Thread(target=rescan, daemon=True).start()
            self.send_json({"ok": True})
        elif path == "/api/sweep":
            if not state["sweep"]["running"]:
                state["sweep"]["running"] = True
                threading.Thread(target=sweep, daemon=True).start()
            self.send_json({"ok": True})
        elif path == "/api/reveal":
            try:
                target = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))["path"]
            except (ValueError, KeyError, TypeError):
                self.send_json({"error": "needs {\"path\": ...}"}, 400)
                return
            if not known_path(target) or not os.path.exists(target):
                self.send_json({"error": "that isn't one of the models listed"}, 404)
                return
            subprocess.Popen(["explorer", "/select,", target] if os.path.isfile(target) else ["explorer", target])
            self.send_json({"ok": True})
        else:
            self.send_json({"error": "not found"}, 404)


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    link = "http://127.0.0.1:%d/" % PORT
    print("Models running at " + link, flush=True)
    started = time.time()
    rescan()
    print("  %d models found in %.1f s" % (len(state["models"]), time.time() - started), flush=True)
    if "--no-browser" not in sys.argv:
        webbrowser.open(link)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
