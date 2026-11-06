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
if not path.exists() or not TaskQueue(path).filled():
    note = "not started: the first turn reads the local mirror and Wikipedia's titles"
    if index_path.exists():
        found = sqlite3.connect(index_path).execute("SELECT value FROM meta WHERE key = 'pages_line'").fetchone()
        if found:
            note = f"filling: reading Wikipedia's titles, line {int(found[0]):,}"
    print(json.dumps({"done": 0, "total": 0, "note": note}))
else:
    queue = TaskQueue(path)
    proposed = sum(1 for _, verdict, _ in queue.judged() if verdict.get("result") == "propose")
    print(json.dumps({**queue.counts(), "proposed": proposed}))
