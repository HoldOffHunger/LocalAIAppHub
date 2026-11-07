# ImageGen: a local picture maker on http://127.0.0.1:8730. Ask with words, with pictures, or both:
# "a fox in a lantern-lit library", or drop in a picture and say "make it winter".
# ComfyUI does the drawing with FLUX.2 [klein] 4B; this server starts it headless, queues the jobs and keeps the gallery.
# Standard-library only. Run:  python server.py

import base64
import hashlib
import json
import os
import queue
import random
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import comfy_progress
import gpu_share
import workflows

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
GALLERY_DIR = os.path.join(DATA_DIR, "gallery")
COMFY_INPUT_DIR = os.path.join(DATA_DIR, "comfy-input")  # reference pictures go straight here; Comfy reads them by name
COMFY_OUTPUT_DIR = os.path.join(DATA_DIR, "comfy-output")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
COMFY_PID_PATH = os.path.join(DATA_DIR, "comfy.pid")  # so a restarted ImageGen can still stop the ComfyUI it started
STATIC_DIR = os.path.join(APP_DIR, "static")
PORT = int(os.environ.get("IMAGEGEN_PORT", "8730"))

# The defaults for a fresh copy: a ComfyUI folder in the hub, and the hub's models folder. data\settings.json,
# written on first run (setup.ps1 fills it in when it finds a ComfyUI), is what's actually used.
COMFY_HOME = os.environ.get("COMFY_HOME") or os.path.normpath(os.path.join(APP_DIR, "..", "ComfyUI"))
MODELS = os.environ.get("AI_MODELS") or os.path.join(APP_DIR, "..", "ModelFiles")
DEFAULT_SETTINGS = {
    "comfy_python": os.path.join(COMFY_HOME, ".venv", "Scripts", "python.exe"),  # Comfy Desktop's own environment
    "comfy_main": os.path.join(COMFY_HOME, "main.py"),
    "comfy_port": 8188,
    "models_folder": os.path.normpath(os.path.join(MODELS, "comfyui")),
    "pause_workers_minutes": 5,  # the AI Workers wait this long after the last picture; 0 turns it off
    "free_vram_minutes": 3,  # Comfy lets go of the card this long after the last picture, so Chat gets it back
    "stop_comfy_minutes": 15,  # and stops altogether this long after, giving back its RAM; 0 keeps it running
}
MAX_REFERENCES = 4
# A 9B edit streaming from RAM is slow, but not this slow; a clip on the 1070 Ti can honestly take an hour or more
JOB_PATIENCE_SECONDS = {"image": 20 * 60, "video": 4 * 60 * 60}
MAX_UPLOAD_BYTES = 40 * 1024 * 1024
IMAGE_TYPES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
ID_PATTERN = re.compile(r"^[a-f0-9]{12}$")
# What can be wrong with a picture Ben marks as a defect. It teaches the models nothing; it keeps the gallery clean and,
# over time, says which model fails at what
DEFECT_TAGS = ("hands", "limbs", "face", "text", "anatomy", "other")
FILE_PATTERN = re.compile(r"^[a-f0-9]{12,40}\.(png|jpg|webp|mp4)$")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                 ".js": "application/javascript; charset=utf-8", ".png": "image/png", ".jpg": "image/jpeg", ".mp4": "video/mp4",
                 ".webp": "image/webp", ".svg": "image/svg+xml"}

jobs = {}  # job id -> what the page shows while it waits
job_queue = queue.Queue()
jobs_lock = threading.Lock()
comfy_process = None  # the ComfyUI this server started, if any
jobs_in_hand = 0  # queued or drawing; guarded by card_lock
card_lock = threading.Lock()  # between counting a new job and letting go of the card
yield_requested = threading.Event()  # the GPU desk gave the card to someone else; let go once the jobs in hand are done
last_finished = time.time()  # when the last job ended, for stopping Comfy once things go quiet


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
    stored = read_json(SETTINGS_PATH, None)
    if stored is None:
        write_json(SETTINGS_PATH, DEFAULT_SETTINGS)
        stored = {}
    merged = dict(DEFAULT_SETTINGS)
    merged.update({key: value for key, value in stored.items() if key in DEFAULT_SETTINGS})
    return merged


