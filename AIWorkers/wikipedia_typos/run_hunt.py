import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from doubled_pairs import doubled_pairs, write_pair_report  # noqa: E402
from ggcms_words import british_spellings, known_misspellings  # noqa: E402
from hunt_queue import HuntQueue  # noqa: E402
from typo_age import TypoAges  # noqa: E402
from typo_judge import TypoJudge  # noqa: E402
from wiki_search import WikiSearch  # noqa: E402
from wiki_text import occurrences, split_by_markup  # noqa: E402
from word_rules import WordRules  # noqa: E402

LEFT_ALONE = {"verdict": "skipped", "fix": "", "reason": "Only in a link, file name, address, reference, template, quotation block "
                                                        "or quotation, or where the article names or defines the word itself."}
TEST_DEPTH = 30  # Wikipedia hits read per slip in a doubled-letter test: three visits
TITLED = {"verdict": "skipped", "fix": "", "reason": "The article's own title has the word, so it's the article's subject, not a slip."}


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Look for GGCMS's known misspellings in English Wikipedia; a local model confirms each.")
    parser.add_argument("--target", default="en.wikipedia")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the typos are written for a person to confirm")
    parser.add_argument("--limit", type=int, default=100, help="misspellings to visit this run")
    parser.add_argument("--per-word", type=int, default=10, help="Wikipedia results read per visit to a misspelling")
    parser.add_argument("--model", default="gemma4:12b")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    parser.add_argument("--dates-only", action="store_true", help="only give the typos already found their ages, then stop")
    return parser.parse_args()


def main() -> None:
    args = options()
    ends = deadline(args.until)
    queue = HuntQueue(Path(args.queue))
    if args.target.startswith("doubled-"):
        # A test of the doubled-letter worker's slips, not GGCMS's lists: its pile grows as it judges, so new slips are
        # added every run, most used words first, as that worker ranks them
        pairs = {wrong: right for wrong, right in doubled_pairs(args.target.removeprefix("doubled-")).items() if len(wrong) >= 3}
        queue.fill(pairs, {"filled_from": f"ggcms_doubled_letters, {args.target}",
                           "filled_at": datetime.now().astimezone().isoformat(timespec="seconds"), "words": len(pairs)}, shuffle=False)
        print(f"{len(pairs)} doubled-letter slips to test", flush=True)
    elif not queue.filled():
        listed = known_misspellings()
        right_either_way = british_spellings()
        # Under three letters, or with a quote mark, the search can't hold it; a British spelling is right on Wikipedia
        pairs = {wrong: right for wrong, right in listed.items() if len(wrong) >= 3 and '"' not in wrong and wrong not in right_either_way}
        queue.fill(pairs, {"filled_from": "GGCMS EnglishMisspellings and IntensiveEnglishMisspellings",
                           "filled_at": datetime.now().astimezone().isoformat(timespec="seconds"), "words": len(pairs)})
        print(f"filled: {len(pairs)} misspellings of {len(listed)} listed", flush=True)
    wiki = WikiSearch()
    ages, tried = TypoAges(wiki.client), set()
    rules = WordRules()
    # The pile was filled from GGCMS's lists as they stood then; a pair later found to be a US/UK spelling (garotting,
    # 3 Nov 2026) is never searched again
    queue.retire(british_spellings())
    date_typos(queue, ages, wiki, ends, tried)
    if args.dates_only:
        print("typos written:", write_results(queue, Path(args.results), rules), flush=True)
        return
    judge = TypoJudge(args.model)
    visits = 0
    while visits < args.limit and not (ends and datetime.now() >= ends):
        word = queue.next_word()
        if not word:
            print("every misspelling's results have all been read", flush=True)
            break
        visit(queue, wiki, judge, word, args.per_word, ends, rules)
        visits += 1
        if args.target.startswith("doubled-") and word["offset"] + args.per_word >= TEST_DEPTH:
            # A test needs a sample, not every hit: "los" (Spanish) has 472,666, and would have held the job for weeks
            queue.finish(word["id"])
        date_typos(queue, ages, wiki, ends, tried)
        write_results(queue, Path(args.results), rules)
        pair_report(queue, args)  # each visit, like the results: a run stopped from the Foreman never reaches the end
    print("typos written:", write_results(queue, Path(args.results), rules), queue.counts(), flush=True)
    if (doubtful := pair_report(queue, args)) is not None:
        print("doubtful pairs:", doubtful, flush=True)


def pair_report(queue: HuntQueue, args: argparse.Namespace) -> int | None:
    if not args.target.startswith("doubled-"):
        return None
    return write_pair_report(queue.connection, Path(args.results).with_suffix(".pairs.txt"), args.target.removeprefix("doubled-"))


