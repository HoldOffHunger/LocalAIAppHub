# Local AI App Hub

A private AI platform that runs entirely on one home PC. Chat, voice, image and video generation, image description, scheduled jobs, and a crew of overnight AI workers, all served from local models on a single 8 GB GPU. Nothing is sent to a cloud service, and personal data never enters this repository.

Built by Ben Tepolt, working daily with Claude Code.

## What's in it

| App | What it does |
|---|---|
| **Hub** | One page with a side panel for every app. Starts them, shows which are running, and keeps each loaded while you switch. |
| **Chat** | A private ChatGPT-style chat over Ollama: streaming replies, saved conversations, per-chat system prompts, reasoning blocks, and a character trainer built from chat logs. |
| **Voice** | Spoken conversation with a character: talk aloud and hear the answer. |
| **Images** | Image and video generation through ComfyUI, with a gallery. |
| **AI Workers** | Small local models doing narrow, well-defined jobs overnight, one item at a time, managed by the Foreman. |
| **Chron Jobs** | Jobs that run on their own each night, such as a 3 AM snapshot backup of Claude Code's memory files and a nightly painting job. |
| **Social** | Findings from the workers (Wikipedia typos, dead links, OCR misreadings) ready to review and act on. |
| **Corpus** | A research library: every copy of every book, what's been read, and a tagging framework. |
| **Minis** | Two desktop companions: Claudia, who shows what Claude Code is doing (via a Claude Code plugin), and Bit, who shows what the AI Workers are doing. |

## How it fits together

- **Local-only by design.** Every app is a small Python server bound to `127.0.0.1`, with plain HTML/CSS/JS front ends. Models run through Ollama and ComfyUI. State lives in SQLite and JSON outside the repo, and `.gitignore` blocks conversations, personas, training material and login tokens by name.
- **The GPU desk.** One 8 GB card, many apps that want it. The hub keeps a single lease record (`gpu_desk.py`) with a small API (`claim`, `renew`, `release`, `kick`). Whatever you're using now gets the card; a picture already drawing finishes; background workers always yield and come back when things go quiet; leases expire on their own so a crashed app can't hold the card. When the card changes hands, the desk unloads models the new holder doesn't need.
- **The Foreman and the night shift.** Each worker is a folder with a `worker.json` (command, targets, stop flag, progress stats). The Foreman runs active tasks in a schedule window, gives each a fair share of the time, waits for Chron Jobs and for anyone using the GPU, and has an "until I'm back at the PC" mode that watches Windows idle time. Every job is resumable and stops cleanly at its deadline.
- **Nothing reaches production unreviewed.** Workers find and report. Writing jobs stage their changes as records for the site's own save path, and a person, working with Claude, confirms them before anything ships.
- **Offloading from Claude Code.** Routine, high-volume checking goes to local models, so cloud tokens are spent on the work that needs a frontier model.

## The AI Workers, and how their models were chosen

The workers run over a family of real websites with tens of thousands of texts: spellchecking 15,000+ texts, pulling word-for-word quotes, tagging, reviewing machine translations for a language-learning site, harvesting new misspellings, finding dead or missing Wikipedia links in billion-row Wikipedia dumps, and mining OCR errors from the Internet Archive.

Models weren't picked on vibes. For translation review, they were scored against hand-checked answer keys:

- On 113 hand-checked Italian words, three local models voting caught 7 of 7 wrong translations, against 2 of 7 for a machine-translation "expert" pipeline.
- On a 12-language test (113 words, 45 wrong), `mistral:7b` alone caught 34 with 7 false alarms, the best balance of any single small model. A `mistral` OR `llama3.1` screen caught all 45, at about 3× the review work.
- `gemma4:12b` with thinking turned off was the best single senior judge (36 caught, 8 false alarms). With thinking on, it spent its budget musing and returned empty answers.
- Two-stage screen-then-judge setups (a fast screen, a stronger model rechecking) became the standard pattern across the workers.

The full record is in [`AIWorkers/README.md`](AIWorkers/README.md), including the mistakes found along the way and the rules added to fix them.

## Running it

This is a working personal setup, not a packaged product: paths point at the author's drives, and the workers expect his sites' database dumps. The apps themselves are small and readable. See [`HUB.md`](HUB.md) for how the hub starts and manages them, and each app's own README for details.

Requirements: Windows, Python 3, [Ollama](https://ollama.com), and [ComfyUI](https://github.com/comfyanonymous/ComfyUI) for images.