def comfy_url():
    return "http://127.0.0.1:%d" % load_settings()["comfy_port"]


def comfy_listening():
    try:
        with socket.create_connection(("127.0.0.1", load_settings()["comfy_port"]), timeout=0.4):
            return True
    except OSError:
        return False


def model_path(kind, name):
    return os.path.join(load_settings()["models_folder"], kind, name)


ALL_MODELS = [("image", workflows.MODELS), ("video", workflows.VIDEO_MODELS)]


def missing_models(model_id):
    files = next(models[model_id] for _, models in ALL_MODELS if model_id in models)["files"]
    return [name for kind, name in files.items() if not os.path.isfile(model_path(kind, name))]


card_vram = None  # bytes, asked of the driver once; it doesn't change while the PC is on


def card_memory():
    # The card's VRAM in bytes, from nvidia-smi, so the menu knows it even while ComfyUI is stopped
    global card_vram
    if card_vram is None:
        try:
            output = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                                    capture_output=True, text=True, timeout=10,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
            card_vram = int(output.split()[0]) * 2 ** 20
        except (OSError, ValueError, IndexError, subprocess.SubprocessError):
            return None, None
    return card_vram, None


def model_menu():
    # "Fits" is about the drawing model, which does the slow part. The text encoder takes its turn on the card first and
    # can stream from RAM for a few seconds without much harm. A little room is kept back for the picture being worked on.
    vram, _ = card_memory()
    menu = []
    for made, model_id, model in [(made, key, value) for made, models in ALL_MODELS for key, value in models.items()]:
        files = model["files"]
        # An SDXL checkpoint is one file holding everything; its drawing part is about 5 of its 6.9 GB, so it fits
        drawing = "checkpoints" if "checkpoints" in files else "diffusion_models"
        sizes = [os.path.getsize(model_path(kind, files[kind])) if kind in files and os.path.isfile(model_path(kind, files[kind]))
                 else None for kind in (drawing, "text_encoders")]
        share = 0.75 if drawing == "checkpoints" else 1.0
        fits = None if sizes[0] is None or vram is None else sizes[0] * share < vram * 0.85
        menu.append({"id": model_id, "kind": made, "label": model["label"], "note": model["note"], "missing": missing_models(model_id),
                     "model_gb": round(sizes[0] / 2 ** 30, 1) if sizes[0] else None,
                     "encoder_gb": round(sizes[1] / 2 ** 30, 1) if sizes[1] else None, "fits": fits,
                     "uncensored": bool(model.get("uncensored")), "references": 1 if "sdxl" in model else None})
    return {"models": menu, "default": {"image": workflows.DEFAULT_MODEL, "video": workflows.DEFAULT_VIDEO_MODEL},
            "vram_gb": round(vram / 2 ** 30, 1) if vram else None}


def write_comfy_paths(folder):
    # comfy_models.yaml tells the headless ComfyUI where the models are; it's written from models_folder each start
    quoted = "'" + folder.replace("'", "''") + "'"
    text = ("imagegen:\n  base_path: %s\n  is_default: true\n  diffusion_models: |-\n    diffusion_models/\n"
            "    unet/\n  text_encoders: |-\n    text_encoders/\n    clip/\n  checkpoints: checkpoints/\n"
            "  vae: vae/\n  loras: loras/\n") % quoted
    with open(os.path.join(APP_DIR, "comfy_models.yaml"), "w", encoding="utf-8") as handle:
        handle.write(text)


