# The 1070 Ti has 8 GB, and Ollama, the AI Workers and ComfyUI can't all fit on it at once.
# Before a picture, ImageGen asks the App Hub's GPU desk for the card: the desk holds the Foreman and has Ollama
# drop its models. While a long clip draws, ImageGen renews its lease so the workers stay out. Without the hub,
# ImageGen makes room itself, as it used to. After a quiet spell, Comfy lets go of the card.

import json
import os
import urllib.error
import urllib.parse
import urllib.request

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
HUB_URL = os.environ.get("APP_HUB_URL", "http://127.0.0.1:8700")
FOREMAN_LOGIN = os.environ.get("FOREMAN_LOGIN_FILE", r"E:\AIWorkers\data\foreman_login.txt")


def post_json(url, value, headers=None, timeout=25):
    request = urllib.request.Request(url, method="POST", data=json.dumps(value).encode("utf-8"),
                                     headers=dict({"Content-Type": "application/json"}, **(headers or {})))
    urllib.request.urlopen(request, timeout=timeout).close()


def claim_card(minutes):
    # Takes the card from whoever had it; best effort, so a missing hub never holds up a picture
    try:
        post_json(HUB_URL + "/api/gpu/claim", {"app": "images", "minutes": minutes}, timeout=60)
    except (urllib.error.URLError, OSError, ValueError):
        pause_workers(minutes)
        unload_ollama()


def renew_card(minutes):
    # Keeps the lease alive while a clip draws, without taking the card back from Chat
    try:
        post_json(HUB_URL + "/api/gpu/renew", {"app": "images", "minutes": minutes}, timeout=5)
    except (urllib.error.URLError, OSError, ValueError):
        pass


def release_card():
    try:
        post_json(HUB_URL + "/api/gpu/release", {"app": "images"}, timeout=5)
    except (urllib.error.URLError, OSError, ValueError):
        pass


def pause_workers(minutes):
    # Same hold Local Chat uses; best effort, so a Foreman that isn't running never holds up a picture
    if minutes <= 0:
        return
    try:
        with open(FOREMAN_LOGIN, encoding="utf-8") as handle:
            link = handle.read().strip()
        parts = urllib.parse.urlsplit(link)
        token = urllib.parse.parse_qs(parts.query).get("token", [""])[0]
        if token:
            post_json("%s://%s/api/chat-hold" % (parts.scheme, parts.netloc), {"minutes": minutes},
                      {"Cookie": "foreman_session=" + token})
    except (urllib.error.URLError, OSError, ValueError):
        pass


def unload_ollama():
    # keep_alive 0 tells Ollama to drop a model from the card straight away
    try:
        with urllib.request.urlopen(OLLAMA_URL + "/api/ps", timeout=5) as response:
            loaded = json.load(response).get("models", [])
        for model in loaded:
            post_json(OLLAMA_URL + "/api/generate", {"model": model["name"], "keep_alive": 0})
    except (urllib.error.URLError, OSError, ValueError, KeyError):
        pass


def free_comfy(comfy_url):
    try:
        post_json(comfy_url + "/free", {"unload_models": True, "free_memory": True}, timeout=10)
    except (urllib.error.URLError, OSError, ValueError):
        pass
