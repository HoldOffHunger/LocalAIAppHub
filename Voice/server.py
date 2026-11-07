# Voice: Chat, spoken. Talk to a model aloud and hear it answer, with its own threads, on http://127.0.0.1:8795
# The characters are Chat's own (..\local-chat\data\personas.json, read, never written). Whisper turns what Ben says into
# text and Kokoro speaks the reply, sentence by sentence as it's written, both on the processor; the model writing the
# reply has the graphics card. Run with this folder's .venv: start.bat does.

import json
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import gpu_claim
from speech import SAMPLE, Speech, split_ready

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
THREAD_DIR = os.path.join(DATA_DIR, "threads")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
CHARACTER_VOICES_PATH = os.path.join(DATA_DIR, "character_voices.json")
STATIC_DIR = os.path.join(APP_DIR, "static")
CHAT_DATA_DIR = os.path.join(APP_DIR, "..", "local-chat", "data")  # Chat, beside Voice in the hub
PERSONAS_PATH = os.environ.get("VOICE_PERSONAS", os.path.join(CHAT_DATA_DIR, "personas.json"))
CHAT_SETTINGS_PATH = os.path.join(CHAT_DATA_DIR, "settings.json")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
HOST = os.environ.get("VOICE_HOST", "127.0.0.1")
PORT = int(os.environ.get("VOICE_PORT", "8795"))

ID_PATTERN = re.compile(r"^[a-f0-9]{8,64}$")
AUDIO_NAME = re.compile(r"^[a-f0-9]{8,64}-\d{1,4}\.wav$")
MAX_RECORDING_BYTES = 20 * 1024 * 1024
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8", ".wav": "audio/wav"}
HINTS = "Talasia, hobthrush, Claudia, Ben."  # words Whisper wouldn't guess; the character's name is added

DEFAULT_SETTINGS = {
    "model": "",  # empty: whatever Chat uses
    "voice": "af_heart",
    "speed": 1.0,
    "temperature": 0.8,
    "num_ctx": 8192,
    "pause_workers_minutes": 5,
}

SPOKEN = ("This is a spoken conversation: Ben talks to you aloud, and your replies are read out to him by a voice. "
          "Answer the way you'd talk, not the way you'd write: usually a few sentences, natural and warm. No lists, "
          "no headings, no markdown, no emoji, and no actions or stage directions in asterisks; only the words you say.")
NO_CHARACTER = "You are a friendly, thoughtful companion having a conversation with Ben."

speech = Speech()


def read_json(path, fallback):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return fallback


def write_json(path, value):
    temp_path = path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def load_settings():
    merged = dict(DEFAULT_SETTINGS)
    merged.update({k: v for k, v in read_json(SETTINGS_PATH, {}).items() if k in DEFAULT_SETTINGS})
    if not merged["model"]:
        merged["model"] = read_json(CHAT_SETTINGS_PATH, {}).get("model", "")
    return merged


def characters():
    personas = read_json(PERSONAS_PATH, [])
    return [p for p in personas if isinstance(p, dict) and ID_PATTERN.match(str(p.get("id", "")))] if isinstance(personas, list) else []


def find_character(character_id):
    return next((c for c in characters() if c["id"] == character_id), None)


def system_prompt(character):
    # The character's own words from Chat, the lines it learned from, then how to talk aloud
    if not character:
        return NO_CHARACTER + "\n\n" + SPOKEN
    parts = [str(character.get("prompt", "")).strip() or "You are %s." % character.get("name", "a friend")]
    examples = [str(x) for x in character.get("examples") or []]
    if examples:
        parts.append("Examples of how %s talks:\n\n%s" % (character.get("name", "they"), "\n\n".join(examples)))
    parts.append(SPOKEN)
    return "\n\n".join(parts)


def thread_path(thread_id):
    return os.path.join(THREAD_DIR, thread_id + ".json") if ID_PATTERN.match(thread_id or "") else None


def load_thread(thread_id):
    path = thread_path(thread_id)
    return read_json(path, None) if path else None


