import json
import random
from pathlib import Path

from dump_reader import DumpReader

# Ten telling rows per language: words with two senses first, then rows identical to the English, then a few at random
DUMP = Path(r"E:\Code\DB-Backups\2026-09-06\earthfluent.sql.gz")
LANGS = ["es", "fr", "de", "nl", "pl", "pt", "ru", "ja", "zh", "ko", "hi", "id"]
TRICKY = {"turkey", "bat", "seal", "orange", "fly", "press", "break", "lean", "cross", "grave", "sound", "watch", "iran", "chicken",
          "date", "pitch", "spring", "match", "glasses", "crane", "mole", "pupil", "bark", "bow", "trunk", "duck"}


def pick(rows: list, rng: random.Random) -> list:
    tricky = [r for r in rows if r.english.lower() in TRICKY]
    same = [r for r in rows if r.current.strip().lower() == r.english.strip().lower() and r not in tricky]
    rest = [r for r in rows if r not in tricky and r not in same]
    chosen = rng.sample(tricky, min(5, len(tricky))) + rng.sample(same, min(3, len(same)))
    return chosen + rng.sample(rest, 10 - len(chosen))


if __name__ == "__main__":
    rng, reader, sample = random.Random(13), DumpReader(DUMP), []
    for lang in LANGS:
        sample += [row.__dict__ for row in pick(reader.rows(lang), rng)]
        print(lang, "picked", flush=True)
    (Path(__file__).parent / "sample_multilang.json").write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
