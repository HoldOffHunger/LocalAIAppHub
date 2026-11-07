# Real progress for the page's bar: ComfyUI announces each node as it starts and each sampler step over its websocket.
# A small standard-library websocket reader, listening for as long as the server runs and reconnecting if Comfy restarts.

import base64
import json
import os
import socket
import struct
import threading
import time

CLIENT_ID = "imagegen"  # Comfy only tells the client that queued a prompt about it
# How far along the bar each stage starts. Loading and reading the prompt happen before "sample"; decoding after it.
STAGE_START = {"model": 0.02, "clip": 0.04, "vae": 0.06, "prompt": 0.10, "sample": 0.30, "decode": 0.90, "save": 0.97}
SAMPLE_END = 0.90

progress = {}  # prompt id -> fraction done, 0..1
lock = threading.Lock()


def fraction(prompt_id):
    with lock:
        return progress.get(prompt_id)


def forget(prompt_id):
    with lock:
        progress.pop(prompt_id, None)


def note(prompt_id, value):
    with lock:
        progress[prompt_id] = max(progress.get(prompt_id, 0.0), value)  # never slides backwards


def handle(message):
    kind, data = message.get("type"), message.get("data") or {}
    prompt_id = data.get("prompt_id")
    if not prompt_id:
        return
    if kind == "executing" and data.get("node") in STAGE_START:
        note(prompt_id, STAGE_START[data["node"]])
    elif kind == "executing" and str(data.get("node", "")).startswith("ref"):
        note(prompt_id, 0.15)  # encoding the pictures to work from
    elif kind == "progress" and data.get("node") == "sample" and data.get("max"):
        note(prompt_id, STAGE_START["sample"] + (SAMPLE_END - STAGE_START["sample"]) * data["value"] / data["max"])
    elif kind == "execution_success":
        note(prompt_id, 1.0)


def read_exact(connection, count):
    buffer = b""
    while len(buffer) < count:
        chunk = connection.recv(count - len(buffer))
        if not chunk:
            raise ConnectionError("closed")
        buffer += chunk
    return buffer


def send_frame(connection, opcode, payload=b""):
    # Frames from a client must be masked
    mask = os.urandom(4)
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    connection.sendall(bytes([0x80 | opcode, 0x80 | len(payload)]) + mask + masked)


def listen_once(port):
    connection = socket.create_connection(("127.0.0.1", port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    connection.sendall(("GET /ws?clientId=%s HTTP/1.1\r\nHost: 127.0.0.1:%d\r\nUpgrade: websocket\r\n"
                        "Connection: Upgrade\r\nSec-WebSocket-Key: %s\r\nSec-WebSocket-Version: 13\r\n\r\n"
                        % (CLIENT_ID, port, key)).encode())
    reply = b""
    while b"\r\n\r\n" not in reply:
        reply += read_exact(connection, 1)
    if b" 101 " not in reply.split(b"\r\n", 1)[0]:
        raise ConnectionError("no websocket")
    connection.settimeout(None)
    while True:
        first, second = read_exact(connection, 2)
        length = second & 0x7F
        if length == 126:
            length = struct.unpack(">H", read_exact(connection, 2))[0]
        elif length == 127:
            length = struct.unpack(">Q", read_exact(connection, 8))[0]
        payload = read_exact(connection, length)
        opcode = first & 0x0F
        if opcode == 1:
            try:
                handle(json.loads(payload))
            except ValueError:
                pass
        elif opcode == 9:
            send_frame(connection, 10, payload)
        elif opcode == 8:
            raise ConnectionError("closed")
        # opcode 2 is preview pictures, which ImageGen turns off


def listen_forever(port):
    while True:
        try:
            listen_once(port)
        except OSError:
            pass
        time.sleep(2)


def start(port):
    threading.Thread(target=listen_forever, args=(port,), daemon=True).start()
