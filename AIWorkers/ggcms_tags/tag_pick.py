import json

import ollama

STRIKE = {"type": "object", "properties": {"about": {"type": "string"}, "strike": {"type": "array", "items": {"type": "integer"}}},
          "required": ["about", "strike"]}  # what the text is about first, so the strikes serve its theme


class TagPick:
    """Asks a local model which of ListKeywords' numbered keywords are off the text's theme, so it can only remove, never invent."""

    def __init__(self, model: str, site: str, client: ollama.Client | None = None):
        self.model = model
        self.site = site
        self.client = client or ollama.Client()

    def strike(self, item: dict) -> dict:
        numbered = "\n".join(f"{n}. {keyword}" for n, keyword in enumerate(item["candidates"], 1))
        reply = self._ask(
            f"\"{item['title']}\" is a text on {self.site}. It opens:\n\n{item['opening']}\n\n"
            f"These keywords were counted from the whole text, most common first:\n\n{numbered}\n\n"
            f"First write about: one sentence on what the text is about. Then list in strike the numbers of the keywords that "
            f"would make poor tags for it: words off its theme (\"ham\" in a speech about a union), filler that says nothing "
            f"about the subject, broken phrases cut off mid-thought, and stray bits of markup or citation. Keep the names, "
            f"places, ideas, movements and things the text is about. Reply as JSON.")
        # The keywords are numbered from 1, the way a model counts; the pile keeps them from 0
        struck = {n - 1 for n in (reply or {}).get("strike", []) if isinstance(n, int) and 1 <= n <= len(item["candidates"])}
        return {"about": (reply or {}).get("about", ""), "struck": sorted(struck), "answered": reply is not None}

    def release(self) -> None:
        self.client.generate(model=self.model, prompt="", keep_alive=0)

    def _ask(self, question: str) -> dict | None:
        for room in (900, 1800):  # a reply cut off mid-list gets one more try with more room
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}], format=STRIKE,
                                     options={"temperature": 0, "num_ctx": 6144, "num_predict": room}, keep_alive="10m", think=False)
            try:
                return json.loads(reply.message.content)
            except json.JSONDecodeError:
                continue
        return None
