import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from task_queue import TaskQueue  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wiki_index import WikiIndex  # noqa: E402

# The Foreman's progress line for this task: one JSON object on stdout
parser = argparse.ArgumentParser()
parser.add_argument("--queue", required=True)
path = Path(parser.parse_args().queue)
index_path = path.with_suffix(".wiki.sqlite")
if not path.exists() or not TaskQueue(path).filled():
    # Still filling: say which stage, since the first turns read dumps rather than judge anything
    note = "not started: the first turn reads the site's dump"
    if index_path.exists():
        index = WikiIndex(index_path)
        if index.meta("pages_done"):
            checked = index.connection.execute("SELECT COUNT(*), COALESCE(SUM(state = 'dead'), 0) FROM domains").fetchone()
            note = f"filling: checking which source sites are still up ({checked[0]} checked, {checked[1]} dead)"
        elif index.meta("pages_line"):
            note = f"filling: reading Wikipedia's titles, line {int(index.meta('pages_line')):,}"
        elif index.meta("links_line"):
            note = f"filling: reading Wikipedia's links, line {int(index.meta('links_line')):,} of about 1.1 billion"
        elif index.meta("ours_done"):
            note = "filling: downloading Wikipedia's tables"
    print(json.dumps({"done": 0, "total": 0, "note": note}))
else:
    queue = TaskQueue(path)
    proposed = sum(1 for _, verdict, _ in queue.judged() if verdict.get("result") == "propose")
    print(json.dumps({**queue.counts(), "proposed": proposed, "sourceless texts": int(queue.meta("sourceless") or 0)}))
