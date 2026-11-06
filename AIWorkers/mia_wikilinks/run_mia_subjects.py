"""Wikipedia articles about the subjects MIA's history/ and subject/ collections document, with no link to that collection:
parties, newspapers, revolutions, congresses, movements, ideas. The author worker's twin, run by run_mia_links.py when the
target is a history/ or subject/ folder. Results are edits for Ben to make by hand, disclosing that he volunteers for MIA.

    run_mia_links.py --target marxists.org/history/france --queue <pile> --results <file> [--until 06:00]

Every folder under the target with an index page and at least MIN_PAGES pages is a collection. Its names are its index page's
title and its folder's own name ("history/france/may-1968" is "may 1968"); a Wikipedia article titled the same is a candidate.
The code drops what it can (films, bands, disambiguation pages, articles that already link the collection), and gemma4:12b
decides the rest from the collection's own opening text and the article's lead. When unsure, no.
"""

import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "shared"))
sys.path.insert(0, str(HERE.parent / "ggcms_wikilinks"))
from task_queue import TaskQueue  # noqa: E402

from article_judge import ArticleJudge  # noqa: E402
from citations import lead  # noqa: E402
from run_wikilinks import deadline  # noqa: E402
from wiki_api import WikiApi  # noqa: E402
from wiki_dumps import WikiDumps  # noqa: E402
from wiki_index import WikiIndex, title_key  # noqa: E402

from mia_texts import BASE, LISTING, SITE as MIRROR, page_title  # noqa: E402
from run_mia_links import ABOUT, SITE, _borrow_links, _disambiguation  # noqa: E402
from subjects_probe import NOISE, TITLE_TAIL, folders  # noqa: E402
from loose_names import acronym, aside_fits, comintern_party, loose_key, scan_loose  # noqa: E402

MIN_PAGES = 3  # fewer than this is a stray document, not a collection worth an External links line
# What a same-named article is when it isn't the subject: the code drops these before the judge sees them
NOT_SUBJECT = ("film", "album", "song", "band", "tv series", "television", "video game", "novel", "play", "painting", "sculpture",
               "opera", "musical", "ep", "single", "comics", "game", "horse", "ship", "football", "cycling team", "sports team",
               "racehorse", "rapper", "musician", "group", "disambiguation", "surname", "given name", "name")
HISTORY_OF = re.compile(r"^(?:a |the )?(?:history|archive|documents|writings) (?:of|on) (?:the )?", re.I)
ASIDES = re.compile(r"\s*\([^()]*\)")
DATES = re.compile(r"[\s,:–—-]*\b\d{4}(?:\s*[-–—]\s*\d{2,4})?s?\s*$")
NOT_TEXT = re.compile(r"<(script|style|head)\b.*?</\1>", re.I | re.S)


@dataclass
class Collection:
    folder: str  # "history/france/may-1968"
    name: str  # what the index page calls it, or the folder's name
    keys: set[str]
    pages: int
    index: str  # "index.htm" or "index.html"
    opening: str  # the index page's first words, for the judge

    @property
    def link(self) -> str:
        return f"{BASE}{self.folder}/{self.index}"

    @property
    def filed(self) -> str:
        # "history / france / may 1968": where MIA files it, which tells the judge what kind of thing it is
        return " / ".join(part.replace("-", " ").replace("_", " ") for part in self.folder.split("/"))


def _decode(raw: bytes) -> str:
    return raw.decode("utf-8", "replace") if b"charset=utf-8" in raw[:3000].lower() else raw.decode("cp1252", "replace")


def opening_text(raw: bytes, most: int = 700) -> str:
    text = NOT_TEXT.sub(" ", _decode(raw))
    text = re.sub(r"<[^>]+>", " ", text)
    return " ".join(html.unescape(text).split())[:most]


