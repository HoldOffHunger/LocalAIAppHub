import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from task_queue import TaskQueue  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data"


def doubled_pairs(pair: str, data: Path = DATA) -> dict[str, str]:
    """The slips the doubled-letter worker has kept so far for one letter pair (target "doubled-ss" → "ss"), as wrong → right.
    That worker is still judging, so the hunt asks again every run and picks up what's new."""
    found = {}
    with sqlite3.connect(f"file:{data / 'foreman.sqlite'}?mode=ro", uri=True) as foreman:
        ids = [task_id for (task_id,) in foreman.execute(
            "SELECT id FROM tasks WHERE kind = 'ggcms_doubled_letters' AND target = ? ORDER BY id", (pair,))]
    for task_id in ids:
        pile = data / "tasks" / f"task-{task_id}.sqlite"
        if not pile.exists():
            continue
        for item, verdict, _ in TaskQueue(pile).judged():
            if verdict.get("english_word"):
                found.update({v["variant"]: item["word"] for v in verdict["variants"] if v["verdict"] == "misspelling"})
    return found


def write_pair_report(connection: sqlite3.Connection, path: Path, pair: str) -> int:
    # The test the hunt is really for: does each slip occur in real writing, and is it a slip there? Many hits the judge calls
    # fine means the "slip" is a real word or name the dictionaries missed, so the pair should come out of the list
    rows = connection.execute(
        "SELECT w.wrong, w.correct, w.total, w.round, "
        "COALESCE(SUM(json_extract(h.verdict, '$.verdict') = 'typo'), 0), "
        "COALESCE(SUM(json_extract(h.verdict, '$.verdict') = 'fine'), 0), "
        "COALESCE(SUM(json_extract(h.verdict, '$.verdict') = 'skipped'), 0) "
        "FROM words w LEFT JOIN hits h ON h.word_id = w.id GROUP BY w.id").fetchall()
    visited = [r for r in rows if r[3] > 0]
    doubtful = sorted((r for r in visited if r[5] > r[4]), key=lambda r: (-r[5], r[0]))
    confirmed = sorted((r for r in visited if r[4] and r[4] >= r[5]), key=lambda r: (-r[4], r[0]))
    unseen = sorted((r for r in visited if not r[4] and not r[5]), key=lambda r: r[0])
    line = lambda r: f"{r[0]} → {r[1]}  [on Wikipedia {r[2] or 0} times · read: typo {r[4]}, fine {r[5]}, skipped {r[6]}]"
    lines = [f"# Doubled \"{pair}\" pairs tested against English Wikipedia: {len(visited)} of {len(rows)} searched so far.", "",
             f"## Doubtful: the judge called it right more often than a slip ({len(doubtful)}). Probably not a misspelling.", "",
             *map(line, doubtful), "", f"## Confirmed: found as a slip at least as often as not ({len(confirmed)})", "",
             *map(line, confirmed), "", f"## Not met in prose yet ({len(unseen)})", "",
             *(f"{r[0]} → {r[1]}  [on Wikipedia {r[2] or 0} times]" for r in unseen)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(doubtful)
