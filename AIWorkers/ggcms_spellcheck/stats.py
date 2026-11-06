import argparse
import json
from pathlib import Path

from spell_queue import SpellQueue

# The Foreman's progress line for this task: one JSON object on stdout
parser = argparse.ArgumentParser()
parser.add_argument("--queue", required=True)
path = Path(parser.parse_args().queue)
print(json.dumps(SpellQueue(path).counts() if path.exists() else {"done": 0, "total": 0, "note": "not started: the first run reads the dump"}))
