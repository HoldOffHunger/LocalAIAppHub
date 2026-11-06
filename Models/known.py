# What we know about the models Ben has, when the file doesn't say: who made it, what kind of model it is, and a line
# about it. Matched in order against the model's name and file name (lower case); the first match wins. A model that
# matches nothing is still listed, by what its folder and header say. Add a line here when a new family arrives.

import re

# The kinds, in the order the page shows them
KINDS = [
    ("chat", "Chat", "💬"),
    ("code", "Code", "⌨️"),
    ("vision", "Vision chat", "👁️"),
    ("embedding", "Embedding", "🧭"),
    ("image", "Image generation", "🎨"),
    ("video", "Video generation", "🎞️"),
    ("image-tool", "Image tools", "✂️"),
    ("speech-to-text", "Speech to text", "👂"),
    ("text-to-speech", "Text to speech", "🗣️"),
    ("translation", "Translation", "🌐"),
    ("component", "Parts of other models", "🧩"),
    ("other", "Not identified", "❔"),
]

# (pattern, details). "creator" is who made the weights in the file; "base" what they built on.
FAMILIES = [
    (r"autonoma", {"creator": "Ben", "kind": "chat", "about": "Your own build, made for Autonoma.", "base": "Mistral 7B (Mistral AI)"}),
    (r"heretic|abliterated.*gemma|gemma.*abliterated", {"creator": "Community abliteration", "kind": "chat",
        "about": "Gemma with its refusals removed (abliterated).", "base": "Gemma (Google DeepMind)"}),
    (r"llama-3-8b-abliterated", {"creator": "Community abliteration", "kind": "chat",
        "about": "Llama 3 8B with its refusals removed (abliterated).", "base": "Llama 3 (Meta)"}),
    (r"mistral-7b-instruct.*abliterated", {"creator": "Community abliteration", "kind": "chat",
        "about": "Mistral 7B Instruct with its refusals removed (abliterated).", "base": "Mistral 7B (Mistral AI)"}),
    (r"cydonia", {"creator": "TheDrummer", "kind": "chat", "about": "Creative writing and roleplay fine-tune.",
        "base": "Mistral Small 24B (Mistral AI)"}),
    (r"rocinante", {"creator": "TheDrummer", "kind": "chat", "about": "Creative writing and roleplay fine-tune.",
        "base": "Mistral Nemo 12B (Mistral AI, NVIDIA)"}),
    (r"dolphin", {"creator": "Eric Hartford (Cognitive Computations)", "kind": "chat",
        "about": "Uncensored general-purpose fine-tune."}),
    (r"hermes", {"creator": "Nous Research", "kind": "chat", "about": "General-purpose fine-tune, good at following roles.",
        "base": "Llama 3.1 (Meta)"}),
    (r"gemma", {"creator": "Google DeepMind", "kind": "chat", "about": "Google's open-weights model family."}),
    (r"llama", {"creator": "Meta", "kind": "chat", "about": "Meta's open-weights model family."}),
    (r"granite-code", {"creator": "IBM", "kind": "code", "about": "IBM's code model."}),
    (r"granite", {"creator": "IBM", "kind": "chat", "about": "IBM's open-weights model family."}),
    (r"phi", {"creator": "Microsoft", "kind": "chat", "about": "Microsoft's small model family."}),
    (r"qwen.*coder", {"creator": "Alibaba (Qwen team)", "kind": "code", "about": "Qwen's code model."}),
    (r"minicpm-v", {"creator": "OpenBMB", "kind": "vision", "about": "Small model that reads images."}),
    (r"nomic-embed", {"creator": "Nomic AI", "kind": "embedding", "about": "Turns text into vectors for search and similarity."}),
    (r"mistral", {"creator": "Mistral AI", "kind": "chat", "about": "Mistral AI's open-weights model."}),
    # ComfyUI
    (r"flux1-dev|flux\.1-dev", {"creator": "Black Forest Labs", "kind": "image", "about": "FLUX.1 [dev]: text to image."}),
    (r"flux-2-klein", {"creator": "Black Forest Labs", "kind": "image", "about": "FLUX.2 [klein]: fast text to image and image editing."}),
    (r"wan2\.2_ti2v", {"creator": "Alibaba (Wan team)", "kind": "video", "about": "Wan 2.2 TI2V 5B: text or image to video."}),
    (r"wan2\.2_vae", {"creator": "Alibaba (Wan team)", "kind": "component", "about": "VAE for Wan 2.2 5B video."}),
    (r"umt5", {"creator": "Google", "kind": "component", "about": "UMT5-XXL text encoder, used by Wan video."}),
    (r"t5xxl", {"creator": "Google", "kind": "component", "about": "T5-XXL text encoder, used by FLUX.1."}),
    (r"clip_l", {"creator": "OpenAI", "kind": "component", "about": "CLIP-L text encoder, used by FLUX.1 and SDXL."}),
    (r"qwen_3_4b", {"creator": "Alibaba (Qwen team)", "kind": "component", "about": "Qwen3 4B as a text encoder, used by FLUX.2 [klein] 4B."}),
    (r"qwen_3_8b", {"creator": "Alibaba (Qwen team)", "kind": "component", "about": "Qwen3 8B as a text encoder, used by FLUX.2 [klein] 9B."}),
    (r"flux2-vae", {"creator": "Black Forest Labs", "kind": "component", "about": "VAE for FLUX.2."}),
    (r"\bae\.safetensors",{"creator": "Black Forest Labs", "kind": "component", "about": "VAE for FLUX.1."}),
    (r"waiillustrious", {"creator": "WAI0731 (Civitai)", "kind": "image", "about": "Anime-style SDXL checkpoint.",
        "base": "Illustrious XL (OnomaAI)"}),
    (r"lustify", {"creator": "Civitai community", "kind": "image", "about": "Photographic SDXL checkpoint.",
        "base": "SDXL (Stability AI)"}),
    # The rest of E:\AIModels
    (r"kokoro", {"creator": "hexgrad", "kind": "text-to-speech", "about": "Kokoro 82M: small, natural-sounding text to speech."}),
    (r"whisper", {"creator": "OpenAI", "kind": "speech-to-text", "about": "Whisper, as a CTranslate2 build for faster-whisper."}),
    (r"opus-mt", {"creator": "Helsinki-NLP (University of Helsinki)", "kind": "translation", "about": "Opus-MT translation model."}),
    (r"birefnet", {"creator": "ZhengPeng7 (BiRefNet)", "kind": "image-tool", "about": "Background removal, used through rembg."}),
    (r"u2net|isnet|silueta", {"creator": "rembg", "kind": "image-tool", "about": "Background removal."}),
    (r"esrgan|upscal", {"kind": "image-tool", "about": "Image upscaler."}),
    (r"embed", {"kind": "embedding"}),
]
_COMPILED = [(re.compile(pattern), details) for pattern, details in FAMILIES]

