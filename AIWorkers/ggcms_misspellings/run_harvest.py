import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ggcms_spellcheck"))
from dump_tables import newest_dump  # noqa: E402
from harvest import harvest  # noqa: E402
from sites import site_about, site_name  # noqa: E402
from task_queue import TaskQueue  # noqa: E402
from typo_check import TypoCheck  # noqa: E402
from wiktionary_words import WiktionaryWords  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Harvest a site's recurring misspellings for GGCMS's misspelling lists.")
    parser.add_argument("--target", default="revoltlib")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the candidates are written for Claude to confirm")
    parser.add_argument("--limit", type=int, default=200, help="words to judge this run")
    parser.add_argument("--judge", default="gemma4:12b")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def main() -> None:
    args = options()
    ends = deadline(args.until)  # before the fill: a fill that ran past the stop time made it tomorrow's
    queue = TaskQueue(Path(args.queue))
    if not queue.filled():
        words = WiktionaryWords(DATA / "wiktionary-words.sqlite")
        words.build(log=lambda line: print(line, flush=True))
        items, about = harvest(newest_dump(args.target), words, log=lambda line: print(line, flush=True))
        queue.fill(items, about)
        print("filled:", about, flush=True)
    judge = TypoCheck(args.judge, site_about(args.target))
    for item in queue.next(args.limit):
        if ends and datetime.now() >= ends:
            break
        verdict = judge_word(judge, item)
        if verdict["verdict"] == "unanswered":
            continue  # left unjudged, so the next turn asks again
        queue.record(item["id"], verdict, args.judge, datetime.now().astimezone().isoformat(timespec="seconds"))
        print(f"{verdict['verdict']:10s} {item['word']} -> {verdict.get('fix') or item['suggestion']}  [{item['texts']} texts]"
              f"  {verdict.get('reason', '')[:90]}", flush=True)
    judge.release()
    print("candidates written:", write_results(queue, Path(args.results), args.target), queue.counts(), flush=True)


def judge_word(judge: TypoCheck, item: dict) -> dict:
    # A slip is a slip in every sentence it's in; a real word the dictionary lacks is fine in all of them. So the word is a
    # typo only if the judge says so in each of its first two sentences, and both times names the same fix
    hint = f" Wiktionary has \"{item['word']}\" as a word in {item['wiktionary']}." if item["wiktionary"] else ""
    verdicts = []
    for context in item["contexts"][:2]:
        word = {"word": item["word"], "context": context["context"] + hint, "suggestion": item["suggestion"], "known": ""}
        verdict = judge.check(context["title"], word)
        verdicts.append(verdict)
        if verdict["verdict"] != "typo":
            return {**verdict, "sentences": len(verdicts)}
    fixes = {v.get("fix", "").strip().lower() for v in verdicts}
    if len(fixes) > 1:
        return {"verdict": "fine", "fix": "", "reason": f"Two different fixes ({', '.join(sorted(fixes))}): not a settled slip.",
                "sentences": len(verdicts)}
    return {**verdicts[0], "sentences": len(verdicts)}


def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


def write_results(queue: TaskQueue, path: Path, target: str) -> int:
    typos = [(item, verdict) for item, verdict, _ in queue.judged() if verdict["verdict"] == "typo"]
    typos.sort(key=lambda pair: (-pair[0]["texts"], pair[0]["word"]))
    lines = [f"# {site_name(target)}: misspellings for GGCMS's lists, harvested by local models. Every pair is UNCONFIRMED:",
             f"# Claude confirms them before they go into Language/Words/EnglishMisspellings. Most texts first.", ""]
    for item, verdict in typos:
        lines.append(f"{item['word']} -> {verdict.get('fix') or item['suggestion']}  [{item['texts']} texts, {item['count']} times]"
                     f"  ({verdict.get('reason', '')})" + (f"  [Wiktionary: {item['wiktionary']}]" if item["wiktionary"] else ""))
        lines += [f"    {c['entryid']} · {c['title'][:60]}: {c['context']}" for c in item["contexts"]]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(typos)


if __name__ == "__main__":
    main()
