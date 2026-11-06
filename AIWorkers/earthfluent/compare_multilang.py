import json
from collections import Counter
from pathlib import Path

from compare_methods import experts_decide, jury_votes
from dump_reader import WordRow
from jury import Jury
from opus_expert import OpusExpert
from wiktionary_online import WiktionaryOnline

HERE = Path(__file__).parent
CACHE = Path(r"E:\AIWorkers\data\wiktionary-online.json")


class Glosses:
    """One dictionary for a mixed-language batch: each site word's Wiktionary senses, looked up ahead in its own language."""

    def __init__(self, rows: list[WordRow]):
        self.by_word = {row.current: WiktionaryOnline(row.lang, CACHE).look_up(row.current) for row in rows}

    def look_up(self, phrase: str) -> list[str]:
        return self.by_word.get(phrase, [])


def testimony(rows: list[WordRow]) -> dict:
    said = {}
    for lang in sorted({r.lang for r in rows}):
        expert = OpusExpert(lang)  # one language's pair of models at a time, on the CPU
        said.update({r.id: expert.testify(r.english, r.current, r.lesson) for r in rows if r.lang == lang})
        print("testimony", lang, flush=True)
    return said


def score(name: str, verdicts: dict, rows: list[WordRow], wrong: set) -> dict:
    by_lang = {}
    for lang in sorted({r.lang for r in rows}):
        mine = [r for r in rows if r.lang == lang]
        caught = sum(1 for r in mine if r.id in wrong and verdicts[r.id] == "suspect")
        alarms = sum(1 for r in mine if r.id not in wrong and verdicts[r.id] == "suspect")
        by_lang[lang] = f"{caught}/{sum(1 for r in mine if r.id in wrong)} caught, {alarms} false"
    total_caught = sum(1 for r in rows if r.id in wrong and verdicts[r.id] == "suspect")
    total_alarms = sum(1 for r in rows if r.id not in wrong and verdicts[r.id] == "suspect")
    print(f"{name}: caught {total_caught}/{len(wrong)}, false alarms {total_alarms}/{len(rows) - len(wrong)}  {by_lang}", flush=True)
    return {"caught": total_caught, "false_alarms": total_alarms, "by_language": by_lang}


def main() -> None:
    key = json.loads((HERE / "answer_key_multilang.json").read_text(encoding="utf-8"))
    sample = json.loads((HERE / "sample_multilang.json").read_text(encoding="utf-8"))
    rows = [WordRow(**r) for r in sample if str(r["id"]) not in key["debatable"]]
    wrong = {int(i) for i in key["wrong"]}
    glosses, said = Glosses(rows), testimony(rows)
    results = {"A experts decide": score("A. experts decide", {r.id: experts_decide(r, said[r.id]) for r in rows}, rows, wrong)}
    cases = Jury(glosses, seed=7).judge(rows)  # votes alone, then the charged debate on the splits
    alone = {c.row.id: Counter(v["verdict"] for v in c.votes.values()).most_common(1)[0][0] for c in cases}
    results["C jury alone"] = score("C. jury votes alone", alone, rows, wrong)
    results["D jury debate with charge"] = score("D. debate with the jury charge", {c.row.id: c.verdict["verdict"] for c in cases}, rows, wrong)
    expert_vote = {r.id: experts_decide(r, said[r.id]) for r in rows}
    pooled = {c.row.id: _pool([v["verdict"] for v in c.votes.values()] + [expert_vote[c.row.id]]) for c in cases}
    results["E experts join the jury"] = score("E. experts join the jury (4 votes, a tie flags it)", pooled, rows, wrong)
    results["B experts testify"] = score("B. experts testify, jury votes", jury_votes(rows, said, glosses), rows, wrong)
    results["each juror alone"] = {juror: score(f"   juror {juror}", {c.row.id: c.votes[juror]["verdict"] for c in cases}, rows, wrong)
                                   for juror in next(iter(cases)).votes}
    (HERE / "compare_multilang_results.json").write_text(json.dumps({"results": results, "testimony": {str(k): v for k, v in said.items()},
        "debates": {str(c.row.id): c.debate for c in cases if c.debate}}, ensure_ascii=False, indent=1), encoding="utf-8")


def _pool(votes: list[str]) -> str:
    count = Counter(votes)
    return "suspect" if count["suspect"] >= count["ok"] else "ok"


if __name__ == "__main__":
    main()
