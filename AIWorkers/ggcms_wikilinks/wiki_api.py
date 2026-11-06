import time

import httpx

from wiki_dumps import AGENT

API = "https://en.wikipedia.org/w/api.php"
PAUSE = 1.0  # seconds between requests: Wikimedia's etiquette for an unauthenticated tool is one at a time, unhurried


class WikiApi:
    """Reads articles' current wikitext by title, fifty at a time, following redirects; it never edits."""

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(headers=AGENT, timeout=60)
        self.last = 0.0

    def articles(self, titles: list[str]) -> dict[str, dict]:
        # Asked-for title -> {"id", "title", "text"} of the article it is or redirects to; a deleted page is left out
        found = {}
        for start in range(0, len(titles), 50):
            batch = titles[start:start + 50]
            reply = self._get({"action": "query", "titles": "|".join(batch), "redirects": 1, "prop": "revisions",
                               "rvprop": "content", "rvslots": "main", "format": "json", "formatversion": 2})
            query = reply.get("query", {})
            pages = {page["title"]: page for page in query.get("pages", []) if "missing" not in page and page.get("revisions")}
            hops = {hop["from"]: hop["to"] for hop in query.get("normalized", []) + query.get("redirects", [])}
            for title in batch:
                landed = title
                for _ in range(3):  # normalised, then redirected, then perhaps once more
                    landed = hops.get(landed, landed)
                if landed in pages:
                    page = pages[landed]
                    found[title] = {"id": page["pageid"], "title": page["title"], "text": page["revisions"][0]["slots"]["main"]["content"]}
        return found

    def _get(self, params: dict) -> dict:
        for attempt in range(5):
            wait = self.last + PAUSE - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self.last = time.monotonic()
            reply = self.client.get(API, params={**params, "maxlag": 5})
            if reply.status_code == 429:
                time.sleep(min(int(reply.headers.get("retry-after") or 30), 300))
                continue
            reply.raise_for_status()
            data = reply.json()
            if data.get("error", {}).get("code") == "maxlag":  # Wikipedia's servers are busy: wait as asked
                time.sleep(5 * (attempt + 1))
                continue
            return data
        raise RuntimeError("Wikipedia kept asking us to wait; the rest stays in the pile for next turn.")
