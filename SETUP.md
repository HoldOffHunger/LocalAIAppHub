# Setting the App Hub up on a new PC

For the Claude helping someone install this on their own machine. Read this first. The rest of the docs (`README.md`
and each app's `README.md`) describe the apps as they run on the machine they were built on, so their drive
letters and model names are examples, not instructions.

A fresh clone carries no chats, characters, voice threads or pictures: those live in each app's `data\` folder,
which git ignores. Everything starts empty and becomes the new owner's.

## What to set up

The general-purpose apps, which work on any Windows PC with Python and Ollama:

| App | Folder | Port | Needs |
|---|---|---|---|
| 💬 Chat | `local-chat` | 8790 | Python, Ollama, a chat model |
| 🎙️ Voice | `Voice` | 8795 | its own `.venv`, the Kokoro and Whisper files |
| 🎨 Images | `ImageGen` | 8730 | an NVIDIA card (6 GB+), ComfyUI, the FLUX.2 klein files |
| 🧠 Models | `Models` | 8800 | nothing extra |

The hub (`start.bat`, `hub_server.py`, `gpu_desk.py`, `static\`) ties them together on http://127.0.0.1:8700.

The other apps were built for the original owner's own projects: AI Workers, Autonoma, Site Stats, Movies and
JellyShim live outside this repo, so the hub hides them automatically when their folders aren't there. Chron Jobs,
Social, Corpus and Minis are in the repo and will show up. **Ask the new owner whether they want them**; if not, set
`"autostart": false` on them in `data\app_list.json`, or remove their entries. Chron Jobs in particular runs
nightly jobs (backing up another app's memory, painting scenes) that mean nothing on a new PC, so turn it off.

## Steps

1. **Look first.** `powershell -ExecutionPolicy Bypass -File setup\setup.ps1 -DryRun` prints the graphics card, each
   drive's free space, and the models it would download. It changes nothing.
2. **Decide where the models go,** with the owner. They're the big part (5–45 GB). The default is `ModelFiles\`
   inside this folder. If C: is small and another drive is roomy, either clone the repo onto that drive or pass
   `-ModelsDir X:\AIModels`.
3. **Install what's missing:** Python 3.10+ (the apps were built on 3.12) and Ollama. `-InstallMissing` does both
   with winget. Ask before running it.
4. **Run setup:** `powershell -ExecutionPolicy Bypass -File setup\setup.ps1` (plus the flags from step 2). It sets
   `OLLAMA_MODELS` (and `AI_MODELS`, if the models aren't in `ModelFiles\`) for the user, restarts Ollama so it
   uses them, pulls chat models sized to the card, builds Voice's `.venv`, and fetches the speech and picture models.
   Downloads resume if interrupted; a rerun skips what's there. `setup.bat` is the same with a yes/no prompt.
5. **Start it** from a new window (so it sees the new environment variables): `start.bat`, then
   http://127.0.0.1:8700. Use `127.0.0.1`, not `localhost`.

Budget: setup spends at most 60% of the drive's free space and always leaves 30 GB free; `-BudgetGB 40` caps it.
When space is tight it drops the picture model (12.5 GB) first. `setup\models.json` lists the picks per card size;
edit it to change them.

## Things a new PC needs changing

- **Chat's default system prompt** in `local-chat\server.py` (`DEFAULT_SETTINGS`) is written for uncensored
  creative writing. Ask the owner what they'd like, and set it in Chat's Settings (that writes
  `local-chat\data\settings.json`, which stays out of git).
- **Voice's name hints** (`HINTS` in `Voice\server.py`) are names from the original owner's world, given to Whisper
  so it spells them right. Replace them with names the new owner uses, or `""`.
- **Images' model menu** (`MODELS` in `ImageGen\workflows.py`) includes two SDXL checkpoints marked uncensored.
  They stay greyed out unless their files are downloaded; setup never downloads them. Ask before adding them.

## Images needs ComfyUI

Images starts a headless ComfyUI itself, only when there's a picture to make. Setup downloads the FLUX.2 klein 4B
files but doesn't install ComfyUI. Put a ComfyUI install (the Windows portable build, or a git clone with its own
venv, from https://github.com/comfyanonymous/ComfyUI) in `ComfyUI\` inside this folder and rerun setup, which finds
it and writes `ImageGen\data\settings.json`. Or set `comfy_python` and `comfy_main` there by hand. Images writes
ComfyUI's model-path file itself from `models_folder`, so nothing needs copying.

Klein 9B and the Wan 2.2 5B video model are supported but not downloaded (10–19 GB each, and slow on small
cards); `ImageGen\README.md` lists their files.

## How the pieces fit

- **The GPU desk** (`gpu_desk.py`): each app asks the hub before it uses the card; the newest request gets it,
  Ollama unloads the models the new holder doesn't need, and ComfyUI lets go. Leases expire on their own. Every
  app still works when the hub isn't running.
- **Voice reads Chat's characters** from `local-chat\data\personas.json` (read only), and uses Chat's model unless
  it has its own.
- **Folders in `data\app_list.json`** may be relative (to the hub) or absolute; an app whose folder is missing is
  hidden.
- **Model files:** the apps look in `AI_MODELS`, or `ModelFiles\` in the hub. On a PC whose models already live
  elsewhere, a junction works too: `New-Item -ItemType Junction -Path ModelFiles -Target X:\AIModels`.

## When something's wrong

- An app shows grey: press **Start it**, then read its console window.
- Voice can't load the speech models: its `.venv`, or `kokoro\` and `whisper\small.en` under the models folder,
  are missing. Rerun setup.
- Voice hears nothing: the browser's default microphone may be a virtual one that sends silence. Pick the real
  microphone in Voice's Mic menu.
- Images can't find ComfyUI: see above; its log is `ImageGen\data\comfy.log`.
- A model is slow: it's bigger than the card and spilling into system RAM. Pick a smaller one, or lower the
  context length in Chat's settings.
