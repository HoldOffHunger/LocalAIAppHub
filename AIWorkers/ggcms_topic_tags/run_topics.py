import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ggcms_tags"))
from dump_tables import DumpTables, newest_dump  # noqa: E402
from keywords import ignore_words  # noqa: E402
from site_texts import site_texts  # noqa: E402
from sites import site_about, site_name  # noqa: E402
from task_queue import TaskQueue  # noqa: E402
from topic_pick import TopicPick  # noqa: E402

LONGEST = 300  # words: past this it's an article, not a quote, and the ggcms_tags worker suits it better
KNOWN = 5  # a tag counts as a house tag once Ben has used it on this many entries
SUGGESTED = 250  # the most-used house tags, shown to the model


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Give every untagged quote 3 to 5 topic tags, from the tags RevoltLib already uses.")
    parser.add_argument("--target", default="revoltsource")
    parser.add_argument("--vocabulary", default="revoltlib", help="the site whose tags are the allowed topics")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the topic tags are written")
    parser.add_argument("--limit", type=int, default=50, help="quotes to do this run")
    parser.add_argument("--model", default="gemma4:12b")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def vocabulary(site: str) -> tuple[list[str], list[str]]:
    # Ben's tags by how many entries use them, less ListKeywords' common words: every house tag, and the most-used ones
    skip, seen, uses = ignore_words(), set(), Counter()
    for _, row in DumpTables(newest_dump(site)).rows({"Tag"}):
        pair = (row["Entryid"], row["Tag"].strip().lower())
        if pair not in seen:
            seen.add(pair)
            uses[pair[1]] += 1
    ranked = [tag for tag, count in uses.most_common() if count >= KNOWN and tag not in skip]
    return ranked, ranked[:SUGGESTED]


def fill(queue: TaskQueue, target: str, source: str) -> None:
    dump, items, long = newest_dump(target), [], 0
    print(f"reading {dump}", flush=True)
    for text in site_texts(dump):
        if "Tag" in text.has:
            continue
        quote = " ".join(text.paragraphs())
        if len(quote.split()) > LONGEST:
            long += 1
            continue
        items.append({"id": text.entryid, "title": text.title, "work": text.work, "author": text.author, "quote": quote})
    print(f"reading {source}'s tags for the allowed topics", flush=True)
    known, suggested = vocabulary(source)
    queue.fill(items, {"filled_from": dump, "skipped": long, "known": json.dumps(known), "suggested": json.dumps(suggested)})
    print(f"filled: {len(items)} quotes to tag, {long} too long for a quote; {len(known)} house tags", flush=True)


def house(proposed: list[str], known: set[str]) -> list[str]:
    # Keep the model's topics that are already tags, trying without "the" and the plural or singular too; at most five
    kept = []
    for topic in proposed:
        topic = topic.removeprefix("the ")
        match = next((form for form in (topic, topic.removesuffix("s"), topic + "s") if form in known), None)
        if match and match not in kept:
            kept.append(match)
    return kept[:5]


def main() -> None:
    args = options()
    ends = deadline(args.until)  # before the first run's fill: a fill that ran past the stop time made it tomorrow's
    queue = TaskQueue(Path(args.queue))
    if not queue.filled():
        fill(queue, args.target, args.vocabulary)
    known = set(json.loads(queue.meta("known")))
    picker = TopicPick(args.model, site_about(args.target), json.loads(queue.meta("suggested")))
    items = queue.next(args.limit)
    print(f"--- {args.model} picks the topics of {len(items)} quotes ---", flush=True)
    for number, item in enumerate(items, 1):
        if ends and datetime.now() >= ends:
            break
        proposed = picker.topics(item)
        kept = house(proposed, known)
        queue.record(item["id"], {"proposed": proposed, "tags": kept}, args.model, datetime.now().astimezone().isoformat(timespec="seconds"))
        print(f"{number}/{len(items)} {item['id']:>6} {item['quote'][:60]:60s} {', '.join(kept) or '(none kept)'}", flush=True)
        if number % 50 == 0:
            write_results(queue, Path(args.results), args.target)  # a stopped run still leaves its tags behind
    picker.release()
    print("quotes tagged:", write_results(queue, Path(args.results), args.target), queue.counts(), flush=True)


def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


def write_results(queue: TaskQueue, path: Path, target: str) -> int:
    # A page to read, and a JSON-lines file with the Tag records, for the push script to come
    tagged = [(item, verdict, model) for item, verdict, model in queue.judged() if verdict["tags"]]
    lines = [f"# {site_name(target)} topic tags picked by a local model from RevoltLib's own tags. UNCONFIRMED.",
             f"# Filled from {queue.meta('filled_from')}. \"not a house tag\" lists what the model said that RevoltLib doesn't use.", ""]
    for item, verdict, model in tagged:
        dropped = [topic for topic in verdict["proposed"] if topic not in verdict["tags"] and topic.removesuffix("s") not in verdict["tags"]]
        lines += [f"entry {item['id']} · {item['work']} · {item['author'] or 'no author'}", f"  {item['quote'][:240]}",
                  f"  tags: {', '.join(verdict['tags'])}" + (f"   (not a house tag: {', '.join(dropped)})" if dropped else ""), f"  [{model}]", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    with path.with_suffix(".jsonl").open("w", encoding="utf-8") as records:
        for item, verdict, model in tagged:
            records.write(json.dumps({"Entryid": item["id"], "record": "Tag", "tags": verdict["tags"], "checked_by": model}, ensure_ascii=False) + "\n")
    return len(tagged)


if __name__ == "__main__":
    main()