def visit(queue: HuntQueue, wiki: WikiSearch, judge: TypoJudge, word: dict, per_word: int, ends, rules: WordRules) -> None:
    total, pages = wiki.insource(word["wrong"], word["offset"], per_word)
    fresh = [page for page in pages if not queue.seen(word["id"], page["id"])]
    texts = wiki.articles([page["title"] for page in fresh]) if fresh else {}
    found = []
    for page in fresh:
        if ends and datetime.now() >= ends:
            return  # this visit isn't counted: next turn reads the same page of results, skipping the articles already judged
        article = texts.get(page["title"])
        # A slip inside a quotation is only fixable once its source is read: it may be the source's own spelling, which
        # wants [sic], not a fix. Sources are often gone (2 Nov 2026: "melow gold", every archive.org copy dead), so
        # quotations are left alone outright. So is a word the article names or defines, "also called callop": it means it
        places = [place for place in occurrences(article["text"], word["wrong"]) if not place["quoted"] and not place["named"]] \
            if article else []
        places = [place for place in places if not rules.fine_here(word["wrong"], place["sentence"])  # what past mistakes taught
                  and not acronym(place["word"])]
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        if in_title(word["wrong"], page["title"]):
            queue.record(word, page, {}, TITLED, "rules", stamp)
            continue
        if not places:
            queue.record(word, page, {}, LEFT_ALONE, "rules", stamp)
            continue
        place = places[0]
        verdict = judge.check(page["title"], word["wrong"], word["correct"], place, rules.note(word["wrong"]))
        if verdict["verdict"] == "typo" and another_word(word["wrong"], word["correct"], verdict.get("fix", "")):
            verdict = {**verdict, "verdict": "fine", "reason": f"The judge's fix, \"{verdict['fix']}\", is another word, not a "
                                                              f"spelling of this one. {verdict.get('reason', '')}"}
        data = {key: place[key] for key in ("word", "sentence", "raw", "quoted", "italic")} | {"also": len(places) - 1}
        queue.record(word, page, data, verdict, judge.model, stamp)
        if verdict["verdict"] == "typo":
            found.append(page["title"])
    queue.visited(word, total, len(pages))
    print(f"round {word['round'] + 1} · {word['wrong']} → {word['correct']}: {total} on Wikipedia, read {word['offset'] + 1}-"
          f"{word['offset'] + len(pages)}, typos in: {', '.join(found) or 'none'}", flush=True)


def date_typos(queue: HuntQueue, ages: TypoAges, wiki: WikiSearch, ends, tried: set) -> None:
    # Each typo's age: a minutes-old one is someone's work in progress, and fixing it under them is poor manners, while
    # one that has stood for years has been read by everyone since. Each is asked about once a run; one WikiWho can't
    # answer yet waits for the next
    undated = [typo for typo in queue.undated() if (typo["word_id"], typo["page_id"]) not in tried]
    for start in range(0, len(undated), 25):
        batch, found = undated[start:start + 25], []
        for typo in batch:
            if ends and datetime.now() >= ends:
                break
            tried.add((typo["word_id"], typo["page_id"]))
            age = ages.date(typo["page_id"], typo["wrong"], typo.get("raw", ""))
            if age:
                found.append((typo, age))
        times = wiki.revision_times(sorted({age["since_rev"] for _, age in found if age["since_rev"]})) if found else {}
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        for typo, age in found:
            queue.dated(typo, {**age, "typo_since": times.get(age["since_rev"], "")}, stamp)
        if found:
            print(f"dated {len(found)} typos, {sum(age['gone'] for _, age in found)} already gone from their articles", flush=True)
        if ends and datetime.now() >= ends:
            return


def in_title(wrong: str, title: str) -> bool:
    # An article named for the word is about it: "Nicotini" is a nicotine product, and its article spells it that way throughout
    return bool(re.search(rf"\b{re.escape(wrong)}\b", title, re.IGNORECASE))


def acronym(written: str) -> bool:
    # In capitals it's an initialism, not a slip: SubSpace's ASSS server, Kenyon College's CSAD
    letters = re.sub(r"[^A-Za-z]", "", written)
    return len(letters) > 1 and letters.isupper()


def another_word(wrong: str, correct: str, fix: str) -> bool:
    # The list is of misspellings, so a fix must be a spelling of the word, not a different word: gemma once "fixed" kaber,
    # a wild mustard listed as a slip for kabar, to charlock, the plant's other name in the same sentence
    if not fix.strip():
        return False
    squeeze = lambda text: re.sub(r"[\s-]", "", text.lower())
    fix, correct, wrong = squeeze(fix), squeeze(correct), squeeze(wrong)
    if fix in correct or correct in fix:  # a phrase's fix often names only the word that changes: "had came" -> "come"
        return False
    return SequenceMatcher(None, wrong, fix).ratio() < 0.6


def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


def article_url(title: str) -> str:
    return "https://en.wikipedia.org/wiki/" + quote(title.replace(" ", "_"))


def stood(typo: dict) -> str:
    if typo.get("gone"):
        return "already gone from the article"
    if typo.get("typo_since"):
        return f"in the article since {typo['typo_since'][:10]}, last edited {(typo['last_edit'] or '?')[:10]}"
    return "age not known yet"


def write_results(queue: HuntQueue, path: Path, rules: WordRules) -> int:
    # A rule learnt today also clears the finds it would have caught before it existed
    right_either_way = british_spellings()
    typos = [typo for typo in queue.typos() if not rules.fine_here(typo["wrong"], typo["sentence"])
             and typo["wrong"].lower() not in right_either_way
             and not in_title(typo["wrong"], typo["title"]) and not another_word(typo["wrong"], typo["correct"], typo["fix"])
             and not acronym(typo["word"]) and not split_by_markup(typo["word"], typo.get("raw", ""))]
    lines = ["# Known misspellings found in English Wikipedia by a local model. Every line is UNCONFIRMED: read it in the "
             "article before fixing, and fix by hand.", ""]
    for typo in typos:
        lines += [f"{typo['title']} · {article_url(typo['title'])}",
                  f"  {typo['word']} → {typo['fix'] or typo['correct']}  ({typo['reason']})  [{typo['checked_by']}]",
                  f"  {stood(typo)}",
                  f"      {typo['sentence']}", ""]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # The same, for the App Hub's Social page
    shown = [{**typo, "url": article_url(typo["title"])} for typo in typos]
    path.with_suffix(".json").write_text(json.dumps(shown, ensure_ascii=False, indent=1), encoding="utf-8")
    return len(typos)


if __name__ == "__main__":
    main()
