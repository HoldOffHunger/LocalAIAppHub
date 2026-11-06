import json
from pathlib import Path

import ollama

from dump_reader import WordRow
from word_check import LANGUAGES

POSITION = {"type": "object", "properties": {"argument": {"type": "string"}, "position": {"type": "string", "enum": ["ok", "suspect"]},
                                             "proposed": {"type": "string"}},
            "required": ["argument", "position", "proposed"]}  # the argument first, so the position follows from it
CHARGE = (Path(__file__).parent / "jury_charge.txt").read_text(encoding="utf-8").strip()  # Ben-editable, read by every juror
CHOICE = {"type": "object", "properties": {"why": {"type": "string"}, "choice": {"type": "string"}}, "required": ["why", "choice"]}


class DebateTurn:
    """One juror's turn in a disagreement: read what the others said, answer them, and say where it stands now."""

    def __init__(self, model: str, dictionary, client: ollama.Client | None = None):
        self.model = model
        self.dictionary = dictionary
        self.client = client or ollama.Client()

    def speak(self, row: WordRow, transcript: list[dict]) -> dict:
        said = "\n".join(f"- {turn['juror']} says {turn['position']}"
                         f"{' (fix: ' + turn['proposed'] + ')' if turn['proposed'] else ''}: {turn['argument']}" for turn in transcript)
        prompt = (f"{CHARGE}\n\n{self._case(row)}\n\nThe jurors disagree about this entry. What has been said so far:\n{said}\n\n"
                  f"You are {self.model}. Answer the others directly, following your instructions: point to the evidence. Then give your "
                  "position now (ok or suspect) and, if suspect, the correct word in proposed. Two or three sentences. Reply as JSON.")
        reply = self._ask(prompt, POSITION, 400)
        if reply.get("position") not in ("ok", "suspect"):  # a garbled turn keeps its last stance rather than inventing one
            last = next((t for t in reversed(transcript) if t["juror"] == self.model), transcript[-1])
            reply = {"argument": "(couldn't put it into words this turn)", "position": last["position"], "proposed": last.get("proposed", "")}
        return {"juror": self.model, **reply}

    def choose(self, row: WordRow, options: list[str]) -> str:
        # The tiebreak: pick the best of the others' fixes, never your own
        listing = "\n".join(f"- {option}" for option in options)
        prompt = (f"{self._case(row)}\n\nThe checkers agree it's wrong but proposed different fixes. Choose the best one, "
                  f"exactly as written, from:\n{listing}\nReply as JSON with why (one sentence) and choice.")
        choice = self._ask(prompt, CHOICE, 120).get("choice", "").strip()
        return choice if choice in options else options[0]

    def _case(self, row: WordRow) -> str:
        language = LANGUAGES.get(row.lang, row.lang)
        glosses = "; ".join(self.dictionary.look_up(row.current)) or "not found"
        return (f"A vocabulary list for people learning {language}. Lesson: {row.lesson}. English word: {row.english}. "
                f"{language} translation on the site: {row.current}. Wiktionary says \"{row.current}\" means: {glosses}. "
                f"The lesson decides the sense (a bird in Animals, a country in Countries). Only call it suspect if it is clearly "
                f"wrong for that sense, not just because another word would also do.")

    def _ask(self, prompt: str, schema: dict, tokens: int) -> dict:
        reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": prompt}], format=schema,
                                 options={"temperature": 0.3, "num_ctx": 4096, "num_predict": tokens}, keep_alive="10m")
        try:
            return json.loads(reply.message.content)
        except json.JSONDecodeError:  # ran out of words mid-sentence
            return {}
