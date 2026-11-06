import time

import httpx

AGENT = {"User-Agent": "AIWorkersOCRMiner/1.0 (https://revoltlib.com/contact.php) httpx"}
SEARCH = "https://archive.org/services/search/beta/page_production/"
PAUSE = 5.0  # seconds between requests; a full-text search costs the Archive 2-4 s of its own, so one at a time, unhurried
MAX_BYTES = 3_000_000  # a bigger OCR text waits for Ben's word: the brief is to ask before any download over a few MB


class ArchiveDown(RuntimeError):
    """The Internet Archive refused or failed: the turn ends, and the pile picks up from here next time."""


class TooBig(RuntimeError):
    """The item's OCR text is over MAX_BYTES; it is listed for Ben rather than downloaded."""


class Unavailable(RuntimeError):
    """This one item's text can't be had: a lending-library book (401, 2 Nov 2026), a dark item, a missing file."""


class ArchiveClient:
    """Read-only: the Archive's full-text search (guest access, through the page service its own search page uses; the
    scrape API's `service=fts` refuses guests), item file lists, and `_djvu.txt` OCR texts. Never uploads or edits."""

    def __init__(self, client: httpx.Client | None = None, pause: float = PAUSE):
        self.client = client or httpx.Client(headers=AGENT, timeout=120, follow_redirects=True)
        self.pause = pause
        self.last = 0.0

    def full_text(self, word: str, count: int = 100) -> tuple[int, list[dict]]:
        # The total pages of OCR that contain the word, and the first `count` hits: {"identifier", "title", "year",
        # "collection", "file", "snippet"}. A phrase or two words find nothing (tried 2 Nov 2026), so it is one word a query
        reply = self._get(SEARCH, {"user_query": word, "service_backend": "fts", "hits_per_page": count, "page_type": "search_results"})
        response = reply.json().get("response") or {}
        if not response.get("header", {}).get("succeeded"):
            raise ArchiveDown(f"the full-text search failed: {(response.get('error') or {}).get('message', 'no reason given')[:200]}")
        hits = response["body"]["hits"]
        found = []
        for hit in hits.get("hits", []):
            fields = hit.get("fields", {})
            found.append({"identifier": fields.get("identifier", ""), "title": str(fields.get("title", "")),
                          "year": fields.get("year"), "collection": ",".join(fields.get("collection") or []),
                          "file": fields.get("file_basename", ""), "snippet": " … ".join(hit.get("highlight", {}).get("text", []))})
        return hits.get("total", 0), [hit for hit in found if hit["identifier"]]

    def ocr_text_file(self, identifier: str, basename: str = "") -> tuple[str, int] | None:
        # The item's _djvu.txt and its size; an item of several volumes has one per file, so the hit's own file is preferred
        files = self._get(f"https://archive.org/metadata/{identifier}/files", {}).json().get("result") or []
        texts = [(entry["name"], int(entry.get("size") or 0)) for entry in files
                 if entry.get("name", "").endswith("_djvu.txt") and entry.get("private") != "true"]
        wanted = [text for text in texts if basename and text[0] == f"{basename}_djvu.txt"]
        return (wanted or texts or [None])[0]

    def ocr_text(self, identifier: str, name: str, size: int) -> str:
        if size > MAX_BYTES:
            raise TooBig(f"{name} is {size / 1e6:.1f} MB")
        reply = self._get(f"https://archive.org/download/{identifier}/{name}", {})
        if len(reply.content) > MAX_BYTES:  # the listing undersold it: keep nothing
            raise TooBig(f"{name} came to {len(reply.content) / 1e6:.1f} MB")
        return reply.content.decode("utf-8", errors="replace")

    def _get(self, url: str, params: dict) -> httpx.Response:
        wait = self.last + self.pause - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        try:
            reply = self.client.get(url, params=params)
        except httpx.HTTPError as error:
            raise ArchiveDown(f"the Internet Archive didn't answer ({type(error).__name__})") from error
        # One item's file failing is that item's trouble (a lending book's 401; a 500 on 2 Nov 2026 that would otherwise
        # have stopped every turn at the same item). Busy, gateway and throttling answers are the Archive's, and end the turn
        if reply.status_code in (401, 403, 404, 410, 500) and "/download/" in url:
            raise Unavailable(f"the Internet Archive answered {reply.status_code}")
        if reply.status_code == 429 or reply.status_code >= 500:
            raise ArchiveDown(f"the Internet Archive answered {reply.status_code}")
        if reply.status_code >= 400 and "page_production" not in url:  # the search page service explains its 400s in JSON
            raise ArchiveDown(f"the Internet Archive answered {reply.status_code} for {url}")
        return reply