def save_thread(thread):
    thread["updated"] = time.time()
    write_json(thread_path(thread["id"]), thread)


def list_threads():
    rows = []
    for name in os.listdir(THREAD_DIR):
        thread = read_json(os.path.join(THREAD_DIR, name), None) if name.endswith(".json") else None
        if thread:
            rows.append({"id": thread["id"], "title": thread.get("title") or "New voice chat",
                         "character_id": thread.get("character_id", ""), "updated": thread.get("updated", 0)})
    return sorted(rows, key=lambda row: row["updated"], reverse=True)


def remove_audio(thread_id, keep=()):
    # Only this thread's own recordings, by their exact names: data/audio/<thread id>/<message id>-<n>.wav
    folder = os.path.join(AUDIO_DIR, thread_id)
    if not ID_PATTERN.match(thread_id) or not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        if AUDIO_NAME.match(name) and name not in keep:
            os.remove(os.path.join(folder, name))
    if not os.listdir(folder):
        os.rmdir(folder)


def remember_voice(character_id, voice):
    # Picking a voice in a thread with a character makes it that character's voice from then on
    if character_id:
        voices = read_json(CHARACTER_VOICES_PATH, {})
        voices[character_id] = voice
        write_json(CHARACTER_VOICES_PATH, voices)


def without_name(text, name):
    # Chat-trained models often start "Claudia: …"; she shouldn't say her own name like a script
    return re.sub(r"^\s*%s\s*:\s*" % re.escape(name), "", text) if name else text


def chat_request(thread, settings):
    messages = [{"role": "system", "content": system_prompt(find_character(thread.get("character_id", "")))}]
    messages += [{"role": m["role"], "content": m["content"]} for m in thread["messages"] if m.get("content")]
    payload = {"model": thread.get("model") or settings["model"], "messages": messages, "stream": True,
               "options": {"temperature": settings["temperature"], "num_ctx": settings["num_ctx"]}}
    return urllib.request.Request(OLLAMA_URL + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                                  headers={"Content-Type": "application/json"}, method="POST")


