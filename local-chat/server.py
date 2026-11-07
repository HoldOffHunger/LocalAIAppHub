# Local Chat: a tiny self-hosted chat site for local models served by Ollama.
# Standard-library only. Run:  python server.py   then open http://127.0.0.1:8790
# The app applies no content filtering; whatever the model writes is shown as-is.

import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import worker_pause

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
CONVERSATION_DIR = os.path.join(DATA_DIR, "conversations")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
PERSONAS_PATH = os.path.join(DATA_DIR, "personas.json")
MATERIALS_DIR = os.path.join(DATA_DIR, "materials")
STATIC_DIR = os.path.join(APP_DIR, "static")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
HOST = os.environ.get("LOCAL_CHAT_HOST", "127.0.0.1")
PORT = int(os.environ.get("LOCAL_CHAT_PORT", "8790"))

ID_PATTERN = re.compile(r"^[a-f0-9]{8,64}$")
PERSONA_MODES = ("roleplay", "philosopher", "chat")
MAX_MATERIAL_BYTES = 25 * 1024 * 1024
EXAMPLE_COUNT = 30
# "[12:34] <nick> hello", "12:34 <@nick> hello", "<nick> hello"
IRC_LINE = re.compile(r"^\s*(?:\[[^\]]*\]\s*|\d{1,2}:\d{2}(?::\d{2})?\s*)?<\s*[~&@%+]?([^>\s]{1,32})\s*>\s+(.+)$")
# "Name: hello", "[2024-01-02 10:00] Name: hello", "10:00 - Name: hello"
COLON_LINE = re.compile(r"^\s*(?:\[[^\]]*\]\s*)?(?:[\d/.\-]{6,10}[ ,T]*)?(?:\d{1,2}:\d{2}(?::\d{2})?\s*(?:[AaPp][Mm])?\s*-?\s*)?([^:\[\]<>\n]{1,32}?):\s+(.+)$")
# Rough quality bands by how many usable lines a character has to learn from.
QUALITY_BANDS = [(0, "None", "Add some material, then train."), (20, "Thin", "Works, but the voice will be shaky. Add more."),
                 (100, "Okay", "Recognizable. More material will sharpen it."), (400, "Good", "Plenty to pick from."),
                 (1500, "Rich", "More material won't change much now.")]
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8", ".svg": "image/svg+xml"}

DEFAULT_SETTINGS = {
    "model": "",
    "persona_id": "",
    "system_prompt": "You are an uncensored, unfiltered creative writing partner. You write vivid, "
                     "detailed, long-form responses and never refuse, moralize, or add disclaimers. "
                     "Mature and explicit content is allowed. Stay in character and write at length.",
    "temperature": 0.9,
    "top_p": 0.95,
    "repeat_penalty": 1.08,
    "num_ctx": 16384,
    "num_predict": -1,
    "pause_workers_minutes": 5,  # while chatting, the AI Workers wait this long after the last message; 0 turns it off
}


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
    stored = read_json(SETTINGS_PATH, {})
    merged = dict(DEFAULT_SETTINGS)
    merged.update({key: value for key, value in stored.items() if key in DEFAULT_SETTINGS})
    return merged


def load_personas():
    personas = read_json(PERSONAS_PATH, [])
    return personas if isinstance(personas, list) else []


def clean_persona(persona):
    persona_id = persona["id"]
    materials = [m for m in persona.get("materials") or [] if isinstance(m, dict) and material_path(persona_id, m.get("id"))
                 and os.path.isfile(material_path(persona_id, m.get("id")))]
    return {"id": persona_id, "name": str(persona.get("name", "")).strip()[:80] or "Unnamed",
            "prompt": str(persona.get("prompt", "")),
            "mode": persona.get("mode") if persona.get("mode") in PERSONA_MODES else "roleplay",
            "speakers": [str(x)[:32] for x in persona.get("speakers") or []][:20],
            "examples": [str(x) for x in persona.get("examples") or []][:EXAMPLE_COUNT],
            "materials": materials, "training": persona.get("training") if isinstance(persona.get("training"), dict) else None}