def clean_title(title: str) -> str:
    for _ in range(3):  # "Red Front: Index | Encyclopedia of Anti-Revisionism On-Line"
        title = TITLE_TAIL.sub("", title)
        title = re.sub(r"\s*[:|–—-]\s*index\s*$", "", title, flags=re.I)
        title = re.sub(r"\s*,?\s*(?:from|on|at)\s+marxists\.org\s*$", "", title, flags=re.I)
    return title.strip(" :|–—-")


def names_for(folder: str, title: str) -> tuple[str, set[str]]:
    # The display name, and every title key it could be filed under on Wikipedia
    slug = folder.rsplit("/", 1)[-1]
    slug_words = "" if NOISE.match(slug) else re.sub(r"[-_.]+", " ", slug).strip()
    titled = bool(title) and len(title.split()) <= 8
    names = set()
    if slug_words and not slug_words.isdigit() and (" " in slug_words or not titled):
        names.add(slug_words)  # a one-word folder ("women", "texts") only when the index page gives no better name
    if titled:
        names.add(title)
        bare = HISTORY_OF.sub("", title)  # "History of the Second International" is filed as "Second International"
        bare = DATES.sub("", ASIDES.sub("", bare)).strip(" ,:–—-")  # "International Socialism (1st Series) 1958-1968"
        if bare and bare != title:
            names.add(bare)
    keys = set()
    for name in names:
        key = title_key(name)[0]
        if key and len(key) >= 4:
            keys |= {key, key.removeprefix("the ")}
    shown = title if titled else slug_words.title()
    return shown, keys - {""}


def read_collections(target: str, listing: Path = LISTING, site: Path = MIRROR, least: int = MIN_PAGES) -> list[Collection]:
    prefix = target.rstrip("/")
    sizes = folders(listing, (prefix + "/",))  # the target folder itself counts too, unless it's a whole section
    found = []
    for folder, pages in sorted(sizes.items()):
        if pages < least or "/" not in folder:
            continue
        index = next((name for name in ("index.htm", "index.html") if (site / folder / name).exists()), None)
        if index is None:
            continue  # no front page to link
        raw = (site / folder / index).read_bytes()
        name, keys = names_for(folder, clean_title(page_title(raw)))
        if keys:
            found.append(Collection(folder, name, keys, pages, index, opening_text(raw)))
    return found


MATCHES = ("same", "broader", "narrower", "different")
# 4 Nov 2026, history/france: a yes/no judge said yes to Trotskyism for French Trotskyists in the Resistance while calling it
# "broader", and to Miró's painting May 1968 while calling it a painting. Naming the relation makes it choose one.
MATCH = {"type": "object", "properties": {"reason": {"type": "string"}, "match": {"type": "string", "enum": list(MATCHES)}},
         "required": ["reason", "match"]}
CREATIVE = re.compile(r"\b(?:is|was) an? (?:[\w-]+ ){0,3}(?:painting|film|book|novel|album|song|poem|play|opera|documentary|"
                      r"sculpture|television series|tv series|short story|biography|video game)\b", re.I)


class SubjectJudge(ArticleJudge):
    def about_collection(self, collection: Collection, article: str, opening: str) -> dict:
        question = (
            f"On {self.site} we host a collection titled \"{collection.name}\": {collection.pages} pages, filed under "
            f"{collection.filed}. Its index page begins:\n\n{collection.opening}\n\nThis is the opening of the Wikipedia article "
            f"\"{article}\":\n\n{opening}\n\nHow does the article's subject compare with the collection's? \"same\": the very "
            f"party, organisation, newspaper or journal, congress, event, person, movement or idea the collection documents. "
            f"\"broader\": the article covers more (a whole ideology, country, parent organisation or era) and the collection "
            f"is one part of it. \"narrower\": the article is one part of the collection's subject. \"different\": another "
            f"thing with the same name, or a book, film or artwork about the subject. When unsure, \"different\". "
            f"First give your reason in one sentence, then match. Reply as JSON.")
        for room in (200, 400):  # a reply cut off mid-sentence gets one more try with more room
            reply = self.client.chat(model=self.model, messages=[{"role": "user", "content": question}], format=MATCH,
                                     options={"temperature": 0, "num_ctx": 4096, "num_predict": room}, keep_alive="10m", think=False)
            try:
                found = json.loads(reply.message.content)
            except json.JSONDecodeError:
                continue
            match = found.get("match") if found.get("match") in MATCHES else "different"
            return {"same": match == "same", "match": match, "reason": str(found.get("reason", ""))}
        return {"same": False, "match": "different", "reason": "The judge's reply couldn't be read; counted as no."}


