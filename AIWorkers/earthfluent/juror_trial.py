import itertools
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from compare_multilang import Glosses, score
from dump_reader import WordRow
from word_check import WordCheck

# Auditions jurors one at a time on the 12-language test, keeps every vote, then scores every jury of three from the saved votes
HERE = Path(__file__).parent
VOTES = Path(r"E:\AIWorkers\data\juror_votes.json")
STOP_AT = "02:45"  # Autonoma's free time starts at 3


def audition(models: list[str], rows: list[WordRow], glosses) -> dict:
    votes = json.loads(VOTES.read_text(encoding="utf-8")) if VOTES.exists() else {}
    for model in models:
        mine = votes.setdefault(model, {})
        check = WordCheck(model, glosses)
        for row in rows:
            if datetime.now().strftime("%H:%M") >= STOP_AT and datetime.now().hour < 12:
                print("stopping for Autonoma's free time", flush=True)
                return votes
            if str(row.id) not in mine:
                mine[str(row.id)] = check.check(row)["verdict"]
                VOTES.write_text(json.dumps(votes, indent=1), encoding="utf-8")
        print("auditioned", model, flush=True)
    return votes


def juries(votes: dict, rows: list[WordRow], wrong: set) -> None:
    complete = [m for m, v in votes.items() if all(str(r.id) in v for r in rows)]
    for model in complete:
        score(f"alone: {model}", {r.id: votes[model][str(r.id)] for r in rows}, rows, wrong)
    for trio in itertools.combinations(complete, 3):
        verdicts = {r.id: Counter(votes[m][str(r.id)] for m in trio).most_common(1)[0][0] for r in rows}
        score(f"jury: {' + '.join(trio)}", verdicts, rows, wrong)


if __name__ == "__main__":
    key = json.loads((HERE / "answer_key_multilang.json").read_text(encoding="utf-8"))
    rows = [WordRow(**r) for r in json.loads((HERE / "sample_multilang.json").read_text(encoding="utf-8")) if str(r["id"]) not in key["debatable"]]
    votes = audition(sys.argv[1:], rows, Glosses(rows))
    juries(votes, rows, {int(i) for i in key["wrong"]})
