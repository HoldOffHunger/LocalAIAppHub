import argparse
import json
from pathlib import Path

from mine_queue import MineQueue

# The Foreman's progress line for this task: one JSON object on stdout
parser = argparse.ArgumentParser()
parser.add_argument("--queue", required=True)
parser.add_argument("--mine", type=int, default=60)
args = parser.parse_args()
path = Path(args.queue)
print(json.dumps(MineQueue(path).counts(args.mine) if path.exists() else {"done": 0, "total": 0,
                                                                          "note": "not started: the first run reads the hunter's finds"}))
