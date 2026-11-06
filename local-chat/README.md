# Local Chat

A small, private, ChatGPT-style chat site that runs entirely on your machine and talks to a local model through [Ollama](https://ollama.com). No accounts, no telemetry, and nothing leaves your PC.

## What's in this folder (`local-chat/`)

| Path | What it is |
|---|---|
| `server.py` | The whole backend. Python 3 standard library only, nothing to `pip install`. |
| `start.bat` | Windows double-click launcher (starts the server, opens the browser). |
| `static/index.html`, `static/app.css`, `static/app.js` | The chat UI. |
| `static/markdown.js` | Tiny Markdown renderer (escapes HTML first, so output can't inject markup). |
| `data/settings.json` | Your defaults (model, system prompt, sampling). Created on first run. |
| `data/conversations/*.json` | One file per saved chat. Back these up, delete them, grep them; they're yours. |

`data/` is not actually in this folder: it's `E:\local-chat\data`, outside the AppHub repo, so chats never end up in git. Set `LOCAL_CHAT_DATA` to use a different folder.

## Setup

1. Install Ollama: https://ollama.com/download
2. Pull a model (see below), e.g. `ollama pull qwen3:14b`
3. Run `python server.py` (or double-click `start.bat` on Windows).
4. Open http://127.0.0.1:8790

Optional environment variables: `OLLAMA_URL` (default `http://127.0.0.1:11434`), `LOCAL_CHAT_PORT` (default `8790`), `LOCAL_CHAT_HOST` (default `127.0.0.1`, so only this PC can reach it).

## Features

- Multiple saved conversations in a sidebar (rename, delete).
- Streaming replies with a Stop button; tokens/sec shown under each reply.
- **Per-chat system prompt** (persona, scenario, rules) plus a default one in Settings.
- Regenerate, Continue (asks the model to pick up where it stopped), Edit a past message and resend from there, Delete any message.
- Long replies: max reply tokens defaults to `-1` (no cap) and context defaults to 16k tokens.
- Reasoning models (Qwen3, DeepSeek-R1 style) show their thinking in a collapsible block.

## Settings that matter for long, full-page replies

- **Max reply tokens**: `-1` means the model writes until it decides to stop. A full page is roughly 600–900 tokens.
- **Context length**: Ollama's own default is small (a few thousand tokens), so the app always sends `num_ctx` explicitly. 16384 is a good default; raise it for long roleplays if you have VRAM, lower it if replies get slow or the model spills into system RAM.
- **Temperature** 0.8–1.0 for creative writing; lower for facts/code.
- The system prompt does a lot of the work. Ask for length explicitly ("write at least 1,500 words", "full scene, no summarizing").

## Models

Output quality depends far more on the model than on this UI. Rough sizing at Q4 quantization:

| GPU VRAM | Suggested starting point |
|---|---|
| 8 GB | `llama3.1:8b` or `mistral:7b` |
| 12–16 GB | `qwen3:14b`, `gemma3:12b`, or `mistral-nemo:12b` |
| 24 GB | `qwen3:32b` or `mistral-small:24b` |
| 48 GB+ | `llama3.3:70b` |

Any GGUF on Hugging Face can be pulled directly: `ollama pull hf.co/<user>/<repo>:Q4_K_M`.

These names come from memory of the Ollama library and Hugging Face, not a live check. Tags move around, so check https://ollama.com/search before pulling.

## Personalities and the chat character trainer

Open **Personalities** in the top bar.

- **Mode when picked**: Roleplay (scenes, a page per turn) or Chat (text messages only, like a chat log). The **Mode** button in the top bar cycles Off, Roleplay, Chat for the current conversation.
- **Training material**: add chat logs (`.txt`/`.log` files, or paste). Each one opens a preview first with its line count, the most active people, and a **Summarize this conversation** button, so you can Add or Skip it. Lines like `[12:34] <nick> text`, `<nick> text` and `Name: text` are understood.
- **Whose voice?**: click the person in the logs the character should sound like (or type several nicknames).
- **Prepare** picks about 30 real lines from that person, spread across all the material, and shows them to the model as examples. It does not change the model's weights; it's fast and can be redone any time.
- **Example pool** is based on how many usable lines that person has: None, Thin (20+), Okay (100+), Good (400+), Rich (1500+). If material changes afterwards, it tells you to prepare again.

Material lives in `data/materials/<personality id>/`, next to everything else in this folder.

## The hub (all our apps in one page)

Open http://127.0.0.1:8790/hub (start.bat opens it). The side panel switches between Chat, Autonoma, AI Workers, Site Stats, Movies and Jellyfin; each app stays loaded in its own frame. A green dot means the app is running. If it isn't, its pane has a **Start it** button that runs that app's own start script with `--no-browser` (Jellyfin is a Windows service, so it has no button). Hover an app for ↻ (reload with a fresh login) and ↗ (open in its own tab). `/hub#movies` opens straight to an app.

- The app list lives in `data/hub_apps.json`, written with defaults the first time. Apps are picked by `id`.
- Autonoma and the Foreman sign in through their own login files (`data\warden_login.txt`, `data\foreman_login.txt`).
- Open the hub as `127.0.0.1`, not `localhost`, so the apps' sign-in cookies match.

**Movies** (`/movies/`) is served from `E:\MovieTheaterWithClaudia\site\`. It reads the recommender's export in `E:\MovieTheaterWithClaudia\data\movies.json` (tiers, Claudia's script reads, her picks); without it, it falls back to `start.txt`. Click a movie with a "script n/10" badge to see the read.

**Chat pauses the AI Workers.** Before each chat reply, Local Chat asks the Foreman to hold: a running task stops and the night shift waits. Five minutes after the last chat message, the stopped task restarts with its original stop time (unless that time has passed). Change the wait with `pause_workers_minutes` in `data/settings.json`; 0 turns it off.
