import json
import re
from pathlib import Path

RULES = Path(__file__).with_name("word_rules.json")  # learnt from wrong finds, one entry per misspelling; see its "about"


class WordRules:
    """What past mistakes taught about particular misspellings: sentences where the word is right, and a note for the judge."""

    def __init__(self, path: Path = RULES):
        words = json.loads(path.read_text(encoding="utf-8")).get("words", {}) if path.exists() else {}
        self.words = {wrong.lower(): rule for wrong, rule in words.items()}

    def fine_here(self, wrong: str, sentence: str) -> bool:
        rule = self.words.get(wrong.lower(), {})
        return any(re.search(pattern, sentence, re.I) for pattern in rule.get("fine_when", []))

    def note(self, wrong: str) -> str:
        return self.words.get(wrong.lower(), {}).get("note", "")
