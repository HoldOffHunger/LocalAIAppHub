import re
from pathlib import Path

from ggcms_words import WORDS

ENTRY = re.compile(r"^\t\t\t\t'((?:[^'\\]|\\.)*)'=>\[\r?$")


def quote(text: str) -> str:
    return "'" + text.replace("\\", "\\\\").replace("'", "\\'") + "'"


def letter_of(correct: str) -> str:
    # The engine loads EnglishMisspellingsWords_0 and _A to _Z; anything not starting with a plain letter lives in _0
    first = correct[:1].upper()
    return first if "A" <= first <= "Z" else "0"


def merge(pairs: dict[str, str], folder: str = "EnglishMisspellings", log=print) -> int:
    """Adds wrong -> correct pairs to GGCMS's per-letter misspelling files, as the engine's own 'correct'=>['wrong',] blocks:
    into the correct word's block if it has one, otherwise as a new block in sorted place. Returns how many were added."""
    by_file: dict[str, dict[str, list[str]]] = {}
    for wrong, correct in pairs.items():
        by_file.setdefault(letter_of(correct), {}).setdefault(correct, []).append(wrong)
    added = 0
    for letter, groups in sorted(by_file.items()):
        if letter == "0":
            # _0 is code that generates the number problems ("1870's"), not a list: 'twas and étale have no file to go to
            log(f"left out, no list for corrections that don't start with a letter: {', '.join(sorted(groups))}")
            continue
        path = WORDS / folder / f"{folder}Words_{letter}.php"
        with path.open(encoding="utf-8", newline="") as page:  # as the bytes are: no CRLF translation either way
            lines = page.read().split("\n")
        start = next(n for n, line in enumerate(lines) if line.strip() == "return [")
        end = next(n for n in range(start, len(lines)) if lines[n].strip() == "];")
        for correct, wrongs in sorted(groups.items()):
            keys = {_unquote(m.group(1)): n for n in range(start, end) if (m := ENTRY.match(lines[n]))}
            # New lines take the ending of the line they go beside: the files mix LF and CRLF, and a line of the wrong
            # ending reads as a change to the whole file
            if correct in keys:
                close = next(n for n in range(keys[correct], end) if lines[n].strip() == "],")
                eol = "\r" if lines[close].endswith("\r") else ""
                have = {_unquote(line.strip().rstrip(",").strip("'")).lower() for line in lines[keys[correct] + 1:close]}
                new = [f"\t\t\t\t\t{quote(w)},{eol}" for w in sorted(wrongs) if w.lower() not in have]
                lines[close:close] = new
            else:
                at = next((n for k, n in sorted(keys.items(), key=lambda kv: kv[1]) if k > correct), end)
                eol = "\r" if lines[at].endswith("\r") else ""
                new = [f"\t\t\t\t\t{quote(w)},{eol}" for w in sorted(wrongs)]
                lines[at:at] = [f"\t\t\t\t{quote(correct)}=>[{eol}", *new, f"\t\t\t\t],{eol}"]
            added += len(new)
            end += len(new) + (0 if correct in keys else 2)
        with path.open("w", encoding="utf-8", newline="") as page:
            page.write("\n".join(lines))
        log(f"{path.name}: {sum(len(w) for w in groups.values())} pairs offered")
    return added


def _unquote(text: str) -> str:
    return re.sub(r"\\(.)", r"\1", text)