def fill(queue: TaskQueue, index: WikiIndex, collections: list[Collection], target: str, ends) -> bool:
    if not index.meta("links_done") and not _borrow_links(index):
        if not index.scan_links(WikiDumps(), {"marxists.org"}, ends):
            return False
    if not index.scan_pages(WikiDumps(), {key for each in collections for key in each.keys}, ends):
        return False
    # Added after whatever the pile already holds, never in its place: a task's finds only ever grow, as every worker's do
    (last,) = queue.connection.execute("SELECT COALESCE(MAX(id), 0) FROM items").fetchone()
    items = _pile(index, collections, last)
    about = {"collections_from": f"{target} ({len(collections)} collections in the local mirror)"}
    if not queue.filled():
        about |= {"filled_from": about["collections_from"], "links_from": index.meta("links_from") or "Wikipedia's externallinks table"}
    queue.fill(items, about)
    print(f"filled: {len(items)} articles titled like {len(collections)} collections under {target}", flush=True)
    return True


def front(folder: str) -> re.Pattern:
    # A link to the collection itself (its folder or its index page), not to one document inside it
    return re.compile(r"marxists\.org/" + re.escape(folder.lower()) + r"/?(?:index\.html?)?(?=[\s|\]}<\"'#?]|$)")


def _linked(index: WikiIndex) -> dict[int, list[str]]:
    linked: dict[int, list[str]] = {}
    for page, _, url, _ in index.links():
        linked.setdefault(page, []).append(url.lower())
    return linked


def history_keys(each: Collection) -> set[str]:
    # 4 Nov 2026, Ben: "USSR" found Soviet Union, but History of the Soviet Union matters as much and shares no title with it.
    # "History of the USSR" is a redirect there, so the variants are looked up the same way the names are
    keys = set()
    for key in each.keys:
        if not key.startswith("history"):
            keys |= {f"history of {key}", f"history of the {key}", f"{key} history"}
    return keys


def _pile(index: WikiIndex, collections: list[Collection], after: int = 0, keys_of=None, linked=None, taken=None,
          source: str = "title") -> list[dict]:
    # Numbered after the pile's last item ("after"), so they're added to it, never written over it
    keys_of = keys_of or (lambda each: each.keys)
    linked = _linked(index) if linked is None else linked
    items, seen = [], set(taken or ())
    for each in sorted(collections, key=lambda each: -each.pages):  # the biggest collections first
        home = front(each.folder)
        for key in sorted(keys_of(each)):
            for page, article, redirect, aside in index.titled(key):
                if (page, each.folder) in seen or any(aside == word or word in aside.split() for word in NOT_SUBJECT):
                    continue
                if aside and not aside_fits(aside, f"{each.name} {each.filed}"):
                    continue  # "May 1968 (Miró)", "The French Revolution (Carlyle)", "Social Democracy (Serbia)": something else
                seen.add((page, each.folder))
                urls = linked.get(page, [])
                if any(home.search(url) for url in urls):
                    continue
                items.append({"kind": "subject", "source": source, "page": article, "page_id": page, "folder": each.folder,
                              "title": each.name, "aside": aside, "redirect": bool(redirect), "pages": each.pages,
                              "mia_links": len(urls)})
    return [{**item, "id": number} for number, item in enumerate(items, after + 1)]