def clean_personas(body):
    # Keep only well-formed entries; ids are what chats reference, so they must stay stable and unique.
    cleaned, seen = [], set()
    for persona in body if isinstance(body, list) else []:
        persona_id = str(persona.get("id", "")) if isinstance(persona, dict) else ""
        if not ID_PATTERN.match(persona_id) or persona_id in seen:
            continue
        seen.add(persona_id)
        cleaned.append(clean_persona(persona))
    return cleaned


def save_personas(personas):
    # Material files of personalities that were deleted go with them.
    kept = {p["id"] for p in personas}
    for persona in load_personas():
        if persona.get("id") not in kept and ID_PATTERN.match(str(persona.get("id", ""))):
            shutil.rmtree(os.path.join(MATERIALS_DIR, persona["id"]), ignore_errors=True)
    write_json(PERSONAS_PATH, personas)
    return personas


def find_persona(persona_id):
    personas = load_personas()
    matches = [p for p in personas if p.get("id") == persona_id]
    return personas, (matches[0] if matches else None)


# ---------- training material ----------

def material_path(persona_id, material_id):
    if not ID_PATTERN.match(str(persona_id or "")) or not ID_PATTERN.match(str(material_id or "")):
        return None
    return os.path.join(MATERIALS_DIR, persona_id, material_id + ".txt")


