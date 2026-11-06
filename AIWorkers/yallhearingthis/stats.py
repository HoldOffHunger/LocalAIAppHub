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
    print(json.dumps({"done": 0, "total": 0, "note": "not started: the first run lists the channel"}))
else:
    queue = TaskQueue(path)
    artists = Path(__file__).resolve().parent.parent / "data" / "yallhearingthis" / "artists.json"
    print(json.dumps({**queue.counts(), "artists": len(json.loads(artists.read_text(encoding="utf-8"))) if artists.exists() else 0}))
