import json

import ollama

VERDICT = {"type": "object", "properties": {"reading": {"type": "string"}, "verdict": {"type": "string", "enum": ["typo", "fine"]},
                                            "fix": {"type": "string"}, "reason": {"type": "string"}},
           "required": ["reading", "verdict", "fix", "reason"]}  # the reading first, so the model looks before it rules


class TypoJudge:
    """Asks a local model one narrow question: in this Wikipedia sentence, is this listed misspelling really a slip?"""

    def __init__(self, model: str, client: ollama.Client | None = None):
        self.model = model
        self.client = client or ollama.Client()

    def check(self, title: str, wrong: str, correct: str, place: dict, note: str = "") -> dict:
        question = self._question(title, wrong, correct, place, note)
        for tokens in (250, 500):  # a reply cut off mid-sentence gets one more try with more room
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}], format=VERDICT,
                                     options={"temperature": 0, "num_ctx": 2048, "num_predict": tokens}, keep_alive="10m", think=False)
            try:
                verdict = json.loads(reply.message.content)
            except json.JSONDecodeError:
                continue
            if verdict.get("verdict") == "typo" and verdict.get("fix", "").strip().lower() == wrong.lower():
                verdict.update(verdict="fine", reason=f"Called a typo, but the fix was the word itself. {verdict.get('reason', '')}")
            return verdict
        return {"verdict": "unanswered", "fix": "", "reason": "The checker couldn't give a readable answer; ask again later."}

    def release(self) -> None:
        self.client.generate(model=self.model, prompt="", keep_alive=0)

    @staticmethod
    def _question(title: str, wrong: str, correct: str, place: dict, note: str = "") -> str:
        # Wikipedia's own rule (MOS:TYPOFIX): a trivial slip in a quotation is corrected; an old text's own spelling is kept
        setting = (" It stands inside quotation marks. Wikipedia corrects plain slips in quotations from modern sources, but keeps "
                   "the spelling of old texts and anything the source spelled that way on purpose." if place["quoted"] else "") + \
                  (" It is in italics, which on Wikipedia usually marks the title of a book, film, album or ship." if place["italic"] else "")
        return (f"You are proofreading the English Wikipedia article \"{title}\".\nSentence: {place['sentence']}\n\n"
                f"A list of common misspellings says \"{place['word']}\" is usually a misspelling of \"{correct}\", but some "
                f"listed words are right in the right sentence.{setting}"
                f"{(' A note from past mistakes with this word: ' + note) if note else ''}\n\n"
                f"First write reading: what the sentence means at that word. Then decide. Answer \"typo\" only when "
                f"\"{place['word']}\" is plainly a mistake the article's editors would want fixed: a slip of the keys, a "
                f"misspelling, a doubled word, or two words run together. Put only the corrected word or words in fix, never "
                f"the sentence. Answer \"fine\" when it is correct here: British, Australian or other national spellings "
                f"(Wikipedia keeps whichever the article uses: \"colour\", \"organise\", \"ageing\" are all fine), a name of a "
                f"person, place, band or company, the title of a work, a word in another language, an old text's spelling "
                f"(\"shew\", \"connexion\"), slang or dialect used on purpose, or a term of art. When unsure, answer \"fine\". "
                f"Give a one-sentence reason a non-linguist can follow. Reply as JSON.")
