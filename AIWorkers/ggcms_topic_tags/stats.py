import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from task_queue import TaskQueue  # noqa: E402

# The Foreman's progress line for this task: one JSON object on stdout
parser = argparse.ArgumentParser()
parser.add_argument("--queue", required=True)
path = Path(parser.parse_args().queue)
if not path.exists():
    print(json.dumps({"done": 0, "total": 0, "note": "not started: the first run reads the dump"}))
else:
    queue = TaskQueue(path)
    print(json.dumps({**queue.counts(), "too long for a quote": int(queue.meta("skipped") or 0)}))