def start_comfy():
    # Headless, with no window of its own; its log goes to data\comfy.log. One already running on the port is reused,
    # but only one ImageGen started is ever stopped again.
    global comfy_process
    if comfy_listening():
        return ""
    settings = load_settings()
    if not os.path.isfile(settings["comfy_python"]):
        return "can't find ComfyUI's Python at " + settings["comfy_python"]
    command = [settings["comfy_python"], settings["comfy_main"], "--listen", "127.0.0.1",
               "--port", str(settings["comfy_port"]), "--disable-auto-launch", "--preview-method", "none",
               # Pinned memory held 13 GB on top of Comfy's model cache and left the PC paging; 32 GB isn't enough for both
               "--disable-pinned-memory",
               "--extra-model-paths-config", os.path.join(APP_DIR, "comfy_models.yaml"),
               "--output-directory", COMFY_OUTPUT_DIR, "--input-directory", COMFY_INPUT_DIR,
               "--user-directory", os.path.join(DATA_DIR, "comfy-user")]
    write_comfy_paths(settings["models_folder"])
    log = open(os.path.join(DATA_DIR, "comfy.log"), "w", encoding="utf-8")
    comfy_process = subprocess.Popen(command, cwd=APP_DIR, stdout=log, stderr=subprocess.STDOUT,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    with open(COMFY_PID_PATH, "w", encoding="utf-8") as handle:
        handle.write(str(comfy_process.pid))
    for _ in range(180):
        if comfy_listening():
            return ""
        time.sleep(1)
    return "ComfyUI didn't answer within three minutes; see data\\comfy.log"


def comfy_call(path, value=None):
    data = json.dumps(value).encode("utf-8") if value is not None else None
    request = urllib.request.Request(comfy_url() + path, data=data, method="POST" if data else "GET",
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def comfy_error_text(error):
    # A refused graph comes back as 400 with the reason per node
    try:
        detail = json.load(error)
        node_errors = [message.get("message", "") for node in detail.get("node_errors", {}).values()
                       for message in node.get("errors", [])]
        return "; ".join([detail.get("error", {}).get("message", "")] + node_errors).strip("; ")
    except (ValueError, AttributeError):
        return str(error)


def save_reference(data_url):
    # "data:image/png;base64,..." -> a file in Comfy's input folder, named by its content so repeats cost nothing
    match = re.match(r"^data:(image/[a-z]+);base64,(.+)$", data_url or "", re.S)
    if not match or match.group(1) not in IMAGE_TYPES:
        raise ValueError("pictures must be PNG, JPEG or WebP")
    content = base64.b64decode(match.group(2))
    name = hashlib.sha1(content).hexdigest() + IMAGE_TYPES[match.group(1)]
    path = os.path.join(COMFY_INPUT_DIR, name)
    if not os.path.isfile(path):
        with open(path, "wb") as handle:
            handle.write(content)
    return name


def update_job(job_id, **changes):
    with jobs_lock:
        jobs[job_id].update(changes)


def comfy_pid_alive(pid):
    # Windows reuses process numbers, so it only counts if it's still a Python
    try:
        listing = subprocess.run(["tasklist", "/FI", "PID eq %d" % pid, "/FO", "CSV", "/NH"], capture_output=True,
                                 text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return listing.lower().startswith('"python')


def adopt_comfy():
    # A ComfyUI this server started before its window was closed is still ours to stop
    global comfy_process
    try:
        with open(COMFY_PID_PATH, encoding="utf-8") as handle:
            pid = int(handle.read().strip())
    except (OSError, ValueError):
        return
    if comfy_listening() and comfy_pid_alive(pid):
        comfy_process = pid


def stop_comfy():
    # Ends ComfyUI outright, which is the only way to get all its RAM back; the next picture starts it again
    global comfy_process
    process, comfy_process = comfy_process, None
    if isinstance(process, int):
        if comfy_pid_alive(process):
            os.kill(process, signal.SIGTERM)  # on Windows this ends the process straight away
    elif process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=20)
        except subprocess.TimeoutExpired:
            process.kill()
    try:
        os.remove(COMFY_PID_PATH)
    except OSError:
        pass


def idle_watch():
    # A quiet while after the last picture: first Comfy lets go of the card, so Chat gets it back quickly;
    # a longer while after that, ImageGen stops Comfy altogether
    freed = True
    while True:
        time.sleep(20)
        settings = load_settings()
        if jobs_in_hand:
            freed = False
            continue
        quiet = (time.time() - last_finished) / 60
        stop_after = float(settings["stop_comfy_minutes"] or 0)
        if comfy_process and stop_after and quiet >= stop_after:
            stop_comfy()
            print("Stopped ComfyUI after %d quiet minutes; the next picture starts it again." % stop_after, flush=True)
        elif not freed and comfy_listening() and quiet >= float(settings["free_vram_minutes"] or 0):
            let_go()
            freed = True


def let_go():
    # Comfy gives the card back and ImageGen hands in its lease at the desk. Never while a job is in hand: then it
    # happens as that job finishes. The lock keeps a late let-go from handing back a lease a new job has just taken.
    with card_lock:
        if jobs_in_hand:
            yield_requested.set()
            return
        yield_requested.clear()
        if comfy_listening():
            gpu_share.free_comfy(comfy_url())
        gpu_share.release_card()


def run_job(job_id, request):
    settings = load_settings()
    update_job(job_id, state="working", message="Making room on the card")
    lease_minutes = max(1, int(settings["pause_workers_minutes"] or 0))
    # A background picture comes from an AI Worker whose turn already holds the card at the desk. Claiming it as Images
    # would have the desk hold the Foreman, stopping the very worker that asked
    if not request.get("background"):
        gpu_share.claim_card(lease_minutes)
    yield_requested.clear()  # this job has the card now; only a later request to let go counts
    if not comfy_listening():
        update_job(job_id, message="Waking ComfyUI")
        problem = start_comfy()
        if problem:
            raise RuntimeError(problem)
    if request["kind"] == "video":
        graph = workflows.wan_video(request["model"], request["prompt"], request["seed"], request["size"],
                                    request["seconds"], (request["references"] or [None])[0])
    else:
        graph = workflows.image(request["model"], request["prompt"], request["seed"], request["width"],
                                      request["height"], request["references"])
    patience = JOB_PATIENCE_SECONDS[request["kind"]]
    started = time.time()
    try:
        prompt_id = comfy_call("/prompt", {"prompt": graph, "client_id": comfy_progress.CLIENT_ID})["prompt_id"]
    except urllib.error.HTTPError as error:
        raise RuntimeError("ComfyUI refused the job: " + comfy_error_text(error))
    update_job(job_id, message="Drawing", started=started)
    renewed = time.time()
    while True:
        time.sleep(0.5)
        update_job(job_id, percent=round(100 * (comfy_progress.fraction(prompt_id) or 0)))
        if time.time() - renewed > 60 and not request.get("background"):
            gpu_share.renew_card(lease_minutes)  # a long clip keeps the workers out without taking the card back
            renewed = time.time()
        if time.time() - started > patience:
            raise RuntimeError("ComfyUI has been at this for %d minutes; see data\\comfy.log" % (patience // 60))
        try:
            entry = comfy_call("/history/" + prompt_id).get(prompt_id)
        except (urllib.error.URLError, OSError):
            continue  # Comfy can be too busy to answer while it decodes; keep waiting
        if not entry:
            continue
        status = entry.get("status", {})
        if status.get("status_str") == "error":
            messages = [item[1].get("exception_message", "") for item in status.get("messages", [])
                        if item[0] == "execution_error"]
            raise RuntimeError("ComfyUI stopped: " + ("; ".join(messages) or "see data\\comfy.log"))
        images = entry.get("outputs", {}).get("save", {}).get("images", [])
        if status.get("completed") and images:
            break
    comfy_progress.forget(prompt_id)
    picture = images[0]
    picture_id = uuid.uuid4().hex[:12]
    file_name = picture_id + os.path.splitext(picture["filename"])[1]  # .png, or .mp4 for a clip
    shutil.move(os.path.join(COMFY_OUTPUT_DIR, picture.get("subfolder", ""), picture["filename"]),
                os.path.join(GALLERY_DIR, file_name))
    entry = {"id": picture_id, "kind": request["kind"], "file": file_name, "prompt": request["prompt"],
             "seed": request["seed"], "model": request["model"], "references": request["references"],
             "seconds": round(time.time() - started, 1), "created": time.strftime("%Y-%m-%d %H:%M:%S")}
    if request.get("fixes"):
        entry["fixes"] = request["fixes"]  # the defect this picture was made to repair
    if request.get("source"):
        entry["source"] = request["source"]  # who asked, when it wasn't Ben: an AI Worker's task and item
    if request["kind"] == "video":
        entry.update(size=request["size"], length=request["seconds"])
    elif not request["references"]:
        entry.update(width=request["width"], height=request["height"])
    write_json(os.path.join(GALLERY_DIR, picture_id + ".json"), entry)
    update_job(job_id, state="done", message="", picture=picture_id)


def job_worker():
    # One picture at a time: the card can't hold two
    global last_finished, jobs_in_hand
    while True:
        job_id, request = job_queue.get()
        try:
            run_job(job_id, request)
        except Exception as error:  # the page shows whatever went wrong; the worker carries on
            update_job(job_id, state="failed", message=str(error))
        last_finished = time.time()
        with card_lock:
            jobs_in_hand -= 1
        if yield_requested.is_set():
            let_go()  # someone took the card while this was drawing; it's theirs now, once the queue is empty


def parse_request(body):
    prompt = str(body.get("prompt", "")).strip()
    if not prompt:
        raise ValueError("say what you'd like, even for an edit")
    kind = body.get("kind") or "image"
    models = dict(ALL_MODELS).get(kind)
    if models is None:
        raise ValueError("make an image or a video")
    model_id = body.get("model") or (workflows.DEFAULT_MODEL if kind == "image" else workflows.DEFAULT_VIDEO_MODEL)
    if model_id not in models:
        raise ValueError("there's no %s model called %s" % (kind, model_id))
    images = body.get("images") or []
    if "sdxl" in models[model_id] and len(images) > 1:
        raise ValueError("%s works from words, or from one picture" % models[model_id]["label"])
    if len(images) > (MAX_REFERENCES if kind == "image" else 1):
        raise ValueError("up to %d pictures at a time" % MAX_REFERENCES if kind == "image"
                         else "a clip starts from one picture")
    seed = body.get("seed")
    seed = int(seed) if str(seed or "").strip().isdigit() else random.randint(0, 2 ** 48)
    fixes = body.get("fixes") if ID_PATTERN.match(str(body.get("fixes") or "")) else ""
    background = body.get("background") is True  # from an AI Worker: rides on its lease, claims nothing at the desk
    source = str(body.get("source") or "")[:80]
    if kind == "video":
        size = body.get("size") if body.get("size") in workflows.VIDEO_SIZES else "small"
        seconds = max(1.0, min(5.0, float(body.get("seconds") or 2)))
        return {"kind": kind, "prompt": prompt, "model": model_id, "seed": seed, "size": size, "seconds": seconds,
                "references": [save_reference(image) for image in images], "fixes": fixes, "background": background,
                "source": source}
    # Klein works in 16-pixel steps; keep sizes sane for 8 GB
    width = max(256, min(1536, int(body.get("width") or 1024) // 16 * 16))
    height = max(256, min(1536, int(body.get("height") or 1024) // 16 * 16))
    return {"kind": kind, "prompt": prompt, "model": model_id, "seed": seed, "width": width, "height": height,
            "references": [save_reference(image) for image in images], "fixes": fixes, "background": background,
            "source": source}


def gallery():
    entries = [read_json(os.path.join(GALLERY_DIR, name), None) for name in os.listdir(GALLERY_DIR)
               if name.endswith(".json")]
    return sorted([entry for entry in entries if entry], key=lambda entry: entry["created"], reverse=True)


class ImageGenHandler(BaseHTTPRequestHandler):
    server_version = "ImageGen/1.0"

    def log_message(self, format_string, *args):
        pass

    def send_json(self, value, status=200):
        encoded = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def send_file(self, base, relative_path, cache=False):
        safe_path = os.path.normpath(os.path.join(base, relative_path))
        if not safe_path.startswith(base + os.sep) or not os.path.isfile(safe_path):
            self.send_json({"error": "not found"}, 404)
            return
        with open(safe_path, "rb") as handle:
            content = handle.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(os.path.splitext(safe_path)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "max-age=31536000" if cache else "no-cache")  # pictures never change
        self.end_headers()
        self.wfile.write(content)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_UPLOAD_BYTES:
            raise ValueError("that's too big; keep it under 40 MB all told")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/":
            self.send_file(STATIC_DIR, "index.html")
        elif path.startswith("/static/"):
            self.send_file(STATIC_DIR, path[len("/static/"):])
        elif path == "/api/status":
            with jobs_lock:
                waiting = sum(1 for job in jobs.values() if job["state"] in ("queued", "working"))
            self.send_json({"comfy": comfy_listening(), "waiting": waiting,
                            "missing_models": missing_models(workflows.DEFAULT_MODEL)})
        elif path == "/api/models":
            self.send_json(model_menu())
        elif path == "/api/gallery":
            self.send_json(gallery())
        elif path.startswith("/api/jobs/"):
            with jobs_lock:
                job = dict(jobs.get(path[len("/api/jobs/"):], {}))
            if "started" in job:
                job["elapsed"] = round(time.time() - job.pop("started"), 1)
            self.send_json(job if job else {"error": "not found"}, 200 if job else 404)
        elif path.startswith("/pictures/") and FILE_PATTERN.match(path[len("/pictures/"):]):
            self.send_file(GALLERY_DIR, path[len("/pictures/"):], cache=True)
        elif path.startswith("/references/") and FILE_PATTERN.match(path[len("/references/"):]):
            self.send_file(COMFY_INPUT_DIR, path[len("/references/"):], cache=True)
        else:
            self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/api/gpu/yield":
            # The GPU desk gave the card to someone else: let go now, or straight after the pictures in hand
            threading.Thread(target=let_go, daemon=True).start()
            self.send_json({"ok": True})
            return
        if self.path.startswith("/api/gallery/") and self.path.endswith("/defect"):
            self.mark_defect(self.path[len("/api/gallery/"):-len("/defect")])
            return
        if self.path != "/api/generate":
            self.send_json({"error": "not found"}, 404)
            return
        try:
            request = parse_request(self.read_body())
        except (ValueError, TypeError) as error:
            self.send_json({"error": str(error)}, 400)
            return
        missing = missing_models(request["model"])
        if missing:
            self.send_json({"error": "still missing: " + ", ".join(missing)}, 409)
            return
        global jobs_in_hand
        job_id = uuid.uuid4().hex[:12]
        with jobs_lock:
            jobs[job_id] = {"state": "queued", "message": "Waiting its turn", "seed": request["seed"], "percent": 0}
        with card_lock:
            jobs_in_hand += 1  # counted before it's queued, so a let-go already under way waits or steps back
        job_queue.put((job_id, request))
        self.send_json({"job": job_id, "seed": request["seed"]})

    def mark_defect(self, picture_id):
        # {"tags": [...], "note": "..."} marks it; {"defect": null} puts it back in the gallery. The files stay where they are.
        path = os.path.join(GALLERY_DIR, picture_id + ".json")
        entry = read_json(path, None) if ID_PATTERN.match(picture_id) else None
        if not entry:
            self.send_json({"error": "not found"}, 404)
            return
        try:
            body = self.read_body()
        except ValueError:
            self.send_json({"error": "send JSON"}, 400)
            return
        if body.get("defect", True) is None:
            entry.pop("defect", None)
        else:
            tags = [tag for tag in body.get("tags") or [] if tag in DEFECT_TAGS]
            if not tags:
                self.send_json({"error": "say what's wrong with it: " + ", ".join(DEFECT_TAGS)}, 400)
                return
            entry["defect"] = {"tags": tags, "note": str(body.get("note") or "").strip()[:300],
                               "marked": time.strftime("%Y-%m-%d %H:%M:%S")}
        write_json(path, entry)
        self.send_json(entry)

    def do_DELETE(self):
        picture_id = self.path[len("/api/gallery/"):] if self.path.startswith("/api/gallery/") else ""
        if not ID_PATTERN.match(picture_id):
            self.send_json({"error": "not found"}, 404)
            return
        for extension in (".png", ".mp4", ".json"):
            try:
                os.remove(os.path.join(GALLERY_DIR, picture_id + extension))
            except OSError:
                pass
        self.send_json({"ok": True})


def main():
    for folder in (GALLERY_DIR, COMFY_INPUT_DIR, COMFY_OUTPUT_DIR):
        os.makedirs(folder, exist_ok=True)
    load_settings()
    threading.Thread(target=job_worker, daemon=True).start()
    comfy_progress.start(load_settings()["comfy_port"])
    # ComfyUI starts with the first picture, not before, and stops again once things go quiet
    adopt_comfy()
    threading.Thread(target=idle_watch, daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), ImageGenHandler)
    link = "http://127.0.0.1:%d/" % PORT
    print("ImageGen running at " + link, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        stop_comfy()
        print("\nStopped, and ComfyUI with it.")


if __name__ == "__main__":
    main()
