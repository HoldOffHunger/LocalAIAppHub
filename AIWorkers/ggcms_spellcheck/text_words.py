import html
import re
from dataclasses import dataclass, field

TAG = re.compile(r"<[^>]+>")
ADDRESS = re.compile(r"(?:https?://|www\.)\S+|\S+@\S+\.\w+|\S+\.(?:com|org|net|info|io)\b\S*")  # web and mail addresses aren't prose
WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)*")  # whole words in any alphabet, so "Führungs" isn't read as "F" and "hrungs"
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
OLD_VERB = re.compile(r"[a-z]{3,}eth$")  # "loveth": with OLD_WORDS, marks a sentence written in old English
# Old English an author quotes on purpose: the words themselves, and (in _old) the endings worn by modern stems
OLD_WORDS = {"thee", "thou", "thy", "thine", "ye", "hath", "doth", "dost", "hast", "wert", "wast", "shalt", "wilt", "canst",
             "didst", "couldst", "wouldst", "shouldst", "mayst", "mightst", "hither", "thither", "whence", "whither", "ere", "oft",
             "betwixt", "shew", "shewn", "shews", "shewed", "shewing", "connexion", "connexions", "olde", "spake", "unto",
             "wherefore", "methinks", "forsooth", "prithee", "yclept", "confest", "twas", "tis", "o'er", "e'en", "ne'er", "e'er",
             "whilom", "fain", "quoth", "wot", "wist", "verily", "eke"}


@dataclass
class Candidate:
    """One word in one text that might be misspelled, with the sentence it first appears in."""

    word: str  # or two, when one word was split ("inhe ritance"): the whole span is what gets replaced
    context: str
    count: int = 1
    known: str = ""  # GGCMS's misspelling list already says what it should be
    suggestion: str = ""  # the spellchecker's nearest dictionary word, or the joined word for a split


@dataclass
class TextWords:
    """Splits one TextBody into the words a spellchecker should look at: unknown ones, ones GGCMS knows are misspellings,
    and words broken in two by a scan or a line-break hyphen."""

    dictionary: object  # a SpellChecker
    allowed: set[str]  # extra right words: British spellings, Ben's tags
    known: dict[str, str]  # misspelling -> correct, from GGCMS
    unknown: dict[str, Candidate] = field(default_factory=dict)

    def read(self, markup: str) -> dict[str, Candidate]:
        text = re.sub(r"\s+", " ", ADDRESS.sub(" ", html.unescape(TAG.sub(" ", markup))))
        self.unknown = {}
        for sentence in SENTENCE_END.split(text):
            words = [word.replace("’", "'") for word in WORD.findall(sentence)]
            old = any(w.lower() in OLD_WORDS or OLD_VERB.match(w.lower()) for w in words)
            place = 0
            while place < len(words):
                if place + 1 < len(words) and self._split(words[place], words[place + 1], sentence):
                    place += 2
                    continue
                self._consider(words[place], sentence, opens=place == 0, old=old)
                place += 1
        return self.unknown

    def _split(self, first: str, second: str, sentence: str) -> bool:
        # "recog nition": joined, a real word, though one half or both aren't. Two real words ("an other") are left alone.
        joined = (first + second).lower()
        if len(joined) < 6 or not (first + second).isalpha() or not second.islower():
            return False
        if self._real(first.lower()) and self._real(second.lower()) or not self.dictionary.known([joined]):
            return False
        span = f"{first} {second}"
        if not re.search(rf"\b{re.escape(first)} {re.escape(second)}\b", sentence):
            return False  # something stood between them in the text (a dash, a footnote mark): not one word
        if span.lower() in self.unknown:
            self.unknown[span.lower()].count += 1
        else:
            self.unknown[span.lower()] = Candidate(span, _around(sentence, span), suggestion=first[0] + joined[1:])
        return True

    def _consider(self, word: str, sentence: str, opens: bool = False, old: bool = False) -> None:
        lower = word.lower()
        if lower in self.unknown:
            self.unknown[lower].count += 1
            return
        if lower in self.known and (word.islower() or opens):  # "Teh" opening a sentence counts; "Jos" mid-sentence is a name
            self.unknown[lower] = Candidate(word, _around(sentence, word), known=self.known[lower])
            return
        if len(word) < 3 or not word.islower() or not word.isascii():  # names and foreign words are different jobs
            return
        stem = lower[:-2] if lower.endswith("'s") else lower.rstrip("'")
        if self._real(stem) or self._plural(stem) or self._old(stem, old):
            return
        self.unknown[lower] = Candidate(word, _around(sentence, word))

    def _real(self, word: str) -> bool:
        return word in self.allowed or bool(self.dictionary.known([word]))

    def _plural(self, word: str) -> bool:
        # The dictionary lacks many plurals ("abolitions", "metalloids"); a real word plus s is no slip
        # Short stems let slips through ("wents", "mus", "pts"), so the stem needs five letters, and the plural must be
        # formed the English way: not "necessitys" or "chamberes"
        if word.endswith("ies"):
            stem = word[:-3] + "y"
        elif word.endswith("es") and re.search(r"(?:s|x|z|ch|sh|o)es$", word):
            stem = word[:-2]
        elif word.endswith("s") and not re.search(r"(?:[^aeiou]y|e)s$|ss$", word) or word.endswith("es"):
            stem = word[:-1]
        else:
            return False
        return len(stem) >= 5 and self._real(stem)

    def _old(self, word: str, old_sentence: bool = False) -> bool:
        # Old English quoted as it was written: "thou blanchest", "he loveth", "pil'd", "musick", "olde". Only on a real
        # stem, so "hohest" (holiest) is still a slip
        if word in OLD_WORDS:
            return True
        stems = []
        if word.endswith(("est", "eth")):
            base = word[:-3]
            stems += [base, base + "e", base[:-1] if len(base) > 2 and base[-1] == base[-2] else "",
                      base[:-1] + "y" if base.endswith("i") else ""]
        if word.endswith(("'d", "'st")):
            base = word[:word.rindex("'")]
            stems += [base + "ed", base + "d", base, base[:-1] + "ied" if base.endswith("i") else ""]
        if word.endswith("ick"):
            stems.append(word[:-1])  # musick, publick
        if word.endswith("e") and len(word) > 4 and old_sentence:
            stems.append(word[:-1])  # "ye olde", but only among other old words: alone, "potatoe" and "smalle" are slips
        return any(len(stem) > 2 and self._real(stem) for stem in stems)


def _around(sentence: str, word: str, reach: int = 140) -> str:
    # The sentence, cut to about 280 characters centred on the word, for long run-ons
    at = sentence.find(word)
    start, end = max(0, at - reach), min(len(sentence), at + len(word) + reach)
    return ("…" if start else "") + sentence[start:end].strip() + ("…" if end < len(sentence) else "")