CITES = 2  # documents an article must cite from inside one collection before the collection itself is offered to it
# A collection holding this many others is a hub (EROL holds 391, ETOL 539). 4 Nov 2026, task 29: an article citing EROL
# documents from all over was offered EROL itself (Communist Party of Poland). Hubs are never offered to a citing article;
# a title match still may be (USSR, 33 inside, is the Soviet Union's)
HUB = 30


def _citing(index: WikiIndex, collections: list[Collection], after: int, taken: set) -> list[dict]:
    # Articles that cite documents inside a collection but never link the collection itself: the borrowed link index
    # already holds them, so no new reading. One per article: the most specific collection holding CITES of its documents
    by_folder = {each.folder.lower(): each for each in collections}
    inside = {folder: sum(1 for other in by_folder if other.startswith(folder + "/")) for folder in by_folder}
    by_folder = {folder: each for folder, each in by_folder.items() if inside[folder] < HUB}
    titles = {page: article for page, article, _, _ in index.links()}
    items = []
    for page, urls in _linked(index).items():
        counts: dict[str, int] = {}
        for url in set(urls):
            path = re.sub(r"^https?://(?:www\.)?marxists\.org/", "", url).split("#")[0].split("?")[0].rstrip("/")
            parts = path.split("/")
            for depth in range(2, len(parts)):  # every collection above the document, not the document itself
                folder = "/".join(parts[:depth])
                if folder in by_folder:
                    counts[folder] = counts.get(folder, 0) + 1
        held = [folder for folder, count in counts.items() if count >= CITES]
        if not held:
            continue
        each = by_folder[max(held, key=lambda folder: folder.count("/"))]
        if (page, each.folder) in taken or any(front(each.folder).search(url) for url in urls):
            continue
        items.append({"kind": "subject", "source": "cites", "cites": counts[each.folder.lower()], "page": titles[page],
                      "page_id": page, "folder": each.folder, "title": each.name, "aside": "", "redirect": False,
                      "pages": each.pages, "mia_links": len(urls)})
    items.sort(key=lambda item: (-item["cites"], -item["pages"]))
    return [{**item, "id": number} for number, item in enumerate(items, after + 1)]


def widen(queue: TaskQueue, index: WikiIndex, collections: list[Collection], target: str, queue_path: Path, ends) -> bool:
    # The two wider sources, each added to the pile once, after what's there
    def last() -> int:
        return queue.connection.execute("SELECT COALESCE(MAX(id), 0) FROM items").fetchone()[0]

    def taken() -> set:
        return {(item["page_id"], item["folder"]) for (data,) in queue.connection.execute("SELECT data FROM items")
                for item in [json.loads(data)] if item.get("kind") == "subject"}

    if queue.meta("citing_from") is None:
        items = _citing(index, collections, last(), taken())
        queue.fill(items, {"citing_from": f"articles citing {CITES}+ documents in one collection under {target}"})
        print(f"added: {len(items)} articles that cite a collection's documents but not the collection", flush=True)
    if queue.meta("history_of_from") is None:
        variants = WikiIndex(queue_path.with_suffix(".history-of.wiki.sqlite"))  # a title read of its own, resumable
        if not variants.scan_pages(WikiDumps(), {key for each in collections for key in history_keys(each)}, ends):
            return False
        items = _pile(variants, collections, last(), history_keys, _linked(index), taken(), "history of")
        queue.fill(items, {"history_of_from": f"\"History of …\" titles for the collections under {target}"})
        print(f"added: {len(items)} articles titled \"History of …\" a collection", flush=True)
    if queue.meta("loose_from") is None:
        loose = WikiIndex(queue_path.with_suffix(".loose.wiki.sqlite"))  # Ben's looser key, a title read of its own
        if not scan_loose(loose, WikiDumps(), {key for each in collections for key in loose_keys(each)}, ends):
            return False
        items = _pile(loose, collections, last(), loose_keys, _linked(index), taken(), "loose")
        queue.fill(items, {"loose_from": f"loose names (ism/ist, a country's adjective, any word order, acronyms, Comintern parties) under {target}"})
        print(f"added: {len(items)} articles by the looser names", flush=True)
    if queue.meta("search_from") is None:
        if not _search(queue, collections, _linked(index), last, taken, ends):
            return False
        queue.fill([], {"search_from": f"Wikipedia's own search, the top {SEARCH_TOP} for each collection's name under {target}"})
    return True


