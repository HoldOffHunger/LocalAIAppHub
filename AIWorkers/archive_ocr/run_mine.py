import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

from spellchecker import SpellChecker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from archive_client import MAX_BYTES, ArchiveClient, ArchiveDown, TooBig, Unavailable  # noqa: E402
from ggcms_words import known_misspellings  # noqa: E402
from mine_queue import MineQueue  # noqa: E402
from ocr_mining import Miner  # noqa: E402
from seeds import HUNTER_QUEUE, ocr_seeds  # noqa: E402

LEAST_SEEDS = 2  # an item two different OCR seeds found is a bad scan; one is any old scan


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find badly scanned texts on the Internet Archive from the Wikipedia typo "
                                                 "hunter's OCR-shaped finds, and mine them for recurring OCR misreadings.")
    parser.add_argument("--target", default="archive.org")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the candidates are written for a person to review")
    parser.add_argument("--hunter-queue", default=str(HUNTER_QUEUE), help="the Wikipedia typo hunter's pile, read-only")
    parser.add_argument("--mine", type=int, default=60, help="how many of the worst items to mine in all")
    parser.add_argument("--per-run", type=int, default=15, help="items mined this run at most")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def main() -> None:
    args = options()
    ends = deadline(args.until)
    queue = MineQueue(Path(args.queue))
    words = SpellChecker().word_frequency
    frequency = lambda word: words[word]  # noqa: E731
    if not queue.filled():
        seeds = ocr_seeds(Path(args.hunter_queue), frequency)
        queue.fill(seeds, {"filled_from": args.hunter_queue, "filled_at": now(), "seeds": len(seeds)})
        print(f"filled: {len(seeds)} OCR-shaped seeds, {sum(s['source'] == 'Wikipedia find' for s in seeds)} of them Wikipedia "
              f"finds", flush=True)
    archive = ArchiveClient()
    try:
        search(queue, archive, ends)
        mine(queue, archive, Miner(frequency, known_misspellings()), args, ends)
    except ArchiveDown as refusal:
        print(f"{refusal}; the rest waits for the next turn", flush=True)
    print("candidates written:", write_results(queue, Path(args.results)), queue.counts(args.mine), flush=True)


def search(queue: MineQueue, archive: ArchiveClient, ends) -> None:
    while not over(ends) and (seed := queue.next_seed()):
        total, hits = archive.full_text(seed["wrong"])
        queue.searched(seed, total, hits, now())
        print(f"searched {seed['wrong']} → {seed['correct']}: {total} pages of OCR, {len({h['identifier'] for h in hits})} items "
              f"kept", flush=True)


def mine(queue: MineQueue, archive: ArchiveClient, miner: Miner, args, ends) -> None:
    done = queue.counts(args.mine)["items mined"]
    for item in queue.worst_items(LEAST_SEEDS, max(0, min(args.per_run, args.mine - done))):
        if over(ends):
            return
        listed = archive.ocr_text_file(item["identifier"], item["file"])
        if not listed:
            queue.set_state(item["identifier"], "no text", "the item has no _djvu.txt")
            continue
        name, size = listed
        try:
            text = archive.ocr_text(item["identifier"], name, size)
        except TooBig as big:
            queue.set_state(item["identifier"], "too big", str(big))
            print(f"left for Ben: {big}", flush=True)
            continue
        except Unavailable as closed:
            queue.set_state(item["identifier"], "unavailable", str(closed))
            print(f"skipped {item['identifier']}: {closed}", flush=True)
            continue
        result = miner.mine(text)
        queue.mined(item["identifier"], result, now())
        print(f"mined {item['identifier']} ({item['seeds']} seeds): {result['words']} words, {result['nonwords']} non-words, "
              f"{len(result['found'])} OCR-shaped", flush=True)


def over(ends) -> bool:
    return bool(ends and datetime.now() >= ends)


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    current = datetime.now()
    ends = datetime.combine(current.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > current else ends + timedelta(days=1)


def write_results(queue: MineQueue, path: Path) -> int:
    known = known_misspellings()
    found = queue.candidates()
    fresh = [c for c in found if c["wrong"] not in known]
    lines = ["# OCR misreadings that recur across badly scanned Internet Archive texts. Every line is a CANDIDATE for GGCMS's "
             "misspelling lists, unconfirmed: nothing is added to any list automatically.",
             f"# {len(fresh)} new, {len(found) - len(fresh)} already listed. Strong shapes (rn/m, cl/d, li/h, long s, ligatures) "
             "first; then single look-alike letters, which need a harder look.", ""]
    for c in fresh:
        lines += [f"{c['wrong']} → {c['correct']}  ({c['shapes']})  in {c['items']} texts, {c['count']} times",
                  f"      {c['example']}  [https://archive.org/details/{c['example_item']}]", ""]
    big = queue.items_waiting("too big")
    if big:
        lines += [f"# Over {MAX_BYTES / 1e6:.0f} MB, so not downloaded: say the word and they will be.", ""]
        lines += [f"{item['identifier']}: {item['title']} ({item['note']})" for item in big]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # The same, for the App Hub's Social page; a mark there is kept against the misspelling itself
    shown = [{**c, "key": c["wrong"], "url": f"https://archive.org/details/{c['example_item']}"} for c in fresh]
    path.with_suffix(".json").write_text(json.dumps(shown, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(fresh)


if __name__ == "__main__":
    main()
