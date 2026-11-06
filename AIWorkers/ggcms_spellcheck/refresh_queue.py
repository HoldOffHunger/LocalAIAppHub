import argparse
import json
import re
import sys
from pathlib import Path

from spellchecker import SpellChecker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from fill_queue import gather  # noqa: E402
from ggcms_words import british_spellings  # noqa: E402
from spell_queue import SpellQueue  # noqa: E402
from text_words import TextWords  # noqa: E402

# Brings a pile filled by an older reader up to date: the unjudged texts are read again from the same dump, and the
# judged verdicts are tidied by the rules added since (24 Oct 2026: splits, old English, plurals, fixes that change nothing)


def revise(verdict: dict, reader: TextWords) -> dict:
    if verdict["verdict"] != "typo":
        return verdict
    word, fix = verdict["word"], verdict["fix"].strip()
    if fix.lower() == word.lower():
        return {**verdict, "verdict": "fine", "reason": f"Called a typo, but the fix was the word itself. {verdict['reason']}"}
    if " " not in word and (reader._plural(word.lower()) or reader._old(word.lower())):
        return {**verdict, "verdict": "fine", "reason": f"A plural or an old English form of a real word. {verdict['reason']}"}
    if span := split_span(word, fix, verdict["context"]):
        return {**verdict, "word": span, "fix": fix}
    return verdict


def split_span(word: str, fix: str, context: str) -> str:
    # "inhe" judged with fix "inheritance", in "the common inhe ritance of": the span to replace is "inhe ritance"
    if " " in word or " " in fix or len(fix) <= len(word):
        return ""
    for pattern in (rf"\b({re.escape(word)}) (\w+)\b", rf"\b(\w+) ({re.escape(word)})\b"):
        for match in re.finditer(pattern, context):
            if (match.group(1) + match.group(2)).lower() == fix.lower():
                return f"{match.group(1)} {match.group(2)}"
    return ""


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-read a spellcheck pile's unjudged texts and tidy its judged verdicts.")
    parser.add_argument("--queue", required=True)
    queue = SpellQueue(Path(parser.parse_args().queue))
    reader = TextWords(SpellChecker(distance=1), british_spellings(), {})
    changed = 0
    with queue.connection:
        for text_id, verdicts in queue.connection.execute("SELECT id, verdicts FROM texts WHERE verdicts IS NOT NULL").fetchall():
            old = json.loads(verdicts)
            new = [revise(v, reader) for v in old]
            if new != old:
                changed += sum(a != b for a, b in zip(old, new))
                queue.connection.execute("UPDATE texts SET verdicts = ? WHERE id = ?", (json.dumps(new, ensure_ascii=False), text_id))
    print("judged verdicts revised:", changed, flush=True)
    texts, about = gather(Path(queue.meta("filled_from")), log=lambda line: print(line, flush=True))
    queue.refill_pending(texts, about)
    print("refilled:", about, queue.counts(), flush=True)


if __name__ == "__main__":
    main()
