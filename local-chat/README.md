# Local Chat

A small, private, ChatGPT-style chat site that runs entirely on your machine and talks to a local model through [Ollama](https://ollama.com). No accounts, no telemetry, and **no content filtering in the app**: whatever the model writes is shown as-is.

## What's in this folder (`local-chat/`)

| Path | What it is |
|---|---|
| `server.py` | The whole backend. Python 3 standard library only, nothing to `pip install`. |
| `start.bat` | Windows double-click launcher (starts the server, opens the browser). |
| `static/index.html`, `static/app.css`, `static/app.js` | The chat UI. |
| `static/markdown.js` | Tiny Markdown renderer (escapes HTML first, so output can't inject markup). |
| `data/settings.json` | Your defaults (model, system prompt, sampling). Created on first run. |
| `data/conversations/*.json` | One file per saved chat. Back these up, delete them, grep them; they're yours. |

## Setup

1. Install Ollama: https://ollama.com/download
2. Pull a model (see below), e.g. `ollama pull huihui_ai/qwen3-abliterated:14b`
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

Output quality depends far more on the model than on this UI. "Abliterated" models have had the refusal behaviour surgically removed; "uncensored" finetunes were retrained without refusals. Rough sizing at Q4 quantization:

| GPU VRAM | Suggested starting point |
|---|---|
| 8 GB | `dolphin3` (Llama 3.1 8B uncensored finetune) |
| 12–16 GB | `huihui_ai/qwen3-abliterated:14b`, `huihui_ai/gemma3-abliterated:12b`, or a Mistral Nemo 12B creative finetune |
| 24 GB | `huihui_ai/qwen3-abliterated:32b`, or a Mistral Small 24B creative finetune (e.g. TheDrummer's Cydonia) |
| 48 GB+ | `huihui_ai/llama3.3-abliterated:70b` |

Any GGUF on Hugging Face can be pulled directly: `ollama pull hf.co/<user>/<repo>:Q4_K_M`.

These names come from memory of the Ollama library and Hugging Face, not a live check. Tags move around, so search https://ollama.com/search?q=abliterated before pulling.

## Personalities and the chat character trainer

Open **Personalities** in the top bar.

- **Mode when picked**: Roleplay (scenes, a page per turn) or Chat (text messages only, like a chat log). The **Mode** button in the top bar cycles Off, Roleplay, Chat for the current conversation.
- **Training material**: add chat logs (`.txt`/`.log` files, or paste). Each one opens a preview first with its line count, the most active people, and a **Summarize this conversation** button, so you can Add or Skip it. Lines like `[12:34] <nick> text`, `<nick> text` and `Name: text` are understood.
- **Whose voice?**: click the person in the logs the character should sound like (or type several nicknames).
- **Prepare** picks about 30 real lines from that person, spread across all the material, and shows them to the model as examples. It does not change the model's weights; it's fast and can be redone any time.
- **Example pool** is based on how many usable lines that person has: None, Thin (20+), Okay (100+), Good (400+), Rich (1500+). If material changes afterwards, it tells you to prepare again.

Material lives in `data/materials/<personality id>/`, next to everything else in this folder.

## Getting the graphics card while you chat

Before each reply, Local Chat asks the App Hub's GPU desk for the card (`worker_pause.py`). The desk:

- holds the AI Workers: a running worker stops, and starts again five minutes after your last message;
- unloads every other Ollama model, so this reply's model has the card to itself;
- tells ImageGen's ComfyUI to let go. If a picture or clip is drawing, it finishes first, and the chat runs slower beside it until then.

Set `pause_workers_minutes` in `data/settings.json` to change the wait; 0 turns all of this off. If the hub isn't running, Chat asks the Foreman to hold directly, as it used to; if neither is running, nothing happens.

Local Chat is usually started by `E:\AppHub\start.bat` now, with the other apps. `start.bat --no-browser` starts it without opening a tab.
