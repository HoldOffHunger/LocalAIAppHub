import json

import ollama

from dump_reader import WordRow

KINDS = ["wrong-word", "wrong-sense", "untranslated", "orthography", "register", "regional", "false-friend",
         "wrong-class", "corrupt", "structural", "wrong-form"]
VERDICT = {"type": "object", "properties": {"sense_needed": {"type": "string"}, "word_means": {"type": "string"},
                                            "verdict": {"type": "string", "enum": ["ok", "suspect"]},
                                            "kind": {"type": "string", "enum": [""] + KINDS},
                                            "proposed": {"type": "string"}, "reason": {"type": "string"}},
           "required": ["sense_needed", "word_means", "verdict", "kind", "proposed", "reason"]}  # thinking fields first, verdict after
LANGUAGES = {"it": "Italian", "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
             "ru": "Russian", "ja": "Japanese", "zh": "Chinese", "ko": "Korean", "hi": "Hindi", "id": "Indonesian"}


class WordCheck:
    """Asks a local model one narrow question: is this translation the right word, in the sense its lesson means?"""

    def __init__(self, model: str, dictionary, client: ollama.Client | None = None):
        self.model = model
        self.dictionary = dictionary
        self.client = client or ollama.Client()

    def check(self, row: WordRow, testimony: dict | None = None) -> dict:
        glosses = self.dictionary.look_up(row.current)
        question = self._question(row, glosses) + (_witnesses(row, testimony) if testimony else "")
        for tokens in (300, 600):  # a reply cut off mid-sentence gets one more try with more room
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}],
                                     format=VERDICT, options={"temperature": 0, "num_ctx": 2048, "num_predict": tokens}, keep_alive="10m",
                                     think=False)  # thinking models (Gemma 4) otherwise spend the whole budget musing
            try:
                return {**json.loads(reply.message.content), "dictionary": glosses}
            except json.JSONDecodeError:
                continue
        return {"verdict": "unanswered", "kind": "", "proposed": "", "reason": "The checker couldn't give a readable answer; ask again later.",
                "dictionary": glosses}

    def _question(self, row: WordRow, glosses: list[str]) -> str:
        language = LANGUAGES.get(row.lang, row.lang)
        evidence = "\n".join(f"- {gloss}" for gloss in glosses) or f"- (not found in the {language} dictionary)"
        return (f"You are checking one entry in a vocabulary list for people learning {language}.\n"
                f"Lesson: {row.lesson}\nEnglish word: {row.english}\n{language} translation on the site: {row.current}\n"
                f"What the {language} dictionary (Wiktionary) says \"{row.current}\" means:\n{evidence}\n\n"
                f"The lesson tells you which sense of the English word is meant (a bird in Animals, a country in Countries). "
                f"First write sense_needed: what the English word means in this lesson. Then word_means: what \"{row.current}\" "
                f"means, from the dictionary. If those two are different things, it is suspect. "
                f"Is \"{row.current}\" the word a {language} speaker would use for that sense, in its dictionary form? "
                f"Ignore capitalisation of the first letter. Answer \"ok\" whenever it is a correct word for that sense, even if "
                f"another word would also do or it's a little formal. These translations came from Google Translate, which leaves "
                f"a word in English when it can't translate it. So a translation identical to the English is a reason to look hard: "
                f"it's right for names and international words (Kenya, sushi, radio), and wrong for ordinary words {language} has its "
                f"own word for (stapler, kettle, gloomy). "
                f"Only answer \"suspect\" when it is clearly wrong: a different thing, the wrong sense, garbled, misspelled, "
                f"not {language} at all, or a phrase or verb form where the dictionary word belongs. For ok, leave kind and proposed "
                f"empty. For suspect, pick the kind ({', '.join(KINDS)}), give the correct {language} word in proposed, "
                f"and a one-sentence reason a non-linguist can follow. Reply as JSON.")


def _witnesses(row: WordRow, testimony: dict) -> str:
    # Expert translation models' testimony: evidence to weigh, alongside the dictionary
    return (f"\n\nTwo translation experts (OPUS-MT) also testified:\n"
            f"- \"{row.current}\" translated back into English: \"{testimony['back']}\"\n"
            f"- \"{row.english}\" ({testimony['hint'] or 'no hint'}) translated into the language: \"{testimony['across']}\"\n"
            "Synonyms are fine: if the experts give a different word that means the same thing, the site's word can still be ok. "
            "But if the back-translation names a different thing, or the site's word is just the English left untranslated "
            "while the expert gives a real translation, that is evidence it is wrong.")
