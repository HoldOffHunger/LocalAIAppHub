import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dump_tables import newest_dump  # noqa: E402
from sites import site_about, site_name  # noqa: E402
from task_queue import TaskQueue  # noqa: E402

from article_judge import ArticleJudge  # noqa: E402
from citations import find_citation, full_text_elsewhere, lead  # noqa: E402
from link_check import ArchiveDown, LinkCheck, TextFinder, overlap  # noqa: E402
from our_texts import our_site  # noqa: E402
from url_tools import host, same_page  # noqa: E402
from wiki_api import WikiApi  # noqa: E402
from wiki_dumps import WikiDumps  # noqa: E402
from wiki_index import WikiIndex, title_key  # noqa: E402

WORK_ASIDES = ("book", "essay", "pamphlet", "novel", "poem", "speech", "play", "treatise", "manifesto", "short story", "story",
               "novella", "article", "lecture", "letter", "memoir", "autobiography", "collection", "anthology", "work")
NOT_WRITING = ("film", "album", "song", "band", "tv series", "television", "video game", "magazine", "newspaper", "journal", "ship",
               "painting", "sculpture", "opera", "musical", "ep", "single", "comics", "game", "horse", "company")
HOSTED_ELSEWHERE = {"archive.org", "books.google.com", "google.com", "youtube.com", "wikipedia.org", "doi.org", "jstor.org", "facebook.com",
                    "twitter.com", "amazon.com"}  # never one text's own page, and Wikipedia links them by the hundred thousand
SAME_TEXT = 0.6  # of an archived page's eight-word runs found in ours, for "this is the same text"
LIKELY_TEXT = 0.3
KINDS = ("link", "near", "work", "author")


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find dead and missing Wikipedia links to texts we host; results are for a person to confirm.")
    parser.add_argument("--target", default="revoltlib")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the proposed edits are written")
    parser.add_argument("--limit", type=int, default=500, help="items to judge this run")
    parser.add_argument("--judge", default="gemma4:12b", help="decides whether a same-titled article is about our work or author")
    parser.add_argument("--refresh-dumps", action="store_true", help="fetch Wikipedia's tables again if Wikimedia has newer ones")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def site_domain(target: str) -> str:
    return f"{target}.com"  # every GGCMS site is served at its name .com (revoltlib.com, revoltsource.com…)


def fill(queue: TaskQueue, index: WikiIndex, target: str, ends, refresh: bool) -> bool:
    # The mechanical pass, in stages that each survive a stop: our side, Wikipedia's tables, the scans, the domains, then the pile
    domain = site_domain(target)
    if not index.meta("ours_done"):
        dump = newest_dump(target)
        print(f"reading {dump}", flush=True)
        with index.connection:
            index.set_meta("filled_from", dump)
        index.save_ours(our_site(dump), domain)
    dumps = WikiDumps()
    if not dumps.fetch(ends, refresh):
        return False
    texts = index.texts()
    watched = {name for text in texts for name in text["domains"]} - {domain, ""}
    watched = {name for name in watched if not any(name == big or name.endswith("." + big) for big in HOSTED_ELSEWHERE)}
    if not index.scan_links(dumps, watched | {domain}, ends):
        return False
    works, authors = _works_and_authors(index, texts)
    if not index.scan_pages(dumps, {title_key(title)[0] for title in list(works.values()) + list(authors.values())}, ends):
        return False
    if not _check_domains(index, watched, ends):
        return False
    items = _pile(index, texts, works, authors, domain)
    queue.fill(items, {"filled_from": index.meta("filled_from"), "wikipedia": json.dumps(dumps.about()),
                       "sourceless": sum(1 for text in texts if not text["sources"])})
    counts = {kind: sum(1 for item in items if item["kind"] == kind) for kind in KINDS}
    print(f"filled: {counts['link']} links to our sources, {counts['near']} links into dead sites, "
          f"{counts['work']} articles titled like our works, {counts['author']} like our authors", flush=True)
    return True