def loose_keys(each: Collection) -> set[str]:
    names = set(each.keys) | set(comintern_party(each.folder))
    slug = acronym(each.folder.rsplit("/", 1)[-1].lower())
    if slug and not NOISE.match(slug):
        names.add(slug)
    return {key for key in (loose_key(name) for name in names) if len(key) >= 3}


SEARCH_TOP = 3  # Wikipedia's search results kept per collection: past three it's mostly articles that merely mention the name


def _search(queue: TaskQueue, collections: list[Collection], linked: dict, last, taken, ends, api: WikiApi | None = None) -> bool:
    # One search per collection, biggest first, at Wikipedia's polite pace; where it has got to is kept, so it resumes
    api = api or WikiApi()
    ordered = sorted(collections, key=lambda each: -each.pages)
    start, added = int(queue.meta("search_at") or 0), 0
    print(f"searching Wikipedia for {len(ordered) - start:,} collections' names" + (f", from {start:,}" if start else ""), flush=True)
    for number in range(start, len(ordered)):
        if ends and datetime.now() >= ends:
            print(f"  stopped at collection {number:,}; the search resumes there next turn", flush=True)
            return False
        each = ordered[number]
        reply = api._get({"action": "query", "list": "search", "srsearch": each.name, "srnamespace": 0, "srlimit": SEARCH_TOP,
                          "srprop": "", "format": "json", "formatversion": 2})
        seen, home, items = taken(), front(each.folder), []
        for hit in reply.get("query", {}).get("search", []):
            page, article = hit["pageid"], hit["title"]
            aside = title_key(article)[1]
            if (page, each.folder) in seen or any(aside == word or word in aside.split() for word in NOT_SUBJECT):
                continue
            if (aside and not aside_fits(aside, f"{each.name} {each.filed}")) or any(home.search(url) for url in linked.get(page, [])):
                continue
            items.append({"kind": "subject", "source": "search", "page": article, "page_id": page, "folder": each.folder,
                          "title": each.name, "aside": aside, "redirect": False, "pages": each.pages,
                          "mia_links": len(linked.get(page, []))})
        first = last() + 1
        queue.fill([{**item, "id": first + offset} for offset, item in enumerate(items)], {"search_at": number + 1})
        added += len(items)
    print(f"added: {added} articles from Wikipedia's search", flush=True)
    return True


