import json

import ollama

VERDICT = {"type": "object", "properties": {"reading": {"type": "string"}, "verdict": {"type": "string", "enum": ["typo", "fine"]},
                                            "fix": {"type": "string"}, "reason": {"type": "string"}},
           "required": ["reading", "verdict", "fix", "reason"]}  # the reading first, so the model looks before it rules


class TypoCheck:
    """Asks a local model one narrow question: in this sentence, is this word a mistake, or a real word the dictionary lacks?"""

    def __init__(self, model: str, site: str, client: ollama.Client | None = None):
        self.model = model
        self.site = site
        self.client = client or ollama.Client()

    def check(self, title: str, word: dict) -> dict:
        question = self._question(title, word)
        for tokens in (250, 500):  # a reply cut off mid-sentence gets one more try with more room
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}], format=VERDICT,
                                     options={"temperature": 0, "num_ctx": 2048, "num_predict": tokens}, keep_alive="10m", think=False)
            try:
                verdict = json.loads(reply.message.content)
            except json.JSONDecodeError:
                continue
            if verdict.get("verdict") == "typo" and verdict.get("fix", "").strip().lower() == word["word"].lower():
                # A "fix" that changes nothing: the model's reason nearly always says the word is fine ("a standard plural")
                verdict.update(verdict="fine", reason=f"Called a typo, but the fix was the word itself. {verdict.get('reason', '')}")
            return verdict
        return {"verdict": "unanswered", "fix": "", "reason": "The checker couldn't give a readable answer; ask again later."}

    def release(self) -> None:
        # The 8 GB card can't hold the screener and the judge at once; one left parked pushes the other onto the CPU
        self.client.generate(model=self.model, prompt="", keep_alive=0)

    def _question(self, title: str, word: dict) -> str:
        hint = (f"\"{word['word']}\" looks like one word broken in two by a scan or a line-break hyphen, probably "
                f"\"{word['suggestion']}\". If so, it's a typo and fix is the joined word; if they are two real words "
                f"here, it's fine." if " " in word["word"] else
                f"Our list of common misspellings says \"{word['word']}\" is usually a misspelling of \"{word['known']}\", "
                f"but some listed words are real in the right sentence (\"ageing\", \"ambience\")." if word["known"] else
                f"\"{word['word']}\" isn't in the English dictionary. The nearest dictionary word is \"{word['suggestion']}\", "
                f"which may or may not be what was meant.")
        return (f"You are proofreading a text on {self.site}.\nTitle: {title}\nSentence: {word['context']}\n\n{hint}\n\n"
                f"First write reading: what the sentence means at that word. Then decide. Answer \"typo\" when \"{word['word']}\" "
                f"is a mistake: a slip of the keys, a scanning error (\"tlie\" for \"the\"), a word split by a line-break hyphen "
                f"(\"revolu tion\"), or two words run together. Then put only the corrected word or words in fix, never the "
                f"sentence; it can differ from the nearest dictionary word. Answer \"fine\" when it is a real word the dictionary "
                f"lacks: an old spelling used on purpose (\"shew\", \"connexion\"), a word in another language (often inside a "
                f"quoted title or phrase), a term the author coined or a movement's own word (\"pantarchy\"), a technical or "
                f"political term, a name, or dialect. Old English is fine wherever the author writes or quotes it (\"thou "
                f"blanchest\", \"he loveth\", \"pil'd\", \"musick\", \"olde\"): it shows the text's age and is not to be modernised. "
                f"When unsure, answer \"fine\". Give a one-sentence reason a non-linguist can follow. Reply as JSON.")
