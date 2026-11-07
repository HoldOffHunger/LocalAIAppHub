# Chat goes first: before each reply, ask the App Hub's GPU desk for the card. The desk holds the AI Workers until
# the chat goes quiet, has ImageGen's ComfyUI let go (straight after its picture, if one is drawing), and unloads
# every Ollama model except the one this reply needs. Without the hub, Chat asks the Foreman directly, as it used to.
# The Foreman makes a fresh login link each time it starts; its token is the session cookie the Foreman's API checks.

import json
import os
import urllib.error
import urllib.parse
import urllib.request

HUB_URL = os.environ.get("APP_HUB_URL", "http://127.0.0.1:8700")
FOREMAN_LOGIN = os.environ.get("FOREMAN_LOGIN_FILE", r"E:\AIWorkers\data\foreman_login.txt")


def claim_gpu(minutes, model):
    # Best effort all round: neither a missing hub nor a missing Foreman ever holds up the chat
    if minutes <= 0:
        return
    request = urllib.request.Request(HUB_URL + "/api/gpu/claim", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"app": "chat", "minutes": minutes,
                                                      "keep_models": [model] if model else []}).encode("utf-8"))
    try:
        urllib.request.urlopen(request, timeout=60).close()  # making room can mean unloading a model or two first
        return
    except (urllib.error.URLError, OSError, ValueError):
        pass
    pause_workers(minutes)


def foreman_link():
    try:
        with open(FOREMAN_LOGIN, encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def hold_request(link, minutes):
    parts = urllib.parse.urlsplit(link)
    token = urllib.parse.parse_qs(parts.query).get("token", [""])[0]
    if not token:
        return None
    return urllib.request.Request("%s://%s/api/chat-hold" % (parts.scheme, parts.netloc), method="POST",
                                  data=json.dumps({"minutes": minutes}).encode("utf-8"),
                                  headers={"Content-Type": "application/json", "Cookie": "foreman_session=" + token})


def pause_workers(minutes):
    # The old way, for when the hub isn't running. Best effort: a Foreman that isn't running never holds up the chat
    request = hold_request(foreman_link(), minutes) if minutes > 0 else None
    if request is None:
        return
    try:
        urllib.request.urlopen(request, timeout=25).close()
    except (urllib.error.URLError, OSError, ValueError):
        pass
