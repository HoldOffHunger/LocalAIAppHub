import re

SENTENCE_END = re.compile(r"(?:(?<=[.!?])|(?<=[.!?][\"”’']))\s+(?=[\"“‘'(]?[A-Z])")
NOT_PROSE = re.compile(r"https?://|www\.|\[[^\]]*\]|^\d|^(?:chapter|footnote|note|section|part|volume|fig)\b|\bibid\b|\bop\. cit\b"
                       r"|[a-z]- [a-z]", re.I)  # editors' [?] and [1], and words still split by an old line-break hyphen
LEANS_BACK = re.compile(r"[\"“‘'(]?(?:it|its|this|that|these|those|he|she|they|them|his|her|their|and|but|or|so|thus|then|hence|"
                        r"however|yet|also|instead|later|such|here|there|which|both|nor|moreover|therefore|again|still)\b", re.I)


def candidates(paragraphs: list[str], most: int = 20, shortest: int = 60, longest: int = 350) -> list[str]:
    """Whole sentences that could stand alone as a quote, spread evenly through the text. The model only ever picks from these,
    so whatever it chooses is word for word from the text."""
    found = []
    for paragraph in paragraphs:
        for sentence in SENTENCE_END.split(paragraph):
            sentence = sentence.strip()
            if shortest <= len(sentence) <= longest and _quotable(sentence):
                found.append(sentence)
    if len(found) <= most:
        return found
    step = len(found) / most
    return [found[int(i * step)] for i in range(most)]


def _quotable(sentence: str) -> bool:
    if NOT_PROSE.search(sentence) or sentence.isupper():
        return False
    if not re.match(r"[\"“‘'(]?[A-Z]", sentence) or not re.search(r"[.!?][\"”’')]?$", sentence):
        return False  # a whole sentence: starts with a capital, ends with a stop
    if LEANS_BACK.match(sentence):
        return False  # "It maintains…", "And while…", "This is an ideal…" need the sentence before them; the screener ignores that rule
    if sum(c.isdigit() for c in sentence) > 6:
        return False  # tables, dates and statistics read badly out of context
    return sentence.count("“") == sentence.count("”") and sentence.count("\"") % 2 == 0  # no half-open quotations
