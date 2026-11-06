import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from doubled import DoubledLetters  # noqa: E402
from letter_judge import LetterJudge  # noqa: E402
from task_queue import TaskQueue  # noqa: E402


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Doubled-letter slips (wordles, wordlesss) for GGCMS's misspelling lists.")
    parser.add_argument("--target", default="ss", help="the doubled letter: ss, ll, tt...")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the pairs are written for Claude to confirm")
    parser.add_argument("--limit", type=int, default=200, help="words to judge this run")
    parser.add_argument("--judge", default="gemma4:12b")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def main() -> None:
    args = options()
    ends = deadline(args.until)  # before the fill: a fill that ran past the stop time made it tomorrow's
    queue = TaskQueue(Path(args.queue))
    if not queue.filled():
        items, about = DoubledLetters.load(log=lambda line: print(line, flush=True)).items(args.target)
        queue.fill(items, about)
        print("filled:", about, flush=True)
    judge = LetterJudge(args.judge)
    for item in queue.next(args.limit):
        if ends and datetime.now() >= ends:
            break
        verdict = judge_item(judge, item)
        if verdict.get("unanswered"):
            continue  # left unjudged, so the next turn asks again
        queue.record(item["id"], verdict, args.judge, datetime.now().astimezone().isoformat(timespec="seconds"))
        kept = [v["variant"] for v in verdict["variants"] if v["verdict"] == "misspelling"]
        print(f"{item['word']:20s} {'english' if verdict['english_word'] else 'NOT ENGLISH'}  -> {', '.join(kept) or '-'}", flush=True)
    judge.release()
    print("pairs written:", write_results(queue, Path(args.results), args.target), queue.counts(), flush=True)


def judge_item(judge: LetterJudge, item: dict) -> dict:
    # Only the dropped slips still open need the model's eye; a tripled letter is never an English word. A word Webster
    # knows is English, so with nothing to ask it needs no model at all (a third of the turn's time, at 20 s a call)
    asked = [v["variant"] for v in item["variants"] if v["kind"] == "dropped" and v["verdict"].startswith("open")]
    if not asked and item.get("in_webster"):
        answer = {"meaning": "", "english_word": True, "variants": []}
    else:
        answer = judge.check(item["word"], asked)
    if answer.get("unanswered"):
        return answer
    ruled = {v["variant"]: v for v in answer["variants"]}
    variants = []
    for v in item["variants"]:
        if not v["verdict"].startswith("open"):
            variants.append({**v, "reason": "found mechanically"})
        elif v["kind"] == "tripled":
            variants.append({**v, "verdict": "misspelling", "reason": "no English word has three in a row"})
        else:
            said = ruled[v["variant"]]
            variants.append({**v, "verdict": "real word (judge)" if said["real_word"] else "misspelling", "reason": said["reason"]})
    return {"meaning": answer.get("meaning", ""), "english_word": answer["english_word"], "variants": variants}


def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


def write_results(queue: TaskQueue, path: Path, pair: str) -> int:
    judged = [(item, verdict) for item, verdict, _ in queue.judged()]
    pairs, refused, not_english = [], [], []
    for item, verdict in judged:
        if not verdict["english_word"]:
            not_english.append(f"{item['word']}  ({verdict.get('meaning', '')})")
            continue
        kept = [v["variant"] for v in verdict["variants"] if v["verdict"] == "misspelling"]
        if kept:
            pairs.append(f"{item['word']} -> {', '.join(kept)}  [{item['frequency']}]")
        refused += [f"{item['word']} -> {v['variant']}  ({v['reason']})" for v in verdict["variants"]
                    if v["verdict"] == "real word (judge)"]
    lines = [f"# Doubled \"{pair}\": slips for GGCMS's misspelling lists, judged by local models. Every pair is UNCONFIRMED:",
             "# Claude confirms them before they go into Language/Words/. Most used words first; the number is pyspellchecker's count.",
             "", f"## Pairs ({len(pairs)})", "", *pairs,
             "", f"## Slips the judge called real words ({len(refused)}): check these, the dictionaries missed them", "", *refused,
             "", f"## Not English, left out ({len(not_english)})", "", *not_english]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(pairs)


if __name__ == "__main__":
    main()
