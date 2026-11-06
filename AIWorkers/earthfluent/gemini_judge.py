import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from dump_reader import WordRow
from word_check import WordCheck

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
KEY = Path(r"E:\Code\GeminiAPIKey.txt")  # Ben's key, kept on his machine, never in code or chat
SCHEMA = {"type": "OBJECT", "properties": {"sense_needed": {"type": "STRING"}, "word_means": {"type": "STRING"},
                                           "verdict": {"type": "STRING", "enum": ["ok", "suspect"]},
                                           "kind": {"type": "STRING"},  # Gemini's schema refuses an empty enum value
                                           "proposed": {"type": "STRING"}, "reason": {"type": "STRING"}},
          "required": ["sense_needed", "word_means", "verdict", "kind", "proposed", "reason"]}


class GeminiJudge:
    """The senior judge in Google's cloud: the same question the local jurors get, asked of a much larger model, gently paced for the free tier."""

    def __init__(self, dictionary, model: str = "gemini-3.8-flash", pace_seconds: float = 6.0):
        self.dictionary = dictionary
        self.model = model
        self.pace = pace_seconds
        self.key = KEY.read_text(encoding="utf-8-sig").strip()  # Notepad may save a byte-order mark first
        self.asker = WordCheck(model, dictionary, client=object())  # only borrows its question, never calls Ollama

    def check(self, row: WordRow) -> dict:
        glosses = self.dictionary.look_up(row.current)
        body = {"contents": [{"parts": [{"text": self.asker._question(row, glosses)}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json", "responseSchema": SCHEMA}}
        for wait in (self.pace, 30, 90):  # the free tier answers "slow down" with a 429; back off and try again
            time.sleep(wait)
            try:
                reply = self._post(body)
                text = reply["candidates"][0]["content"]["parts"][0]["text"]
                return {**json.loads(text), "dictionary": glosses}
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 503):
                    raise
            except (KeyError, IndexError, json.JSONDecodeError, TimeoutError, urllib.error.URLError):
                continue
        return {"verdict": "unanswered", "kind": "", "proposed": "", "reason": "The senior judge couldn't answer (busy or out of free quota); ask again later.", "dictionary": glosses}

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(API.format(model=self.model), data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "x-goog-api-key": self.key}, method="POST")
        with urllib.request.urlopen(request, timeout=90) as response:
            return json.load(response)
