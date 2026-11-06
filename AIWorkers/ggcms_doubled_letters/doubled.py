import re
import sys
from pathlib import Path

from spellchecker import SpellChecker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dump_tables import DumpTables  # noqa: E402
from english_wiktionary import EnglishWiktionary  # noqa: E402
from ggcms_words import british_spellings, known_misspellings  # noqa: E402

WEBSTER = Path(r"E:\Code\DB-Backups\2026-09-06\alldictionaries.sql.gz")  # Webster's 1913, the dictionaries site's only dictionary
PLAIN = re.compile(r"[a-z]+")

# A dropped letter that leaves a real word plus an ending is probably real: Webster lists "idle" but never "idles"
ENDINGS = (("ies", "y"), ("es", ""), ("s", ""), ("ied", "y"), ("ed", ""), ("ed", "e"), ("ing", ""), ("ing", "e"),
           ("er", ""), ("er", "e"), ("est", ""), ("ly", ""))


def webster_words(dump: Path = WEBSTER) -> set[str]:
    words = set()
    for _, row in DumpTables(dump).rows({"Definition"}):
        for field in (row["Term"], row["AlternateSpelling"]):
            for word in re.split(r"[;,]\s*", field):
                if word.strip():
                    words.add(word.strip().lower())
    return words


class DoubledLetters:
    """Every common English word with a doubled letter, and its two slips: one letter dropped ("wordles") and one added
    ("wordlesss"). A dropped letter often lands on another real word (dessert, desert), and those never go in the list."""

    def __init__(self, frequencies: dict[str, int], real: set[str], listed: set[str], webster: set[str] = frozenset()):
        self.frequencies = frequencies
        self.real = real
        self.listed = listed
        self.webster = webster

    @classmethod
    def load(cls, log=print) -> "DoubledLetters":
        frequencies = dict(SpellChecker().word_frequency.dictionary)
        log("reading Webster's 1913")
        listed = known_misspellings()
        webster = webster_words()
        modern = set(frequencies) | british_spellings() | {w.lower() for w in listed.values()}
        wiktionary = EnglishWiktionary()
        wiktionary.build(log=log)  # once per download; it reads 26 GB
        modern |= wiktionary.words()  # every inflected form ("idles", "princes"), and loanwords
        # Webster's spellings only it knows (mispell, mispend) are old forms a modern writer would mean as slips, so those
        # go to the judge rather than being thrown out
        return cls(frequencies, modern, set(listed) - modern - webster, webster)

    def items(self, pair: str) -> tuple[list[dict], dict]:
        # Most used first, so the words worth most are judged first; pyspellchecker's floor (about 50) is the rarity cut, which
        # leaves out Webster's diskindness and docoglossa: they only ever serve as real words here
        words = sorted((w for w in self.frequencies if PLAIN.fullmatch(w) and pair in w and pair[0] * 3 not in w),
                       key=lambda w: (-self.frequencies[w], w))
        items = [{"id": n, "word": w, "frequency": self.frequencies[w], "variants": self.variants(w, pair),
                  "in_webster": w in self.webster or bool(self.inflection_of(w, self.webster))}
                 for n, w in enumerate(words, 1)]
        return items, {"filled_from": "pyspellchecker + Webster 1913", "pair": pair, "words": len(items)}

    def variants(self, word: str, pair: str) -> list[dict]:
        found = []
        spots = [m.start() for m in re.finditer(f"(?={pair})", word)]
        for kind, swap in (("dropped", pair[0]), ("tripled", pair[0] * 3)):
            for at in spots:
                variant = word[:at] + swap + word[at + 2:]
                if variant in (v["variant"] for v in found):
                    continue
                found.append({"variant": variant, "kind": kind, "verdict": self.verdict(variant, kind)})
        return found

    def verdict(self, variant: str, kind: str) -> str:
        if variant in self.real:
            return "real word"
        if variant in self.listed:
            return "already listed"
        if kind == "dropped" and (stem := self.inflection_of(variant, self.real | self.webster)):
            return f"real word ({stem} + ending)"
        if variant in self.webster:
            return "open (Webster only)"
        return "open"

    def inflection_of(self, variant: str, real: set[str]) -> str:
        for end, back in ENDINGS:
            if variant.endswith(end):
                stem = variant[:-len(end)] + back
                if len(stem) < 4:
                    continue  # Webster has "mis", but "mised" isn't mis + ed
                if end == "es" and not re.search("(s|x|z|ch|sh|o)$", stem):
                    continue  # "archeres" isn't archer + es
                if stem in real:
                    return stem
                if end in ("ed", "ing", "er", "est") and stem[-1] == stem[-2] and stem[:-1] in real:
                    return stem[:-1]
        return ""
