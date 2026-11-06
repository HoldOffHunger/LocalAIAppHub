import json
import sqlite3
from pathlib import Path

from ocr_shapes import ocr_shaped

HUNTER_QUEUE = Path(r"E:\AIWorkers\data\tasks\task-21.sqlite")  # the Wikipedia typo hunter's pile
SAID_OCR = ("ocr", "scan", "optical character")


def ocr_seeds(hunter_queue: Path, frequency) -> list[dict]:
    """The hunter's OCR-shaped misspellings: its confirmed Wikipedia finds first, then the rest of GGCMS's list it hunts.

    A seed is searched for on the Archive, so it must not be a real word (a search for "modem" finds modems), and it must
    take only strong shapes (rn/m, cl/d, li/h, long s…) or the judge must have said a scanner did it: "unfiled" for
    "unfilled" is a dropped ligature plus i/l, but a typist's doubling slip too, and searching it finds clean scans.
    Read-only: the hunter's pile is opened as a file URI with mode=ro."""
    hunter = sqlite3.connect(f"file:{hunter_queue.as_posix()}?mode=ro", uri=True)
    seeds: dict[str, dict] = {}
    finds = hunter.execute("SELECT w.wrong, w.correct, h.verdict FROM hits h JOIN words w ON w.id = h.word_id "
                           "WHERE json_extract(h.verdict, '$.verdict') = 'typo' ORDER BY h.checked_at")
    for wrong, correct, verdict in finds:
        verdict = json.loads(verdict)
        right = (verdict.get("fix") or correct).strip().lower()
        reading = ocr_shaped(wrong, right) or ocr_shaped(wrong, correct)
        said = any(word in verdict.get("reason", "").lower() for word in SAID_OCR)
        if (reading and reading.only_strong or said) and _searchable(wrong, frequency):
            seeds.setdefault(wrong, {"wrong": wrong, "correct": reading.word if reading else right,
                                     "shapes": reading.describe() if reading else "the judge said OCR", "source": "Wikipedia find"})
    for wrong, correct in hunter.execute("SELECT wrong, correct FROM words ORDER BY id"):
        reading = ocr_shaped(wrong, correct)
        if reading and reading.only_strong and _searchable(wrong, frequency):
            seeds.setdefault(wrong, {"wrong": wrong, "correct": correct.lower(), "shapes": reading.describe(), "source": "GGCMS list"})
    hunter.close()
    return list(seeds.values())


def _searchable(word: str, frequency) -> bool:
    return len(word) >= 4 and word.isalpha() and word.islower() and not frequency(word)
