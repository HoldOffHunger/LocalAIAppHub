import argparse
import json
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "yallhearingthis"))
from int_site import IntSite  # noqa: E402
from records import narrow  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"

# Puts a quote task's picks on int through modify_entry.php, each as an Update of its entry, so modify.php's own rules
# run. Int only: going live is the int-to-prod copy (Ben, 24 Oct 2026: "just run it on int"). An entry that already has
# a quote is skipped, so a rerun picks up where a stopped one left off.


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save a quote task's .jsonl picks on int, one Update per entry.")
    parser.add_argument("records", help="the task's results .jsonl")
    parser.add_argument("--domain", default="revoltlib.com")
    parser.add_argument("--database", default="revoltlib")
    parser.add_argument("--user", default="1")
    parser.add_argument("--jobs", type=int, default=8, help="saves at once; each is its own PHP process")
    parser.add_argument("--limit", type=int, default=0, help="stop after this many saves (0: all)")
    return parser.parse_args()


def entry_paths(site: IntSite) -> dict[int, str]:
    # /parent/child/ for every entry, walked up the Assignment table to the root, which has no segment of its own
    codes = {int(r["id"]): r["Code"] for r in site.query("SELECT id, Code FROM Entry")}
    parents = {}
    for row in site.query("SELECT Childid, Parentid FROM Assignment WHERE Childid > 0 ORDER BY id"):
        parents.setdefault(int(row["Childid"]), int(row["Parentid"]))
    root = int(site.query("SELECT Parentid FROM Assignment WHERE Childid = 0 LIMIT 1")[0]["Parentid"])
    paths = {}
    for entry in codes:
        chain, at = [], entry
        while at != root and at in parents and len(chain) < 20:
            chain.append(codes.get(at, ""))
            at = parents[at]
        if at == root and all(chain):
            paths[entry] = "/" + "/".join(reversed(chain)) + "/"
    # Two entries at one path (RevoltLib has 18 such pairs) can't be told apart by modify.php: saving 104 through
    # /anarchism/note-to-the-article…/ wrote 104's whole form over 9710. Neither twin is given a path.
    shared = Counter(paths.values())
    return {entry: path for entry, path in paths.items() if shared[path] == 1}


def main() -> None:
    args = options()
    site = IntSite(DATA / "quote-push" / args.database, args.domain, args.database, args.user)
    picks = [json.loads(line) for line in Path(args.records).read_text(encoding="utf-8").splitlines() if line.strip()]
    quoted = {int(r["Entryid"]) for r in site.query("SELECT DISTINCT Entryid FROM Quote")}
    paths = entry_paths(site)
    todo = [p for p in picks if p["Entryid"] not in quoted]
    lost = [p["Entryid"] for p in todo if p["Entryid"] not in paths]
    todo = [p for p in todo if p["Entryid"] in paths]
    print(f"{len(picks)} picks, {len(picks) - len(todo) - len(lost)} already quoted, {len(lost)} with no path or a shared one, {len(todo)} to save"
          + (f", {args.limit} of them this run" if args.limit else ""), flush=True)
    todo = todo[:args.limit or None]

    def save(pick: dict) -> tuple[dict, dict]:
        fields = pick["fields"]
        record = {"fields": {"Quote": [narrow(fields["Quote"])[:2048]], "quote_Source": [fields["quote_Source"]],
                             "quote_Language": [fields["quote_Language"]]}}
        return pick, site.save(paths[pick["Entryid"]], f"quote-{pick['Entryid']}", record, True, "Update")

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
