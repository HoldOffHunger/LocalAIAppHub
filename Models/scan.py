# Finding the models: everything under E:\AIModels, read the way each tool lays out its folder, plus the stragglers
# a drive sweep turned up elsewhere. Every model becomes one entry for the page. Nothing here writes to a model folder.
# Standard library only.

import hashlib
import json
import os
import re
import string
import urllib.request
from pathlib import Path

import file_meta
import known

# The hub's models folder (a junction to the real one, if it lives elsewhere), resolved so the sweep knows it
MODELS_ROOT = Path(os.environ.get("AI_MODELS") or Path(__file__).resolve().parent.parent / "ModelFiles").resolve()
# Where Ben builds his own models (the Autonoma fine-tunes): a home too, so nothing in it counts as a straggler
WORKSHOP = Path(os.environ.get("MODEL_WORKSHOP", r"E:\ModelWorkshop"))
HOMES = [MODELS_ROOT, WORKSHOP]
OLLAMA_ROOT = Path(os.environ.get("OLLAMA_MODELS", str(MODELS_ROOT / "ollama" / "models")))
OLLAMA_API = "http://127.0.0.1:11434/api/tags"
MODEL_EXTENSIONS = {".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".onnx", ".ggml", ".bin", ".tflite", ".h5", ".sft"}
SMALLEST_MODEL = 20 * 1024 * 1024  # anything smaller under AIModels is a config, tokenizer or vocabulary file
# Where models gather when a tool downloads them itself; checked on every scan, they're quick
USUAL_HIDEOUTS = [Path.home() / ".cache" / "huggingface" / "hub", Path.home() / ".cache" / "torch",
                  Path.home() / ".u2net", Path.home() / ".ollama" / "models", Path.home() / ".cache" / "whisper"]
# The full drive sweep skips these folders by name
SWEEP_SKIP = {"windows", "$recycle.bin", "system volume information", "node_modules", ".git", "__pycache__",
              "windowsapps", "$windows.~bt", "$windows.~ws", "msocache", "recovery"}
SWEEP_SMALLEST = 40 * 1024 * 1024
QUANT_NAME = re.compile(r"(?<![a-z])(i?q\d(_[a-z0-9]+)*|f16|bf16|f32|fp8|fp16)(?![a-z0-9])", re.I)


def folder_size(folder):
    total = 0
    for base, _, names in os.walk(folder):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(base, name))
            except OSError:
                pass
    return total


def entry(name, source, path, size, details=None, hint="", **extra):
    # One model, filled in from the known families, then from whatever the caller read from the file; the hint is the
    # tool's folder name ("whisper") when the model's own name ("small.en") doesn't say what it is
    found = known.lookup(name, Path(str(path)).name, hint)
    model = {"name": name, "source": source, "path": str(path), "size": size, "kind": found.get("kind", "other"),
             "creator": found.get("creator", ""), "base": found.get("base", ""), "about": found.get("about", ""),
             "params": "", "quant": "", "format": "", "license": "", "context": 0, "capabilities": [], "files": [],
             "shared": [], "straggler": False, "notes": ""}
    model.update({key: value for key, value in (details or {}).items() if value})
    model.update(extra)
    model["drive"] = str(path)[:2].upper()
    return model


def gguf_details(meta):
    # What a GGUF header adds: its own name, maker, size label, quantisation, licence and context length
    context = next((value for key, value in meta.items() if key.endswith(".context_length")), 0)
    organisation = meta.get("general.organization") or meta.get("general.author") or ""
    base = meta.get("general.base_model.0.name", "")
    if base and meta.get("general.base_model.0.organization"):
        base = "%s (%s)" % (base, meta["general.base_model.0.organization"])
    return {"title": meta.get("general.name", ""), "header_creator": organisation, "params": meta.get("general.size_label", ""),
            "quant": meta.get("general.file_type", ""), "license": meta.get("general.license", ""),
            "context": context if isinstance(context, int) else 0, "header_base": base,
            "arch": meta.get("general.architecture", "")}


