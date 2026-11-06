"""Wikipedia links to one Marxists Internet Archive author: dead links into their folder, and articles about them or their works
with no link there. Results are edits for Ben to make by hand, disclosing that he volunteers for MIA; it never edits Wikipedia.

    run_mia_links.py --target marxists.org/archive/luxemburg --queue <pile> --results <file> [--until 06:00]

Our side is the local mirror (fetch_mia.py), so the only requests to marxists.org are the live checks of links that look dead.
Wikipedia's side is the RevoltLib links task's index: it already holds every link into marxists.org (11,612 on 3 Nov 2026), so
only the title table is read again, for this author's work titles. Anything RevoltLib holds is left to the RevoltLib task.
"""

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "shared"))
sys.path.insert(0, str(HERE.parent / "ggcms_wikilinks"))
from task_queue import TaskQueue  # noqa: E402

from article_judge import ArticleJudge  # noqa: E402
from citations import find_citation, full_text_elsewhere, lead  # noqa: E402
from link_check import LinkCheck  # noqa: E402
from run_wikilinks import NOT_WRITING, WORK_ASIDES, deadline  # noqa: E402
from wiki_api import WikiApi  # noqa: E402
from wiki_dumps import WikiDumps  # noqa: E402
from wiki_index import WikiIndex, title_key  # noqa: E402

from mia_texts import Author, listed_paths, main_title, read_author  # noqa: E402

SITE = "the Marxists Internet Archive"
ABOUT = "the Marxists Internet Archive (marxists.org), a volunteer-run online library of Marxist and socialist writing"
DONORS = HERE.parent / "data" / "tasks"  # other tasks' Wikipedia indexes, whose marxists.org links this one borrows
KINDS = ("link", "work", "author")


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find dead and missing Wikipedia links to one MIA author; results are for a person to confirm.")
    parser.add_argument("--target", required=True, help="marxists.org/archive/<author>, or just the author's folder name")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the proposed edits are written")
    parser.add_argument("--limit", type=int, default=500, help="items to look at this run")
    parser.add_argument("--judge", default="gemma4:12b", help="decides whether a same-titled article is about this author or work")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def folder_of(target: str) -> str:
    folder = re.sub(r"^(?:https?://)?(?:www\.)?marxists\.org/", "", target.strip()).strip("/")
    return folder if "/" in folder else f"archive/{folder}"


def keys_of(title: str) -> set[str]:
    # "The Junius Pamphlet" is filed on Wikipedia as either; so is "Junius Pamphlet"
    keys = set()
    for each in {title, main_title(title)}:
        key = title_key(each)[0]
        if len(key.split()) >= 2 or each == title:  # a subtitle-less "Imperialism" alone would match every general article
            keys |= {key, key.removeprefix("the ")}
    return keys - {""}


def fill(queue: TaskQueue, index: WikiIndex, author: Author, ends) -> bool:
    if not index.meta("links_done") and not _borrow_links(index):
        if not index.scan_links(WikiDumps(), {"marxists.org"}, ends):
            return False
    titles = {key for work in author.works for key in keys_of(work.title)} | keys_of(author.name)
    if not index.scan_pages(WikiDumps(), titles, ends):
        return False
    items = _pile(index, author, listed_paths(), _revoltlib_titles(author.surname))
    queue.fill(items, {"filled_from": f"{author.folder} ({len(author.works)} works in the local mirror)",
                       "links_from": index.meta("links_from") or "Wikipedia's externallinks table"})
    counts = {kind: sum(1 for item in items if item["kind"] == kind) for kind in KINDS}
    print(f"filled: {counts['link']} links that look dead, {counts['work']} articles titled like {author.name}'s works, "
          f"{counts['author']} like {author.name}", flush=True)
    return True


