import json
from datetime import datetime, timedelta
from pathlib import Path

DEFAULTS = {"schedule": {"enabled": False, "mode": "window", "start": "03:00", "end": "06:00", "days": [0, 1, 2, 3, 4, 5, 6]},
            "rest_minutes": 5}
MODES = ("window", "until_awake")  # from start until end; or from start until Ben is back at the PC
LONGEST_REST = 240  # minutes; a rest longer than this is a pause, and the cards' switches are for that


class ForemanSettings:
    """Ben's choices, kept in a small JSON file: when the night shift runs."""

    def __init__(self, path: Path):
        self.path = path
        self.data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else json.loads(json.dumps(DEFAULTS))

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")

    def set_schedule(self, enabled: bool, start: str, end: str, days: list[int], mode: str = "window") -> None:
        for moment in (start, end):
            datetime.strptime(moment, "%H:%M")  # refuses anything that isn't HH:MM
        if mode not in MODES:
            raise ValueError(f"The mode is one of {', '.join(MODES)}.")
        self.data["schedule"] = {"enabled": enabled, "mode": mode, "start": start, "end": end, "days": sorted(set(days))}
        self.save()

    def rest_minutes(self) -> int:
        # The breather the shift takes between one task's turn and the next; files from before it get the default
        return int(self.data.get("rest_minutes", DEFAULTS["rest_minutes"]))

    def set_rest(self, minutes: int) -> None:
        if not 0 <= minutes <= LONGEST_REST:
            raise ValueError(f"Rest 0 to {LONGEST_REST} minutes between jobs.")
        self.data["rest_minutes"] = minutes
        self.save()

    def until_awake(self) -> bool:
        return self.data["schedule"].get("mode", "window") == "until_awake"  # files from before the modes are windows

    def window_end(self, now: datetime) -> datetime | None:
        # The end of tonight's shift if one is open right now; a window can cross midnight, and belongs to the day it starts.
        # Until Ben wakes, the window runs to the next night's start, and the night shift closes it early when he's back
        shift = self.data["schedule"]
        if not shift["enabled"]:
            return None
        for started_on in (now.date(), now.date() - timedelta(days=1)):
            start = datetime.combine(started_on, datetime.strptime(shift["start"], "%H:%M").time(), now.tzinfo)
            end = datetime.combine(started_on, datetime.strptime(shift["end"], "%H:%M").time(), now.tzinfo)
            end += timedelta(days=1) if end <= start else timedelta()
            if self.until_awake():
                end = start + timedelta(days=1)
            if start.weekday() in shift["days"] and start <= now < end:
                return end
        return None
