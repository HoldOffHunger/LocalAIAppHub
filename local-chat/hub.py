# The hub: one page with a side panel for every app Ben and Claudia built.
# Which apps exist, where they live and how they start is in data/hub_apps.json, written with these defaults the first time.

import os
import socket
import subprocess

DEFAULT_APPS = [
    {"id": "chat", "title": "Chat", "icon": "💬", "url": "/"},
    {"id": "autonoma", "title": "Autonoma", "icon": "✦", "port": 8710, "folder": "E:\\Autonoma",
     "start": "start.bat", "login": "data\\warden_login.txt"},
    {"id": "workers", "title": "AI Workers", "icon": "⚒", "port": 8720, "folder": "E:\\AIWorkers",
     "start": "start_foreman.bat", "login": "data\\foreman_login.txt"},
    {"id": "stats", "title": "Site Stats", "icon": "📈", "port": 8770, "folder": "E:\\GGCMS_Stats", "start": "start.bat"},
    {"id": "movies", "title": "Movies", "icon": "🎬", "url": "/movies/", "folder": "E:\\MovieTheaterWithClaudia"},
    {"id": "jellyfin", "title": "Jellyfin", "icon": "📺", "port": 8096},
]


def is_listening(port):
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.4):
            return True
    except OSError:
        return False


def login_link(app):
    # Autonoma and the Foreman make a fresh login link each time they start, and save it in their own folder
    if not app.get("login"):
        return ""
    try:
        with open(os.path.join(app["folder"], app["login"]), encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def describe(app):
    # What the side panel needs: where to point the frame, and whether there's anything there yet
    if "port" not in app:
        return {"id": app["id"], "title": app["title"], "icon": app.get("icon", ""), "url": app["url"], "running": True}
    running = is_listening(app["port"])
    url = (login_link(app) if running else "") or "http://127.0.0.1:%d/" % app["port"]
    return {"id": app["id"], "title": app["title"], "icon": app.get("icon", ""), "url": url, "running": running,
            "can_start": bool(app.get("start"))}


def find_app(apps, app_id):
    for app in apps:
        if app["id"] == app_id:
            return app
    return None


def start_app(app):
    # Runs the app's own start script in its own console window, without the extra browser tab
    if is_listening(app["port"]):
        return "already running"
    script = os.path.join(app["folder"], app["start"])
    if not os.path.isfile(script):
        return "can't find " + script
    flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    try:
        subprocess.Popen([script, "--no-browser"], cwd=app["folder"], creationflags=flags)
    except OSError as error:
        return "couldn't run %s: %s" % (script, error)
    return ""