def _donor() -> Path | None:
    for path in sorted(DONORS.glob("task-*.wiki.sqlite")):
        connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            done = connection.execute("SELECT value FROM meta WHERE key = 'links_done'").fetchone()
            if done and connection.execute("SELECT 1 FROM links WHERE domain = 'marxists.org' LIMIT 1").fetchone():
                return path
        except sqlite3.Error:
            pass
        finally:
            connection.close()
    return None


def _borrow_links(index: WikiIndex) -> bool:
    # The RevoltLib task scanned all 1.1 billion links an hour at a time; its marxists.org rows are the same answer, read in a second
    donor = _donor()
    if donor is None:
        return False
    index.connection.commit()
    index.connection.execute("ATTACH DATABASE ? AS donor", (str(donor),))  # never inside a transaction; only read
    with index.connection:
        index.connection.execute("INSERT INTO links SELECT * FROM donor.links WHERE domain = 'marxists.org'")
        index.connection.execute("INSERT OR REPLACE INTO pages SELECT * FROM donor.pages WHERE id IN (SELECT page FROM links)")
        stamp = index.connection.execute("SELECT value FROM donor.meta WHERE key = 'filled_from'").fetchone()
        index.set_meta("links_done", 1)
        index.set_meta("links_from", f"{donor.name}" + (f", filled from {stamp[0]}" if stamp else ""))
    index.connection.execute("DETACH DATABASE donor")
    print(f"borrowed marxists.org's Wikipedia links from {donor.name}", flush=True)
    return True


def _revoltlib_titles(surname: str) -> set[str]:
    # This author's titles on RevoltLib: a work it holds is linked by the RevoltLib task, never twice. By author as well as title,
    # since RevoltLib's "The Russian Revolution" may be Berkman's, not Luxemburg's (RevoltLib holds 170 of hers, 3 Nov 2026)
    donor = _donor()
    if donor is None:
        return set()
    connection = sqlite3.connect(f"file:{donor}?mode=ro", uri=True)
    try:
        rows = connection.execute("SELECT text.title, work.title FROM texts JOIN entries AS writer ON writer.id = texts.author "
                                  "LEFT JOIN entries AS text ON text.id = texts.id LEFT JOIN entries AS work ON work.id = texts.work "
                                  "WHERE writer.title LIKE ?", (f"%{surname}%",)).fetchall()
        return {key for pair in rows for title in pair for key in keys_of(title or "")}
    finally:
        connection.close()


def _path(url: str) -> str:
    return unquote(urlsplit(url).path).lstrip("/").rstrip("/").lower()


def _pile(index: WikiIndex, author: Author, listed: set[str], revoltlib: set[str]) -> list[dict]:
    folder = author.folder.lower() + "/"
    items, linking = [], set()
    for page, article, url, _ in index.links():
        path = _path(url)
        if not (path + "/").startswith(folder):
            continue
        linking.add(page)
        if path not in listed:
            items.append({"kind": "link", "page": article, "page_id": page, "url": url})
    for work in author.works:
        if keys_of(work.title) & revoltlib:
            continue
        for key in keys_of(work.title):
            for page, article, redirect, aside in index.titled(key):
                if page in linking or any(word in aside.split() or aside == word for word in NOT_WRITING):
                    continue
                items.append({"kind": "work", "page": article, "page_id": page, "work": work.path, "title": work.title,
                              "aside": aside, "redirect": bool(redirect)})
    for key in keys_of(author.name):
        for page, article, redirect, aside in index.titled(key):
            if page not in linking:
                items.append({"kind": "author", "page": article, "page_id": page, "title": author.name, "aside": aside,
                              "redirect": bool(redirect)})
    seen, unique = set(), []
    for item in items:  # "The X" and "X" can land on one article
        mark = (item["kind"], item["page_id"], item.get("work", item.get("url", "")))
        if mark not in seen:
            seen.add(mark)
            unique.append(item)
    order = {kind: number for number, kind in enumerate(KINDS)}
    unique.sort(key=lambda item: order[item["kind"]])
    return [{**item, "id": number} for number, item in enumerate(unique, 1)]


