import argparse
import json
from pathlib import Path

from review_queue import ReviewQueue

# The Foreman's progress line for this worker: one JSON object on stdout
parser = argparse.ArgumentParser()
parser.add_argument("--lang", default="it")
lang = parser.parse_args().lang
print(json.dumps({"language": lang, **ReviewQueue(Path(r"E:\AIWorkers\data\earthfluent-review.sqlite")).counts(lang)}))