# ComfyUI's own folders say what a file is when the name doesn't
COMFY_FOLDER_KINDS = {"checkpoints": "image", "diffusion_models": "image", "unet": "image", "loras": "image",
                      "embeddings": "image", "controlnet": "image-tool", "upscale_models": "image-tool",
                      "background_removal": "image-tool", "text_encoders": "component", "clip": "component",
                      "clip_vision": "component", "vae": "component", "vae_approx": "component",
                      "audio_encoders": "component", "frame_interpolation": "video"}

LANGUAGES = {"en": "English", "de": "German", "es": "Spanish", "fr": "French", "hi": "Hindi", "id": "Indonesian",
             "it": "Italian", "ja": "Japanese", "jap": "Japanese", "ko": "Korean", "nl": "Dutch", "pl": "Polish",
             "ru": "Russian", "zh": "Chinese", "mul": "many languages", "romance": "the Romance languages"}


def lookup(*names):
    text = " ".join(name for name in names if name).lower()
    for pattern, details in _COMPILED:
        if pattern.search(text):
            return dict(details)
    return {}


def translation_pair(folder_name):
    # "opus-mt-en-ROMANCE" -> "English → the Romance languages"
    parts = folder_name.lower().split("-")
    if len(parts) >= 4:
        return "%s → %s" % (LANGUAGES.get(parts[2], parts[2]), LANGUAGES.get(parts[3], parts[3]))
    return ""