class Workbench:
    """Reads each article as it stands today, checks what the code can, and asks the judge only whether a same-titled article is ours."""

    def __init__(self, author: Author, judge: str):
        self.author = author
        self.works = {work.path: work for work in author.works}
        self.api = WikiApi()
        self.check = LinkCheck()
        self.judge = ArticleJudge(judge, ABOUT) if judge else None
        self.used_judge = False
        self.slug = re.escape(author.folder.rsplit("/", 1)[-1].lower())

    def batch(self, queue: TaskQueue, items: list[dict], ends) -> None:
        articles = self.api.articles(list(dict.fromkeys(item["page"] for item in items)))
        for item in items:
            if ends and datetime.now() >= ends:
                return  # unrecorded items are looked at again next turn
            article = articles.get(item["page"])
            verdict = {"result": "skip", "why": "the article is gone"} if article is None else getattr(self, f"_{item['kind']}")(item, article)
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            queue.record(item["id"], verdict, self.judge.model if verdict.get("judged") else "code", stamp)
            if verdict["result"] == "propose":
                print(f"{item['id']:>6} {item['kind']:6} {item['page'][:50]:50} {verdict['why'][:80]}", flush=True)

    def release(self) -> None:
        if self.judge and self.used_judge:
            self.judge.release()

    def _links_here(self, text: str) -> bool:
        # A link into the author's English folder, written out or through a template ({{marxists.org|luxemburg}} and the like)
        lowered = text.lower()
        return (f"marxists.org/{self.author.folder.lower()}" in lowered
                or re.search(r"\{\{\s*(?:marxists|mia)[^{}]*\b" + self.slug + r"\b", lowered) is not None)

    def _link(self, item: dict, article: dict) -> dict:
        cite = find_citation(article["text"], item["url"])
        if cite is None:
            return {"result": "skip", "why": "the link has left the article since the dump"}
        found = self.check.check(item["url"])  # MIA redirects most moved pages, so the server has the last word
        if found["state"] not in ("dead", "soft-dead"):
            return {"result": "skip", "why": f"the link still works, or may ({found['why']})"}
        cited = cite.text.lower()
        work = max((work for work in self.author.works if work.title.lower() in cited), key=lambda work: len(work.title), default=None)
        if work is None:
            return {"result": "skip", "why": "dead, but the citation names none of the author's works; worth a look by hand", "dead": True}
        replacement = cite.with_our_link(work.link, item["url"], SITE)
        if replacement == cite.text:
            return {"result": "skip", "why": "the new link couldn't be placed in the citation as written"}
        return {"result": "propose", "why": f"the citation names \"{work.title}\"", "confidence": "low" if cite.archived else "medium",
                "title": work.title, "link": work.link, "dead": found["state"], "dead_why": found["why"], "marked": cite.marked_dead,
                "archived": cite.archived, "section": cite.section, "shape": cite.shape, "as_written": cite.text,
                "replacement": replacement, "article": article["title"]}

    def _work(self, item: dict, article: dict) -> dict:
        if self._links_here(article["text"]):
            return {"result": "skip", "why": f"the article already links {self.author.name} on marxists.org"}
        if _disambiguation(article):
            return {"result": "skip", "why": "a disambiguation page"}
        opening = lead(article["text"])
        surname = self.author.surname.lower()
        if surname not in opening.lower():
            # An article about the book names its author up front; a same-titled film, place or idea doesn't
            return {"result": "skip", "why": f"the article's opening doesn't name {self.author.name}"}
        written_by = WRITTEN_BY.search(opening[:400])
        if written_by and surname not in written_by.group(1).lower():
            # 3 Nov 2026: "Terrorism and Communism" is Trotsky's reply to Kautsky's book of that name; gemma said so, then said yes
            return {"result": "skip", "why": f"the article is about a work by {written_by.group(1).strip()}"}
        if item["aside"] in WORK_ASIDES or surname in item["aside"]:
            verdict = {"same": True, "reason": f"titled as a {item['aside']}, and its opening names {self.author.name}"}
        else:
            verdict = self._judged(lambda: self.judge.about_work(item["title"], self.author.name, article["title"], opening))
        return self._proposal(item, article, verdict, self.works[item["work"]].link)

    def _author(self, item: dict, article: dict) -> dict:
        if self._links_here(article["text"]):
            return {"result": "skip", "why": f"the article already links {self.author.name} on marxists.org"}
        if _disambiguation(article):
            # 3 Nov 2026: gemma passed "James Connolly (disambiguation)" because it lists the right Connolly among the others
            return {"result": "skip", "why": "a disambiguation page"}
        works = [work.title for work in sorted(self.author.works, key=lambda work: -len(work.pages))]
        verdict = self._judged(lambda: self.judge.about_author(self.author.name, works, article["title"], lead(article["text"])))
        return self._proposal(item, article, verdict, self.author.link)

    def _proposal(self, item: dict, article: dict, verdict: dict, link: str) -> dict:
        if not verdict["same"]:
            return {"result": "skip", "why": verdict["reason"], "judged": verdict.get("judged", False)}
        # marxists.org itself isn't "elsewhere": the article links some other MIA page, never this author's
        elsewhere = [name for name in full_text_elsewhere(article["text"]) if name != "Marxists Internet Archive"]
        return {"result": "propose", "why": verdict["reason"], "judged": verdict.get("judged", False), "title": item["title"],
                "link": link, "elsewhere": elsewhere, "article": article["title"],
                "author": self.author.name if item["kind"] == "work" else "", "confidence": "medium" if elsewhere else "high"}

    def _judged(self, ask) -> dict:
        if not self.judge:
            return {"same": False, "reason": "no judge was given"}
        self.used_judge = True
        return {**ask(), "judged": True}


