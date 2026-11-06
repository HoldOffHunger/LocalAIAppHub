import re
import time
from urllib.parse import urlsplit

import httpx

from url_tools import host, same_page
from wiki_dumps import AGENT

PAUSE = 3.0  # seconds between two requests to one host: these are other people's (often dying) servers
CDX = "https://web.archive.org/cdx/search/cdx"
WAYBACK_PAUSE = 4.0  # the Internet Archive throttles anything quicker than about fifteen a minute
GONE = re.compile(r"(?:404|not found|page (?:cannot|can't|could not) be found|no longer (?:available|exists)|domain (?:is )?for sale|"
                  r"buy this domain|parked|this domain may be|account (?:has been )?suspended|coming soon)", re.I)
TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
TAG = re.compile(r"<[^>]+>")
SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.I | re.S)


class ArchiveDown(RuntimeError):
    """The Internet Archive is throttling us or offline: the items wait in the pile, rather than being judged 'no copy'."""


class LinkCheck:
    """Asks whether a link still leads to its text, gently: one request per host every few seconds, and a dead host is asked once."""

    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(headers={**AGENT, "Accept": "text/html,*/*"}, timeout=30, follow_redirects=True, verify=False)
        self.asked: dict[str, float] = {}
        self.dead_hosts: dict[str, str] = {}
        self.rest = 0.0  # seconds the Archive is left alone after it refuses: 5 minutes, doubling to an hour, reset by an answer
        self.rest_until = 0.0

    def resting(self) -> bool:
        return time.monotonic() < self.rest_until

    def archive_refused(self) -> float:
        self.rest = min(max(self.rest * 2, 300.0), 3600.0)
        self.rest_until = time.monotonic() + self.rest
        return self.rest

    def check(self, url: str) -> dict:
        # {"state": "dead" | "soft-dead" | "alive" | "unsure", "why", "text"}; "unsure" is a site that turned the robot away
        name = host(url)
        if name in self.dead_hosts:
            return {"state": "dead", "why": self.dead_hosts[name], "text": ""}
        self._wait(name)
        try:
            reply = self.client.get(url)
        except httpx.ConnectError as error:
            why = "the host doesn't answer" if "getaddrinfo" not in str(error) else "the domain no longer exists"
            self.dead_hosts[name] = why
            return {"state": "dead", "why": why, "text": ""}
        except (httpx.TimeoutException, httpx.TooManyRedirects) as error:
            return {"state": "dead", "why": f"no page: {type(error).__name__}", "text": ""}
        except httpx.HTTPError as error:
            return {"state": "unsure", "why": f"{type(error).__name__}", "text": ""}
        if reply.status_code in (401, 403, 429, 503):
            return {"state": "unsure", "why": f"the site answered {reply.status_code} (it may just refuse robots)", "text": ""}
        if reply.status_code >= 400:
            return {"state": "dead", "why": f"the site answers {reply.status_code}", "text": ""}
        page = reply.text if "html" in reply.headers.get("content-type", "") or not reply.headers.get("content-type") else ""
        landed = str(reply.url)
        if host(landed) != host(url) and urlsplit(landed).path in ("", "/"):
            return {"state": "soft-dead", "why": f"it sends you to {host(landed)}'s front page", "text": ""}
        if same_page(landed) != same_page(url) and urlsplit(landed).path in ("", "/"):
            return {"state": "soft-dead", "why": "it sends you to the site's front page", "text": ""}
        titled = TITLE.search(page)
        title = " ".join(TAG.sub("", titled.group(1)).split()) if titled else ""
        text = plain(page)
        if GONE.search(title) or (len(text.split()) < 150 and GONE.search(text)):
            return {"state": "soft-dead", "why": f"the page says \"{(title or text)[:80]}\"", "text": text}
        return {"state": "alive", "why": f"the site answers {reply.status_code}", "text": text}

    def archived(self, url: str) -> dict | None:
        # The Internet Archive's newest good copy, if it has one: {"url", "timestamp"}. Asked of the CDX index on web.archive.org:
        # on 4 Nov 2026 archive.org/wayback/available answered every request 429 for days, while CDX answered at once
        self._wait("archive.org", WAYBACK_PAUSE)
        try:
            reply = self.client.get(CDX, params={"url": url, "output": "json", "limit": "-1", "filter": "statuscode:200",
                                                 "fl": "timestamp,original"})
            if reply.status_code >= 400:
                raise ArchiveDown(f"the Internet Archive answered {reply.status_code}")
            rows = reply.json() if reply.text.strip() else []
        except (httpx.HTTPError, ValueError) as error:
            raise ArchiveDown(f"the Internet Archive didn't answer ({type(error).__name__})") from error
        self.rest = 0.0
        if len(rows) < 2:  # the first row is the field names
            return None
        timestamp, original = rows[-1][:2]
        return {"url": f"https://web.archive.org/web/{timestamp}/{original}", "timestamp": timestamp}

    def archived_text(self, snapshot: dict) -> str:
        # The copy as it was captured, without the Archive's own toolbar (the id_ form)
        self._wait("archive.org", WAYBACK_PAUSE)
        raw = re.sub(r"/web/(\d+)/", r"/web/\1id_/", snapshot["url"], count=1)
        try:
            reply = self.client.get(raw)
        except httpx.HTTPError as error:
            raise ArchiveDown(f"the Internet Archive didn't send its copy ({type(error).__name__})") from error
        if reply.status_code == 429 or reply.status_code >= 500:
            raise ArchiveDown(f"the Internet Archive answered {reply.status_code}")
        return plain(reply.text)

    def _wait(self, name: str, pause: float = PAUSE) -> None:
        wait = self.asked.get(name, 0) + pause - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.asked[name] = time.monotonic()


def plain(page: str) -> str:
    return " ".join(TAG.sub(" ", SCRIPT.sub(" ", page or "")).split())


def runs(text: str, size: int = 8) -> set:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[at:at + size]) for at in range(max(len(words) - size + 1, 0))}


def overlap(theirs: str, ours: str) -> float:
    # How much of their page's running text (in eight-word runs) is in ours: 1.0 is all of it
    found = runs(theirs)
    return len(found & runs(ours)) / len(found) if found else 0.0


class TextFinder:
    """Which of a site's texts an archived page is, without comparing it with all 1,453 of them: one run in sixteen is indexed,
    the texts holding most of the page's indexed runs are the suspects, and only they are compared in full."""

    def __init__(self, texts: dict[int, str]):
        self.texts = texts
        self.index: dict[int, set[int]] = {}
        for entry, words in texts.items():
            for run in runs(words):
                key = hash(run)
                if key % 16 == 0:
                    self.index.setdefault(key, set()).add(entry)

    def best(self, theirs: str) -> tuple[int, float]:
        votes: dict[int, int] = {}
        for run in runs(theirs):
            for entry in self.index.get(hash(run), ()):
                votes[entry] = votes.get(entry, 0) + 1
        suspects = sorted(votes, key=votes.get, reverse=True)[:3]
        scored = [(entry, overlap(theirs, self.texts[entry])) for entry in suspects]
        return max(scored, key=lambda pair: pair[1], default=(0, 0.0))