class SubjectBench:
    """Reads each article as it stands today, drops what the code can, and asks the judge whether it's the collection's subject."""

    def __init__(self, collections: list[Collection], judge: str, queue: TaskQueue):
        self.collections = {each.folder: each for each in collections}
        self.api = WikiApi()
        self.judge = SubjectJudge(judge, ABOUT) if judge else None
        self.used_judge = False
        # Redirects land several titles on one article: one judgement per article and collection, kept across turns
        self.decided = {(verdict["article"], item["folder"]): (item["id"], verdict) for item, verdict, _ in queue.judged()
                        if item.get("kind") == "subject" and verdict.get("article") and not verdict.get("repeat")}

    def batch(self, queue: TaskQueue, items: list[dict], ends) -> None:
        articles = self.api.articles(list(dict.fromkeys(item["page"] for item in items)))
        for item in items:
            if ends and datetime.now() >= ends:
                return  # unrecorded items are looked at again next turn
            article = articles.get(item["page"])
            verdict = {"result": "skip", "why": "the article is gone"} if article is None else self._subject(item, article)
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            queue.record(item["id"], verdict, self.judge.model if verdict.get("judged") else "code", stamp)
            if verdict["result"] == "propose":
                print(f"{item['id']:>6} {item['page'][:45]:45} {item['folder'][:45]:45} {verdict['why'][:60]}", flush=True)

    def release(self) -> None:
        if self.judge and self.used_judge:
            self.judge.release()

    def _subject(self, item: dict, article: dict) -> dict:
        collection = self.collections.get(item["folder"])
        if collection is None:
            return {"result": "skip", "why": "the collection has left the mirror"}
        done = self.decided.get((article["title"], item["folder"]))
        if done:  # another title that redirects here: counted once, under the first
            return {"result": "skip", "why": f"the same article as item {done[0]} ({done[1]['result']})", "repeat": True,
                    "article": article["title"]}
        # One collection per article. 4 Nov 2026, task 29: Executive Order 11490 got the same order from two folders, and
        # Montoneros got its own folder and FAR's. Title matches come first in the pile, biggest collection first, so they win
        offered = next(((number, verdict) for (title, folder), (number, verdict) in self.decided.items()
                        if title == article["title"] and folder != item["folder"] and verdict["result"] == "propose"), None)
        if offered:
            return {"result": "skip", "why": f"the article already has a proposal: {offered[1]['title']} (item {offered[0]})",
                    "article": article["title"]}
        lowered = article["text"].lower()
        if front(collection.folder).search(lowered):  # citing a document inside it doesn't count: that's the "cites" source
            return {"result": "skip", "why": "the article already links this collection", "article": article["title"]}
        if _disambiguation(article):
            return {"result": "skip", "why": "a disambiguation page", "article": article["title"]}
        opening = lead(article["text"])
        made = CREATIVE.search(opening[:400])
        if made and not CREATIVE.search(f"{collection.name}. {collection.opening[:300]}"):
            return {"result": "skip", "why": f"the article is about a work ({made.group(0)})", "article": article["title"]}
        if not self.judge:
            return {"result": "skip", "why": "no judge was given"}
        self.used_judge = True
        found = self.judge.about_collection(collection, article["title"], opening)
        others = lowered.count("marxists.org/")
        if not found["same"]:
            verdict = {"result": "skip", "why": f"{found['match']}: {found['reason']}", "judged": True, "article": article["title"]}
        else:
            verdict = {"result": "propose", "why": found["reason"] + (f" (the article links MIA {others}x elsewhere)" if others else ""),
                       "judged": True, "title": collection.name, "link": collection.link, "elsewhere": [], "author": "",
                       "article": article["title"], "pages": collection.pages, "confidence": "medium" if others else "high"}
        self.decided[(article["title"], item["folder"])] = (item["id"], verdict)
        return verdict


RANK = {"high": 0, "medium": 1, "low": 2}


def _edit(verdict: dict) -> dict:
    name = verdict["title"]
    shown = name if re.search(r"\barchive\b", name, re.I) else f"{name} archive"
    line = f"* [{verdict['link']} {shown}] at {SITE}"
    return {"what": name, "external_line": line, "summary": f"Added an external link to {SITE} (I volunteer there).",
            "talk": f"{{{{Edit COI}}}} I volunteer for {SITE}, which hosts a collection of {verdict['pages']} documents on {name}. "
                    f"I'd like to suggest adding it under External links: {line[2:]} ~~~~"}