WRITTEN_BY = re.compile(r"\bis an? (?:[\w-]+ ){0,3}(?:book|pamphlet|essay|work|treatise|novel|text|tract|article|poem|speech) "
                        r"(?:\w+ ){0,2}by ([^,.;()]+)", re.I)
DISAMBIGUATION = re.compile(r"\{\{\s*(?:disambiguation|disambig|dab|hndis|human name disambiguation|geodis|surname|given name)\b", re.I)


def _disambiguation(article: dict) -> bool:
    # A redirect can land on one under another name ("Class Struggle" -> "Class struggle (disambiguation)"), so the page's own template counts too
    return "(disambiguation)" in article["title"].lower() or DISAMBIGUATION.search(article["text"]) is not None


RANK = {"high": 0, "medium": 1, "low": 2}


def _edit(item: dict, verdict: dict, author: Author) -> dict:
    # Each piece as Ben pastes it; the summary always says he volunteers there
    summary = f"Added an external link to {SITE} (I volunteer there)."
    if item["kind"] == "link":
        return {"summary": f"Dead link replaced with the same text at {SITE} (I volunteer there)."}
    if item["kind"] == "work":
        what = f"''{verdict['title']}'' by {author.name}"
        line = f"* [{verdict['link']} Full text of ''{verdict['title']}''] at {SITE}"
        hosts = f"the full text of {what}"
    else:
        what = author.name
        line = f"* [{verdict['link']} {author.name} Internet Archive] at {SITE}"
        hosts = f"an archive of {author.name}'s writing"
    return {"what": what, "external_line": line, "summary": summary,
            "talk": f"{{{{Edit COI}}}} I volunteer for {SITE}, which hosts {hosts}. I'd like to suggest adding it under "
                    f"External links: {line[2:]} ~~~~"}


