from pathlib import Path

from dictionary_index import DictionaryIndex
from dump_reader import WordRow
from jury import Jury
from known_cases import CASES

# The jury against the same 12 known answers the single models were scored on
jury = Jury(DictionaryIndex(Path(r"E:\AIWorkers\data\dictionary-it.sqlite")), seed=1)
cases = jury.judge([WordRow(0, 0, 0, lesson, "it", english, current) for english, current, lesson, _ in CASES])
right = 0
for case, (_, _, _, wrong) in zip(cases, CASES):
    hit = (case.verdict["verdict"] == "suspect") == wrong
    right += hit
    print(f"{'ok  ' if hit else 'MISS'} {case.row.english} -> {case.row.current}: {case.verdict['verdict']} ({case.verdict['how']}) {case.verdict['proposed']}")
    for turn in case.debate[3:]:
        print(f"      {turn['juror']}: {turn['position']} — {turn['argument'][:140]}")
print(f"jury: {right}/{len(CASES)} judged as a person would")