class VoiceHandler(BaseHTTPRequestHandler):
    server_version = "Voice/1.0"

    def log_message(self, format_string, *args):
        if "/api/audio/" not in self.path:
            sys.stderr.write("[voice] " + (format_string % args) + "\n")

    def send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, value, status=200):
        self.send_bytes(json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8", status)

    def read_raw(self, limit):
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if 0 < length <= limit else None

    def read_body(self):
        raw = self.read_raw(1024 * 1024)
        try:
            return json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            return {}

    def send_file(self, folder, relative):
        path = os.path.normpath(os.path.join(folder, relative))
        if not path.startswith(folder + os.sep) or not os.path.isfile(path):
            return self.send_json({"error": "not found"}, 404)
        with open(path, "rb") as handle:
            self.send_bytes(handle.read(), CONTENT_TYPES.get(os.path.splitext(path)[1], "application/octet-stream"))

    # ---------- routes ----------

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self.send_file(STATIC_DIR, "index.html")
        elif path.startswith("/static/"):
            self.send_file(STATIC_DIR, path[len("/static/"):])
        elif path == "/api/setup":
            self.send_setup()
        elif path == "/api/threads":
            self.send_json(list_threads())
        elif re.match(r"^/api/threads/[a-f0-9]+$", path):
            thread = load_thread(path.rsplit("/", 1)[1])
            self.send_json(thread) if thread else self.send_json({"error": "not found"}, 404)
        elif re.match(r"^/api/audio/[a-f0-9]+/[^/]+$", path):
            _, _, _, thread_id, name = path.split("/")
            if ID_PATTERN.match(thread_id) and AUDIO_NAME.match(name):
                self.send_file(AUDIO_DIR, os.path.join(thread_id, name))
            else:
                self.send_json({"error": "not found"}, 404)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/threads":
            self.new_thread(self.read_body())
        elif path == "/api/preview":
            self.preview(self.read_body())
        elif re.match(r"^/api/threads/[a-f0-9]+/listen$", path):
            self.listen(path.split("/")[3])
        elif re.match(r"^/api/threads/[a-f0-9]+/say$", path):
            self.say(path.split("/")[3], self.read_body())
        else:
            self.send_json({"error": "not found"}, 404)

    def do_PATCH(self):
        path = self.path.split("?", 1)[0]
        if not re.match(r"^/api/threads/[a-f0-9]+$", path):
            return self.send_json({"error": "not found"}, 404)
        thread = load_thread(path.rsplit("/", 1)[1])
        if not thread:
            return self.send_json({"error": "not found"}, 404)
        body = self.read_body()
        for key in ("title", "model", "voice", "speed", "character_id"):
            if key in body:
                thread[key] = body[key]
        if "voice" in body:
            remember_voice(thread.get("character_id", ""), body["voice"])
        save_thread(thread)
        self.send_json(thread)

    def do_PUT(self):
        if self.path.split("?", 1)[0] != "/api/settings":
            return self.send_json({"error": "not found"}, 404)
        settings = {k: v for k, v in read_json(SETTINGS_PATH, {}).items() if k in DEFAULT_SETTINGS}
        settings.update({k: v for k, v in self.read_body().items() if k in DEFAULT_SETTINGS})
        write_json(SETTINGS_PATH, settings)
        self.send_json(load_settings())

    def do_DELETE(self):
        path = self.path.split("?", 1)[0]
        thread_id = path.rsplit("/", 1)[1]
        if re.match(r"^/api/threads/[a-f0-9]+$", path) and thread_path(thread_id) and os.path.isfile(thread_path(thread_id)):
            os.remove(thread_path(thread_id))
            remove_audio(thread_id)
        self.send_json({"ok": True})

    # ---------- the parts ----------

    def send_setup(self):
        try:
            with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=5) as response:
                models = [m["name"] for m in json.load(response).get("models", []) if "embed" not in m["name"]]
            problem = ""
        except (urllib.error.URLError, OSError, ValueError) as error:
            models, problem = [], "Ollama isn't answering at %s (%s)." % (OLLAMA_URL, error)
        self.send_json({"models": sorted(models), "voices": speech.voices(), "settings": load_settings(),
                        "characters": [{"id": c["id"], "name": c.get("name", "Unnamed")} for c in characters()],
                        "character_voices": read_json(CHARACTER_VOICES_PATH, {}),
                        "problem": speech.problem or problem})

    def new_thread(self, body):
        settings = load_settings()
        character_id = str(body.get("character_id") or "")
        voice = body.get("voice") or read_json(CHARACTER_VOICES_PATH, {}).get(character_id) or settings["voice"]
        thread = {"id": os.urandom(8).hex(), "title": "", "character_id": character_id, "model": body.get("model") or settings["model"],
                  "voice": voice, "speed": body.get("speed") or settings["speed"], "created": time.time(), "messages": []}
        save_thread(thread)
        self.send_json(thread)

    def preview(self, body):
        settings = load_settings()
        audio = speech.speak(SAMPLE, body.get("voice") or settings["voice"], body.get("speed") or settings["speed"])
        self.send_bytes(audio, "audio/wav") if audio else self.send_json({"error": speech.problem or "nothing to say"}, 500)

    def listen(self, thread_id):
        thread = load_thread(thread_id)
        audio = self.read_raw(MAX_RECORDING_BYTES)
        if not thread or not audio:
            return self.send_json({"error": "No recording, or no such thread."}, 400)
        with open(os.path.join(DATA_DIR, "last_recording.webm"), "wb") as handle:
            handle.write(audio)  # the latest one only, for when it hears nothing and we want to know why
        character = find_character(thread.get("character_id", ""))
        hints = HINTS + (" " + character["name"] + "." if character else "")
        try:
            self.send_json({"text": speech.listen(audio, hints)})
        except Exception as error:  # a garbled recording shouldn't take the server down
            self.send_json({"error": "Couldn't make out the recording: %s" % error}, 500)

    def say(self, thread_id, body):
        # Ben's words go into the thread; the reply streams back as text, and as each sentence is spoken, its audio.
        # One line of JSON per event: {"type": "text", "text"}, {"type": "audio", "url"}, {"type": "done"}, {"type": "error"}
        thread = load_thread(thread_id)
        text = str(body.get("text", "")).strip()
        if not thread or not text:
            return self.send_json({"error": "Nothing was said, or no such thread."}, 400)
        settings = load_settings()
        thread["messages"].append({"id": os.urandom(6).hex(), "role": "user", "content": text, "time": time.time()})
        if not thread.get("title"):
            thread["title"] = text[:48] + ("…" if len(text) > 48 else "")
        reply = {"id": os.urandom(6).hex(), "role": "assistant", "content": "", "audio": [], "time": time.time()}
        save_thread(thread)
        gpu_claim.claim_gpu(int(settings["pause_workers_minutes"] or 0), thread.get("model") or settings["model"])
        try:
            upstream = urllib.request.urlopen(chat_request(thread, settings), timeout=600)
        except (urllib.error.URLError, OSError) as error:
            return self.send_json({"error": "The model didn't answer: %s" % error}, 502)
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self.relay(upstream, thread, reply)
        finally:
            upstream.close()
            character = find_character(thread.get("character_id", ""))
            reply["content"] = without_name(reply["content"], character.get("name", "") if character else "")
            thread["messages"].append(reply)
            save_thread(thread)

    def relay(self, upstream, thread, reply):
        # Three hands: this one writes events to the page; a reader pulls the model's words and hands each finished
        # sentence to the speaker, which makes its .wav. Stop in the page breaks the connection, and everything winds down
        events, sentences, stopped = queue.Queue(), queue.Queue(), threading.Event()
        character = find_character(thread.get("character_id", ""))
        name = character.get("name", "") if character else ""
        folder = os.path.join(AUDIO_DIR, thread["id"])
        os.makedirs(folder, exist_ok=True)

        def read():
            buffer, first = "", True
            try:
                for line in upstream:
                    if stopped.is_set():
                        break
                    chunk = json.loads(line).get("message", {}).get("content", "")
                    if not chunk:
                        continue
                    reply["content"] += chunk
                    events.put({"type": "text", "text": chunk})
                    buffer += chunk
                    ready, buffer = split_ready(buffer, first)
                    for sentence in ready:
                        sentences.put(without_name(sentence, name) if first else sentence)
                        first = False
                if buffer.strip() and not stopped.is_set():
                    sentences.put(without_name(buffer, name) if first else buffer)
            except (OSError, ValueError) as error:
                events.put({"type": "error", "error": "The model stopped: %s" % error})
            sentences.put(None)

        def speak():
            while True:
                sentence = sentences.get()
                if sentence is None or stopped.is_set():
                    break
                try:
                    audio = speech.speak(sentence, thread.get("voice") or "af_heart", thread.get("speed") or 1.0)
                except Exception as error:
                    events.put({"type": "error", "error": "The voice failed: %s" % error})
                    continue
                if audio:
                    name = "%s-%d.wav" % (reply["id"], len(reply["audio"]))
                    with open(os.path.join(folder, name), "wb") as handle:
                        handle.write(audio)
                    reply["audio"].append(name)
                    events.put({"type": "audio", "url": "/api/audio/%s/%s" % (thread["id"], name)})
            events.put(None)

        threading.Thread(target=read, daemon=True).start()
        threading.Thread(target=speak, daemon=True).start()
        try:
            while True:
                event = events.get()
                if event is None:
                    break
                self.wfile.write((json.dumps(event, ensure_ascii=False) + "\n").encode("utf-8"))
                self.wfile.flush()
            self.wfile.write(b'{"type": "done"}\n')
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            stopped.set()  # Ben pressed Stop, or talked over her: what was said so far is kept


def main():
    for folder in (THREAD_DIR, AUDIO_DIR):
        os.makedirs(folder, exist_ok=True)
    threading.Thread(target=speech.load, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), VoiceHandler)
    print("Voice running at http://%s:%d  (Ollama: %s)" % (HOST, PORT, OLLAMA_URL), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
