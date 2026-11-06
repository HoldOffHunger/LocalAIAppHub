import json
import urllib.request


class GpuGuard:
    """Autonoma and the workers share one 8 GB card: a worker waits while her model is loaded, and asks the App Hub's GPU desk
    before each turn. The workers are background, so the desk only says yes while nobody Ben is using holds the card."""

    def __init__(self, ollama: str = "http://127.0.0.1:11434", prefix: str = "autonoma-", hub: str = "http://127.0.0.1:8700"):
        self.ollama = ollama
        self.prefix = prefix
        self.hub = hub

    def autonoma_busy(self) -> bool:
        return any(name.startswith(self.prefix) for name in self._loaded())

    def desk_refusal(self, minutes: int = 5) -> str:
        # "" when the desk gives the workers the card (or the hub isn't running, as before the desk); otherwise why not
        try:
            reply = self._desk("claim", {"app": "workers", "minutes": minutes, "background": True})
        except (OSError, ValueError):
            return ""
        return "" if reply.get("granted", True) else reply.get("reason", "someone else has the GPU")

    def desk_renew(self, minutes: int = 2) -> None:
        # A running task keeps its background lease alive; the desk can still hand the card to Ben at any moment
        try:
            self._desk("renew", {"app": "workers", "minutes": minutes})
        except (OSError, ValueError):
            pass

    def _desk(self, action: str, body: dict) -> dict:
        request = urllib.request.Request(f"{self.hub}/api/gpu/{action}", method="POST", headers={"Content-Type": "application/json"},
                                         data=json.dumps(body).encode())
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)

    def clear_card(self) -> None:
        # A worker's models stay parked ten minutes after its turn; the next worker's model then spills onto the CPU and
        # crawls (a 15-minute spellcheck turn did one text). Unload every worker model before a turn; never Autonoma's.
        for name in self._loaded():
            if not name.startswith(self.prefix):
                request = urllib.request.Request(f"{self.ollama}/api/generate", method="POST", headers={"Content-Type": "application/json"},
                                                 data=json.dumps({"model": name, "keep_alive": 0}).encode())
                try:
                    urllib.request.urlopen(request, timeout=30).close()
                except OSError:
                    pass

    def _loaded(self) -> list[str]:
        try:
            with urllib.request.urlopen(f"{self.ollama}/api/ps", timeout=5) as response:
                return [model.get("name", "") for model in json.load(response).get("models", [])]
        except OSError:
            return []  # no Ollama answering means nobody holds the card
