import json

import ollama

TOPICS = {"type": "object", "properties": {"topics": {"type": "array", "items": {"type": "string"}}}, "required": ["topics"]}


class TopicPick:
    """Asks a local model for a quote's 3 to 5 topics; the caller keeps only tags the site already uses."""

    def __init__(self, model: str, site: str, suggested: list[str], client: ollama.Client | None = None):
        self.model = model
        self.site = site
        self.suggested = suggested  # the most-used tags, so the model reaches for the house spellings
        self.client = client or ollama.Client()

    def topics(self, item: dict) -> list[str]:
        said = f" by {item['author']}" if item["author"] else ""
        reply = self._ask(
            f"This quote{said} is on {self.site}, filed under \"{item['work']}\":\n\n{item['quote']}\n\n"
            f"Give 3 to 5 topic tags for it: the subjects it's about, the way a librarian would shelve it. Name ideas, "
            f"movements, institutions and struggles (\"the state\" is \"state\"; \"imperial power\" is \"imperialism\"), not "
            f"words that merely appear in it. Use lowercase, and use these tags where one fits:\n\n{', '.join(self.suggested)}\n\n"
            f"Reply as JSON, most fitting first.")
        return [topic.strip().lower() for topic in (reply or {}).get("topics", []) if isinstance(topic, str) and topic.strip()]

    def release(self) -> None:
        self.client.generate(model=self.model, prompt="", keep_alive=0)

    def _ask(self, question: str) -> dict | None:
        for room in (150, 300):  # a reply cut off mid-list gets one more try with more room
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}], format=TOPICS,
                                     options={"temperature": 0, "num_ctx": 4096, "num_predict": room}, keep_alive="10m", think=False)
            try:
                return json.loads(reply.message.content)
            except json.JSONDecodeError:
                continue
        return None
