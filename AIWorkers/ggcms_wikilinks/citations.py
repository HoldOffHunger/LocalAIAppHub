import re
from dataclasses import dataclass

from url_tools import URL, TRAILING, same_page

HEADING = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$", re.M)
DEAD_MARK = re.compile(r"\{\{\s*(?:dead[ _]link|deadlink|404|broken[ _]link|cbignore)[^{}]*\}\}", re.I)
DEAD_PARAM = re.compile(r"\|\s*(?:url-status\s*=\s*(?:dead|unfit|usurped)|dead-?url\s*=\s*(?:yes|true|y))\b", re.I)
ARCHIVED = re.compile(r"\|\s*archive-?url\s*=\s*https?://", re.I)
WEBARCHIVE = re.compile(r"\{\{\s*(?:webarchive|wayback|archive\.today|cite archive)[^{}]*\}\}", re.I)
URL_PARAM = re.compile(r"(\|\s*url\s*=\s*)([^|}]+)")
STATUS_PARAM = re.compile(r"\|\s*(?:url-status|dead-?url)\s*=[^|}]*")


@dataclass
class Citation:
    """Where one link sits in an article and what Wikipedia already knows about it."""

    shape: str  # "template", "bracketed" or "bare"
    text: str  # the citation exactly as written, with any dead-link mark after it
    section: str
    marked_dead: bool
    archived: bool  # an archive copy is already in it: adding ours is an extra, not a fix

    def with_our_link(self, link: str, url: str, site: str) -> str:
        # The citation with our permalink in place of the dead one; the dead-link mark goes, since the link no longer is
        body = DEAD_MARK.sub("", self.text).rstrip()
        if self.shape == "template":
            body = URL_PARAM.sub(lambda found: found.group(1) + link + (" " if found.group(2).endswith(" ") else ""), body, count=1)
            body = STATUS_PARAM.sub("", body)
            if not re.search(r"\|\s*via\s*=", body):
                body = body[:-2].rstrip() + f" |via={site}}}}}"
            return body
        return body.replace(url, link, 1)


def find_citation(wikitext: str, url: str) -> Citation | None:
    """The citation holding this url, matched however the article spells it (scheme, www, trailing slash)."""
    key = same_page(url)
    for found in URL.finditer(wikitext):
        written = found.group(0).rstrip(TRAILING)
        if same_page(written) == key:
            return _around(wikitext, found.start(), written)
    return None


def _around(wikitext: str, at: int, written: str) -> Citation:
    section = next((match.group(2) for match in reversed(list(HEADING.finditer(wikitext, 0, at)))), "(lead)")
    opened = wikitext.rfind("{{", 0, at)
    closed = wikitext.rfind("}}", 0, at)
    if opened > closed and re.match(r"\{\{\s*(?:cite|citation|ws|webcite)", wikitext[opened:], re.I):
        start, end = opened, _template_end(wikitext, opened)
        shape = "template"
    elif wikitext.rfind("[", 0, at) == at - 1:
        start, end = at - 1, wikitext.find("]", at) + 1 or at + len(written)
        shape = "bracketed"
    else:
        start, end, shape = at, at + len(written), "bare"
    after = wikitext[end:end + 160]
    mark = DEAD_MARK.match(after.lstrip())
    text = wikitext[start:end] + (after[:after.find(mark.group(0)) + len(mark.group(0))] if mark else "")
    marked = bool(mark) or (shape == "template" and bool(DEAD_PARAM.search(wikitext[start:end])))
    archived = bool(ARCHIVED.search(wikitext[start:end])) or bool(WEBARCHIVE.match(after.lstrip()[len(mark.group(0)) if mark else 0:].lstrip()))
    return Citation(shape, text, section, marked, archived)


def _template_end(wikitext: str, opened: int) -> int:
    depth, at = 0, opened
    while at < len(wikitext) - 1:
        pair = wikitext[at:at + 2]
        if pair == "{{":
            depth, at = depth + 1, at + 2
        elif pair == "}}":
            depth, at = depth - 1, at + 2
            if depth == 0:
                return at
        else:
            at += 1
    return len(wikitext)


FULL_TEXT = {"gutenberg.org": "Project Gutenberg", "wikisource.org": "Wikisource", "marxists.org": "Marxists Internet Archive",
             "theanarchistlibrary.org": "The Anarchist Library", "libcom.org": "libcom.org", "archive.org/details": "the Internet Archive",
             "hathitrust.org": "HathiTrust", "fadedpage.com": "Faded Page", "gutenberg.ca": "Project Gutenberg Canada",
             "librivox.org": "LibriVox (audio)", "standardebooks.org": "Standard Ebooks"}
FULL_TEXT_TEMPLATES = re.compile(r"\{\{\s*(wikisource|gutenberg|librivox|internet archive|standard ebooks|fadedpage)\b", re.I)


def full_text_elsewhere(wikitext: str) -> list[str]:
    # Who already gives the full text on this article, so Ben can see when ours would be a second copy
    lowered = wikitext.lower()
    found = [name for marker, name in FULL_TEXT.items() if marker in lowered]
    found += [f"{{{{{template.group(1)}}}}} template" for template in FULL_TEXT_TEMPLATES.finditer(wikitext)]
    return list(dict.fromkeys(found))


def lead(wikitext: str, most: int = 1500) -> str:
    # The article's opening prose, without templates, refs or files: what a reader (or the judge) sees first
    text = wikitext.split("\n==", 1)[0]
    for _ in range(4):
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"<ref[^>]*/>|<ref[^>]*>.*?</ref>", "", text, flags=re.S)
    text = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", text, flags=re.I)
    text = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"'{2,}|<[^>]+>", "", text)
    return " ".join(text.split())[:most]
