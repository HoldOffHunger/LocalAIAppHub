# ImageGen

A local picture maker on http://127.0.0.1:8730, and the 🎨 Images entry in the App Hub. Ask with words, with pictures, or both:

- **Words only:** "a fox reading by lantern-light in an old library" makes a new picture in the chosen shape.
- **Pictures and words:** drop in a picture and say "make it winter". With several pictures, call them *image 1*, *image 2* and so on in the prompt: "put the cloak from image 2 on the knight in image 1". An edit comes out the shape of the first picture.

The drawing is done by ComfyUI with FLUX.2 [klein], 4 steps. Pick the model per picture from the **Model** menu. Each entry shows the drawing model's size and whether it fits on the card, worked out from the file on disk and the VRAM Comfy reports:

- **Klein 4B · quick:** 3.8 GB, fits. On the 1070 Ti, about 76 s for a new picture warm, and about 160–190 s for an edit.
- **Klein 9B KV · better edits, slower:** 9.1 GB, streams from RAM. Much better at doing what an edit asks; it got all six colours of a rainbow flag in order where the 4B managed four. About 150 s for a new picture warm, about 190 s for an edit cold. It reads reference pictures once instead of on every step and uses a lighter decoder, which is why edits cost it so little extra. Non-commercial licence.

- 🔴 **Lustify APEX · photoreal, uncensored** and 🔴 **WAI Illustrious v17 · illustration and anime, uncensored:** SDXL checkpoints, one 6.9 GB file each in `checkpoints\`, trained on adult material, so they draw what's asked. The red dot in the menu marks them. They work from words, or from one picture (it's redrawn at 0.65 strength, `SDXL_EDIT_STRENGTH`). WAI gets "masterpiece, best quality, amazing quality" put before the prompt, as its makers advise; booru-style tags work well with it. Their originals are on Civitai; the files came from Hugging Face re-uploads (`Lzzyb/lustify_nsfw_sdxl`, `IbarakiDouji/WAI-NSFW-illustrious-SDXL`) and matched the sha256 Civitai publishes for each. Lustify is APEX (V8), one version behind its newest SDXL release, because ZENITH (V9) has no Hugging Face copy.

To add a model, add it to `MODELS` in `workflows.py`. It shows in the menu, greyed out until its files are in place.

## Video

Flip the switch to **Video** for a clip from **Wan 2.2 5B**: from words alone, or from one picture the clip opens on. Pick a length (1–5 seconds, at 24 fps) and a size: Small (832×480) or Full (1280×704, what Wan 5B was trained at). A starting picture keeps its own shape at about the chosen size's pixel count.

Clips land in the gallery with a ▶ badge and play while the mouse is over them. The progress bar follows Wan's 20 drawing steps.

Speed on the 1070 Ti, measured at Small: 1 second from words took 8¼ minutes (cold), and 2 seconds from a picture took 20 minutes. Call it about 10 minutes per second of clip. Full size and 5-second clips will be far slower: an hour or more, not yet measured. Each drawing step is about 20 s, and RAM stayed above 13 GB free.

Starting from a picture works much better than words alone. The winter-fox picture became a clip of the fox lifting its head toward the window, with the scarf, lantern and snow consistent throughout. A words-only clip came out more cartoonish than asked.

## Starting it

Run `start.bat`, or let the App Hub start it. ComfyUI is started only when there's a picture to make: headless with no window, on port 8188, using Comfy Desktop's own install (`C:\Users\<you>\AppData\Local\Comfy-Desktop\ComfyUI-Installs\ComfyUI\ComfyUI\.venv`). The first picture after a quiet spell waits about 20 seconds for it.

Three minutes after the last picture, Comfy lets go of the card. Fifteen minutes after, ImageGen stops Comfy outright, which is the only way to get all its RAM back. If ImageGen's window was closed in between, the next ImageGen picks up where it left off (it keeps Comfy's process number in `data\comfy.pid`). A ComfyUI that ImageGen didn't start, such as Comfy Desktop's, is used but never stopped.

Comfy Desktop also uses port 8188 by default. Its port setting is "auto", so if ImageGen got there first, Desktop should pick another.

## Using it

- Drop, paste (Ctrl+V) or pick up to 4 pictures; drag one in from the gallery too. Ctrl+Enter makes it.
- Click a picture to open it: **Work from this** puts it in the composer for the next edit, **Same prompt again** reloads the prompt and its pictures with a new seed, **Reuse seed** keeps the seed too.
- Queue as many as you like; they run one at a time.
- The gallery's tabs are **Images**, **Videos** and **Defects**. Images and Videos follow the make switch.

## Defects

A badly made picture (six fingers, a fused arm, a missing head) can be marked from its viewer: **Mark as defect**, pick what's wrong (hands, limbs, face, text, anatomy, other), add a note if you like. It leaves Images or Videos for the Defects tab; **Not a defect** puts it back. The files never move: the mark is a `defect` field in the picture's `.json`, with the tags, the note and when it was marked.

Marking teaches the models nothing; their weights are fixed. What it gives is a clean gallery and, over time, a record of which model fails at what.

**Fix this** (pictures only) opens the defect in the composer as an edit, with a repair prompt built from its tags and note, on Klein 9B KV when its files are in place: it follows edits best. The new picture records the defect it was made to fix (`fixes` in its `.json`), and the viewer says so.

## Sharing the card

The GTX 1070 Ti has 8 GB, which can't hold Ollama's models, the AI Workers and klein at once. So before each picture:

1. The Foreman is asked to pause its worker (the same hold Local Chat uses).
2. Ollama drops whatever models it has loaded.

A few minutes after the last picture, ComfyUI lets go of the card too, so Chat gets it back quickly.

**Pictures from the AI Workers** come with `"background": true` in the `/api/generate` request, and skip both steps: the worker's turn already holds the card at the desk, and claiming it as Images would have the desk stop that very worker. When you take the card, a background picture already drawing finishes, and the worker steps aside. Any request can carry a `"source"` saying who asked, kept in the picture's `.json`: the App Hub's Chron Jobs paints a Talasia scene each night with sources such as `chron:race_scenes:army-of-thrunmora:2`, and finds a version already made by its source rather than drawing it again. Those pictures are ordinary ones, claiming the card as Images, since the workers are waiting while a Chron Job runs.

## Settings

`data\settings.json`, written with defaults on first run:

| Setting | What it does |
|---|---|
| `comfy_python`, `comfy_main` | Which ComfyUI to start. |
| `comfy_port` | 8188. |
| `models_folder` | `E:\AIModels\comfyui`. Comfy Desktop's `ComfyUI-Shared\models` is a junction to the same folder. |
| `pause_workers_minutes` | How long the AI Workers wait after the last picture. 0 turns it off. |
| `free_vram_minutes` | How long until ComfyUI lets go of the card after the last picture. 0 keeps it on the card. |
| `stop_comfy_minutes` | How long until ImageGen stops ComfyUI altogether, giving back its RAM. 15; 0 keeps it running. |

## Files

| Path | What it is |
|---|---|
| `server.py` | The web server, the job queue, and starting ComfyUI. Standard library only. |
| `workflows.py` | The ComfyUI graph, built from the official klein 4B templates. |
| `gpu_share.py` | Pausing the workers, unloading Ollama, freeing Comfy. |
| `comfy_models.yaml` | Tells the headless ComfyUI where the models are. |
| `static\` | The page. |
| `data\gallery\` | Every picture as `<id>.png` plus `<id>.json` (prompt, seed, the pictures it worked from, time taken). |
| `data\comfy-input\` | The pictures you worked from, named by their content. |
| `data\comfy.log` | ComfyUI's log, for when something goes wrong. |

## Models

In `E:\AIModels\comfyui`:

| | Klein 4B | Klein 9B KV |
|---|---|---|
| `diffusion_models\` | `flux-2-klein-4b-fp8.safetensors` | `flux-2-klein-9b-kv-fp8.safetensors` |
| `text_encoders\` | `qwen_3_4b.safetensors` | `qwen_3_8b_fp8mixed.safetensors` |
| `vae\` | `flux2-vae.safetensors` | `full_encoder_small_decoder.safetensors` |

Video, Wan 2.2 5B: `diffusion_models\wan2.2_ti2v_5B_fp16.safetensors`, `text_encoders\umt5_xxl_fp8_e4m3fn_scaled.safetensors`, `vae\wan2.2_vae.safetensors`.

## Memory

ComfyUI is started with `--disable-pinned-memory`. With pinned memory on, it held about 23 GB and left the PC with 3 GB free; the 4B slowed to about 30 s a step, and Comfy stopped answering mid-decode. With it off, the PC kept 11+ GB free even with the 9B.

The older `flux1-dev.safetensors`, with `t5xxl`, `clip_l` and `ae`, is still there for Comfy Desktop's own workflows. ImageGen doesn't use them.
