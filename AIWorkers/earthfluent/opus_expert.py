import re
from pathlib import Path

from transformers import MarianMTModel, MarianTokenizer

MODELS = Path(r"E:\AIModels\opus-mt")  # Ben keeps every model under E:\AIModels
ARTICLES = r"^(il|lo|la|i|gli|le|un|uno|una|l'|un'|el|los|las|le|les|der|die|das|de|het|een|o|a|os|as)\s+"
# Pairs Helsinki-NLP doesn't publish fall back to the multilingual models, steered by a target-language token
BACK = {"pt": ("opus-mt-mul-en", "")}
ACROSS = {"pl": ("opus-mt-en-mul", ">>pol<< "), "pt": ("opus-mt-en-mul", ">>por<< "), "ko": ("opus-mt-en-mul", ">>kor<< "),
          "ja": ("opus-mt-en-jap", "")}


class OpusExpert:
    """OPUS-MT as an expert witness: the site's word translated back to English, and the English word, in its lesson's sense, translated across."""

    def __init__(self, lang: str):
        self.back, self.back_tag = self._load(*BACK.get(lang, (f"opus-mt-{lang}-en", "")))
        self.across, self.across_tag = self._load(*ACROSS.get(lang, (f"opus-mt-en-{lang}", "")))

    def testify(self, english: str, current: str, lesson: str) -> dict:
        hint = lesson_hint(lesson)
        back = self._translate(self.back, self.back_tag + current)
        across = self._translate(self.across, self.across_tag + (f"{english} ({hint})" if hint else english))
        return {"back": back, "across": re.sub(r"\s*[(（].*$", "", across).strip(" .。"), "hint": hint}

    def _load(self, name: str, tag: str):
        return (MarianTokenizer.from_pretrained(MODELS / name), MarianMTModel.from_pretrained(MODELS / name)), tag

    def _translate(self, pair, text: str) -> str:
        tokenizer, model = pair
        out = model.generate(**tokenizer([text], return_tensors="pt"), max_new_tokens=40)
        return tokenizer.decode(out[0], skip_special_tokens=True)


def lesson_hint(lesson: str) -> str:
    # "Nouns - Animals, Part 11" -> "animal"; "Adjectives - Feeling" -> "feeling"; "(no lesson)" -> ""
    if " - " not in lesson:
        return ""
    part = lesson.split(" - ", 1)[-1].split(",")[0].strip().lower()
    kind = lesson.split(" - ", 1)[0].strip().lower()
    word = part[:-3] + "y" if part.endswith("ies") else (part[:-1] if part.endswith("s") and not part.endswith("ss") else part)
    return {"verbs": f"verb, {word}", "adjectives": f"adjective, {word}"}.get(kind, word)


def same_word(one: str, other: str) -> bool:
    clean = lambda text: re.sub(ARTICLES, "", text.strip().lower()).strip(" .!。")
    return clean(one) == clean(other)