def write_results(queue: TaskQueue, path: Path, target: str) -> int:
    once = {}
    for item, verdict, _ in queue.judged():  # one proposal per article and collection
        if item.get("kind") == "subject" and verdict.get("result") == "propose" and not verdict.get("repeat"):
            once.setdefault((verdict["article"], verdict["link"]), (item, verdict))
    found = sorted(once.values(), key=lambda pair: (RANK.get(pair[1].get("confidence"), 3), -pair[1].get("pages", 0)))
    for _, verdict in found:
        verdict.update(_edit(verdict))
    lines = [f"# Wikipedia articles about subjects {SITE} documents under {target}, found by local code and models. "
             "All UNCONFIRMED: open each article first.",
             f"# Our side: {queue.meta('filled_from')}. Wikipedia's links: {queue.meta('links_from')}.",
             "# Disclose on your user page that you volunteer for MIA; for anything arguable, use the talk-page text instead.", "",
             f"## SUBJECTS' ARTICLES WITH NO LINK TO THE COLLECTION ({len(found)})", ""]
    for item, verdict in found:
        lines += [f"[{verdict['confidence']}] {verdict['article']}", f"  ours: {verdict['link']} · {verdict['title']} ({verdict['pages']} pages)",
                  f"  why: {verdict['why']}", f"  External links line: {verdict['external_line']}", f"  talk page: {verdict['talk']}", ""]
    earlier = json.loads(queue.meta("earlier_finds") or "[]")
    if earlier:
        lines += [f"## EARLIER FINDS IN THIS PILE ({len(earlier)}), kept as they were", ""]
        lines += [f"[{find.get('confidence', '')}] {find['kind']} · {find['article']} · ours: {find.get('link', '')}"
                  + (f" · dead: {find['dead_url']}" if find.get("dead_url") else "") for find in earlier] + [""]
    path.write_text("\n".join(lines), encoding="utf-8")
    with path.with_suffix(".jsonl").open("w", encoding="utf-8") as records:  # for the App Hub's Social page
        for find in earlier:
            records.write(json.dumps(find, ensure_ascii=False) + "\n")
        for item, verdict in found:
            records.write(json.dumps({"kind": "subject", "key": f"subject:{item['page_id']}:{verdict['link']}", "dead_url": "",
                                      **verdict}, ensure_ascii=False) + "\n")
    return len(found)


def keep_earlier(queue: TaskQueue, results: Path) -> None:
    # The finds already on Social from this pile's other kinds (an author run's links and works), kept in the pile itself the
    # first time, so every later write carries them forward: a run adds to a task's finds and never takes any away
    if queue.meta("earlier_finds") is not None:
        return
    jsonl = results.with_suffix(".jsonl")
    lines = jsonl.read_text(encoding="utf-8").splitlines() if jsonl.exists() else []
    earlier = []
    for line in lines:
        try:
            find = json.loads(line)
        except ValueError:
            continue
        if find.get("kind") != "subject":
            earlier.append(find)
    with queue.connection:
        queue.connection.execute("INSERT OR REPLACE INTO meta VALUES ('earlier_finds', ?)", (json.dumps(earlier, ensure_ascii=False),))


def run(target: str, queue_path: Path, results: Path, limit: int, judge: str, until: str) -> None:
    ends = deadline(until)
    queue = TaskQueue(queue_path)
    index = WikiIndex(queue_path.with_suffix(".wiki.sqlite"))
    keep_earlier(queue, results)
    collections = read_collections(target)
    if queue.meta("collections_from") is None:
        if not collections:
            sys.exit(f"No collections under {target} in the local mirror; run fetch_mia.py first.")
        if not fill(queue, index, collections, target, ends):
            print("the fill stopped at the stop time; it carries on next turn", flush=True)
            return
    if not widen(queue, index, collections, target, queue_path, ends):
        print("the \"History of …\" title read stopped at the stop time; it carries on next turn", flush=True)
        return
    bench = SubjectBench(collections, judge, queue)
    items = queue.next(limit)
    for start in range(0, len(items), 50):
        if ends and datetime.now() >= ends:
            break
        try:
            bench.batch(queue, items[start:start + 50], ends)
        finally:
            write_results(queue, results, target)
    bench.release()
    print("proposals written:", write_results(queue, results, target), queue.counts(), flush=True)
