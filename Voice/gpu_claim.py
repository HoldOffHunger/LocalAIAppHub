# Voice goes first, as Chat does: before each reply, ask the App Hub's GPU desk for the card, keeping only the model that
# writes the reply. The desk holds the AI Workers until the talk goes quiet and has ImageGen's ComfyUI let go. Without
# the hub, nothing happens; the workers' own guard still keeps them off a card that's in use.

import json
import os
import urllib.error
import urllib.request

HUB_URL = os.environ.get("APP_HUB_URL", "http://127.0.0.1:8700")


def claim_gpu(minutes, model):
    # Best effort: a missing hub never holds up the conversation
    if minutes <= 0:
        return
    request = urllib.request.Request(HUB_URL + "/api/gpu/claim", method="POST", headers={"Content-Type": "application/json"},
                                     data=json.dumps({"app": "voice", "minutes": minutes,
                                                      "keep_models": [model] if model else []}).encode("utf-8"))
    try:
        urllib.request.urlopen(request, timeout=60).close()  # making room can mean unloading a model or two first
    except (urllib.error.URLError, OSError, ValueError):
        pass
