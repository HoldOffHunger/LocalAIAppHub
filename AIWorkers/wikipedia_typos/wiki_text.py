import re

# Where a word in wikitext is never ours to fix: file names, link targets, addresses, references, templates, code
# and quotations set apart. Each is blanked to spaces of the same length, so positions in the blanked text are
# positions in the article.
BLOCKS = re.compile(r"<!--.*?-->|<ref[^>/]*/>|<ref[^>]*>.*?</ref>|"
                    r"<(blockquote|poem|syntaxhighlight|source|math|code|pre|nowiki|gallery|timeline|score|chem)\b[^>]*>.*?</\1>",
                    re.S | re.I)
TEMPLATE = re.compile(r"\{\{[^{}]*\}\}|\{\|[^{}]*?\|\}", re.S)  # innermost first, so nested ones come apart from the inside
LINK = re.compile(r"\[\[([^\[\]|]*)(\|?)([^\[\]]*)\]\]([a-z]*)")  # letters straight after ]] are part of the link
URL = re.compile(r"\[?(?:https?:)?//[^\s\]|}<]+")
WHOLE_LINK = ("file:", "image:", "category:", "media:")
SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]]*\s+|\n")


def _blank(match: re.Match) -> str:
    return re.sub(r"[^\n]", " ", match.group(0))


def blank_markup(text: str) -> str:
    text = BLOCKS.sub(_blank, text)
    while True:
        blanked = TEMPLATE.sub(_blank, text)
        blanked = LINK.sub(_link, blanked)
        if blanked == text:
            break
        text = blanked
    return URL.sub(_blank, text)


def _link(match: re.Match) -> str:
    # [[target|label]] keeps only its label, where it stood; [[target]] is a title and [[File:…]] a file, so neither is
    # prose. The trail goes with the link, so "[[youth program]]mes" is never a word "mes" (2 Nov 2026: Denmark, the UAE)
    target, pipe, label, trail = match.groups()
    if not pipe or target.strip().lower().startswith(WHOLE_LINK):
        return _blank(match)
    return " " * (len(target) + 3) + label + trail + "  "


def occurrences(text: str, wrong: str) -> list[dict]:
    """Each place the misspelling stands as prose: its sentence (markup gone) and the raw wikitext round it."""
    blanked = blank_markup(text)
    # A whole word: not part of a longer one, nor of "o'word" or "word's", nor a quotation's "[w]hether" (2 Nov 2026: eight of
    # "hether"'s ten hits); wiki italics' '' round it are fine. Bold or italics inside a word don't end it: a poetry article's
    # "'''shu'''ttle", stress marked syllable by syllable, is "shuttle", never a word "ttle" (3 Nov 2026: Dactyl (poetry))
    pattern = re.compile(r"(?<![\w\-\])])(?<!\w')(?<!\w'')(?<!\w''')" + r"\s+".join(map(re.escape, wrong.split())) +
                         r"(?![\w-])(?!'\w)(?!'{2,3}\w)", re.I)
    found = []
    for match in pattern.finditer(blanked):
        start, end = match.span()
        if _sic(blanked, end) or (wrong[0].islower() and match.group(0)[0].isupper() and not _opens_sentence(blanked, start)):
            continue  # marked [sic], or capitalised mid-sentence: a name ("Lover Alot"), not a slip
        line_start = blanked.rfind("\n", 0, start) + 1
        if blanked[line_start:line_start + 1] in ("|", "!", "*", ";", ":") and blanked[line_start:start].count("=") > 0:
            continue  # a field of an infobox or table: "| name = …" is data, not prose
        sentence = _sentence(blanked, start, end)
        found.append({"word": match.group(0), "sentence": sentence, "quoted": _quoted(blanked, line_start, start),
                      "italic": _italic(text, line_start, start), "named": _named(text, blanked, line_start, start, end),
                      "raw": text[max(0, start - 100):end + 100], "at": start})
    return found


def split_by_markup(word: str, raw: str) -> bool:
    # For finds made before the whole-word check knew about bold and italics: the word fused to letters through '' or '''
    escaped = re.escape(word)
    return bool(re.search(rf"\w'{{2,3}}{escaped}|{escaped}'{{2,3}}\w", raw))


