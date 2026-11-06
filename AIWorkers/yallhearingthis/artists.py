import json
import re
import unicodedata
from pathlib import Path

import httpx
import ollama

AGENT = {"User-Agent": "YallHearingThisFiller/1.0 (https://yallhearingthis.com/contact.php) httpx/0.28"}  # Wikimedia refuses a bot that gives no way to reach its owner
MUSIC = re.compile(r"\b(k-pop|korean|japanese|chinese|thai|singer|rapper|girl group|boy group|band|idol|duo|trio|unit|"
                   r"sub-unit|musician|songwriter|vocalist|entertainer|music)\b", re.I)
NAMES = {"type": "object", "properties": {"artists": {"type": "array", "items": {"type": "object", "properties": {
    "name": {"type": "string"}, "kind": {"type": "string", "enum": ["group", "soloist", "unit"]},
    "group": {"type": "string"}}, "required": ["name", "kind", "group"]}}}, "required": ["artists"]}


def plain(text: str) -> str:
    # Rosé, ROSÉ and rose are one name: no accents, no case, letters and digits only
    folded = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", folded)


class ArtistFinder:
    """Asks a local model who a show reacts to. It may only name what the video's own title, tags or description name,
    and the code checks that, so an artist it half-remembers from elsewhere can't get onto the site."""

    def __init__(self, model: str, client: ollama.Client | None = None):
        self.model = model
        self.client = client or ollama.Client()

    def find(self, video: dict, known: list[str]) -> list[dict]:
        tags = ", ".join(video.get("tags") or [])
        about = (video.get("description") or "").split("\n\n")[0][:600]
        roster = ", ".join(known[:300]) or "(none yet)"
        question = (
            f"This is a video from Y'all Hearing This?!, a YouTube channel where the hosts react to K-pop music videos, "
            f"live stages and variety shows.\n\nTitle: {video.get('title', '')}\nTags: {tags}\nDescription: {about}\n\n"
            f"Which musical artists is this video reacting to, or about? List each one. A member's solo release is that "
            f"member, as a soloist, with their group in group (e.g. Jennie, group BLACKPINK); otherwise group is empty. "
            f"A collaboration is each artist separately. A sub-unit with its own name is a unit. Not the channel itself, "
            f"not a TV show, label, song or album. If it's a giveaway or not about any artist, give an empty list.\n"
            f"Artists already on the site, spelled as the site spells them; reuse a spelling from here when it's the same "
            f"artist: {roster}\n\nReply as JSON.")
        reply = self._ask(question)
        evidence = plain(" ".join([video.get("title", ""), tags, video.get("description", "")]))
        found = []
        for artist in (reply or {}).get("artists", []):
            name = (artist.get("name") or "").strip()
            if name and plain(name) and (plain(name) in evidence or self._known_alias(name, known, evidence)):
                group = (artist.get("group") or "").strip()
                if artist.get("kind") != "soloist" or plain(group) == plain(name):
                    group = ""  # asked for a soloist's group, a model will name a group as its own
                found.append({"name": name, "kind": artist.get("kind", "group"), "group": group})
        return list({plain(a["name"]): a for a in found}.values())

    def release(self) -> None:
        self.client.generate(model=self.model, prompt="", keep_alive=0)

    def _known_alias(self, name: str, known: list[str], evidence: str) -> bool:
        # "Rosé" reused from the roster for a title that says "Rose" still passes; plain() folds both to rose
        return any(plain(name) == plain(k) and plain(k) in evidence for k in known)

    def _ask(self, question: str) -> dict | None:
        for room in (400, 800):
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}], format=NAMES,
                                     options={"temperature": 0, "num_ctx": 4096, "num_predict": room}, keep_alive="10m", think=False)
            try:
                return json.loads(reply.message.content)
            except json.JSONDecodeError:
                continue
        return None


class ArtistBook:
    """Every artist the job has met, in a JSON file: the site's spelling, the spellings videos use, the Wikipedia page
    and the int entry id. Two videos spelling BABYMONSTER and BabyMonster make one artist."""

    def __init__(self, path: Path):
        self.path = path
        self.artists = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}

    def names(self) -> list[str]:
        return sorted(self.artists)

    def find(self, name: str) -> dict | None:
        key = plain(name)
        for artist in self.artists.values():
            if key in {plain(alias) for alias in artist["aliases"]}:
                return artist
        return None

    def add(self, artist: dict) -> dict:
        self.artists[artist["name"]] = artist
        self.save()
        return artist

    def alias(self, artist: dict, name: str) -> None:
        if name not in artist["aliases"]:
            artist["aliases"].append(name)
            self.save()

    def save(self) -> None:
        self.path.write_text(json.dumps(self.artists, ensure_ascii=False, indent=1), encoding="utf-8")


