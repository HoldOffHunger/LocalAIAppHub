import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from task_queue import TaskQueue  # noqa: E402

# The Foreman's progress line for this task: one JSON object on stdout
parser = argparse.ArgumentParser()
parser.add_argument("--queue", required=True)
path = Path(parser.parse_args().queue)
index_path = path.with_suffix(".wiki.sqlite")
queue = TaskQueue(path) if path.exists() else None
if queue is None or not queue.filled():
    note = "not started: the first turn reads the local mirror and Wikipedia's titles"
    if index_path.exists():
        found = sqlite3.connect(index_path).execute("SELECT value FROM meta WHERE key = 'pages_line'").fetchone()
        if found:
            note = f"filling: reading Wikipedia's titles, line {int(found[0]):,}"
    print(json.dumps({"done": 0, "total": 0, "note": note}))
else:
    proposed = sum(1 for _, verdict, _ in queue.judged() if verdict.get("result") == "propose")
    counts = {**queue.counts(), "proposed": proposed}
    sources = ("citing_from", "history_of_from", "loose_from", "search_from")  # run_mia_subjects.widen's, in order
    if queue.meta("collections_from") and any(queue.meta(source) is None for source in sources):
        # A collection pile still waiting for its wider candidates isn't finished, even with every item so far judged
        counts |= {"total": counts["total"] + 1, "note": "more candidates to add next turn"}
    print(json.dumps(counts))
