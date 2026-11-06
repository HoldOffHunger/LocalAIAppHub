import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from dump_reader import WordRow
from word_check import VERDICT, WordCheck

SCHEMA = {"name": "verdict", "strict": True, "schema": {**VERDICT, "additionalProperties": False,
          "properties": {**VERDICT["properties"], "kind": {"type": "string"}}}}  # strict mode wants every field plain and listed
# Every OpenAI-style service: where it lives and where Ben's key for it is kept (never in code or chat)
SERVICES = {"openai": ("https://api.openai.com/v1", Path(r"E:\Code\OpenAI.txt")),
            "nvidia": ("https://integrate.api.nvidia.com/v1", Path(r"E:\Code\Nvidia.txt")),
            "hf": ("https://router.huggingface.co/v1", Path(r"E:\Code\HuggingFace.txt"))}


class OpenAIJudge:
    """A senior judge on any OpenAI-style API (OpenAI, NVIDIA, Hugging Face): the jurors' question, asked of a bigger model."""

    def __init__(self, dictionary, model: str = "gpt-5.4-mini", service: str = "openai", pace_seconds: float = 1.0):
        self.dictionary = dictionary
        self.model = model
        self.pace = pace_seconds
        self.base, key_file = SERVICES[service]
        self.key = _key(key_file.read_text(encoding="utf-8-sig"))
        self.asker = WordCheck(model, dictionary, client=object())  # only borrows its question, never calls Ollama
        self.strict = True  # dropped for services that refuse JSON-schema replies

    def check(self, row: WordRow) -> dict:
        glosses = self.dictionary.look_up(row.current)
        for wait in (self.pace, 20, 60):  # a busy or rate-limited answer gets two calmer retries
            time.sleep(wait)
            try:
                return {**_json(self._ask(self.asker._question(row, glosses))), "dictionary": glosses}
            except urllib.error.HTTPError as error:
                if error.code == 400 and self.strict:
                    self.strict = False
                elif error.code not in (429, 500, 502, 503):
                    raise
            except (KeyError, IndexError, TypeError, ValueError, TimeoutError, urllib.error.URLError):
                continue
        return {"verdict": "unanswered", "kind": "", "proposed": "", "reason": "The senior judge couldn't answer (busy or out of free quota); ask again later.", "dictionary": glosses}

    def _ask(self, question: str) -> str:
        body = {"model": self.model, "messages": [{"role": "user", "content": question}], "temperature": 0, "max_tokens": 600}
        if self.strict:
            body["response_format"] = {"type": "json_schema", "json_schema": SCHEMA}
        request = urllib.request.Request(f"{self.base}/chat/completions", data=json.dumps(body).encode(), method="POST",
                                         headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.key}"})
        with urllib.request.urlopen(request, timeout=180) as response:
            return json.load(response)["choices"][0]["message"]["content"]


def _key(text: str) -> str:
    # Ben's key files may carry labels ("API Key: nvapi-…"); a known key prefix wins, else the last line's last word
    found = re.search(r"(nvapi-|sk-|hf_)[A-Za-z0-9_\-]+", text)
    return found.group(0) if found else text.strip().splitlines()[-1].split()[-1]


def _json(text: str) -> dict:
    # Without strict mode a model may wrap its JSON in prose or a code fence; take the object itself
    found = re.search(r"\{.*\}", text, re.S)
    reply = json.loads(found.group(0) if found else text)
    if reply.get("verdict") not in ("ok", "suspect"):
        raise ValueError("no verdict")
    return reply
