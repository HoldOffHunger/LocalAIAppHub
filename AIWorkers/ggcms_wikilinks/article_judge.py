import json

import ollama

VERDICT = {"type": "object", "properties": {"reason": {"type": "string"}, "same": {"type": "boolean"}}, "required": ["reason", "same"]}


class ArticleJudge:
    """Asks a local model whether a Wikipedia article is about our work or our author, from the article's opening; it can only say yes or no."""

    def __init__(self, model: str, site: str, client: ollama.Client | None = None):
        self.model = model
        self.site = site
        self.client = client or ollama.Client()

    def about_work(self, title: str, author: str, article: str, opening: str) -> dict:
        by = f" by {author}" if author else ""
        return self._ask(
            f"On {self.site} we host the full text of \"{title}\"{by}.\n\nThis is the opening of the Wikipedia article "
            f"\"{article}\":\n\n{opening}\n\nIs this article about that very written work (the book, essay, pamphlet, poem or "
            f"speech \"{title}\"{by}), and not a person, place, idea, film, another work of the same name, or a general "
            f"topic? First give your reason in one sentence, then same: true or false. Reply as JSON.")

    def about_author(self, author: str, works: list[str], article: str, opening: str) -> dict:
        listed = "; ".join(f"\"{work}\"" for work in works[:6])
        return self._ask(
            f"On {self.site} we host writing by {author}, including {listed}.\n\nThis is the opening of the Wikipedia article "
            f"\"{article}\":\n\n{opening}\n\nIs this article about that same person, the writer of those works, and not someone "
            f"else with the same name? First give your reason in one sentence, then same: true or false. Reply as JSON.")

    def release(self) -> None:
        self.client.generate(model=self.model, prompt="", keep_alive=0)

    def _ask(self, question: str) -> dict:
        for room in (200, 400):  # a reply cut off mid-sentence gets one more try with more room
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}], format=VERDICT,
                                     options={"temperature": 0, "num_ctx": 4096, "num_predict": room}, keep_alive="10m", think=False)
            try:
                found = json.loads(reply.message.content)
                return {"same": bool(found.get("same")), "reason": str(found.get("reason", ""))}
            except json.JSONDecodeError:
                continue
        return {"same": False, "reason": "The judge's reply couldn't be read; counted as no."}
