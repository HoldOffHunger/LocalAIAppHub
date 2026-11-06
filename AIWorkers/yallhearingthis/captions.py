import re
from dataclasses import dataclass
from pathlib import Path

CUE = re.compile(r"^(\d\d:\d\d:\d\d\.\d\d\d) --> (\d\d:\d\d:\d\d\.\d\d\d)")
TAG = re.compile(r"<[^>]+>")
NOISE = re.compile(r"^\[(?:music|applause|laughter|__)\]$", re.I)


@dataclass
class Line:
    start: float  # seconds into the video
    text: str


def caption_lines(path: str | Path) -> list[Line]:
    """YouTube's automatic captions as plain lines, each said once. Its VTT rolls: every line appears twice, once growing
    word by word and once whole above the next, so a line already said is dropped."""
    if not path:
        return []
    lines, start, last = [], 0.0, ""
    for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
        cue = CUE.match(raw)
        if cue:
            start = _seconds(cue.group(1))
            continue
        text = re.sub(r"\s+", " ", TAG.sub("", raw)).strip()
        if not text or text in ("WEBVTT",) or text.startswith(("Kind:", "Language:")) or NOISE.match(text):
            continue
        text = re.sub(r"\[(?:music|applause|laughter)\]\s*", "", text, flags=re.I).strip()
        if text and text != last:
            lines.append(Line(start, text))
            last = text
    return lines


def paragraphs(lines: list[Line], gap: float = 8.0, words: int = 70) -> list[str]:
    # Automatic captions have no punctuation, so a paragraph breaks at a long pause, or at about seventy words
    found, current, previous = [], [], None
    for line in lines:
        if current and (line.start - previous > gap or sum(len(text.split()) for text in current) >= words):
            found.append(" ".join(current))
            current = []
        current.append(line.text)
        previous = line.start
    if current:
        found.append(" ".join(current))
    return [_sentence_case(paragraph) for paragraph in found]


def stamp(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600}:{whole % 3600 // 60:02d}:{whole % 60:02d}" if whole >= 3600 else f"{whole // 60}:{whole % 60:02d}"


def _sentence_case(text: str) -> str:
    text = re.sub(r"\bi\b", "I", text)
    return text[:1].upper() + text[1:]


def _seconds(clock: str) -> float:
    hours, minutes, seconds = clock.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
