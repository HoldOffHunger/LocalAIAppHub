import json
import re
import sqlite3
from pathlib import Path

from dictionary_index import DictionaryIndex
from dump_reader import WordRow
from jury import JURORS
from opus_expert import OpusExpert, same_word
from word_check import WordCheck

HERE = Path(__file__).parent
QUEUE = Path(r"E:\AIWorkers\data\earthfluent-review.sqlite")


def key_rows() -> tuple[list[WordRow], dict]:
    key = json.loads((HERE / "answer_key_it.json").read_text(encoding="utf-8"))
    rows = [WordRow(**json.loads(w)) for (w,) in sqlite3.connect(QUEUE).execute("SELECT word FROM rows WHERE lang = 'it' ORDER BY id")]
    picked = [r for r in rows if r.lesson.startswith(("Nouns - Animals", "Culture - Countries")) and str(r.id) not in key["debatable"]]
    return picked, key


def experts_decide(row: WordRow, said: dict) -> str:
    # Ben's method: the experts alone. Fine if either expert agrees with the site; flagged if both disagree
    back_words = set(re.findall(r"[a-z]+", said["back"].lower()))
    back_ok = set(re.findall(r"[a-z]+", row.english.lower())) <= back_words
    return "ok" if same_word(said["across"], row.current) or back_ok else "suspect"


def jury_votes(rows: list[WordRow], testimony: dict, dictionary) -> dict:
    # Batched by juror, so each model loads once; independent votes, the majority decides
    votes = {row.id: [] for row in rows}
    for juror in JURORS:
        check = WordCheck(juror, dictionary)
        for row in rows:
            votes[row.id].append(check.check(row, testimony.get(row.id))["verdict"])
    return {rid: max(set(v), key=v.count) for rid, v in votes.items()}


def score(name: str, verdicts: dict, rows: list[WordRow], key: dict) -> dict:
    wrong = set(int(i) for i in key["wrong"])
    caught = sorted(r.english for r in rows if r.id in wrong and verdicts[r.id] == "suspect")
    missed = sorted(r.english for r in rows if r.id in wrong and verdicts[r.id] != "suspect")
    alarms = sorted(f"{r.english}->{r.current}" for r in rows if r.id not in wrong and verdicts[r.id] == "suspect")
    print(f"{name}: caught {len(caught)}/{len(wrong)}, false alarms {len(alarms)}/{len(rows) - len(wrong)}\n  missed: {missed}\n  false alarms: {alarms}", flush=True)
    return {"caught": caught, "missed": missed, "false_alarms": alarms}


def main() -> None:
    rows, key = key_rows()
    expert = OpusExpert("it")
    testimony = {row.id: expert.testify(row.english, row.current, row.lesson) for row in rows}
    dictionary = DictionaryIndex(Path(r"E:\AIWorkers\data\dictionary-it.sqlite"))
    results = {"experts decide": score("A. experts decide", {r.id: experts_decide(r, testimony[r.id]) for r in rows}, rows, key),
               "jury with experts": score("B. experts testify, jury votes", jury_votes(rows, testimony, dictionary), rows, key),
               "jury alone": score("C. jury alone (before)", jury_votes(rows, {}, dictionary), rows, key)}
    (HERE / "compare_results.json").write_text(json.dumps({"testimony": {r.english + "|" + r.lesson: testimony[r.id] for r in rows}, **results},
                                                          indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
