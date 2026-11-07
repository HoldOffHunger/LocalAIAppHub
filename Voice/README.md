# Voice

Chat, spoken. The 🎙️ Voice entry in the App Hub, under Chat, on http://127.0.0.1:8795. Hold the button (or hold Space), talk, and let go: what you said appears as text, the writer answers, and the voice reads the answer aloud sentence by sentence while the rest is still being written. Talk again while she's speaking and she stops to listen. **Stop** cuts her off; what she'd said so far is kept.

## Three ways to talk

The menu beside the talk button, remembered in this browser:

- **Hold to talk:** hold the button (or Space) while you talk; let go to send.
- **Click on, click off:** click (or tap Space) to start, again to send.
- **Hands-free:** click once to turn it on. It listens; when you've talked and then gone quiet for 1.3 seconds, it sends what you said, she answers, and once she's finished speaking it listens again. A cough or a click under 0.3 s doesn't count as talking, and the line between talking and quiet rides above the room's own noise. It doesn't listen while she speaks, so her voice from the speakers isn't taken for yours. Click again to turn it off, which also stops her. **Stop** stays lit all through hands-free: while she's thinking or speaking it hushes her and listening carries on; while it's only listening, it ends hands-free. The timings are `QUIET_MS`, `LEAST_SPEECH_MS` and `REARM_MS` in `static\app.js`.

## The pickers

- **Character:** Chat's own characters, read from `E:\local-chat\data\personas.json` (never written). Make or change one in Chat's Personalities and it's here too. Its prompt and the lines it learned from go in, plus a note that this is a spoken conversation: a few sentences, no markdown, no emoji, no *actions*. No Roleplay mode, since that needs a narrator.
- **Writer:** any Ollama model. Empty in settings means whatever Chat uses.
- **Voice:** Kokoro's 54 voices, grouped by accent and sex, and each option says its own sex and accent too (a closed menu only shows the one picked). ★ marks the ones Kokoro's makers graded best. The English voices sound most natural; the others speak English with their own accent. **Hear it** plays a sample line.
- **Speed:** 0.7× to 1.4×.
- **Mic:** which microphone to listen to, remembered in this browser, with a meter beside it. On 1 Nov 2026 the browser's default was one of the PC's virtual microphones (Virtual Desktop, Oculus, Steam Streaming), which send perfect silence, and every try came back "I didn't catch that." A recording with no sound in it now says so and isn't sent. `data\last_recording.webm` keeps the latest recording, for when it hears nothing and we want to know why.

Picking a voice in a chat with a character makes it that character's voice from then on (`data\character_voices.json`), so a new chat with her starts with it.

## How it works

| Step | What does it | Where |
|---|---|---|
| Listening | Whisper `small.en` (faster-whisper, int8), on the processor | `E:\AIModels\whisper\small.en` |
| Writing | The writer model, through Ollama, on the graphics card | |
| Speaking | Kokoro 82M (kokoro-onnx), on the processor | `E:\AIModels\kokoro` |

Both speech models run on the processor, so the writer has the 1070 Ti to itself. Before each reply Voice asks the hub's GPU desk for the card, as Chat does: the AI Workers wait, and other models are unloaded.

Whisper is given a few names it wouldn't guess (Talasia, hobthrush, Claudia, Ben, and the character's name), so they come out spelled right. A leading "Claudia:" that chat-trained models like to write is taken off, so she doesn't announce herself.

Measured on 1 Nov 2026 with Rocinante warm: hearing five seconds of speech takes about 2.5 s; her first sentence starts about 2 s after that. Cold, the first reply waits about 10 s more while Ollama loads the model.

## Files

| Path | What it is |
|---|---|
| `server.py` | The web server, the threads, and the reply: the model's words stream in, finished sentences go to the voice, and the page gets each sentence's audio as soon as it's spoken |
| `speech.py` | Kokoro and Whisper, the voice list, and what gets spoken (no thinking, no *actions*, no emoji, no links) |
| `gpu_claim.py` | Asking the hub's GPU desk for the card |
| `static\` | The page |
| `data\threads\` | One `.json` per voice chat |
| `data\audio\<chat>\` | Her spoken sentences, `<message>-<n>.wav`, for **replay**. Deleting a chat deletes them |
| `data\settings.json` | Defaults: model, voice, speed, temperature, context, `pause_workers_minutes` |
| `tests\` | `.venv\Scripts\python -m pytest tests` |

## Setting it up again

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

The models: `kokoro-v1.0.onnx` and `voices-v1.0.bin` from the kokoro-onnx GitHub release `model-files-v1.0`, into `E:\AIModels\kokoro`; Whisper with `from faster_whisper import download_model; download_model("small.en", output_dir=r"E:\AIModels\whisper\small.en")`.

PyAV is held below 16: faster-whisper 1.2.1 passes an argument PyAV 16 dropped, and every recording failed to decode.

In the hub, Voice's frame is allowed the microphone (`"allow": "microphone; autoplay"` in the hub's `app_list.json`); the browser still asks once.
