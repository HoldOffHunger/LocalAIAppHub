# The App Hub: one page with a side panel for every app Ben and Claudia built, on http://127.0.0.1:8700
# start.bat runs this; it starts every app that isn't already running, then opens the panel. Standard-library only.

import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import app_registry
import gpu_desk
import movie_list

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
APPS_PATH = os.path.join(DATA_DIR, "app_list.json")
STATIC_DIR = os.path.join(APP_DIR, "static")
MOVIES_DIR = os.path.join(APP_DIR, "movies")
PORT = int(os.environ.get("APP_HUB_PORT", "8700"))
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8"}


last_good_apps = []  # what the panel shows while app_list.json has a typo in it
apps_problem = ""


def load_apps():
    # data\app_list.json is the one list of apps, and the hub never writes to it: a slip while editing keeps the last good list
    global last_good_apps, apps_problem
    try:
        with open(APPS_PATH, encoding="utf-8") as handle:
            apps = json.load(handle)
        if not isinstance(apps, list):
            raise ValueError("it should be a list, [ ... ]")
        last_good_apps, apps_problem = apps, ""
    except (OSError, ValueError) as error:
        problem = "Can't read %s (%s); showing the last good list." % (APPS_PATH, error)
        if problem != apps_problem:
            print(problem, flush=True)
            apps_problem = problem
    return last_good_apps


def movie_folder():
    movies = app_registry.find_app(load_apps(), "movies")
    return movies["folder"] if movies else ""


class HubHandler(BaseHTTPRequestHandler):
    server_version = "AppHub/1.0"

    def log_message(self, format_string, *args):
        pass  # the console stays readable: only start-up lines and errors

    def send_json(self, value, status=200):
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_file(self, base, relative_path):
        safe_path = os.path.normpath(os.path.join(base, relative_path))
        if not safe_path.startswith(base + os.sep) or not os.path.isfile(safe_path):
            self.send_json({"error": "not found"}, 404)
            return
        with open(safe_path, "rb") as handle:
            content = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(safe_path)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self.send_file(STATIC_DIR, "hub.html")
        elif path == "/api/apps":
            self.send_json([app_registry.describe(app) for app in load_apps()])
        elif path == "/api/gpu":
            self.send_json(gpu_desk.state(load_apps()))
        elif path == "/api/movies":
            self.send_json(movie_list.load_movies(movie_folder()))
        elif path.startswith("/movies/"):
            self.send_file(MOVIES_DIR, path[len("/movies/"):] or "index.html")
        elif path.startswith("/static/"):
            self.send_file(STATIC_DIR, path[len("/static/"):])
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        parts = self.path.split("?", 1)[0].strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "apps"] and parts[3] == "start":
            self.start_app(parts[2])
        elif len(parts) == 3 and parts[:2] == ["api", "gpu"] and parts[2] in ("claim", "renew", "release", "kick"):
            self.gpu(parts[2])
        else:
            self.send_json({"error": "not found"}, 404)

    def gpu(self, action):
        # The desk's moves, and Ben's kick; see gpu_desk.py for who gets the card when
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            app_id = str(body["app"])
            if action == "claim":
                self.send_json(gpu_desk.claim(load_apps(), app_id, body.get("minutes", 5), bool(body.get("background")),
                                              [str(name) for name in body.get("keep_models") or []]))
            elif action == "kick":
                self.send_json(gpu_desk.kick(load_apps(), app_id))
            elif action == "renew":
                self.send_json(gpu_desk.renew(load_apps(), app_id, body.get("minutes", 2)))
            else:
                self.send_json(gpu_desk.release(app_id))
        except (ValueError, KeyError, TypeError) as error:
            self.send_json({"error": "the desk needs {\"app\": ...}: %s" % error}, 400)

    def start_app(self, app_id):
        app = app_registry.find_app(load_apps(), app_id)
        if not app or not app.get("start"):
            self.send_json({"error": "that app can't be started from here"}, 404)
            return
        problem = app_registry.start_app(app)
        self.send_json({"ok": not problem, "error": problem})


def main():
    server = ThreadingHTTPServer(("127.0.0.1", PORT), HubHandler)
    link = "http://127.0.0.1:%d/" % PORT
    print("App Hub running at " + link + "\nStarting the apps:", flush=True)
    app_registry.start_all(load_apps())
    if "--no-browser" not in sys.argv:
        webbrowser.open(link)  # the server is already listening, so the page waits for it
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. The apps keep running in their own windows.")


if __name__ == "__main__":
    main()