def ollama_capabilities():
    # Ollama knows which models see images, use tools or only embed; it's asked if it's running, and skipped if not
    try:
        with urllib.request.urlopen(OLLAMA_API, timeout=2) as response:
            listing = json.load(response)
    except (OSError, ValueError):
        return {}
    return {model["name"]: model.get("capabilities") or [] for model in listing.get("models", [])}


def scan_ollama(root=OLLAMA_ROOT, location_note=""):
    manifests, blobs = root / "manifests", root / "blobs"
    if not manifests.is_dir():
        return []
    capabilities = ollama_capabilities()
    models, owners = [], {}
    for manifest in sorted(manifests.rglob("*")):
        if not manifest.is_file():
            continue
        parts = manifest.relative_to(manifests).parts  # host, namespace, model, tag
        if len(parts) != 4:
            continue
        host, namespace, model_name, tag = parts
        name = "%s:%s" % (model_name, tag) if host == "registry.ollama.ai" and namespace == "library" \
            else "%s/%s/%s:%s" % (host, namespace, model_name, tag)
        try:
            manifest_json = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        layers = manifest_json.get("layers", [])
        size = sum(layer.get("size", 0) for layer in layers)
        files, details, has_projector = [], {}, False
        for layer in layers:
            blob = blobs / layer.get("digest", "").replace(":", "-")
            kind = layer.get("mediaType", "").rsplit(".", 1)[-1]
            if kind in ("model", "projector", "adapter", "draft"):
                files.append({"path": str(blob), "size": layer.get("size", 0), "role": kind, "from": layer.get("from", "")})
                owners.setdefault(str(blob), []).append(name)
            if kind == "projector":
                has_projector = True
            if kind == "model" and not details:
                details = gguf_details(file_meta.gguf(blob))
        config = {}
        try:
            config = json.loads((blobs / manifest_json["config"]["digest"].replace(":", "-")).read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            pass
        if not re.search(r"\d", details.get("params", "")):
            details["params"] = config.get("model_type", "") or details.get("params", "")
        if not details.get("quant") and QUANT_NAME.search(tag):
            details["quant"] = QUANT_NAME.search(tag).group(0).upper()
        if not details.get("quant") and config.get("file_type", "unknown") != "unknown":
            details["quant"] = config["file_type"]
        model = entry(name, "Ollama", manifest, size, None, format="GGUF", files=files, notes=location_note)
        apply_header(model, details)
        if host == "hf.co":
            model["packaged_by"] = namespace
            if not model["creator"]:
                model["creator"] = details.get("header_creator") or namespace
        caps = capabilities.get(name, [])
        model["capabilities"] = caps
        if "embedding" in caps and "completion" not in caps:
            model["kind"] = "embedding"
        elif ("vision" in caps or has_projector) and model["kind"] in ("chat", "other"):
            model["kind"] = "vision"
        elif model["kind"] == "other":
            model["kind"] = "chat"
        models.append(model)
    # Ollama stores each weight file once; models built on the same weights share it, so say so
    for model in models:
        for file in model["files"]:
            others = [owner for owner in owners.get(file["path"], []) if owner != model["name"]]
            if others:
                model["shared"].append({"size": file["size"], "with": others})
    return models


def apply_header(model, details):
    # The header fills only what the known families left blank; it's the file's own word, so it wins on licence and size
    model["title"] = details.get("title", "")
    for key in ("params", "quant", "license", "context"):
        if details.get(key):
            model[key] = details[key]
    if not model["creator"] and details.get("header_creator"):
        model["creator"] = details["header_creator"]
    if not model["base"] and details.get("header_base"):
        model["base"] = details["header_base"]
    if details.get("arch"):
        model["arch"] = details["arch"]


def scan_lmstudio(root=MODELS_ROOT / "lmstudio" / "models"):
    models = []
    if not root.is_dir():
        return models
    for gguf in sorted(root.rglob("*.gguf")):
        if gguf.name.lower().startswith("mmproj"):
            continue  # a vision projector, counted with the model beside it
        parts = gguf.relative_to(root).parts
        publisher = parts[0] if len(parts) > 2 else ""
        projectors = [p for p in gguf.parent.glob("mmproj*.gguf")]
        files = [{"path": str(gguf), "size": gguf.stat().st_size, "role": "model"}] + \
                [{"path": str(p), "size": p.stat().st_size, "role": "projector"} for p in projectors]
        model = entry(gguf.stem, "LM Studio", gguf, sum(f["size"] for f in files), format="GGUF", files=files)
        apply_header(model, gguf_details(file_meta.gguf(gguf)))
        if not model["quant"] and QUANT_NAME.search(gguf.stem):
            model["quant"] = QUANT_NAME.search(gguf.stem).group(0).upper()
        if publisher:
            model["packaged_by"] = publisher
        if projectors and model["kind"] in ("chat", "other"):
            model["kind"] = "vision"
        elif model["kind"] == "other":
            model["kind"] = "chat"
        models.append(model)
    return models


def safetensors_details(path):
    meta = file_meta.safetensors(path) if path.suffix.lower() in (".safetensors", ".sft") else {}
    details = {"title": meta.get("modelspec.title", ""), "license": meta.get("modelspec.license", ""),
               "header_creator": meta.get("modelspec.author", ""), "arch": meta.get("modelspec.architecture", ""),
               "quant": meta.get("_dtype", "")}
    if meta.get("modelspec.description"):
        details["description"] = meta["modelspec.description"]
    return details


def scan_comfyui(root=MODELS_ROOT / "comfyui"):
    models = []
    if not root.is_dir():
        return models
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in MODEL_EXTENSIONS or path.stat().st_size < 1024 * 1024:
            continue
        folder = path.relative_to(root).parts[0]
        model = entry(path.stem, "ComfyUI", path, path.stat().st_size, format=path.suffix[1:].lower(),
                      files=[{"path": str(path), "size": path.stat().st_size, "role": folder}], comfy_folder=folder)
        details = safetensors_details(path)
        apply_header(model, details)
        if details.get("description") and not model["about"]:
            model["about"] = details["description"]
        if model["kind"] == "other":
            model["kind"] = known.COMFY_FOLDER_KINDS.get(folder, "other")
        models.append(model)
    return models


def folder_model(folder, source, name=None, **extra):
    files = [{"path": str(p), "size": p.stat().st_size, "role": "weights"} for p in sorted(folder.rglob("*"))
             if p.is_file() and p.suffix.lower() in MODEL_EXTENSIONS | {".bin"} and p.stat().st_size >= SMALLEST_MODEL // 20
             and ".cache" not in p.parts]
    model = entry(name or folder.name, source, folder, folder_size(folder), files=files, **extra)
    model["format"] = ", ".join(sorted({Path(f["path"]).suffix[1:] for f in files}))
    return model


def scan_simple_folders(root=MODELS_ROOT):
    # Kokoro, Whisper, Opus-MT, rembg, and anything new: one model per subfolder (or per big loose file)
    models = []
    handled = {"ollama", "lmstudio", "comfyui"}
    if not root.is_dir():
        return models
    for tool in sorted(root.iterdir()):
        if not tool.is_dir() or tool.name.lower() in handled:
            continue
        source = {"kokoro": "Kokoro", "whisper": "Whisper", "opus-mt": "Opus-MT", "rembg": "rembg"}.get(tool.name.lower(), tool.name)
        if tool.name.lower() == "kokoro":
            models.append(folder_model(tool, source, "Kokoro v1.0", params="82M"))
            continue
        inner = tool / "models" if (tool / "models").is_dir() else tool
        for item in sorted(inner.iterdir()):
            if item.is_dir():
                extra = {}
                if tool.name.lower() == "opus-mt":
                    extra["about"] = "Opus-MT translation: %s." % known.translation_pair(item.name)
                elif tool.name.lower() == "whisper":
                    extra["params"] = {"tiny": "39M", "base": "74M", "small": "244M", "medium": "769M"}.get(item.name.split(".")[0], "")
                model = folder_model(item, source, item.name, hint=tool.name, **extra)
                if model["files"] or model["size"] >= SMALLEST_MODEL:
                    models.append(model)
            elif item.suffix.lower() in MODEL_EXTENSIONS and item.stat().st_size >= SMALLEST_MODEL:
                models.append(entry(item.stem, source, item, item.stat().st_size, format=item.suffix[1:].lower(),
                                    files=[{"path": str(item), "size": item.stat().st_size, "role": "weights"}]))
    return models


def is_inside(path, folder):
    try:
        Path(path).resolve().relative_to(Path(folder).resolve())
        return True
    except (ValueError, OSError):
        return False


def in_a_home(path):
    return any(is_inside(path, home) for home in HOMES)


def straggler_entries(found, source="Elsewhere", outside=True):
    # Files found outside the homes (or, for the workshop, inside it): grouped by folder when the folder is one model (a config.json beside the weights,
    # or a Hugging Face cache folder), otherwise one entry a file
    groups = {}
    for item in found:
        path = Path(item["path"])
        if outside and in_a_home(path):
            continue
        hub = next((parent for parent in path.parents if parent.name.startswith("models--")), None)
        if hub:
            key = hub
        elif (path.parent / "config.json").is_file() or "-of-" in path.name:
            key = path.parent
        else:
            key = path
        groups.setdefault(key, []).append(item)
    models = []
    for key, items in sorted(groups.items(), key=lambda pair: str(pair[0]).lower()):
        name = key.name
        creator = ""
        if name.startswith("models--"):
            pieces = name.split("--")
            creator, name = (pieces[1], "/".join(pieces[1:])) if len(pieces) > 2 else ("", name)
        files = [{"path": item["path"], "size": item["size"], "role": "weights"} for item in items]
        size = folder_size(key) if key.is_dir() else sum(f["size"] for f in files)
        name = Path(name).stem if key.is_file() else name
        if name.lower() in ("weights", "model", "models", "checkpoint", "final", "merged", "output"):
            name = "%s/%s" % (key.parent.name, name)  # "weights" alone says nothing; its folder says whose
        # The folders above say what it is when the file name doesn't ("free1-f16" under autonoma-mistral7b-free1)
        model = entry(name, source, key, size, hint=" ".join(part for part in key.parent.parts[-2:]), files=files, straggler=outside,
                      format=", ".join(sorted({Path(f["path"]).suffix[1:].lower() for f in files})))
        if creator and not model["creator"]:
            model["creator"] = creator
        first = Path(files[0]["path"])
        if first.suffix.lower() == ".gguf":
            apply_header(model, gguf_details(file_meta.gguf(first)))
        elif first.suffix.lower() in (".safetensors", ".sft"):
            apply_header(model, safetensors_details(first))
        if not model["quant"] and QUANT_NAME.search(first.stem):
            model["quant"] = QUANT_NAME.search(first.stem).group(0).upper()
        models.append(model)
    return models


def walk_for_models(top, smallest, skip_roots=(), progress=None):
    # os.scandir, never following junctions or links, so C:\Users\<you>\.lmstudio\models isn't counted twice
    found, stack = [], [top]
    while stack:
        folder = stack.pop()
        if progress:
            progress(folder)
        try:
            with os.scandir(folder) as entries:
                for item in entries:
                    try:
                        if item.is_symlink() or item.is_junction():
                            continue
                        if item.is_dir(follow_symlinks=False):
                            if item.name.lower() in SWEEP_SKIP or any(is_inside(item.path, root) for root in skip_roots):
                                continue
                            stack.append(item.path)
                        elif os.path.splitext(item.name)[1].lower() in MODEL_EXTENSIONS:
                            size = item.stat(follow_symlinks=False).st_size
                            if size >= smallest and looks_like_weights(item.name):
                                found.append({"path": item.path, "size": size})
                    except OSError:
                        continue
        except OSError:
            continue
    return found


def looks_like_weights(file_name):
    # .bin is everyone's extension; only the Hugging Face weight names count
    lower = file_name.lower()
    if lower.endswith(".bin"):
        return lower.startswith(("pytorch_model", "model", "diffusion_pytorch_model", "ggml-", "voices"))
    return True


def drives():
    return ["%s:\\" % letter for letter in string.ascii_uppercase if os.path.isdir("%s:\\" % letter)]


def hideouts():
    found = []
    for place in USUAL_HIDEOUTS:
        if place.is_dir() and not in_a_home(place):
            found.extend(walk_for_models(str(place), SMALLEST_MODEL))
    return found


HASHES_PATH = Path(__file__).resolve().parent / "data" / "hashes.json"


def file_hash(path):
    # SHA-256, kept in data/hashes.json by path, size and modified time, so a 4 GB file is read once, not every scan
    try:
        cache = json.loads(HASHES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    try:
        stat = os.stat(path)
    except OSError:
        return ""
    key = "%s|%d|%d" % (os.path.normcase(path), stat.st_size, int(stat.st_mtime))
    if key not in cache:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
                digest.update(block)
        cache[key] = digest.hexdigest()
        HASHES_PATH.parent.mkdir(exist_ok=True)
        HASHES_PATH.write_text(json.dumps(cache, indent=1), encoding="utf-8")
    return cache[key]


def params_value(label):
    # "7.2B" -> 7.2, "137M" -> 0.137, "30B-A3B" -> 30, in billions, for sorting
    match = re.match(r"\s*(\d+(?:\.\d+)?)\s*([BMK])", label or "", re.I)
    if not match:
        return 0
    return float(match.group(1)) * {"b": 1, "m": 1e-3, "k": 1e-6}[match.group(2).lower()]


def catalogue(sweep_found=()):
    models = scan_ollama() + scan_lmstudio() + scan_comfyui() + scan_simple_folders()
    if WORKSHOP.is_dir():
        models += straggler_entries(walk_for_models(str(WORKSHOP), SMALLEST_MODEL), "Workshop", outside=False)
    seen = {os.path.normcase(f["path"]) for model in models for f in model["files"]}
    loose = [item for item in list(sweep_found) + hideouts() if os.path.normcase(item["path"]) not in seen]
    unique = {os.path.normcase(item["path"]): item for item in loose}
    models += straggler_entries(unique.values())
    # Ollama copies a GGUF into its own blobs when it imports one, so the workshop's quantised files often have a twin
    # there. Ollama names each blob by its SHA-256, so a file whose size matches a blob is hashed to be sure: every
    # Q4_K_M of one architecture is the same size to the byte, so size alone would pair the wrong builds
    ollama_blobs = {}
    for model in models:
        if model["source"] == "Ollama":
            for file in model["files"]:
                ollama_blobs.setdefault(file["size"], {}).setdefault(Path(file["path"]).name, []).append(model["name"])
    for model in models:
        if model["source"] != "Ollama" and len(model["files"]) == 1 and model["files"][0]["size"] in ollama_blobs:
            digest = "sha256-" + file_hash(model["files"][0]["path"])
            model["twin"] = sorted(set(ollama_blobs[model["files"][0]["size"]].get(digest, [])))
    for model in models:
        model.setdefault("twin", [])
        model.setdefault("title", "")
        model.setdefault("arch", "")
        model.setdefault("packaged_by", "")
        model["params_value"] = params_value(model["params"])
    return models
