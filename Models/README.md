# Models

Every AI model on this machine, on http://127.0.0.1:8800, and the 🧠 Models entry in the App Hub. Standard-library Python, like the hub. It only reads model folders; it never moves or deletes anything.

## What it shows

- **Grouped by kind:** chat, code, vision chat, embedding, image generation, video generation, image tools, speech to text, text to speech, translation, and the parts other models need (text encoders, VAEs). Click a heading to hide or show that section (remembered in the browser); **Hide all** folds them all.
- **For each model:** who made it and what it's built on, size class (7B, 24B…), precision (Q4_K_M, fp8…), where it lives, and its size on disk. Click a model for its licence, context length, abilities, every file with its path, and a **Show in Explorer** button.
- **Shared weights:** Ollama keeps each weight file once, so `cydonia:latest` and `hf.co/TheDrummer/Cydonia-24B-v2-GGUF` are one 14 GB file. Both are marked "shares", and the disk total counts it once.
- **Two homes:** `E:\AIModels`, and `E:\ModelWorkshop`, where the Autonoma fine-tunes are built (listed as "Workshop").
- **Also in Ollama:** Ollama copies a GGUF into its own folder when it imports one. A workshop file that's the same file, byte for byte, as an Ollama model's is marked "also in Ollama". Size alone can't tell (every Q4_K_M of Mistral 7B is the same size), so a file whose size matches is hashed once and the hash kept in `data\hashes.json`.
- **Stragglers:** models outside both homes, marked in amber. The Hugging Face and torch caches are checked on every scan; **Sweep the drives** looks through every folder on every drive (several minutes on E:) and keeps the result in `data\sweep.json` until the next sweep.

## Where the details come from

1. The file itself: GGUF headers (Ollama, LM Studio) and safetensors headers (ComfyUI) often carry the name, maker, size and licence. Only the header is read, so even FLUX's 24 GB loads in a blink.
2. Ollama, if it's running, for which models see images or only embed.
3. `known.py`, a hand-kept list of families: who made them, what kind they are, one line about each. When a new family arrives and shows up as "Not identified", add a line there.

## How it reads `E:\AIModels`

| Folder | Read as |
|---|---|
| `ollama\models` | One model per manifest, sized by its layers. |
| `lmstudio\models` | One model per `.gguf`; an `mmproj` beside it is its vision part. |
| `comfyui` | One model per weight file; ComfyUI's folder says what it is if the name doesn't. |
| anything else | One model per subfolder (Opus-MT, Whisper, rembg), or per big loose file. Kokoro is one model. |

## Files

| Path | What it is |
|---|---|
| `models.py` | The server, and the drive sweep. |
| `scan.py` | Finding the models and building each entry. |
| `file_meta.py` | Reading GGUF and safetensors headers. |
| `known.py` | The kinds, and what we know about each family. |
| `web\index.html` | The page. |
| `data\sweep.json` | The last drive sweep. Not in git. |
| `data\hashes.json` | SHA-256s of files checked against Ollama's. Not in git. |
