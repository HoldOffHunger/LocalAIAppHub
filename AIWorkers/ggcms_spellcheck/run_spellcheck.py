import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))
from dump_tables import newest_dump  # noqa: E402
from fill_queue import gather  # noqa: E402
from spell_queue import SpellQueue  # noqa: E402
from sites import site_about, site_name  # noqa: E402
from typo_check import TypoCheck  # noqa: E402

PROGRESS = 25  # a log line every this many words screened, so a long part doesn't look like a hang
PART = 250  # words judged and kept at a time: a text with thousands (entry 7090 has 4,255) finishes over several turns


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Spellcheck a GGCMS site's text bodies; confirmed typos go to a results file.")
    parser.add_argument("--target", default="revoltlib")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="where the typos are written for a person to confirm")
    parser.add_argument("--limit", type=int, default=50, help="texts to check this run")
    parser.add_argument("--model", default="mistral:7b", help="the screener: judges every word")
    parser.add_argument("--judge", default="gemma4:12b", help="the senior judge: rechecks only what the screener calls a typo ('' for none)")
    parser.add_argument("--batch", type=int, default=100, help="texts per batch, so each model loads once per batch")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


def main() -> None:
    args = options()
    ends = deadline(args.until)  # before the first run's fill: a fill that ran past the stop time made it tomorrow's
    queue = SpellQueue(Path(args.queue))
    if not queue.filled():
        texts, about = gather(newest_dump(args.target), log=lambda line: print(line, flush=True))
        queue.fill(texts, about)
        print("filled:", about, flush=True)
    screen = TypoCheck(args.model, site_about(args.target))
    judge = TypoCheck(args.judge, site_about(args.target)) if args.judge else None
    # Batches until the stop time or the limit: a batch that stops early for a long text's part leaves the rest for the next
    start_done, finished = queue.counts()["done"], 0
    while finished < args.limit and not (ends and datetime.now() >= ends):
        texts = queue.next(min(args.batch, args.limit - finished))
        if not texts:
            break
        batch_two_stage(queue, texts, screen, judge, ends)
        write_results(queue, Path(args.results), args.target)  # a stopped run still leaves its typos behind
        finished = queue.counts()["done"] - start_done
    print("typos written:", write_results(queue, Path(args.results), args.target), queue.counts(), flush=True)


def batch_two_stage(queue: SpellQueue, texts: list[dict], screen: TypoCheck, judge: TypoCheck | None, ends) -> None:
    # Mistral screens every word; Gemma 4 rechecks only the typos, loading once per batch
    judged = []
    # The judge rechecks every typo at 15-60 s each, so the screener gets at most half the turn; on 26 Oct 2026 it screened
    # all 100 texts, and the recheck, which never looked at the clock, ran 75 minutes past the stop time
    screen_until = datetime.now() + (ends - datetime.now()) / 2 if ends and judge else ends
    # Screening a whole batch takes the best part of a turn, so say each text as it starts: the log isn't blank while it works
    print(f"--- {screen.model} screens the words of up to {len(texts)} texts; then {judge.model if judge else 'nobody'} rechecks the typos ---",
          flush=True)
    for number, text in enumerate(texts, 1):
        if screen_until and datetime.now() >= screen_until:
            break
        part = text["words"][len(text["done"]):][:PART]
        first = len(text["done"]) + 1
        where = f", words {first}-{first + len(part) - 1} of {len(text['words'])}" if len(text["words"]) > PART else ""
        print(f"screening {number}/{len(texts)}: {text['title'][:60]} (entry {text['entryid']}) [{len(part)} words to judge{where}]",
              flush=True)
        # The clock is checked every word: on 29 Oct 2026 one part of 250 outlasted a half-hour turn's screening half, the
        # Foreman stopped it, and the judge never saw a word of it
        screened = []
        for word in part:
            if screen_until and datetime.now() >= screen_until:
                break
            screened.append({**word, **screen.check(text["title"], word), "checked_by": screen.model})
            if len(screened) % PROGRESS == 0 and len(screened) < len(part):
                print(f"  screened {len(screened)} of {len(part)}", flush=True)
        if screened:
            judged.append((text, screened))
        # A long text's part goes to the judge at once: on 29 Oct 2026 an hour's turn screened two of entry 7090's parts, the
        # judge ran out of clock in the first, and the turn kept nothing, three turns running
        if len(text["words"]) > PART or len(screened) < len(part):
            break
    if judge:
        screen.release()
    for text, verdicts in judged:
        if ends and datetime.now() >= ends:
            break  # the parts left unrecorded are screened again next turn; the parts before them are kept
        settled = len(verdicts)
        if judge:
            for number, verdict in enumerate(verdicts):
                if verdict["verdict"] != "typo":
                    continue
                if ends and datetime.now() >= ends:
                    settled = number  # out of clock: keep the words up to the first typo not yet rechecked
                    break
                second = judge.check(text["title"], verdict)
                verdict.update({**second, "screen_fix": verdict["fix"], "checked_by": f"{screen.model} > {judge.model}"})
        kept = verdicts[:settled]
        if kept:
            queue.record_part(text, kept, screen.model, datetime.now().astimezone().isoformat(timespec="seconds"))
        typos = [f"{v['word']}→{v['fix']}" for v in kept if v["verdict"] == "typo"]
        stopped = f" (stopped at the stop time; {len(verdicts) - settled} left for next turn)" if settled < len(verdicts) else ""
        print(f"{text['entryid']:>6} {text['title'][:50]:50s} {len(kept)} looked at, typos: {', '.join(typos) or 'none'}{stopped}", flush=True)
        if settled < len(verdicts):
            break
    if judge:
        judge.release()

def deadline(until: str) -> datetime | None:
    # "06:00" asked for at 23:00 means tomorrow morning, not a moment ago
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


def write_results(queue: SpellQueue, path: Path, target: str) -> int:
    typos = queue.typos()
    lines = [f"# {site_name(target)} spellcheck by local models. Every line is UNCONFIRMED: read it in its sentence before fixing.",
             f"# Filled from {queue.meta('filled_from')}. Grouped by entry.", ""]
    last = None
    for text, verdict in typos:
        if text["entryid"] != last:
            lines += ["", f"entry {text['entryid']} · {text['title']} · code {text['code']}"]
            last = text["entryid"]
        lines.append(f"  {verdict['word']} → {_fix(verdict)}  ({verdict['reason']})  [{verdict['checked_by']}]")
        lines.append(f"      {verdict['context']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # A split ("inhe ritance") isn't a misspelling to teach GGCMS's lists: "inhe -> inheritance" would mangle other texts
    new = sorted({(v["word"].lower(), _fix(v)) for _, v in typos if not v["known"] and " " not in v["word"] + _fix(v)})
    path.with_suffix(".new-misspellings.txt").write_text(
        "# Typos the models found that GGCMS's misspelling lists don't have yet: candidates to add, once confirmed.\n" +
        "".join(f"{wrong} -> {right}\n" for wrong, right in new), encoding="utf-8")
    return len(typos)


def _fix(verdict: dict) -> str:
    # Small models sometimes hand back the whole corrected sentence; past three words, the list's word is the better guess
    fix = verdict["fix"].strip()
    return fix if fix and len(fix.split()) <= 3 else verdict["known"] or verdict["suggestion"] or fix


if __name__ == "__main__":
    main()
