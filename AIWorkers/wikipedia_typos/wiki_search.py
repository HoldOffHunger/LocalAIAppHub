import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ggcms_wikilinks"))
from wiki_api import WikiApi  # noqa: E402  (one request a second, maxlag, and the waits Wikipedia asks for)


class WikiSearch(WikiApi):
    """English Wikipedia's own search over articles' wikitext: no login and no key, and it never edits."""

    def insource(self, phrase: str, offset: int, count: int) -> tuple[int, list[dict]]:
        # The total matching articles, and this page of them as {"id", "title"}
        reply = self._get({"action": "query", "list": "search", "srsearch": f'insource:"{phrase}"', "srnamespace": 0,
                           "srlimit": count, "sroffset": offset, "srprop": "", "srwhat": "text", "format": "json",
                           "formatversion": 2})
        query = reply.get("query", {})
        return (query.get("searchinfo", {}).get("totalhits", 0),
                [{"id": hit["pageid"], "title": hit["title"]} for hit in query.get("search", [])])

    def revision_times(self, revids: list[int]) -> dict[int, str]:
        # Revision id -> its timestamp, fifty to a request; a deleted or hidden revision is left out
        found = {}
        for start in range(0, len(revids), 50):
            reply = self._get({"action": "query", "revids": "|".join(map(str, revids[start:start + 50])), "prop": "revisions",
                               "rvprop": "ids|timestamp", "format": "json", "formatversion": 2})
            for page in reply.get("query", {}).get("pages", []):
                for revision in page.get("revisions", []):
                    found[revision["revid"]] = revision["timestamp"]
        return found