def _works_and_authors(index: WikiIndex, texts: list[dict]) -> tuple[dict, dict]:
    works = {text["work"]: index.entry(text["work"])[0] for text in texts if text["work"]}
    authors = {text["author"]: index.entry(text["author"])[0] for text in texts if text["author"]}
    return {k: v for k, v in works.items() if v}, {k: v for k, v in authors.items() if v}


def _check_domains(index: WikiIndex, watched: set[str], ends) -> bool:
    # Is each source site still there at all? A dead one's every Wikipedia link is worth a closer look
    # A front page often still answers (spunk.org's does) when the old pages are gone, so three of the site's own Wikipedia links are asked
    linked = defaultdict(list)
    for _, _, url, domain in index.links():
        linked[domain].append(url)
    check = LinkCheck()
    for domain in sorted(watched & set(linked)):
        if index.domain_state(domain):
            continue
        if ends and datetime.now() >= ends:
            return False
        sample = linked[domain][::max(len(linked[domain]) // 3, 1)][:3]
        states = [check.check(url) for url in sample]
        gone = [found for found in states if found["state"] in ("dead", "soft-dead")]
        if len(gone) * 2 > len(states):
            state, why = "dead", f"{len(gone)} of {len(states)} of its Wikipedia links sampled are dead: {gone[0]['why']}"
        else:
            state, why = "alive", f"{len(states) - len(gone)} of {len(states)} of its Wikipedia links sampled still answer"
        index.set_domain_state(domain, state, why)
        print(f"  {domain}: {state} ({why})", flush=True)
    return True


def _pile(index: WikiIndex, texts: list[dict], works: dict, authors: dict, domain: str) -> list[dict]:
    by_source = defaultdict(list)
    for text in texts:
        for url in text["sources"]:
            by_source[same_page(url)].append(text)
    items, seen = [], set()
    ours_titled = {title_key(title)[0] for title in list(works.values()) + list(authors.values())}
    for page, article, url, linked_domain in index.links():
        if linked_domain == domain or (article, same_page(url)) in seen:
            continue
        seen.add((article, same_page(url)))
        ours = by_source.get(same_page(url))
        if ours:
            shared = {text["work"] for text in ours}
            entry = shared.pop() if len(shared) == 1 and len(ours) > 1 else ours[0]["id"]  # one source page behind many chapters: link the work
            items.append({"kind": "link", "page": article, "page_id": page, "url": url, "entry": entry,
                          "source_from": ours[0]["source_from"]})
        elif (index.domain_state(linked_domain) or ("", ""))[0] in ("dead", "soft-dead") or title_key(article)[0] in ours_titled:
            # Every link into a dead site, and links into a live one from our own works' and authors' articles, where a moved page matters most
            items.append({"kind": "near", "page": article, "page_id": page, "url": url, "domain": linked_domain})
    linked_to_us = {page for page, _, _, linked_domain in index.links() if linked_domain == domain}
    for kind, named in (("work", works), ("author", authors)):
        for entry, title in sorted(named.items()):
            for page, article, redirect, aside in index.titled(title_key(title)[0]):
                if page in linked_to_us or any(word in aside.split() or aside == word for word in NOT_WRITING):
                    continue
                items.append({"kind": kind, "page": article, "page_id": page, "entry": entry, "title": title, "aside": aside,
                              "redirect": bool(redirect)})
    order = {kind: number for number, kind in enumerate(KINDS)}
    items.sort(key=lambda item: order[item["kind"]])
    return [{**item, "id": number} for number, item in enumerate(items, 1)]


def main() -> None:
    args = options()
    ends = deadline(args.until)  # before the first run's fill: a fill that ran past the stop time made it tomorrow's
    queue = TaskQueue(Path(args.queue))
    index = WikiIndex(Path(args.queue).with_suffix(".wiki.sqlite"))
    if not queue.filled() and not fill(queue, index, args.target, ends, args.refresh_dumps):
        print("the fill stopped at the stop time; it carries on next turn", flush=True)
        return
    work = Workbench(index, args.target, args.judge)
    # The items that never ask the Archive first (works and authors with no link to us, 7,751 of them on 31 Oct 2026): they sat
    # behind 208,000 Archive items, so a refusing Archive left them untouched
    items = sorted(queue.next(queue.counts()["total"]), key=lambda item: item["kind"] == "near")[:args.limit]
    for start in range(0, len(items), 50):
        if ends and datetime.now() >= ends:
            break
        if work.check.resting() and items[start]["kind"] == "near":
            # Only the Archive's items are left, and it's resting: end the turn. On 4 Nov 2026 a turn spent its quarter hour
            # skipping 100,000 resting items fifty at a time, writing the results file again after each empty batch
            print("only the Archive's items are left and it's resting; they stay in the pile for next turn", flush=True)
            break
        recorded = 0
        try:
            recorded = work.batch(queue, items[start:start + 50], ends)
        except ArchiveDown as down:
            print(f"stopping: {down}; the rest stays in the pile for next turn", flush=True)
            break
        finally:
            if recorded:
                write_results(queue, index, Path(args.results), args.target)  # a stopped run still leaves its finds behind
    work.release()
    print("proposals written:", write_results(queue, index, Path(args.results), args.target), queue.counts(), flush=True)


class Workbench:
    """Looks at one batch of the pile: reads the articles, checks the links, and asks the judge only what the code can't settle."""

    def __init__(self, index: WikiIndex, target: str, judge: str):
        self.index = index
        self.target = target
        self.domain = site_domain(target)
        self.api = WikiApi()
        self.check = LinkCheck()
        self.judge = ArticleJudge(judge, site_about(target)) if judge else None
        self.used_judge = False
        self.finders: dict[str, TextFinder] = {}

    def batch(self, queue: TaskQueue, items: list[dict], ends) -> int:
        # While the Archive rests, its items wait in the pile and the rest of the pile carries on: on 31 Oct 2026 one 429 at
        # the first item ended every turn in a second, with 7,751 work and author items behind it that never ask the Archive.
        # Returns how many items it recorded
        items = [item for item in items if not (item["kind"] == "near" and self.check.resting())]
        if not items:
            return 0
        articles = self.api.articles(list(dict.fromkeys(item["page"] for item in items)))
        recorded = 0
        for item in items:
            if ends and datetime.now() >= ends:
                return recorded  # the items left unrecorded are looked at again next turn
            if item["kind"] == "near" and self.check.resting():
                continue
            article = articles.get(item["page"])
            try:
                verdict = {"result": "skip", "why": "the article is gone"} if article is None else getattr(self, f"_{item['kind']}")(item, article)
            except ArchiveDown as down:
                rest = self.check.archive_refused()
                print(f"{down}: the Archive's items rest {rest / 60:.0f} minutes; the rest of the pile carries on", flush=True)
                continue
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            queue.record(item["id"], verdict, self.judge.model if verdict.get("judged") else "code", stamp)
            recorded += 1
            if verdict["result"] == "propose":
                print(f"{item['id']:>6} {item['kind']:6} {item['page'][:50]:50} {verdict['why'][:80]}", flush=True)
        return recorded

    def release(self) -> None:
        if self.judge and self.used_judge:
            self.judge.release()

    def _link(self, item: dict, article: dict) -> dict:
        if urlsplit(item["url"]).path in ("", "/"):
            # A site's front page names a publisher, not a text: on 2 Nov 2026 three articles' links to kaya.com, Kaya Press's
            # home page, were offered as dead copies of one poet's book because the book's Source names that site
            return {"result": "skip", "why": "the link is a site's front page, not a text"}
        cite = find_citation(article["text"], item["url"])
        if cite is None:
            return {"result": "skip", "why": "the link has left the article since the dump"}
        found = self.check.check(item["url"])
        if found["state"] == "unsure":
            return {"result": "skip", "why": f"the link may still work ({found['why']})"}
        if found["state"] == "alive":
            ours = self.index.words(item["entry"])
            if not found["text"] or overlap(found["text"], ours) >= LIKELY_TEXT or len(found["text"].split()) > 300:
                return {"result": "skip", "why": f"the link still works ({found['why']})"}
            found = {"state": "soft-dead", "why": "the page loads, but our text isn't on it any more"}
        return self._proposal(item, article, cite, found, item["entry"], f"the article cites our source ({item['source_from']} field)")

    def _near(self, item: dict, article: dict) -> dict:
        # A link into a dead site that isn't one of our sources: is its archived copy one of our texts anyway?
        cite = find_citation(article["text"], item["url"])
        if cite is None:
            return {"result": "skip", "why": "the link has left the article since the dump"}
        state = self.index.domain_state(item["domain"]) or ("dead", "the site is gone")
        found = {"state": state[0], "why": state[1]}
        if state[0] not in ("dead", "soft-dead"):  # a live site: is this one page gone?
            found = self.check.check(item["url"])
            if found["state"] in ("alive", "unsure"):
                return {"result": "skip", "why": f"the link still works, or may ({found['why']})"}
        snapshot = self.check.archived(item["url"])
        if snapshot is None:
            return {"result": "skip", "why": "no archived copy to compare with"}
        theirs = self.check.archived_text(snapshot)
        best, score = self._finder(item["domain"]).best(theirs)
        if score < LIKELY_TEXT:
            return {"result": "skip", "why": f"the archived copy isn't one of our texts (best {score:.0%})"}
        return self._proposal(item, article, cite, found, best,
                              f"{score:.0%} of the archived copy is word for word in ours", snapshot=snapshot, score=score)

    def _proposal(self, item, article, cite, found, entry, matched, snapshot=None, score=1.0) -> dict:
        title, link = self.index.entry(entry)
        if not link:
            return {"result": "skip", "why": f"entry {entry} has no permalink"}
        replacement = cite.with_our_link(link, item["url"], site_name(self.target))
        if replacement == cite.text:
            return {"result": "skip", "why": "our link couldn't be placed in the citation as written"}
        confidence = "high" if score >= SAME_TEXT and not cite.archived and found["state"] in ("dead", "soft-dead") else "medium"
        if found["state"] == "unsure" or cite.archived:
            confidence = "low"
        return {"result": "propose", "why": matched, "confidence": confidence, "entry": entry, "title": title, "link": link,
                "dead": found["state"], "dead_why": found["why"], "marked": cite.marked_dead, "archived": cite.archived,
                "snapshot": (snapshot or {}).get("url", ""), "section": cite.section, "shape": cite.shape, "as_written": cite.text,
                "replacement": replacement, "article": article["title"]}

    def _work(self, item: dict, article: dict) -> dict:
        return self._unlinked(item, article, "work")

    def _author(self, item: dict, article: dict) -> dict:
        return self._unlinked(item, article, "author")

    def _unlinked(self, item: dict, article: dict, kind: str) -> dict:
        if self.domain in article["text"].lower():
            return {"result": "skip", "why": f"the article already links {self.domain}"}
        opening = lead(article["text"])
        author = self._author_of(item["entry"]) if kind == "work" else item["title"]
        if kind == "work" and _not_a_work_page(article["title"], author):
            return {"result": "skip", "why": "a disambiguation page, or our entry has no author, so it isn't a book"}
        surname = author.split()[-1].lower() if author else ""
        if kind == "work" and (item["aside"] in WORK_ASIDES or (surname and surname in item["aside"])) and surname and surname in opening.lower():
            verdict = {"same": True, "reason": f"titled as a {item['aside']}, and its opening names {author}"}
        elif kind == "work" and not (surname and surname in opening.lower()):
            # An article about the book names its author up front. On 2 Nov 2026 gemma passed "Law and Order", "1967" and
            # "Afrin" as Bourne's, Russell's and the ACG's works, its reasons only echoing the question back
            verdict = {"same": False, "reason": f"the article's opening doesn't name {author}"}
        elif kind == "work":
            verdict = self._judged(lambda: self.judge.about_work(item["title"], author, article["title"], opening))
        else:
            verdict = self._judged(lambda: self.judge.about_author(author, self._works_of(item["entry"]), article["title"], opening))
        if not verdict["same"]:
            return {"result": "skip", "why": verdict["reason"], "judged": verdict.get("judged", False)}
        title, link = self.index.entry(item["entry"])
        return {"result": "propose", "why": verdict["reason"], "judged": verdict.get("judged", False), "entry": item["entry"],
                "title": title, "link": link, "elsewhere": full_text_elsewhere(article["text"]), "article": article["title"],
                "author": author, "confidence": "high" if not full_text_elsewhere(article["text"]) else "medium"}

    def _judged(self, ask) -> dict:
        if not self.judge:
            return {"same": False, "reason": "no judge was given"}
        self.used_judge = True
        return {**ask(), "judged": True}

    def _author_of(self, work: int) -> str:
        found = self.index.connection.execute("SELECT author FROM texts WHERE work = ? AND author != 0 LIMIT 1", (work,)).fetchone()
        return self.index.entry(found[0])[0] if found else ""

    def _works_of(self, author: int) -> list[str]:
        rows = self.index.connection.execute("SELECT DISTINCT work FROM texts WHERE author = ? LIMIT 6", (author,)).fetchall()
        return [self.index.entry(work)[0] for (work,) in rows]

    def _finder(self, domain: str) -> TextFinder:
        # Built once per site per turn; the pile is in Wikipedia's page order, so one site's links come in runs
        if domain not in self.finders:
            self.finders = {domain: TextFinder({text["id"]: self.index.words(text["id"]) for text in self.index.texts() if domain in text["domains"]})}
        return self.finders[domain]


def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


RANK = {"high": 0, "medium": 1, "low": 2}


def write_results(queue: TaskQueue, index: WikiIndex, path: Path, target: str) -> int:
    # One page to read, best first in each part, and a JSON-lines copy; nothing here has touched Wikipedia
    site = site_name(target)
    found = [(item, verdict) for item, verdict, _ in queue.judged() if verdict.get("result") == "propose" and not _withdrawn(item, verdict)]
    found.sort(key=lambda pair: RANK.get(pair[1].get("confidence"), 3))
    # One proposal per article and entry: a work's article was in the pile once per chapter of it
    once = {}
    for item, verdict in found:
        once.setdefault((item["kind"], verdict["article"], verdict["entry"]), (item, verdict))
    found = list(once.values())
    for item, verdict in found:
        verdict.update(_edit(item, verdict, site))
    marked = [pair for pair in found if pair[0]["kind"] in ("link", "near") and pair[1]["marked"]]
    unmarked = [pair for pair in found if pair[0]["kind"] in ("link", "near") and not pair[1]["marked"]]
    works = [pair for pair in found if pair[0]["kind"] == "work"]
    authors = [pair for pair in found if pair[0]["kind"] == "author"]
    lines = [f"# Wikipedia links to {site}, found by local code and models. All UNCONFIRMED: open each article before editing.",
             f"# Filled from {queue.meta('filled_from')}. Every link is a permalink (?id= is the oldest Assignment, never the entry).",
             f"# Disclose on your user page that you run {site}; for anything arguable, use the talk-page text instead of editing.", ""]
    for heading, pairs in ((f"DEAD LINKS WIKIPEDIA HAS MARKED ({len(marked)})", marked),
                           (f"DEAD LINKS NOBODY HAS MARKED ({len(unmarked)})", unmarked)):
        lines += [f"## {heading}", ""]
        for item, verdict in pairs:
            lines += [f"[{verdict['confidence']}] {verdict['article']} · section: {verdict['section']}",
                      f"  dead: {item['url']} ({verdict['dead_why']})" + ("; already has an archive copy, so ours would be an extra" if verdict["archived"] else ""),
                      f"  ours: {verdict['link']} · entry {verdict['entry']} · {verdict['title']}", f"  match: {verdict['why']}",
                      f"  as written:  {verdict['as_written']}", f"  replace with: {verdict['replacement']}",
                      f"  edit summary: {verdict['summary']}", ""]
    for heading, pairs in ((f"OUR WORKS' ARTICLES WITH NO LINK TO US ({len(works)})", works),
                           (f"OUR AUTHORS' ARTICLES WITH NO LINK TO US ({len(authors)})", authors)):
        lines += [f"## {heading}", ""]
        for item, verdict in pairs:
            also = f"; full text already at {', '.join(verdict['elsewhere'])}" if verdict["elsewhere"] else "; no full-text link at all"
            lines += [f"[{verdict['confidence']}] {verdict['article']}{also}", f"  ours: {verdict['link']} · entry {verdict['entry']} · {verdict['what']}",
                      f"  why: {verdict['why']}", f"  External links line: {verdict['external_line']}", f"  talk page: {verdict['talk']}", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    # The same, one proposal a line with every piece of the edit ready to paste, for the App Hub's Social page
    with path.with_suffix(".jsonl").open("w", encoding="utf-8") as records:
        for item, verdict in found:
            records.write(json.dumps({"kind": item["kind"], "key": f"{item['kind']}:{item.get('page_id', item['page'])}:{verdict['entry']}",
                                      "dead_url": item.get("url", ""), **verdict}, ensure_ascii=False) + "\n")
    _write_sourceless(index, path.with_suffix(".sourceless.txt"), site)
    _write_unknown(index, path.with_suffix(".source-names.txt"), site)
    return len(found)


def _withdrawn(item: dict, verdict: dict) -> bool:
    # Proposals made before a rule was learnt, which it now refuses (2 Nov 2026: the kaya.com front pages; and "work" links
    # to disambiguation pages, and to other people's books named like our sections, such as Miller's "Anarchism")
    if item["kind"] == "work":
        return _not_a_work_page(verdict["article"], verdict.get("author", ""))
    if item["kind"] not in ("link", "near"):
        return False
    return (urlsplit(item["url"]).path in ("", "/") or verdict.get("dead") == "unsure"
            or verdict.get("replacement") == verdict.get("as_written"))


def _not_a_work_page(article: str, author: str) -> bool:
    # A disambiguation page takes no external links; and an entry with no author is a section or an author's page of ours,
    # not a book, so a same-titled book's article is somebody else's book
    return "(disambiguation)" in article.lower() or not author


def _edit(item: dict, verdict: dict, site: str) -> dict:
    # Each piece of the edit as Ben pastes it: the summary always says he runs the site
    if item["kind"] in ("link", "near"):
        return {"summary": f"Dead link replaced with the same text at {site} (I run {site})."}
    what = f"''{verdict['title']}''" + (f" by {verdict['author']}" if item["kind"] == "work" and verdict["author"] else "")
    line = (f"* [{verdict['link']} Full text of ''{verdict['title']}''] at {site}" if item["kind"] == "work"
            else f"* [{verdict['link']} Works by {verdict['title']}] at {site}")
    hosts = "the full text of " if item["kind"] == "work" else "writing by "
    return {"what": what, "external_line": line, "summary": f"Added an external link to {site} (I run {site}).",
            "talk": f"{{{{Edit COI}}}} I run {site}, which hosts {hosts}{what}. I'd like to suggest adding it under External links: "
                    f"{line[2:]} ~~~~"}


def _write_sourceless(index: WikiIndex, path: Path, site: str) -> None:
    # Texts with no source anywhere: academically questionable, Ben's words, and a cleanup list of their own
    rows = [text for text in index.texts() if not text["domains"] and not text["unknown"]]
    lines = [f"# {site} texts with no source at all: TextBody.Source is empty and the body names none ({len(rows)}).", ""]
    lines += [f"entry {text['id']} · {index.entry(text['id'])[0]} · {index.entry(text['id'])[1]}" for text in rows]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_unknown(index: WikiIndex, path: Path, site: str) -> None:
    # Source names that aren't a site's address ("University of Virginia Library"): their texts can't be matched until NAMED knows them
    counts: dict[str, int] = {}
    for text in index.texts():
        for name in text["unknown"]:
            counts[name] = counts.get(name, 0) + 1
    lines = [f"# {site} Source names this worker couldn't turn into a site, most texts first. Add the common ones to NAMED in our_texts.py.", ""]
    lines += [f"{count:>6}  {name}" for name, count in sorted(counts.items(), key=lambda pair: -pair[1])]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