# The article naming or defining the word itself: "also called callop", "Claping (pronounced "clay-ping") refers to". Every
# exception Ben caught by 2 Nov 2026 that a sentence could show was written like this; a slip never is
NAMED_BEFORE = re.compile(r"\b(called|known( \w+ly)? as|termed|named|nicknamed|dubbed|the (word|term|name)|spelt|spelled)\s*['\"“‘]*$", re.I)
NAMED_AFTER = re.compile(r"^['\"”’]*\s*(\(\s*(pronounced|from|meaning|lit\b|literally|also|plural|singular|or)|"
                         r",?\s*(pronounced|refers to|referring to|means|meaning|is a (term|word|name)|is the (term|word|name)|"
                         r"is (an? )?(\w+ )?(word|term|name|spelling) for))", re.I)


# A word given in another language: "Tib. ''thig le''". A language's full name counts only before italics, the way a foreign
# word is set, since "Russian jursidiction" is a slip
LANGUAGE_SHORT = re.compile(r"\b(skt|tib|lat|gk|gr|ger|fr|it|sp|ar|heb|jap|chin|oe|me|ofr)\.\s*:?\s*['\"“‘]*$", re.I)
LANGUAGE_NAME = re.compile(r"\b(sanskrit|tibetan|pali|latin|greek|german|french|italian|spanish|portuguese|arabic|hebrew|"
                           r"japanese|chinese|korean|russian|old english|middle english|old french|anglo-norman)\s*:?\s*['\"“‘]*$", re.I)


def _named(text: str, blanked: str, line_start: int, start: int, end: int) -> bool:
    # Bold is Wikipedia's mark for the term an article or section defines: '''Claping'''. A bold line on its own, though,
    # is a makeshift heading ("'''Aditional sources'''", a real slip), so the bold must sit in prose
    line = text[line_start:text.find("\n", start) if "\n" in text[start:] else len(text)].strip()
    bold = text[line_start:start].count("'''") % 2 == 1 and not (line.startswith("'''") and line.endswith("'''"))
    # Linked to its own entry, "[[wikt:culch|culch]]": the editor looked it up
    own_entry = re.search(r"\[\[\s*(wikt:|wiktionary:)?" + re.escape(text[start:end]) + r"\s*\|$", text[max(0, start - 80):start], re.I)
    before = blanked[max(line_start, start - 40):start]
    foreign = LANGUAGE_SHORT.search(before) or (LANGUAGE_NAME.search(before) and _italic(text, line_start, start))
    return bold or bool(own_entry) or bool(NAMED_BEFORE.search(before)) or bool(foreign) or \
        bool(NAMED_AFTER.match(blanked[end:end + 60]))


def _sic(blanked: str, end: int) -> bool:
    return bool(re.match(r"\W{0,3}\[?sic\b", blanked[end:end + 12], re.I))


def _opens_sentence(blanked: str, start: int) -> bool:
    before = blanked[:start].rstrip(" '\"([")
    return not before or before[-1] in ".!?\n=|"


def _sentence(blanked: str, start: int, end: int) -> str:
    opening = max([m.end() for m in SENTENCE_END.finditer(blanked, max(0, start - 600), start)] or [max(0, start - 600)])
    closing = SENTENCE_END.search(blanked, end)
    span = blanked[opening:closing.start() + 1 if closing else end + 300]
    # Blanked markup leaves gaps ("1999 ."); the judge reads it as plain prose
    return re.sub(r" ([.,;:!?)])", r"\1", " ".join(span.replace("'''", "").replace("''", "").split()))


def _quoted(blanked: str, line_start: int, start: int) -> bool:
    # An odd number of straight or curly opening quotes before it on its line: it's inside a quotation
    before = blanked[line_start:start]
    return before.count('"') % 2 == 1 or before.count("“") > before.count("”")


def _italic(text: str, line_start: int, start: int) -> bool:
    # Inside ''…'': usually the title of a work, whose spelling is the work's own
    return text[line_start:start].replace("'''", "").count("''") % 2 == 1
