import re
from collections import Counter

from ocr_shapes import Reading, readings

LINE_BREAK = re.compile(r"([a-z])-\s*\n\s*([a-z])")  # "organi-\nzation" is one word
TOKEN = re.compile(r"(?<![A-Za-z'])[a-z]+(?![A-Za-z'])")  # lowercase only: a capital is mostly a name, and wants another job
LEAST_FREQUENCY = 50  # what an OCR misreading maps to must be a word people actually use, not a dictionary oddity


class Miner:
    """Finds the non-words in a scanned text that look-alike swaps turn into common words: candidate misspellings.

    `frequency(word)` is pyspellchecker's count for the word (0 for a non-word). `known` is what GGCMS lists already."""

    def __init__(self, frequency, known: dict[str, str], least: int = LEAST_FREQUENCY):
        self.frequency = frequency
        self.known = known
        self.least = least
        self.cache: dict[str, Reading | None] = {}

    def meant(self, seen: str) -> Reading | None:
        # The likeliest word: fewest swaps, then the commonest. Two swaps only for longer words, where they can't wander far
        if seen not in self.cache:
            options = [reading for reading in readings(seen, 2 if len(seen) >= 7 else 1) if self.frequency(reading.word) >= self.least]
            fewest = min((len(reading.steps) for reading in options), default=0)
            best = max((reading for reading in options if len(reading.steps) == fewest), key=lambda r: self.frequency(r.word), default=None)
            self.cache[seen] = best
        return self.cache[seen]

    def mine(self, text: str) -> dict:
        """{"words", "nonwords", "found": {wrong: {"right", "shapes", "strong", "count", "example"}}} for one text."""
        text = LINE_BREAK.sub(r"\1\2", text)
        tokens = [match for match in TOKEN.finditer(text)]
        counts = Counter(match.group(0) for match in tokens)
        nonwords = {word for word in counts if len(word) >= 4 and not self.frequency(word)}
        found = {}
        for word in sorted(nonwords):
            reading = self.meant(word)
            if reading:
                found[word] = {"right": reading.word, "shapes": reading.describe(), "strong": reading.strong, "count": counts[word],
                               "known": self.known.get(word, "")}
        for match in tokens:  # one line of context each, for the reader
            entry = found.get(match.group(0))
            if entry and "example" not in entry:
                start, end = match.start(), match.end()
                entry["example"] = " ".join(text[max(0, start - 70):end + 70].split())
        return {"words": len(tokens), "nonwords": sum(counts[word] for word in nonwords), "found": found}
