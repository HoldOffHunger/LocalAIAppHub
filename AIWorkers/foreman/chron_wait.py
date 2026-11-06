import json
import urllib.request


class ChronWait:
    """The App Hub's Chron Jobs runs its jobs at set times each night (the memory backup at 03:00, when the night shift
    also opens). No turn starts while a job is due or running; a turn already going finishes."""

    def __init__(self, chron: str = "http://127.0.0.1:8740"):
        self.chron = chron

    def busy_job(self) -> str:
        # The job's title while one is due or running; "" when none is, or Chron Jobs isn't running, as before it existed
        try:
            with urllib.request.urlopen(f"{self.chron}/api/busy", timeout=5) as response:
                reply = json.load(response)
        except (OSError, ValueError):
            return ""
        return reply.get("job", "") if reply.get("busy") else ""
