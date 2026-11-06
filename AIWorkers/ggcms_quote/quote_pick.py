import json

import ollama

SHORTLIST = {"type": "object", "properties": {"about": {"type": "string"}, "picks": {"type": "array", "items": {"type": "integer"}}},
             "required": ["about", "picks"]}  # what the text is about first, so the picks serve its theme
CHOICE = {"type": "object", "properties": {"pick": {"type": "integer"}, "reason": {"type": "string"}}, "required": ["pick", "reason"]}


class QuotePick:
    """Asks a local model to choose a text's best quote from numbered sentences, so it can never invent one."""

    def __init__(self, model: str, site: str, client: ollama.Client | None = None):
        self.model = model
        self.site = site
        self.client = client or ollama.Client()

    def shortlist(self, item: dict, size: int = 3) -> list[int]:
        reply = self._ask(self._numbered(item) + (
            f"First write about: one sentence on what this text is about. Then pick the {size} most inspiring sentences: the "
            f"ones that would move a reader if they saw them alone on the page. Look for a call to act, a conviction stated "
            f"boldly, defiance, hope, or a hard truth put memorably. A plain definition, a summary, a fact or an argument's "
            f"middle step is not inspiring. Each must make sense on its own, without the sentences around it. Give their numbers "
            f"in picks, most inspiring first. Reply as JSON."), SHORTLIST, 300)
        # The sentences are numbered from 1, the way a model counts; the pile keeps them from 0
        picks = [n - 1 for n in (reply or {}).get("picks", []) if isinstance(n, int) and 1 <= n <= len(item["candidates"])]
        return list(dict.fromkeys(picks))[:size]

    def choose(self, item: dict, shortlist: list[int]) -> dict:
        options = "\n".join(f"{n + 1}. {item['candidates'][n]}" for n in shortlist)
        reply = self._ask(
            f"These sentences are from {_named(item)}, a text on {self.site}.\n\n{options}\n\n"
            f"Which one is the most inspiring quote to show on the text's page: the one that would most move or rouse a reader "
            f"who saw it alone, a call, a conviction, defiance or hope, rather than a definition or summary? It must still make "
            f"sense alone. Give its number in pick, and a one-sentence reason. Reply as JSON.", CHOICE, 200)
        if reply and isinstance(reply.get("pick"), int) and reply["pick"] - 1 in shortlist:
            return {**reply, "pick": reply["pick"] - 1}
        return {"pick": shortlist[0], "reason": "The judge couldn't decide; this was the screener's first choice."}

    def release(self) -> None:
        # The 8 GB card can't hold the screener and the judge at once; one left parked pushes the other onto the CPU
        self.client.generate(model=self.model, prompt="", keep_alive=0)

    def _numbered(self, item: dict) -> str:
        lines = "\n".join(f"{n}. {sentence}" for n, sentence in enumerate(item["candidates"], 1))
        return f"These numbered sentences are from {_named(item)}, a text on {self.site}.\n\n{lines}\n\n"

    def _ask(self, question: str, schema: dict, tokens: int) -> dict | None:
        for room in (tokens, tokens * 2):  # a reply cut off mid-sentence gets one more try with more room
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}], format=schema,
                                     options={"temperature": 0, "num_ctx": 4096, "num_predict": room}, keep_alive="10m", think=False)
            try:
                return json.loads(reply.message.content)
            except json.JSONDecodeError:
                continue
        return None


def _named(item: dict) -> str:
    return f"\"{item['title']}\"" + (f" ({item['source']})" if item["source"] else "")