class Wikipedia:
    """The facts about an artist come from Wikipedia and Wikidata rather than from a small model's memory: the intro as
    the biography (cited, as RevoltLib's biographies are), its first sentence as the description, debut or birth dates,
    the official site and the infobox picture."""

    def __init__(self, client: httpx.Client | None = None):
        self.http = client or httpx.Client(headers=AGENT, timeout=30, follow_redirects=True)

    def lookup(self, name: str, kind: str, group: str = "") -> dict | None:
        hint = "singer" if kind == "soloist" else "group"
        queries = [f"{name} {group} {hint}".strip(), f"{name} K-pop {hint}", name]
        for query in dict.fromkeys(queries):
            for title in self._search(query):
                page = self._summary(title)
                if page and self._is_artist(page, name):
                    return self._details(page)
        return None

    def _search(self, query: str) -> list[str]:
        reply = self.http.get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "list": "search", "srsearch": query, "srlimit": 4, "format": "json"}).json()
        return [hit["title"] for hit in reply.get("query", {}).get("search", [])]

    def _summary(self, title: str) -> dict | None:
        reply = self.http.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{title.replace(' ', '_')}")
        return reply.json() if reply.status_code == 200 else None

    def _is_artist(self, page: dict, name: str) -> bool:
        # The page has to be named for the artist and say it's about music: "Lay (singer)", not "Lay's", the crisps
        base = re.sub(r"\s*\(.*?\)\s*$", "", page.get("title", ""))
        named = plain(name) in plain(base) or plain(base) in plain(name) or plain(name) in plain(page.get("extract", "")[:200])
        return page.get("type") == "standard" and named and bool(MUSIC.search(page.get("description", "") + " " + page.get("extract", "")))

    def _details(self, page: dict) -> dict:
        title = page["title"]
        intro = self.http.get("https://en.wikipedia.org/w/api.php", params={
            "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "titles": title, "format": "json",
            "formatversion": 2}).json()["query"]["pages"][0].get("extract", "")
        facts = self._wikidata(page.get("wikibase_item", ""))
        return {"title": title, "url": page.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "short": page.get("description", ""), "intro": [_tidy(p) for p in intro.split("\n") if p.strip()],
                "image": _picture(page), **facts}

    def _wikidata(self, item: str) -> dict:
        if not item:
            return {}
        claims = self.http.get(f"https://www.wikidata.org/wiki/Special:EntityData/{item}.json").json()["entities"][item]["claims"]
        return {"born": _claim_date(claims, "P569"), "formed": _claim_date(claims, "P571") or _claim_date(claims, "P2031"),
                "website": _claim_value(claims, "P856")}

    def download(self, url: str, path: Path) -> Path | None:
        if not url:
            return None
        reply = self.http.get(url)
        if reply.status_code != 200:
            return None
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(reply.content)
        return path


def _tidy(paragraph: str) -> str:
    # The plain-text extract drops the pronunciation and leaves its separator: "Nmixx (; Korean: 엔믹스; ...)"
    paragraph = re.sub(r"\(\s*[;,]\s*", "(", paragraph.strip())
    return re.sub(r"\s*\(\s*\)", "", paragraph)


def _picture(page: dict) -> str:
    # Commons originals run to 6000 pixels and 15 MB; the site makes its own icon and standard sizes from 1280.
    # Wikimedia serves only its standard thumbnail widths (1280 is one; 1600 is a 400), and only from upload.
    original, thumbnail = page.get("originalimage") or {}, (page.get("thumbnail") or {}).get("source", "")
    if original.get("width", 0) > 1280 and re.search(r"/\d+px-", thumbnail):
        return re.sub(r"/\d+px-", "/1280px-", thumbnail.replace("//thumb.wikimedia.org/", "//upload.wikimedia.org/").split("?")[0])
    return original.get("source", "").split("?")[0]


def _claim_value(claims: dict, prop: str) -> str:
    for claim in claims.get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str):
            return value
    return ""


def _claim_date(claims: dict, prop: str) -> str:
    # Wikidata writes +2022-02-22T00:00:00Z; a date known only to the year has precision 9 and stays a bare year
    for claim in claims.get(prop, []):
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, dict) and value.get("time"):
            day = value["time"].lstrip("+")[:10]
            return day[:4] if value.get("precision", 11) < 11 else day
    return ""
