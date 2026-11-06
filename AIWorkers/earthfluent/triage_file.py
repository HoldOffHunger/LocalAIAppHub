from pathlib import Path

from dump_reader import WordRow


class TriageFile:
    """Writes the worker's suspects in TranslationReview's record format, marked suspect: a person confirms each before it's proposed."""

    def __init__(self, path: Path, header: str):
        self.path = path
        self.header = header

    def write(self, suspects: list[tuple[WordRow, dict, str]]) -> int:
        records = [self._record(row, verdict, model) for row, verdict, model in suspects]
        self.path.write_text(self.header + "\n\n" + "\n\n".join(records) + "\n", encoding="utf-8")
        return len(records)

    def _record(self, row: WordRow, verdict: dict, model: str) -> str:
        evidence = "; ".join(verdict.get("dictionary", [])) or "not found"
        lines = [f"id: {row.id}", f"entryid: {row.entryid}", f"permalink: {row.permalink}", f"lesson: {row.lesson}",
                 f"lang: {row.lang}", f"english: {row.english}", f"current: {row.current}", f"proposed: {verdict['proposed']}",
                 f"kind: {verdict['kind']}", f"reason: {verdict['reason']}",
                 f"source: Wiktionary (via kaikki.org), s.v. \"{row.current}\": {evidence[:300]}",
                 f"checked by: {model}, unconfirmed", "status: suspect"]
        return "\n".join(lines)
