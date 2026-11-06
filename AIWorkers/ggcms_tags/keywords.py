import json
import re
from pathlib import Path

IGNORE = Path(__file__).with_name("ignore_words.json")  # ListKeywords' own list, from export_ignore_words.js
# getCleanupReplacements(), in the page's order: punctuation to spaces, curly quotes to straight, a few old spellings joined
CLEANUP = {"\t": " ", "\n": " ", "\r": " ", ",": " ", "!": " ", ";": " ", ":": " ", "?": " ", ".": " ", "(": " ", ")": " ",
           "[": " ", "]": " ", "{": " ", "}": " ", '"': " ", "*": " ", "•": " ", "“": " ", "”": " ", "’": "'", "`": "'",
           " ' ": " ", "good-bye": "goodbye", "to-day": "today", "to-morrow": "tomorrow", "to-night": "tonight"}
CLEANUP_PATTERN = re.compile("|".join(re.escape(find) for find in CLEANUP))


def ignore_words() -> set[str]:
    return set(json.loads(IGNORE.read_text(encoding="utf-8")))


def words(text: str) -> list[str]:
    # formatInput + cleanupInput + getInputWords, for text that's already plain
    cleaned = CLEANUP_PATTERN.sub(lambda match: CLEANUP[match.group(0)], text.lower())
    return [word for word in cleaned.split(" ") if word.strip()]


def list_keywords(text: str, skip: set[str]) -> list[tuple[str, int]]:
    """ListKeywords with "ignore common words" and "include phrases" ticked, most common first: six-word phrases down to two, then single words."""
    found = words(text)
    output = []
    for size in range(6, 1, -1):
        output += _ranked(_phrases(found, size, skip), phrases=True)
    singles = {}
    for word in found:
        if word not in skip:
            singles[word] = singles.get(word, 0) + 1
    return output + _ranked(singles, phrases=False)


def _phrases(found: list[str], size: int, skip: set[str]) -> dict[str, int]:
    # A pair needs both words kept; a longer phrase needs any two of its words kept
    counts = {}
    for start in range(len(found) - size + 1):
        window = found[start:start + size]
        if sum(word not in skip for word in window) >= 2:
            phrase = " ".join(window)
            counts[phrase] = counts.get(phrase, 0) + 1
    return counts


def _ranked(counts: dict[str, int], phrases: bool) -> list[tuple[str, int]]:
    # sortKeywords: a phrase has to turn up twice; ties keep the order they first appeared in
    kept = [(key, count) for key, count in counts.items() if not phrases or count > 1]
    return sorted(kept, key=lambda pair: -pair[1])