def write_results(queue: TaskQueue, path: Path, author: Author) -> int:
    found = [(item, verdict) for item, verdict, _ in queue.judged() if verdict.get("result") == "propose"]
    found.sort(key=lambda pair: (KINDS.index(pair[0]["kind"]), RANK.get(pair[1].get("confidence"), 3)))
    once = {}
    for item, verdict in found:  # one proposal per article and work
        once.setdefault((item["kind"], verdict["article"], verdict["link"]), (item, verdict))
    found = list(once.values())
    for item, verdict in found:
        verdict.update(_edit(item, verdict, author))
    dead_unmatched = [item for item, verdict, _ in queue.judged() if verdict.get("dead")]
    lines = [f"# Wikipedia links to {author.name} on {SITE}, found by local code and models. All UNCONFIRMED: open each article first.",
             f"# Our side: {queue.meta('filled_from')}. Wikipedia's links: {queue.meta('links_from')}.",
             "# Disclose on your user page that you volunteer for MIA; for anything arguable, use the talk-page text instead.", ""]
    for kind, heading in (("link", "DEAD LINKS INTO THE AUTHOR'S FOLDER"), ("work", f"{author.name.upper()}'S WORKS' ARTICLES WITH NO LINK"),
                          ("author", f"{author.name.upper()}'S OWN ARTICLE WITH NO LINK")):
        pairs = [pair for pair in found if pair[0]["kind"] == kind]
        lines += [f"## {heading} ({len(pairs)})", ""]
        for item, verdict in pairs:
            if kind == "link":
                lines += [f"[{verdict['confidence']}] {verdict['article']} · section: {verdict['section']}",
                          f"  dead: {item['url']} ({verdict['dead_why']})", f"  ours: {verdict['link']} · {verdict['title']}",
                          f"  as written:  {verdict['as_written']}", f"  replace with: {verdict['replacement']}",
                          f"  edit summary: {verdict['summary']}", ""]
            else:
                also = f"; full text already at {', '.join(verdict['elsewhere'])}" if verdict["elsewhere"] else "; no other full-text link"
                lines += [f"[{verdict['confidence']}] {verdict['article']}{also}", f"  ours: {verdict['link']} · {verdict['what']}",
                          f"  why: {verdict['why']}", f"  External links line: {verdict['external_line']}",
                          f"  talk page: {verdict['talk']}", ""]
    if dead_unmatched:
        lines += [f"## DEAD LINKS WITH NO WORK NAMED IN THE CITATION ({len(dead_unmatched)}), to find by hand", ""]
        lines += [f"{item['page']} · {item['url']}" for item in dead_unmatched] + [""]
    path.write_text("\n".join(lines), encoding="utf-8")
    with path.with_suffix(".jsonl").open("w", encoding="utf-8") as records:  # for the App Hub's Social page
        for item, verdict in found:
            records.write(json.dumps({"kind": item["kind"], "key": f"{item['kind']}:{item['page_id']}:{verdict['link']}",
                                      "dead_url": item.get("url", ""), **verdict}, ensure_ascii=False) + "\n")
    return len(found)


def main() -> None:
    args = options()
    ends = deadline(args.until)
    author = read_author(folder_of(args.target))
    if not author.works:
        sys.exit(f"No pages for {folder_of(args.target)} in the local mirror yet; run fetch_mia.py first.")
    queue = TaskQueue(Path(args.queue))
    index = WikiIndex(Path(args.queue).with_suffix(".wiki.sqlite"))
    if not queue.filled() and not fill(queue, index, author, ends):
        print("the fill stopped at the stop time; it carries on next turn", flush=True)
        return
    work = Workbench(author, args.judge)
    items = queue.next(args.limit)
    for start in range(0, len(items), 50):
        if ends and datetime.now() >= ends:
            break
        try:
            work.batch(queue, items[start:start + 50], ends)
        finally:
            write_results(queue, Path(args.results), author)
    work.release()
    print("proposals written:", write_results(queue, Path(args.results), author), queue.counts(), flush=True)


if __name__ == "__main__":
    main()
