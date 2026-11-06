import re
from pathlib import Path

WORDS = Path(r"E:\GGCMS\usr\lib\ggcms\src\classes\Language\Words")
STRING = r"'((?:[^'\\]|\\.)*)'"
HEADWORD = re.compile(rf"^\s*{STRING}=>\[\s*$")
VARIANT = re.compile(rf"^\s*{STRING},\s*$")
PAIR = re.compile(rf"^\s*{STRING}=>{STRING},\s*$")
SPELLINGS = re.compile(rf"^\s*{STRING}=>\[(.*)\],\s*$")  # one US spelling, several UK: 'garroting'=>['garrotting', 'garotting',],


def _unquote(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)


def known_misspellings(folders=("EnglishMisspellings", "IntensiveEnglishMisspellings")) -> dict[str, str]:
    """GGCMS's own misspelling dictionaries, as misspelling -> correct word (read from the engine's PHP word classes)."""
    found = {}
    for folder in folders:
        for path in sorted((WORDS / folder).glob("*.php")):
            correct = None
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if match := HEADWORD.match(line):
                    correct = _unquote(match.group(1))
                elif correct and (match := VARIANT.match(line)):
                    wrong = _unquote(match.group(1)).lower()
                    if wrong != correct.lower():
                        found.setdefault(wrong, correct)
                elif line.strip().startswith("]"):
                    correct = None
    return found


def british_spellings() -> set[str]:
    """Both sides of GGCMS's American/British pairs: either spelling is right on these sites."""
    words = set()
    for path in sorted((WORDS / "AmericanBritish").glob("*.php")):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            if match := PAIR.match(line):
                words.update(_unquote(match.group(n)).lower() for n in (1, 2))
            elif match := SPELLINGS.match(line):
                # Until 3 Nov 2026 only the one-to-one lines were read, so these 1,437 entries' spellings counted as
                # unknown everywhere ("garotting" was listed as a typo on Wikipedia)
                words.add(_unquote(match.group(1)).lower())
                words.update(_unquote(spelling).lower() for spelling in re.findall(STRING, match.group(2)))
    return words
