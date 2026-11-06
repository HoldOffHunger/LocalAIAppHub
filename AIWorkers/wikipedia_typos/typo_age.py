import re
import time

import httpx

# WikiWho, on Wikimedia Cloud: every token of an article's current wikitext with the revision that first added it, and
# each revision that took it out or put it back. One request an article answers "how long has this typo stood", where
# walking the history ourselves would take a dozen full-text downloads. It only reads, like everything here.
WIKIWHO = "https://wikiwho-api.wmcloud.org/en/api/v1.0.0-beta/rev_content/page_id/{}/"
PAUSE = 1.0
WORD = re.compile(r"\w+")


def stood_since(tokens: list[dict], wrong: str, raw: str) -> int | None:
    # The revision since which the misspelling has stood unbroken, for the occurrence whose surroundings best match the
    # find's own wikitext; None when it isn't in the article any more. Punctuation and markup tokens are passed over,
    # so "don't" and "[[sring]]" match whatever way WikiWho split them
    wanted = WORD.findall(wrong.lower())
    words = [token for token in tokens if WORD.fullmatch(token["str"])]
    around = set(WORD.findall(raw.lower()))
    best, best_score = None, -1
    for at in range(len(words) - len(wanted) + 1):
        if [token["str"] for token in words[at:at + len(wanted)]] != wanted:
            continue
        score = sum(token["str"] in around for token in words[max(0, at - 8):at + len(wanted) + 8])
        if score > best_score:
            best, best_score = words[at:at + len(wanted)], score
    if best is None:
        return None
    # A token taken out and put back has stood only since it went back; a phrase, only since its newest word arrived
    return max(max(token["in"]) if token["in"] else token["o_rev_id"] for token in best)


class TypoAges:
    """When each typo entered its article, and when the article was last edited, by asking WikiWho."""

    def __init__(self, client: httpx.Client):
        self.client = client
        self.last = 0.0

    def date(self, page_id: int, wrong: str, raw: str) -> dict | None:
        # {"since_rev", "last_rev", "last_edit", "gone"}, or None when WikiWho can't say yet (it may still be reading a
        # long history for the first time): the find stays undated and is asked about again next turn
        wait = self.last + PAUSE - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        try:
            reply = self.client.get(WIKIWHO.format(page_id), params={"o_rev_id": "true", "in": "true", "out": "false",
                                                                     "editor": "false", "token_id": "false"}, timeout=180)
            reply.raise_for_status()
            data = reply.json()
        except (httpx.HTTPError, ValueError):
            return None
        if not data.get("success") or not data.get("revisions"):
            return None
        [(last_rev, current)] = data["revisions"][0].items()
        since = stood_since(current["tokens"], wrong, raw)
        return {"since_rev": since, "last_rev": int(last_rev), "last_edit": current.get("time", ""), "gone": since is None}
