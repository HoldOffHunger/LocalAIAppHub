import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://en.wiktionary.org/api/rest_v1/page/definition/"
AGENT = "EarthFluent-review/0.1 (a personal, local translation check)"


class WiktionaryOnline:
    """The same lookup as DictionaryIndex, but asked of Wiktionary's live API one word at a time, cached on disk. For small tests before a full dump is indexed."""

    def __init__(self, lang: str, cache: Path):
        self.lang = lang
        self.cache = cache
        self.known = json.loads(cache.read_text(encoding="utf-8")) if cache.exists() else {}

    def look_up(self, phrase: str) -> list[str]:
        word = phrase.strip()
        key = f"{self.lang}:{word}"
        if key not in self.known:
            found = self._fetch(word)
            found = found if found or word == word.lower() else self._fetch(word.lower())
            if found is None:
                return []  # couldn't ask; don't remember "nothing" for a word we never really looked up
            self.known[key] = found
            self.cache.write_text(json.dumps(self.known, ensure_ascii=False), encoding="utf-8")
        return self.known[key]

    def _fetch(self, word: str) -> list[str] | None:
        # Wikimedia asks for a gentle pace: one request a second, and a pause when it says slow down
        request = urllib.request.Request(API + urllib.parse.quote(word.replace(" ", "_")), headers={"User-Agent": AGENT})
        for wait in (1.2, 10, 30):
            time.sleep(wait)
            try:
                with urllib.request.urlopen(request, timeout=20) as response:
                    entries = json.load(response).get(self.lang, [])
                return [f"{e['partOfSpeech'].lower()}: {'; '.join(_text(d['definition']) for d in e['definitions'][:6])}" for e in entries][:4]
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return []
            except (OSError, ValueError):
                pass
        return None


def _text(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment)).strip()
