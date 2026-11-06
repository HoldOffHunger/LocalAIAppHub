import json
import sys
from pathlib import Path

from compare_multilang import Glosses, score
from dump_reader import WordRow
from cloudflare_judge import CloudflareJudge
from gemini_judge import GeminiJudge
from openai_judge import OpenAIJudge
from word_check import WordCheck

# The two-stage court on the 12-language test: local screeners flag, the senior judge in the cloud decides the flagged ones
HERE = Path(__file__).parent
VOTES = Path(r"E:\AIWorkers\data\juror_votes.json")
SENIOR_DIR = Path(r"E:\AIWorkers\data")  # one votes file per judge, so two trials can run side by side


def main(model: str) -> None:
    key = json.loads((HERE / "answer_key_multilang.json").read_text(encoding="utf-8"))
    rows = [WordRow(**r) for r in json.loads((HERE / "sample_multilang.json").read_text(encoding="utf-8")) if str(r["id"]) not in key["debatable"]]
    wrong, local = {int(i) for i in key["wrong"]}, json.loads(VOTES.read_text(encoding="utf-8"))
    glosses = Glosses(rows)
    judge = (GeminiJudge(glosses, model) if model.startswith("gemini") else CloudflareJudge(glosses, model) if model.startswith("@cf/")
             else OpenAIJudge(glosses, model) if model.startswith("gpt-")
             else OpenAIJudge(glosses, model.split(":", 1)[1], model.split(":", 1)[0]) if model.startswith(("nvidia:", "hf:"))
             else WordCheck(model, glosses))  # a cloud judge, or a big local one
    SENIOR = SENIOR_DIR / f"senior_votes_{model.replace(':', '_').replace('/', '_').replace('@', '')}.json"
    senior = json.loads(SENIOR.read_text(encoding="utf-8")) if SENIOR.exists() else {}
    mine = senior.setdefault(model, {})
    for row in rows:  # the judge sees every word once, so it can also be scored on its own
        if str(row.id) not in mine:
            verdict = judge.check(row)["verdict"]
            if verdict == "unanswered":
                print(f"{model} stopped answering (likely out of free quota) after {len(mine)} words; run again later to finish", flush=True)
                return
            mine[str(row.id)] = verdict
            SENIOR.write_text(json.dumps(senior, indent=1), encoding="utf-8")
    flagged = lambda r: "suspect" in (local["mistral:7b"][str(r.id)], local["llama3.1:8b"][str(r.id)])
    score(f"{model} alone", {r.id: mine[str(r.id)] for r in rows}, rows, wrong)
    score(f"screen (mistral OR llama) then {model}", {r.id: mine[str(r.id)] if flagged(r) else "ok" for r in rows}, rows, wrong)
    score(f"screen (mistral alone) then {model}", {r.id: mine[str(r.id)] if local["mistral:7b"][str(r.id)] == "suspect" else "ok" for r in rows}, rows, wrong)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "gemini-3.8-flash")
