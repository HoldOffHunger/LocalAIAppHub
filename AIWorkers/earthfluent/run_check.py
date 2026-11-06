import argparse
import time
from datetime import datetime, timedelta
from pathlib import Path

from dictionary_index import DictionaryIndex
from dump_reader import DumpReader
from review_queue import ReviewQueue
from triage_file import TriageFile
from word_check import LANGUAGES, WordCheck

ROOT = Path(r"E:\AIWorkers")
# Prod as of 26 Oct 2026, after the Spanish wave (Italian's is already filled): a language filled from it starts from what is live
DUMP = ROOT / "data" / "earthfluent-2026-10-26.sql.gz"
DICTIONARIES = {code: Path(rf"E:\ModelWorkshop\dictionaries\{name.lower()}\kaikki.org-dictionary-{name}.jsonl")
                for code, name in LANGUAGES.items()}


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check EarthFluent translations a row at a time; suspects go to a triage file.")
    parser.add_argument("--lang", default="it")
    parser.add_argument("--limit", type=int, default=50, help="rows to check this run")
    parser.add_argument("--lesson", default="%", help="SQL LIKE pattern on the lesson, e.g. 'Nouns - Animals%%'")
    parser.add_argument("--model", default="mistral:7b", help="the screener: checks every row")
    parser.add_argument("--judge", default="gemma4:12b", help="the senior judge: rechecks only what the screener flags ('' for none)")
    parser.add_argument("--batch", type=int, default=50, help="rows per batch, so each model loads once per batch")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def main() -> None:
    # The two-stage court that won the 12-language test: Mistral screens, Gemma 4 12B judges the flagged (34/45 caught, 4 false)
    args = options()
    queue = ReviewQueue(ROOT / "data" / "earthfluent-review.sqlite")
    if not queue.counts(args.lang)["checked"] + queue.counts(args.lang)["left"]:
        print("filled", queue.fill(DumpReader(DUMP).rows(args.lang)), "rows", flush=True)
    dictionary = DictionaryIndex(ROOT / "data" / f"dictionary-{args.lang}.sqlite")
    dictionary.build(DICTIONARIES[args.lang])
    screen, judge, ends = WordCheck(args.model, dictionary), WordCheck(args.judge, dictionary) if args.judge else None, deadline(args.until)
    rows = queue.next(args.lang, args.limit, args.lesson)
    for start in range(0, len(rows), args.batch):
        if ends and datetime.now() >= ends:
            break
        batch_two_stage(queue, rows[start:start + args.batch], screen, judge, ends)
        write_triage(queue, args.lang)  # a stopped run still leaves its suspects behind
    print("suspects written:", write_triage(queue, args.lang), queue.counts(args.lang))


def batch_two_stage(queue: ReviewQueue, rows: list, screen: WordCheck, judge: WordCheck | None, ends) -> None:
    flagged = []
    for row in rows:
        if ends and datetime.now() >= ends:
            break
        verdict = screen.check(row)
        if verdict["verdict"] == "suspect" and judge:
            flagged.append((row, verdict))
            continue
        _keep(queue, row, verdict, screen.model)
    for row, first in flagged:  # the judge loads once for the whole batch's flags
        if ends and datetime.now() >= ends:
            break  # the rows left unrecorded are screened again next turn
        verdict = judge.check(row)
        _keep(queue, row, {**verdict, "screened_by": screen.model, "screen_reason": first["reason"]}, f"{screen.model} > {judge.model}")


def _keep(queue: ReviewQueue, row, verdict: dict, model: str) -> None:
    queue.record(row, verdict, model, datetime.now().astimezone().isoformat(timespec="seconds"))
    print(f"{verdict['verdict']:7s} {row.english} -> {row.current}  [{row.lesson}] ({model}) {verdict['reason'][:80]}", flush=True)


def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


def write_triage(queue: ReviewQueue, lang: str) -> int:
    header = (f"# {lang} — EarthFluent triage by a local model. Every record is a SUSPECT, not a proposal: confirm against a "
              "dictionary of record first.\n# Format: see E:\\GGCMS\\Development\\TranslationReview\\README.md")
    return TriageFile(ROOT / "earthfluent" / "triage" / f"{lang}.triage.txt", header).write(queue.suspects(lang))


if __name__ == "__main__":
    main()
