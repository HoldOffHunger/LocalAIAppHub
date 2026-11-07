# Speaking and listening, both on the processor so the graphics card stays free for the model writing the replies.
# Kokoro (82M, onnx) speaks; Whisper small.en (faster-whisper, int8) listens. Models live in the hub's models folder (or AI_MODELS).

import io
import re
import threading
import wave

import os

import numpy as np

APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODELS = os.environ.get("AI_MODELS") or os.path.join(APP_DIR, "..", "ModelFiles")

KOKORO_MODEL = os.path.join(MODELS, "kokoro", "kokoro-v1.0.onnx")
KOKORO_VOICES = os.path.join(MODELS, "kokoro", "voices-v1.0.bin")
WHISPER_MODEL = os.path.join(MODELS, "whisper", "small.en")
SAMPLE = "Hello, Ben. It's lovely to hear from you. Shall we talk for a while?"

# Kokoro's voice names say who they are: the first letter is the accent, the second the sex ("af_heart" is an American
# woman). Every voice speaks English here; the ones from other languages speak it with their own accent
ACCENTS = {"a": "American", "b": "British", "e": "Spanish", "f": "French", "h": "Hindi", "i": "Italian", "j": "Japanese",
           "p": "Brazilian", "z": "Chinese"}
SEXES = {"f": "female", "m": "male"}
ACCENT_ORDER = list(ACCENTS)
FAVOURITES = {"af_heart", "af_bella", "bf_emma", "am_michael", "am_fenrir", "bm_george"}  # graded best in Kokoro's own notes


def describe_voice(voice_id):
    # "af_heart" -> {"id", "name": "Heart", "sex": "female", "accent": "American", "english": True}
    prefix, _, name = voice_id.partition("_")
    accent = ACCENTS.get(prefix[:1], "Other")
    return {"id": voice_id, "name": name.replace("_", " ").title() or voice_id, "sex": SEXES.get(prefix[1:2], "unknown"),
            "accent": accent, "english": accent in ("American", "British"), "favourite": voice_id in FAVOURITES}


def catalogue(voice_ids):
    # English voices first, then the accents; within each, women then men, by name
    voices = [describe_voice(v) for v in voice_ids]
    return sorted(voices, key=lambda v: (ACCENT_ORDER.index(v["id"][0]) if v["id"][0] in ACCENT_ORDER else 99,
                                         v["sex"] != "female", v["name"]))


def lang_for(voice_id):
    return "en-gb" if voice_id.startswith("b") else "en-us"


def wav_bytes(samples, rate):
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes())
    return buffer.getvalue()


EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]")


def speakable(text):
    # What the voice should say: no thinking, no *actions*, no markdown, no emoji, no links
    text = re.sub(r"<think>.*?(</think>|$)", "", text, flags=re.S)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"\1", text)  # **bold** keeps its words; a lone *action* doesn't
    text = re.sub(r"\*[^*\n]{1,200}\*", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = EMOJI.sub("", text)
    text = re.sub(r"[#*_`>~|]", "", text)
    return re.sub(r"\s+", " ", text).strip()


SENTENCE_END = re.compile(r"(?<=[.!?…])[\"')\]]*\s+|\n+")


def split_ready(buffer, first):
    # Pulls whole sentences off the front of a growing reply, keeping the unfinished tail. Short ones are joined to the
    # next, so the voice doesn't stop and start on "Oh." The first piece goes as soon as it's a sentence: she starts sooner
    pieces, start = [], 0
    for match in SENTENCE_END.finditer(buffer):
        piece = buffer[start:match.end()].strip()
        if len(piece) >= (1 if first and not pieces else 40):
            pieces.append(piece)
            start = match.end()
    return pieces, buffer[start:]


class Speech:
    """Loads both models once, in the background, and lets one thing at a time use each."""

    def __init__(self):
        self.kokoro = None
        self.whisper = None
        self.problem = ""
        self.ready = threading.Event()
        self.speak_lock = threading.Lock()
        self.listen_lock = threading.Lock()

    def load(self):
        try:
            from faster_whisper import WhisperModel
            from kokoro_onnx import Kokoro
            self.kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
            self.whisper = WhisperModel(WHISPER_MODEL, device="cpu", compute_type="int8", cpu_threads=8)
        except Exception as error:  # the page says what went wrong rather than the server dying
            self.problem = "Couldn't load the speech models: %s" % error
        self.ready.set()

    def voices(self):
        self.ready.wait()
        return catalogue(self.kokoro.get_voices()) if self.kokoro else []

    def speak(self, text, voice, speed=1.0):
        # One sentence or so to a .wav; "" when there's nothing to say
        text = speakable(text)
        if not text:
            return b""
        self.ready.wait()
        with self.speak_lock:
            samples, rate = self.kokoro.create(text, voice=voice, speed=float(speed), lang=lang_for(voice))
        return wav_bytes(samples, rate)

    def listen(self, audio, hints=""):
        # The browser's recording (webm/opus) to text. Hints are names Whisper wouldn't guess, like "hobthrush"
        self.ready.wait()
        with self.listen_lock:
            segments, _info = self.whisper.transcribe(io.BytesIO(audio), beam_size=1, vad_filter=True, language="en",
                                                      initial_prompt=hints or None)
            return " ".join(segment.text.strip() for segment in segments).strip()
