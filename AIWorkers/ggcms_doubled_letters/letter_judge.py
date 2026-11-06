import json

import ollama

RULING = {"type": "object", "properties": {"real_word": {"type": "boolean"}, "reason": {"type": "string"}},
          "required": ["real_word", "reason"]}


def verdict_shape(variants: list[str]) -> dict:
    # One named slot per spelling, not a list: given a list, gemma filled it with "missy", "missy", "missy"… until it ran out
    # of room, and 17 words came back unreadable on every run (3 Nov 2026)
    return {"type": "object", "properties": {"meaning": {"type": "string"}, "english_word": {"type": "boolean"},
                                             **{variant: RULING for variant in variants}},
            "required": ["meaning", "english_word", *variants]}  # the meaning first, so the model looks before it rules


class LetterJudge:
    """Asks a local model about one word and its dropped-letter slips: is the word English worth guarding, and is each slip
    a real word or spelling the dictionaries missed? The mechanical pass has already thrown out the slips it can prove real."""

    def __init__(self, model: str, client: ollama.Client | None = None):
        self.model = model
        self.client = client or ollama.Client()

    def check(self, word: str, variants: list[str]) -> dict:
        question = self._question(word, variants)
        for tokens in (300, 600):  # a reply cut off mid-sentence gets one more try with more room
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}],
                                     format=verdict_shape(variants),
                                     options={"temperature": 0, "num_ctx": 2048, "num_predict": tokens}, keep_alive="10m", think=False)
            try:
                verdict = json.loads(reply.message.content)
            except json.JSONDecodeError:
                continue
            # A spelling the model skipped counts as real: "when unsure, real"
            verdict["variants"] = [{"variant": v, **(verdict.pop(v, None) or {"real_word": True, "reason": "The judge didn't rule on it."})}
                                   for v in variants]
            return verdict
        return {"unanswered": True}

    def release(self) -> None:
        # The 8 GB card can't hold two models at once; one left parked pushes the next task's onto the CPU
        self.client.generate(model=self.model, prompt="", keep_alive=0)

    def _question(self, word: str, variants: list[str]) -> str:
        listed = "\n".join(f"- {v}" for v in variants) or "(none)"
        return (f"We are building a list of common English misspellings. The word is \"{word}\".\n\n"
                f"First write meaning: what \"{word}\" means, in a few words.\n"
                f"Then english_word: true if \"{word}\" is a word that might appear in an English text, including words and "
                f"phrases borrowed from other languages that English writers use (\"bouillabaisse\", \"pianissimo\", "
                f"\"bon appetit\", \"schadenfreude\"). False only if it is a proper name, a place, a people or language name, "
                f"a brand or an abbreviation (\"agassiz\", \"assamese\", \"caltanissetta\").\n\n"
                f"Then, under each spelling below as its own key, real_word: true if it is itself a real English word or an "
                f"accepted spelling (\"desert\" for \"dessert\", \"princes\" for \"princess\", \"cares\" for \"caress\"), including "
                f"plurals, verb forms and British spellings; false if it is only a misspelling of \"{word}\". When unsure, answer "
                f"true.\n{listed}\n\nGive each a one-sentence reason a non-linguist can follow. Reply as JSON.")
