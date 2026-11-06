import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "yallhearingthis"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ggcms_quote"))
from int_site import IntSite  # noqa: E402
from push_int import entry_paths  # noqa: E402
from records import narrow  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"

# Puts a topic task's tags on int through modify_entry.php, each as an Update of its entry, as the quotes went on
# 24 Oct 2026. Int only: going live is the guarded table swap in ship/. An entry that already has tags is skipped, so a
# rerun picks up where a stopped one left off.


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save a topic task's .jsonl tags on int, one Update per entry.")
    parser.add_argument("records", help="the task's results .jsonl")
    parser.add_argument("--domain", default="revoltsource.com")
    parser.add_argument("--database", default="revoltsource")
    parser.add_argument("--user", default="1")
    parser.add_argument("--jobs", type=int, default=8, help="saves at once; each is its own PHP process")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many saves (0: all)")
    return parser.parse_args()


def main() -> None:
    args = options()
    site = IntSite(DATA / "tag-push" / args.database, args.domain, args.database, args.user)
    picks = [json.loads(line) for line in Path(args.records).read_text(encoding="utf-8").splitlines() if line.strip()]
    picks = [p for p in picks if p.get("tags")]
    tagged = {int(r["Entryid"]) for r in site.query("SELECT DISTINCT Entryid FROM Tag")}
    # Never the site's root (26 Oct 2026: a save gave RevoltSource's home page two empty author links), and never an
    # entry with a picture: int has no picture folder for this site, so a save renamed the file to one that isn't there
    root = int(site.query("SELECT Parentid FROM Assignment WHERE Childid = 0 LIMIT 1")[0]["Parentid"])
    pictured = {int(r["Entryid"]) for r in site.query("SELECT DISTINCT Entryid FROM Image")}
    skipped = [p["Entryid"] for p in picks if p["Entryid"] == root or p["Entryid"] in pictured]
    picks = [p for p in picks if p["Entryid"] not in skipped]
    if skipped:
        print("skipped, the root or pictured:", skipped[:50], flush=True)
    paths = entry_paths(site)
    todo = [p for p in picks if p["Entryid"] not in tagged]
    lost = [p["Entryid"] for p in todo if p["Entryid"] not in paths]
    todo = [p for p in todo if p["Entryid"] in paths]
    print(f"{len(picks)} tag sets, {len(picks) - len(todo) - len(lost)} already tagged, {len(lost)} with no path or a shared one, {len(todo)} to save"
          + (f", {args.limit} of them this run" if args.limit else ""), flush=True)
    todo = todo[:args.limit or None]

    def save(pick: dict) -> tuple[dict, dict]:
        tags = [narrow(tag) for tag in pick["tags"]]
        record = {"fields": {"Tag": tags, "tag_Language": ["en"] * len(tags)}}
        return pick, site.save(paths[pick["Entryid"]], f"tags-{pick['Entryid']}", record, True, "Update")

    start, failed = time.time(), []
    with ThreadPoolExecutor(args.jobs) as pool:
        for number, (pick, saved) in enumerate(pool.map(save, todo), 1):
            if not saved["ok"]:
                failed.append(pick["Entryid"])
                print(f"FAILED {pick['Entryid']} {paths[pick['Entryid']]}: {saved['status'] or saved['output'][-300:]}", flush=True)
            if number % 100 == 0 or number == len(todo):
                print(f"{number}/{len(todo)} saved in {time.time() - start:.0f}s, {len(failed)} failed", flush=True)
    if lost:
        print("no path, or a path another entry shares, on int:", lost[:50], flush=True)


if __name__ == "__main__":
    main()