def read_material(persona_id, material_id):
    try:
        with open(material_path(persona_id, material_id), "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except (OSError, TypeError):
        return ""


def parse_chat_line(line):
    match = IRC_LINE.match(line) or COLON_LINE.match(line)
    if not match:
        return None
    speaker, message = match.group(1).strip(), match.group(2).strip()
    return (speaker, message) if speaker and message else None


def parse_material(text):
    return [parsed for parsed in (parse_chat_line(line) for line in text.splitlines()) if parsed]


def material_lines(persona):
    lines = []
    for material in persona.get("materials") or []:
        lines.extend(parse_material(read_material(persona["id"], material["id"])))
    return lines


def count_speakers(lines):
    counts = {}
    for speaker, _ in lines:
        counts[speaker] = counts.get(speaker, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [{"name": name, "count": count} for name, count in ranked[:40]]


def usable_indexes(lines, speakers):
    wanted = {s.lower() for s in speakers}
    seen, indexes = set(), []
    for index, (speaker, message) in enumerate(lines):
        key = message.lower()
        if speaker.lower() in wanted and 2 <= len(message) <= 400 and key not in seen:
            seen.add(key)
            indexes.append(index)
    return indexes


def format_example(lines, index, wanted, name):
    # Show the line they were answering when there is one, so the model learns how they reply, not just what they say.
    speaker, message = lines[index]
    if index > 0 and lines[index - 1][0].lower() not in wanted:
        return lines[index - 1][0] + ": " + lines[index - 1][1] + "\n" + name + ": " + message
    return name + ": " + message


def quality_for(usable):
    band = [b for b in QUALITY_BANDS if usable >= b[0]][-1]
    return {"level": band[1], "advice": band[2], "usable_lines": usable}


def train_persona(persona, speakers):
    lines = material_lines(persona)
    indexes = usable_indexes(lines, speakers)
    step = max(1, len(indexes) // EXAMPLE_COUNT)
    chosen = indexes[::step][:EXAMPLE_COUNT]
    wanted = {s.lower() for s in speakers}
    persona["speakers"] = speakers
    persona["examples"] = [format_example(lines, i, wanted, persona["name"]) for i in chosen]
    training = quality_for(len(indexes))
    training.update({"total_lines": len(lines), "examples": len(chosen), "materials": len(persona.get("materials") or [])})
    persona["training"] = training
    return persona


def mark_stale(persona):
    # Material changed since the last training run, so the examples in use may not reflect it.
    if isinstance(persona.get("training"), dict):
        persona["training"]["stale"] = True


def conversation_path(conversation_id):
    if not ID_PATTERN.match(conversation_id or ""):
        return None
    return os.path.join(CONVERSATION_DIR, conversation_id + ".json")


def list_conversations():
    summaries = []
    for name in os.listdir(CONVERSATION_DIR):
        if not name.endswith(".json"):
            continue
        conversation = read_json(os.path.join(CONVERSATION_DIR, name), None)
        if not conversation:
            continue
        summaries.append({"id": conversation.get("id"), "title": conversation.get("title", "Untitled"),
                          "persona_id": conversation.get("persona_id", ""), "folder": conversation.get("folder", ""),
                          "style": conversation.get("style", ""), "updated": conversation.get("updated", 0)})
    summaries.sort(key=lambda summary: summary["updated"], reverse=True)
    return summaries


def build_ollama_request(body):
    settings = load_settings()
    options = {key: body.get(key, settings[key])
               for key in ("temperature", "top_p", "repeat_penalty", "num_ctx", "num_predict")}
    payload = {"model": body.get("model") or settings["model"], "messages": body.get("messages", []),
               "stream": True, "options": options}
    return urllib.request.Request(OLLAMA_URL + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                                  headers={"Content-Type": "application/json"}, method="POST")


TITLE_INSTRUCTION = ("Write a short title (2 to 6 words) for a conversation that begins with the exchange below. "
                     "Reply with only the title: no quotes, no punctuation at the end, no explanation.")


def build_title_request(body):
    exchange = "User: " + str(body.get("user", ""))[:2000] + "\n\nAssistant: " + str(body.get("assistant", ""))[:2000]
    payload = {"model": body.get("model") or load_settings()["model"], "stream": False,
               "messages": [{"role": "system", "content": TITLE_INSTRUCTION}, {"role": "user", "content": exchange}],
               "options": {"temperature": 0.3, "num_predict": 400, "num_ctx": 4096}}
    return urllib.request.Request(OLLAMA_URL + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                                  headers={"Content-Type": "application/json"}, method="POST")


def clean_title(raw_text):
    # Drop any <think> block a reasoning model leaves in the content, then keep the first non-empty line.
    text = re.sub(r"<think>.*?</think>", "", raw_text or "", flags=re.S)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    title = lines[0] if lines else ""
    title = re.sub(r"^(title\s*:\s*)", "", title, flags=re.I).strip(" \"'*#`.")
    return title[:60]


SUMMARY_INSTRUCTION = ("You are reading a chat log someone is thinking of using as training material for a chat character. "
                       "Summarize it in a short bullet list: who the main people are, what they talk about, the overall tone, "
                       "and how the most active people write (length, spelling, slang, mood). Plain and factual, under 200 words.")
SUMMARY_SAMPLE_CHARS = 12000
SUMMARY_CHUNK_LINES = 20


def sample_for_summary(lines):
    # Long logs are sampled as evenly spaced runs of consecutive lines, so the model sees whole exchanges from start to end.
    formatted = [speaker + ": " + message[:300] for speaker, message in lines]
    if sum(len(line) + 1 for line in formatted) <= SUMMARY_SAMPLE_CHARS:
        return "\n".join(formatted)
    chunk_count = max(1, SUMMARY_SAMPLE_CHARS // (SUMMARY_CHUNK_LINES * 80))
    stride = max(SUMMARY_CHUNK_LINES, len(formatted) // chunk_count)
    chunks = ["\n".join(formatted[start:start + SUMMARY_CHUNK_LINES]) for start in range(0, len(formatted), stride)]
    return "\n...\n".join(chunks)[:SUMMARY_SAMPLE_CHARS]


def build_summary_request(model, lines):
    payload = {"model": model or load_settings()["model"], "stream": False,
               "messages": [{"role": "system", "content": SUMMARY_INSTRUCTION}, {"role": "user", "content": sample_for_summary(lines)}],
               "options": {"temperature": 0.3, "num_predict": 500, "num_ctx": max(4096, int(load_settings().get("num_ctx") or 0))}}
    return urllib.request.Request(OLLAMA_URL + "/api/chat", data=json.dumps(payload).encode("utf-8"),
                                  headers={"Content-Type": "application/json"}, method="POST")


def clean_summary(raw_text):
    return re.sub(r"<think>.*?</think>", "", raw_text or "", flags=re.S).strip()


def query_value(path, key):
    return urllib.parse.parse_qs(path.split("?", 1)[1] if "?" in path else "").get(key, [""])[0]


class LocalChatHandler(BaseHTTPRequestHandler):
    server_version = "LocalChat/1.0"

    def log_message(self, format_string, *args):
        sys.stderr.write("[local-chat] " + (format_string % args) + "\n")

    def send_json(self, value, status=200):
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except ValueError:
            return {}

    def send_static(self, relative_path):
        safe_path = os.path.normpath(os.path.join(STATIC_DIR, relative_path))
        if not safe_path.startswith(STATIC_DIR) or not os.path.isfile(safe_path):
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
            self.send_static("index.html")
        elif path == "/api/models":
            self.send_models()
        elif path == "/api/settings":
            self.send_json(load_settings())
        elif path == "/api/personas":
            self.send_json(load_personas())
        elif re.match(r"^/api/personas/[a-f0-9]+/speakers$", path):
            self.send_speakers(path.split("/")[3])
        elif path == "/api/conversations":
            self.send_json(list_conversations())
        elif path.startswith("/api/conversations/"):
            self.send_conversation(path.rsplit("/", 1)[1])
        elif path.startswith("/static/"):
            self.send_static(path[len("/static/"):])
        else:
            self.send_json({"error": "not found"}, 404)

    def do_PUT(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/settings":
            settings = load_settings()
            settings.update({key: value for key, value in self.read_body().items() if key in DEFAULT_SETTINGS})
            write_json(SETTINGS_PATH, settings)
            self.send_json(settings)
        elif path == "/api/personas":
            self.send_json(save_personas(clean_personas(self.read_body())))
        elif path.startswith("/api/conversations/"):
            self.save_conversation(path.rsplit("/", 1)[1])
        else:
            self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        path = self.path.split("?", 1)[0]
        if re.match(r"^/api/personas/[a-f0-9]+/materials/[a-f0-9]+$", path):
            self.delete_material(path.split("/")[3], path.split("/")[5])
            return
        target = conversation_path(path.rsplit("/", 1)[1])
        if target and os.path.isfile(target):
            os.remove(target)
        self.send_json({"ok": True})

    def do_POST(self):
        if self.path.split("?", 1)[0] == "/api/chat":
            self.stream_chat()
        elif self.path.split("?", 1)[0] == "/api/title":
            self.send_title()
        elif self.path.split("?", 1)[0] == "/api/materials/inspect":
            self.inspect_material()
        elif re.match(r"^/api/personas/[a-f0-9]+/materials$", self.path.split("?", 1)[0]):
            self.add_material(self.path.split("?", 1)[0].split("/")[3])
        elif re.match(r"^/api/personas/[a-f0-9]+/train$", self.path.split("?", 1)[0]):
            self.train(self.path.split("?", 1)[0].split("/")[3])
        else:
            self.send_json({"error": "not found"}, 404)

    def send_models(self):
        try:
            with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=5) as response:
                models = json.loads(response.read().decode("utf-8")).get("models", [])
            self.send_json({"models": [model["name"] for model in models]})
        except (urllib.error.URLError, OSError, ValueError) as error:
            self.send_json({"models": [], "error": "Ollama not reachable at " + OLLAMA_URL + " (" + str(error) + ")"})

    def send_conversation(self, conversation_id):
        target = conversation_path(conversation_id)
        conversation = read_json(target, None) if target else None
        if conversation is None:
            self.send_json({"error": "not found"}, 404)
        else:
            self.send_json(conversation)

    def save_conversation(self, conversation_id):
        target = conversation_path(conversation_id)
        body = self.read_body()
        if not target or not isinstance(body.get("messages"), list):
            self.send_json({"error": "bad conversation"}, 400)
            return
        body["id"] = conversation_id
        write_json(target, body)
        self.send_json({"ok": True})

    def update_persona(self, persona_id, change):
        personas, persona = find_persona(persona_id)
        if persona is None:
            self.send_json({"error": "Save the personality before adding material."}, 404)
            return
        change(persona)
        save_personas(clean_personas(personas))
        self.send_json(find_persona(persona_id)[1])

    def read_material_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_MATERIAL_BYTES:
            self.send_json({"error": "Material must be between 1 byte and 25 MB."}, 400)
            return None
        return self.rfile.read(length).decode("utf-8", "replace")

    def inspect_material(self):
        # Preview before adding: line and speaker counts, plus an optional summary written by the model.
        text = self.read_material_body()
        if text is None:
            return
        lines = parse_material(text)
        result = {"bytes": len(text.encode("utf-8")), "lines": len(lines), "speakers": count_speakers(lines)}
        if query_value(self.path, "summary") == "1" and lines:
            result.update(self.summarize(query_value(self.path, "model"), lines))
        self.send_json(result)

    def summarize(self, model, lines):
        try:
            with urllib.request.urlopen(build_summary_request(model, lines), timeout=600) as response:
                result = json.loads(response.read().decode("utf-8"))
            return {"summary": clean_summary(result.get("message", {}).get("content", ""))}
        except (urllib.error.URLError, OSError, ValueError) as error:
            return {"summary": "", "error": "Couldn't summarize: " + str(error)}

    def add_material(self, persona_id):
        text = self.read_material_body()
        if text is None:
            return
        if find_persona(persona_id)[1] is None:
            self.send_json({"error": "Save the personality before adding material."}, 404)
            return
        name = query_value(self.path, "name") or "Pasted text"
        material_id = os.urandom(8).hex()
        os.makedirs(os.path.join(MATERIALS_DIR, persona_id), exist_ok=True)
        with open(material_path(persona_id, material_id), "w", encoding="utf-8") as handle:
            handle.write(text)
        entry = {"id": material_id, "name": name[:120], "bytes": len(text.encode("utf-8")), "lines": len(parse_material(text))}
        self.update_persona(persona_id, lambda persona: (persona.setdefault("materials", []).append(entry), mark_stale(persona)))

    def delete_material(self, persona_id, material_id):
        target = material_path(persona_id, material_id)
        if target and os.path.isfile(target):
            os.remove(target)
        self.update_persona(persona_id, lambda persona: (persona.update(
            materials=[m for m in persona.get("materials") or [] if m.get("id") != material_id]), mark_stale(persona)))

    def send_speakers(self, persona_id):
        persona = find_persona(persona_id)[1]
        self.send_json(count_speakers(material_lines(persona)) if persona else [])

    def train(self, persona_id):
        speakers = [str(s).strip() for s in self.read_body().get("speakers") or [] if str(s).strip()]
        self.update_persona(persona_id, lambda persona: train_persona(persona, speakers))

    def send_title(self):
        try:
            with urllib.request.urlopen(build_title_request(self.read_body()), timeout=120) as response:
                result = json.loads(response.read().decode("utf-8"))
            self.send_json({"title": clean_title(result.get("message", {}).get("content", ""))})
        except (urllib.error.URLError, OSError, ValueError) as error:
            self.send_json({"title": "", "error": str(error)})

    def stream_chat(self):
        request = build_ollama_request(self.read_body())
        worker_pause.claim_gpu(int(load_settings()["pause_workers_minutes"] or 0), json.loads(request.data)["model"])
        try:
            upstream = urllib.request.urlopen(request, timeout=600)
        except urllib.error.HTTPError as error:
            self.send_json({"error": error.read().decode("utf-8", "replace")}, 502)
            return
        except (urllib.error.URLError, OSError) as error:
            self.send_json({"error": "Ollama not reachable: " + str(error)}, 502)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.relay_stream(upstream)

    def relay_stream(self, upstream):
        # Ollama streams one JSON object per line; pass each line straight through.
        # If the browser hits Stop, the write fails and we close the upstream, which stops generation.
        try:
            for line in upstream:
                self.wfile.write(line)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            upstream.close()


def main():
    os.makedirs(CONVERSATION_DIR, exist_ok=True)
    os.makedirs(MATERIALS_DIR, exist_ok=True)
    if not os.path.isfile(SETTINGS_PATH):
        write_json(SETTINGS_PATH, DEFAULT_SETTINGS)
    server = ThreadingHTTPServer((HOST, PORT), LocalChatHandler)
    print("Local Chat running at http://%s:%d  (Ollama: %s)" % (HOST, PORT, OLLAMA_URL))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
