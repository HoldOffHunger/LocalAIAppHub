import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from dump_reader import WordRow
from word_check import VERDICT, WordCheck

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
CREDENTIALS = Path(r"E:\Code\CloudFlareAPIKey.txt")  # Ben's account ID and token, kept on his machine, never in code or chat


def _credentials() -> tuple[str, str]:
    # The account ID is the 32-character hex line; the token is the other one
    lines = [line.strip() for line in CREDENTIALS.read_text(encoding="utf-8-sig").splitlines() if line.strip()]
    account = next(line for line in lines if re.fullmatch(r"[0-9a-f]{32}", line))
    return account, next(line for line in lines if line != account)


class CloudflareJudge:
    """A senior judge on Cloudflare Workers AI's free daily allowance: the jurors' question, asked of a much bigger model."""

    def __init__(self, dictionary, model: str = "@cf/meta/llama-3.3-70b-instruct-fp8-fast", pace_seconds: float = 2.0):
        self.dictionary = dictionary
        self.model = model
        self.pace = pace_seconds
        self.account, self.token = _credentials()
        self.asker = WordCheck(model, dictionary, client=object())  # only borrows its question, never calls Ollama

    def check(self, row: WordRow) -> dict:
        glosses = self.dictionary.look_up(row.current)
        body = {"messages": [{"role": "user", "content": self.asker._question(row, glosses)}], "temperature": 0, "max_tokens": 400,
                "response_format": {"type": "json_schema", "json_schema": VERDICT}}
        for wait in (self.pace, 20, 60):  # a busy or rate-limited answer gets two calmer retries
            time.sleep(wait)
            try:
                result = self._post(body)["result"]["response"]
                return {**(result if isinstance(result, dict) else json.loads(result)), "dictionary": glosses}
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503):
                    raise
            except (KeyError, TypeError, json.JSONDecodeError, TimeoutError, urllib.error.URLError):
                continue
        return {"verdict": "unanswered", "kind": "", "proposed": "", "reason": "The senior judge couldn't answer (busy or out of free quota); ask again later.", "dictionary": glosses}

    def _post(self, body: dict) -> dict:
        request = urllib.request.Request(API.format(account=self.account, model=self.model), data=json.dumps(body).encode(),
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}, method="POST")
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)
