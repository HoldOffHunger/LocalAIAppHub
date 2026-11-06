import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dump_tables import newest_dump  # noqa: E402
from keywords import ignore_words, list_keywords  # noqa: E402
from site_texts import site_texts  # noqa: E402
from sites import site_about, site_name  # noqa: E402
from tag_pick import TagPick  # noqa: E402
from task_queue import TaskQueue  # noqa: E402

CANDIDATES = 150  # ListKeywords' top keywords the model looks over
KEEP = 100  # Ben's own RevoltLib tag sets run about 90 a text
ARTICLES = {"a", "an", "the"}  # ListKeywords lets a phrase start or end on one; a tag never should


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tag every text that has no tags: ListKeywords proposes, a local model strikes the off-theme ones.")
    parser.add_argument("--target", default="revoltlib")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the tag lists are written")
    parser.add_argument("--limit", type=int, default=50, help="texts to do this run")
    parser.add_argument("--model", default="mistral:7b")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def fill(queue: TaskQueue, target: str) -> None:
    # The mechanical pass: ListKeywords over every untagged text, keeping its top keywords and the opening for the model's context
    dump, skip, items, short = newest_dump(target), ignore_words(), [], 0
    print(f"reading {dump}", flush=True)
    for text in site_texts(dump):
        if "Tag" in text.has:
            continue
        body = " ".join(text.paragraphs())
        found = [keyword for keyword, _ in list_keywords(body, skip)[:CANDIDATES]]
        if len(found) < 10:
            short += 1
            continue
        items.append({"id": text.entryid, "title": text.title, "candidates": found, "opening": body[:1200], "words": len(body.split())})
    queue.fill(items, {"filled_from": dump, "too_short": short})
    print(f"filled: {len(items)} texts to tag, {short} too short to tag", flush=True)


def kept(item: dict, verdict: dict) -> list[str]:
    # What the model didn't strike, trimmed of edge articles so "the one-armed prisoner" in one text is the same tag as
    # "one-armed prisoner" in another; a phrase that trims to one already kept is dropped, keeping the first one's place
    struck, tags = set(verdict["struck"]), []
    for n, keyword in enumerate(item["candidates"]):
        tag = trimmed(keyword)
        if n not in struck and tag and tag not in tags:
            tags.append(tag)
    return tags[:KEEP]


def trimmed(keyword: str) -> str:
    found = keyword.split(" ")
    while found and found[0] in ARTICLES:
        found.pop(0)
    while found and found[-1] in ARTICLES:
        found.pop()
    return " ".join(found)


def main() -> None:
    args = options()
    ends = deadline(args.until)  # before the first run's fill: a fill that ran past the stop time made it tomorrow's
    queue = TaskQueue(Path(args.queue))
    if not queue.filled():
        fill(queue, args.target)
    picker = TagPick(args.model, site_about(args.target))
    items = queue.next(args.limit)
    print(f"--- {args.model} strikes the off-theme keywords in {len(items)} texts ---", flush=True)
    for number, item in enumerate(items, 1):
        if ends and datetime.now() >= ends:
            break
        verdict = picker.strike(item)
        queue.record(item["id"], verdict, args.model, datetime.now().astimezone().isoformat(timespec="seconds"))
        tags = kept(item, verdict)
        print(f"{number}/{len(items)} {item['id']:>6} {item['title'][:50]:50s} {len(verdict['struck'])} struck, {len(tags)} kept, "
              f"the first of them: {', '.join(tags[:8])}", flush=True)
        if number % 25 == 0:
            write_results(queue, Path(args.results), args.target)  # a stopped run still leaves its tags behind
    picker.release()
    print("texts tagged:", write_results(queue, Path(args.results), args.target), queue.counts(), flush=True)


def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


def write_results(queue: TaskQueue, path: Path, target: str) -> int:
    # A page to read, and a JSON-lines file with one Tag record per keyword, for the push script to come
    tagged = [(item, verdict, model, kept(item, verdict)) for item, verdict, model in queue.judged() if verdict.get("answered")]
    lines = [f"# {site_name(target)} tags: ListKeywords' keywords, with the off-theme ones struck by a local model. UNCONFIRMED.",
             f"# Filled from {queue.meta('filled_from')}.", ""]
    for item, verdict, model, tags in tagged:
        struck = [item["candidates"][n] for n in verdict["struck"]]
        lines += [f"entry {item['id']} · {item['title']}", f"  about: {verdict['about']}", f"  tags ({len(tags)}): {', '.join(tags)}",
                  f"  struck ({len(struck)}): {', '.join(struck)}", f"  [{model}]", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    with path.with_suffix(".jsonl").open("w", encoding="utf-8") as records:
        for item, verdict, model, tags in tagged:
            records.write(json.dumps({"Entryid": item["id"], "record": "Tag", "tags": tags, "checked_by": model}, ensure_ascii=False) + "\n")
    return len(tagged)


if __name__ == "__main__":
    main()
