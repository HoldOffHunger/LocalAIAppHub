import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dump_tables import newest_dump  # noqa: E402
from quote_candidates import candidates  # noqa: E402
from quote_pick import QuotePick  # noqa: E402
from site_texts import site_texts  # noqa: E402
from sites import site_about, site_name  # noqa: E402
from task_queue import TaskQueue  # noqa: E402


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pick one quote for every text that has none; results are for a person to confirm.")
    parser.add_argument("--target", default="revoltlib")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the picked quotes are written")
    parser.add_argument("--limit", type=int, default=50, help="texts to do this run")
    parser.add_argument("--model", default="mistral:7b", help="the screener: shortlists three sentences per text")
    parser.add_argument("--judge", default="gemma4:12b", help="the senior judge: picks one of the three ('' to take the screener's first)")
    parser.add_argument("--batch", type=int, default=100, help="texts per batch, so each model loads once per batch")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def fill(queue: TaskQueue, target: str) -> None:
    # The mechanical pass: texts with no quote yet, each with up to 20 whole sentences that could stand alone
    dump, items, short = newest_dump(target), [], 0
    print(f"reading {dump}", flush=True)
    for text in site_texts(dump):
        if "Quote" in text.has:
            continue
        found = candidates(text.paragraphs())
        if len(found) < 3:
            short += 1
            continue
        items.append({"id": text.entryid, "title": text.title, "source": text.source(), "candidates": found,
                      "words": sum(len(paragraph.split()) for paragraph in text.paragraphs())})
    queue.fill(items, {"filled_from": dump, "too_short": short})
    print(f"filled: {len(items)} texts to quote, {short} too short to quote", flush=True)


def main() -> None:
    args = options()
    ends = deadline(args.until)  # before the first run's fill: a fill that ran past the stop time made it tomorrow's
    queue = TaskQueue(Path(args.queue))
    if not queue.filled():
        fill(queue, args.target)
    screen = QuotePick(args.model, site_about(args.target))
    judge = QuotePick(args.judge, site_about(args.target)) if args.judge else None
    items = queue.next(args.limit)
    for start in range(0, len(items), args.batch):
        if ends and datetime.now() >= ends:
            break
        batch_two_stage(queue, items[start:start + args.batch], screen, judge, ends)
        write_results(queue, Path(args.results), args.target)  # a stopped run still leaves its picks behind
    print("quotes written:", write_results(queue, Path(args.results), args.target), queue.counts(), flush=True)


def batch_two_stage(queue: TaskQueue, items: list[dict], screen: QuotePick, judge: QuotePick | None, ends) -> None:
    # Mistral shortlists three for every text; Gemma 4 picks one of the three, loading once per batch
    shortlisted = []
    print(f"--- {screen.model} finds the top 3 quotes in each of {len(items)} texts; then {judge.model if judge else "nobody"} picks the winner ---",
          flush=True)
    for number, item in enumerate(items, 1):
        if ends and datetime.now() >= ends:
            break
        size = f" [{item['words']:,} words]" if item.get("words") else ""  # piles filled before word counts don't have them
        print(f"finding the top 3 in {number}/{len(items)}: {item['title'][:60]} (entry {item['id']}){size}", flush=True)
        shortlisted.append((item, screen.shortlist(item)))
    if judge:
        screen.release()
        print(f"--- {judge.model} picks the winning quote for each of the {len(shortlisted)} texts ---", flush=True)
    for item, shortlist in shortlisted:
        if ends and datetime.now() >= ends:
            break  # the texts left unrecorded are shortlisted again next turn
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        if not shortlist:
            queue.record(item["id"], {"pick": None, "reason": "The screener couldn't pick any sentence."}, screen.model, stamp)
            continue
        choice = judge.choose(item, shortlist) if judge and len(shortlist) > 1 else {"pick": shortlist[0], "reason": "The screener's first choice."}
        verdict = {**choice, "quote": item["candidates"][choice["pick"]], "shortlist": shortlist}
        queue.record(item["id"], verdict, f"{screen.model} > {judge.model}" if judge else screen.model, stamp)
        print(f"{item['id']:>6} {item['title'][:50]:50s} {verdict['quote'][:90]}", flush=True)
    if judge:
        judge.release()


def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


def write_results(queue: TaskQueue, path: Path, target: str) -> int:
    # A page to read, and a JSON-lines file in modify.php's own field names, for the push script to come
    picked = [(item, verdict, model) for item, verdict, model in queue.judged() if verdict.get("quote")]
    lines = [f"# {site_name(target)} quotes picked by local models. Every quote is word for word from its text, and UNCONFIRMED.",
             f"# Filled from {queue.meta('filled_from')}.", ""]
    for item, verdict, model in picked:
        lines += [f"entry {item['id']} · {item['title']} · {item['source']}", f"  “{verdict['quote']}”",
                  f"  ({verdict['reason']}) [{model}]", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    with path.with_suffix(".jsonl").open("w", encoding="utf-8") as records:
        for item, verdict, model in picked:
            records.write(json.dumps({"Entryid": item["id"], "record": "Quote", "fields": {
                "Quote": verdict["quote"], "quote_Source": item["source"], "quote_Language": "en"}, "checked_by": model},
                ensure_ascii=False) + "\n")
    return len(picked)


if __name__ == "__main__":
    main()
