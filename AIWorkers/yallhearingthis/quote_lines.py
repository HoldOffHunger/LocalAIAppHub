import json
import re

import ollama

from captions import Line

CHOICE = {"type": "object", "properties": {"pick": {"type": "integer"}, "words": {"type": "string"}, "reason": {"type": "string"}},
          "required": ["pick", "words", "reason"]}
FILLER = re.compile(r"^(?:um+|uh+|oh+|okay|ok|so|yeah|like|and)\b\s*", re.I)


def candidates(lines: list[Line], most: int = 60) -> list[str]:
    """Stretches of two or three caption lines, 8 to 30 words, spread through the whole video. The captions have no
    sentences to lift, so a stretch of speech is the unit, and the model can only choose, never write."""
    found = []
    for size in (2, 3):
        for start in range(0, len(lines) - size + 1, size):
            text = " ".join(line.text for line in lines[start:start + size])
            text = FILLER.sub("", FILLER.sub("", text)).strip()
            if 8 <= len(text.split()) <= 30:
                found.append(text)
    found = list(dict.fromkeys(found))
    if len(found) > most:
        step = len(found) / most
        found = [found[int(n * step)] for n in range(most)]
    return found


def trimmed(stretch: str, words: str) -> str:
    """The model's trim, only if it's a run of the stretch's own words, five or more; otherwise the whole stretch."""
    said, kept = stretch.split(), words.split()
    if len(kept) < 5:
        return stretch
    fold = [w.lower().strip(".,!?\"'") for w in said]
    want = [w.lower().strip(".,!?\"'") for w in kept]
    for start in range(len(fold) - len(want) + 1):
        if fold[start:start + len(want)] == want:
            return " ".join(said[start:start + len(want)])
    return stretch


class QuotePick:
    """Picks the line from a show that best says what the hosts felt, from numbered stretches of its captions."""

    def __init__(self, model: str, client: ollama.Client | None = None):
        self.model = model
        self.client = client or ollama.Client()

    def pick(self, title: str, options: list[str]) -> dict | None:
        if len(options) < 3:
            return None
        numbered = "\n".join(f"{n}. {text}" for n, text in enumerate(options, 1))
        question = (
            f"These numbered stretches are word for word from the automatic captions of \"{title}\", a video on Y'all "
            f"Hearing This?!, where the hosts react to K-pop.\n\n{numbered}\n\n"
            f"Pick the one stretch that would make the best quote on the show's page: the hosts' own reaction, put "
            f"memorably -- delight, surprise, praise for a vocal, a dance or a visual, a funny line. Not song lyrics being "
            f"sung along, not housekeeping (\"like and subscribe\", \"next up we have\", \"let's get into it\"), and it must make sense on its "
            f"own. Give its number in pick. In words, copy the part of it worth quoting, word for word, dropping repeats and "
            f"half-finished words at either end; don't add or change a word. Then a one-sentence reason. Reply as JSON.")
        for room in (200, 400):
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}], format=CHOICE,
                                     options={"temperature": 0, "num_ctx": 4096, "num_predict": room}, keep_alive="10m", think=False)
            try:
                answer = json.loads(reply.message.content)
            except json.JSONDecodeError:
                continue
            if isinstance(answer.get("pick"), int) and 1 <= answer["pick"] <= len(options):
                text = trimmed(options[answer["pick"] - 1], answer.get("words", ""))
                return {"quote": text[:1].upper() + text[1:], "reason": answer.get("reason", "")}
        return None

    def release(self) -> None:
        self.client.generate(model=self.model, prompt="", keep_alive=0)
