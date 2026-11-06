# How the hub talks about and starts each app. The apps themselves (where each lives, its port, how it starts)
# are listed in data/app_list.json and only there; apps are always picked by "id".

import os
import socket
import subprocess
import time

START_PATIENCE_SECONDS = 90  # Autonoma loads her memory before she answers
launched_at = {}  # app id -> when the hub last ran its start script


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
    starting = not running and time.time() - launched_at.get(app["id"], 0) < START_PATIENCE_SECONDS
    return {"id": app["id"], "title": app["title"], "icon": app.get("icon", ""), "url": url, "running": running,
            "starting": starting, "can_start": bool(app.get("start")), "note": app.get("note", ""), "allow": app.get("allow", "")}


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
    launched_at[app["id"]] = time.time()
    return ""


def start_all(apps):
    # start.bat's job: everything with a start script that isn't already up
    for app in apps:
        if app.get("start") and app.get("autostart", True):
            problem = start_app(app)
            print("  %-12s %s" % (app["title"], problem or "starting"), flush=True)
