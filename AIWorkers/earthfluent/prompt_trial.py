import sys
from pathlib import Path

from dictionary_index import DictionaryIndex
from dump_reader import WordRow
from known_cases import CASES
from word_check import WordCheck

model = sys.argv[1] if len(sys.argv) > 1 else "gemma3:4b"
check = WordCheck(model, DictionaryIndex(Path(r"E:\AIWorkers\data\dictionary-it.sqlite")))
right = 0
for english, current, lesson, wrong in CASES:
    verdict = check.check(WordRow(0, 0, 0, lesson, "it", english, current))
    hit = (verdict["verdict"] == "suspect") == wrong
    right += hit
    print(f"{'ok  ' if hit else 'MISS'} {english} -> {current}: {verdict['verdict']} {verdict['reason'][:80]}")
print(f"{model}: {right}/{len(CASES)} judged as a person would")
