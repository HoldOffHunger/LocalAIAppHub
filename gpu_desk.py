# The GPU desk: one 8 GB card, several apps that want it, and one place that decides.
#
# Apps ask before they use the card. What Ben is doing right now (Chat, Images, talking with Autonoma) always gets
# it, and the newest such request takes it from the last one. The AI Workers and Autonoma's free time are background:
# they get the card only while nobody else has a lease, and step aside the moment someone does. A picture or clip
# that's already drawing can't be paused, so it finishes while Chat goes ahead, slowly, beside it; Comfy lets go as
# soon as it's done.
#
# When the card changes hands the desk makes room: Ollama drops the models the new holder doesn't need,
# ImageGen's Comfy lets go, and the Foreman holds its worker. Every one of those is best effort: an app that
# isn't running is simply skipped.

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434"
AUTONOMA_PREFIX = "autonoma-"  # her older models are named this way in Ollama; she may run on any model now
LONGEST_LEASE_MINUTES = 60
# Between background users: Autonoma's free time goes before the workers, whatever model she's running on
BACKGROUND_RANK = {"autonoma": 1, "workers": 0}

lock = threading.Lock()
leases = {}  # app id -> {"until": epoch seconds, "background": bool, "since": epoch seconds}
owner = ""  # the app that last took the card; it's the one shown in the panel
handovers = []  # the last few changes of hands, newest last, for the panel's tooltip


def _post(url, value, headers=None, timeout=20):
    request = urllib.request.Request(url, method="POST", data=json.dumps(value).encode("utf-8"),
                                     headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _active(now):
    # Leases that haven't run out; expired ones are forgotten, and an owner whose lease ran out isn't one any more
    global owner
    for app_id in [key for key, lease in leases.items() if lease["until"] <= now]:
        del leases[app_id]
    if owner not in leases:
        owner = ""
    return leases


def ollama_models():
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/ps", timeout=5) as response:
            return [model.get("name", "") for model in json.load(response).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        return []


def unload_ollama(keep, spare_autonoma):
    # keep_alive 0 tells Ollama to drop a model from the card straight away
    dropped = []
    for name in ollama_models():
        if name in keep or (spare_autonoma and name.startswith(AUTONOMA_PREFIX)):
            continue
        try:
            _post(OLLAMA_URL + "/api/generate", {"model": name, "keep_alive": 0}, timeout=30)
            dropped.append(name)
        except (urllib.error.URLError, OSError):
            pass
    return dropped


def ask_images_to_yield(apps):
    # ImageGen lets go now if it's idle, or straight after the picture or clip it's drawing
    images = _find(apps, "images")
    if not images:
        return
    try:
        _post("http://127.0.0.1:%d/api/gpu/yield" % images["port"], {}, timeout=5)
    except (urllib.error.URLError, OSError):
        pass


def _foreman_post(apps, path, value):
    # The Foreman makes a fresh login link each start; its token is the session cookie its API checks
    workers = _find(apps, "workers")
    if not workers or not workers.get("login"):
        return
    try:
        with open(workers["folder"] + "\\" + workers["login"], encoding="utf-8") as handle:
            link = handle.read().strip()
        parts = urllib.parse.urlsplit(link)
        token = urllib.parse.parse_qs(parts.query).get("token", [""])[0]
        if token:
            _post("%s://%s%s" % (parts.scheme, parts.netloc, path), value, {"Cookie": "foreman_session=" + token}, timeout=25)
    except (urllib.error.URLError, OSError, ValueError):
        pass


def hold_workers(apps, minutes):
    # The Foreman's own hold: its running task steps aside and comes back once the hold runs out
    _foreman_post(apps, "/api/chat-hold", {"minutes": max(1, min(60, round(minutes)))})


def _find(apps, app_id):
    return next((app for app in apps if app.get("id") == app_id), None)


def claim(apps, app_id, minutes, background=False, keep_models=()):
    # Returns {"granted": bool, ...}. A now-claim is always granted; a background one only on an empty desk.
    global owner
    minutes = max(0.5, min(LONGEST_LEASE_MINUTES, float(minutes)))
    now = time.time()
    with lock:
        active = _active(now)
        rank = BACKGROUND_RANK.get(app_id, 0)
        others = [key for key, lease in active.items() if key != app_id
                  and (not lease["background"] or BACKGROUND_RANK.get(key, 0) > rank)]
        if background and others:
            return {"granted": False, "holder": others[0], "reason": "%s has the GPU" % _title(apps, others[0])}
        taking = owner != app_id
        outranks_workers = background and rank > BACKGROUND_RANK["workers"] and "workers" in active
        lease = active.get(app_id) or {"since": now}
        lease.update(until=now + minutes * 60, background=background)
        active[app_id] = lease
        if taking:
            owner = app_id
            handovers.append({"to": app_id, "at": now})
            del handovers[:-5]
    # Making room happens outside the lock: it talks to other apps, and a slow one mustn't stall the desk
    if taking or not background:
        if app_id != "images":
            ask_images_to_yield(apps)
        if not background or outranks_workers:
            hold_workers(apps, minutes)  # a running worker steps aside, for Ben or for her free time
        if taking:
            unload_ollama(set(keep_models), spare_autonoma=background)
    return {"granted": True, "holder": app_id}


def renew(apps, app_id, minutes):
    # Keeps an existing lease alive without taking the card from anyone: a long clip renews, it doesn't re-claim.
    # A foreground lease renews the Foreman's hold too, or the worker would come back halfway through a 20-minute clip.
    now = time.time()
    minutes = max(0.5, min(LONGEST_LEASE_MINUTES, float(minutes)))
    with lock:
        lease = _active(now).get(app_id)
        if not lease:
            return {"renewed": False}
        lease["until"] = max(lease["until"], now + minutes * 60)
        background = lease["background"]
    if not background:
        hold_workers(apps, minutes)
    return {"renewed": True, "background": background}


def release(app_id):
    global owner
    with lock:
        leases.pop(app_id, None)
        if owner == app_id:
            owner = ""
    return {"released": True}


def kick(apps, app_id):
    # Ben's yellow button: take the card off an app now. Its lease goes, its Ollama models drop, and if nobody else
    # Ben is using holds a lease, the Foreman stops waiting out the quiet time and the stepped-aside worker comes back.
    global owner
    with lock:
        leases.pop(app_id, None)
        if owner == app_id:
            owner = ""
        others_in_use = [key for key, lease in _active(time.time()).items() if not lease["background"]]
    dropped = unload_ollama(set(), spare_autonoma=True)
    if not others_in_use:
        _foreman_post(apps, "/api/chat-hold/end", {})
    return {"kicked": app_id, "dropped": dropped, "workers_freed": not others_in_use}


def state(apps):
    # What the panel shows: who has the card and for how long, and who else is still holding a lease
    now = time.time()
    with lock:
        active = {key: dict(lease) for key, lease in _active(now).items()}
        current = owner
    rows = [{"app": key, "title": _title(apps, key), "background": lease["background"],
             "minutes_left": round((lease["until"] - now) / 60, 1)} for key, lease in active.items()]
    rows.sort(key=lambda row: (row["app"] != current, row["background"]))
    autonoma = [name for name in ollama_models() if name.startswith(AUTONOMA_PREFIX)]
    return {"owner": current, "owner_title": _title(apps, current) if current else "", "leases": rows,
            "autonoma_loaded": autonoma}


def _title(apps, app_id):
    app = _find(apps, app_id)
    return app["title"] if app else app_id
