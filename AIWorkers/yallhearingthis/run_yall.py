import argparse
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "shared"))
from task_queue import TaskQueue  # noqa: E402

from artists import ArtistBook, ArtistFinder, Wikipedia, plain  # noqa: E402
from captions import caption_lines  # noqa: E402
from channel import RateLimited, fetch, list_videos  # noqa: E402
from int_site import IntSite  # noqa: E402
from quote_lines import QuotePick, candidates  # noqa: E402
from records import artist_record, show_record, slug, split_title  # noqa: E402

DATA = HERE.parent / "data" / "yallhearingthis"


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fill YallHearingThis.com on int from its YouTube channel: a show per video, "
                                                 "an artist per act it reacts to.")
    parser.add_argument("--target", default="yallhearingthis")
    parser.add_argument("--queue", required=True, help="this task's SQLite pile")
    parser.add_argument("--results", required=True, help="the report of what was made on int")
    parser.add_argument("--limit", type=int, default=10, help="videos to do this run")
    parser.add_argument("--model", default="gemma4:12b", help="names the artists and picks the quote")
    parser.add_argument("--only", action="append", default=[], help="a video id to do now, ahead of the pile (repeatable)")
    parser.add_argument("--dry", action="store_true", help="build the records and run modify.php dry; nothing is written")
    parser.add_argument("--refresh", action="store_true", help="rebuild shows already on int and update them in place")
    parser.add_argument("--deferred", action="store_true", help="go back for transcripts YouTube rate-limited, and update those shows")
    parser.add_argument("--pause", type=float, default=8, help="seconds between videos, so YouTube doesn't start answering 429")
    parser.add_argument("--until", default="", help="stop at this local time, HH:MM")
    return parser.parse_args()


class Filler:
    """One video at a time: fetch it, name its artists, make any artist the site hasn't got, pick a quote, make the show."""

    def __init__(self, args: argparse.Namespace):
        self.apply = not args.dry
        self.refresh = args.refresh
        self.rebuilt = set()  # artists refreshed this run
        self.site = IntSite(DATA / "records")
        self.book = ArtistBook(DATA / "artists.json")
        self.wiki = Wikipedia()
        self.finder = ArtistFinder(args.model)
        self.picker = QuotePick(args.model)  # the same model as the finder, so it loads once
        self.shows = self.site.section_id("shows")
        self.artists = self.site.section_id("artists")

    def do(self, item: dict) -> dict:
        video = fetch(item["video"], DATA / "videos" / item["video"])
        url = video["webpage_url"]
        existing = self.site.entry_with_link(url)
        if existing and not self.refresh:
            return {"show": existing, "note": "already on int", "title": video.get("title", "")}
        lines = caption_lines(video["_captions"])
        title = split_title(video.get("title", ""))[0]
        named = self.finder.find(video, self.book.names())
        quote = self.picker.pick(title, candidates(lines))
        artist_ids, made, missing = [], [], []
        for artist in named:
            entry, wiki_found, new = self.artist(artist, quote, title)
            if entry:
                artist_ids.append(entry)
                made += [artist["name"]] if new else []
                missing += [] if wiki_found else [artist["name"]]
        video["_code"] = self.free_code(slug(title), video)
        if existing:
            # A refresh keeps the show's code unless the title it came from has changed and the new one is free
            old = self.site.code_of(existing)
            taken = self.site.child_id(self.shows, slug(title))
            path = f"/shows/{old}/"
            video["_code"] = slug(title) if slug(title) and taken in (None, existing) else old
        record = show_record(video, lines, quote, artist_ids, DATA / "images" / "shows", item["format"])
        if existing:
            # Every record type the show has is replaced by the rebuilt one, as if a person had retyped the page
            record["clear"] = ["Description", "Quote", "TextBody", "Image", "Tag", "Link", "EventDate", "Association"]
            saved = self.site.save(path, f"show-{item['video']}", record, self.apply, "Update")
        else:
            saved = self.site.save("/shows/", f"show-{item['video']}", record, self.apply)
        show = self.site.entry_with_link(url) if self.apply else None
        return {"show": show, "ok": saved["ok"], "status": saved["status"], "title": video.get("title", ""), "code": video["_code"],
                "artists": [a["name"] for a in named], "artist_ids": artist_ids, "new_artists": made, "no_wikipedia": missing,
                "quote": (quote or {}).get("quote", ""), "quote_reason": (quote or {}).get("reason", ""),
                "transcript_lines": len(lines), "thumbnail": bool(video.get("_thumbnail")),
                "transcript_deferred": bool(video.get("_captions_deferred")), "no_english": bool(video.get("_no_english"))}

    def artist(self, artist: dict, quote: dict | None, show_title: str) -> tuple[int | None, bool, bool]:
        known = self.book.find(artist["name"])
        if known:
            self.book.alias(known, artist["name"])
        record = known or {"name": artist["name"], "aliases": [artist["name"]], "code": slug(artist["name"])}
        record |= {"kind": artist["kind"], "group": artist["group"]}  # this video's reading, not an older run's
        on_site = self.site.child_id(self.artists, record["code"])  # made earlier, or by a person: theirs stands
        rebuild = self.refresh and on_site and record["code"] not in self.rebuilt  # once a run, however many shows they're in
        if on_site and not rebuild:
            return self.book.add({**record, "entryid": on_site})["entryid"], bool(record.get("wikipedia")), False
        wiki = self.wiki.lookup(artist["name"], artist["kind"], artist["group"])
        picture = None
        if wiki and wiki.get("image"):
            suffix = Path(urlparse(wiki["image"]).path).suffix.lower() or ".jpg"
            picture = self.wiki.download(wiki["image"], DATA / "images" / "artists" / f"{record['code']}{suffix}")
        built = artist_record(record, wiki, quote, show_title, DATA / "images", picture)
        if rebuild:
            self.rebuilt.add(record["code"])
            built["clear"] = ["Description", "Quote", "TextBody", "Image", "Tag", "Link", "EventDate"]
            saved = self.site.save(f"/artists/{record['code']}/", f"artist-{record['code']}", built, self.apply, "Update")
            if self.apply:
                self.book.add({**record, "entryid": on_site, "wikipedia": (wiki or {}).get("url", ""), "status": saved["status"]})
            return on_site, bool(wiki), False
        saved = self.site.save("/artists/", f"artist-{record['code']}", built, self.apply)
        if not self.apply:
            print(f"     dry artist {record['name']}: {saved['status'][:80]} wiki={bool(wiki)} picture={bool(picture)}", flush=True)
            return None, bool(wiki), True
        entry = self.site.child_id(self.artists, record["code"]) if saved["ok"] else None
        self.book.add({**record, "entryid": entry, "wikipedia": (wiki or {}).get("url", ""), "status": saved["status"]})
        return entry, bool(wiki), True

    def free_code(self, code: str, video: dict) -> str:
        # Two shows with one title ("Stray Kids Holiday MV Reaction!" might come round again) get the upload date added,
        # and a count after it when one day had several (each Artist of the Week came out as three videos at once)
        code = code or video["id"].lower()
        dated = f"{code}-{video.get('upload_date', video['id'].lower())}"
        for candidate in [code, dated] + [f"{dated}-{n}" for n in range(2, 100)]:
            if not self.site.child_id(self.shows, candidate):
                return candidate
        return f"{dated}-{video['id'].lower()}"

    def release(self) -> None:
        self.finder.release()


def fill(queue: TaskQueue) -> None:
    videos = list_videos()
    queue.fill([{"id": n, **video} for n, video in enumerate(videos, 1)], {"filled_from": "youtube.com/@yallhearingthis",
                                                                            "listed_at": datetime.now().isoformat(timespec="seconds")})
    print(f"filled: {len(videos)} videos", flush=True)


def main() -> None:
    args = options()
    ends = deadline(args.until)  # before the first run's fill: a fill that ran past the stop time made it tomorrow's
    queue = TaskQueue(Path(args.queue))
    if not queue.filled():
        fill(queue)
    if args.deferred:
        args.refresh = True  # a deferred transcript belongs to a show already on int
        pile = [item for item, verdict, _ in queue.judged() if verdict.get("transcript_deferred")]
    elif args.refresh:
        pile = [item for item, _, _ in queue.judged()] + queue.next(100000)
    else:
        pile = queue.next(100000)
    if args.only:
        wanted = set(args.only)
        pile = [item for item in pile if item["video"] in wanted]
    filler = Filler(args)
    try:
        for item in pile[:args.limit]:
            if ends and datetime.now() >= ends:
                break
            if item is not pile[0]:
                time.sleep(args.pause)
            print(f"{item['id']:>4} {item['video']} {item['title'][:70]}", flush=True)
            stamp = datetime.now().astimezone().isoformat(timespec="seconds")
            try:
                verdict = filler.do(item)
            except RateLimited:
                # Ten minutes, then once more; a second 429 ends the run, and the rest waits in the pile for the next one
                print("     YouTube says too many requests; waiting ten minutes", flush=True)
                time.sleep(600)
                try:
                    verdict = filler.do(item)
                except RateLimited:
                    print("     still rate limited; stopping here", flush=True)
                    break
            except Exception as failure:  # one bad video shouldn't end the night; it stays in the pile for next time
                print(f"     failed: {failure}", flush=True)
                traceback.print_exc()
                continue
            if args.dry:
                print(f"     dry: {verdict.get('status')} artists={verdict.get('artists')} quote={verdict.get('quote', '')[:80]}", flush=True)
                continue
            if verdict.get("show") or verdict.get("note"):
                queue.record(item["id"], verdict, filler.finder.model, stamp)
            print(f"     show {verdict.get('show')} · artists {verdict.get('artists')} · {verdict.get('status', verdict.get('note', ''))[:60]}",
                  flush=True)
            write_results(queue, Path(args.results))
    finally:
        filler.release()
    print("written:", write_results(queue, Path(args.results)), queue.counts(), flush=True)


def deadline(until: str) -> datetime | None:
    if not until:
        return None
    now = datetime.now()
    ends = datetime.combine(now.date(), datetime.strptime(until, "%H:%M").time())
    return ends if ends > now else ends + timedelta(days=1)


def write_results(queue: TaskQueue, path: Path) -> int:
    # What's on int now, for a person to look over before any of it goes near production
    done = queue.judged()
    lines = ["# YallHearingThis.com, filled on int (Fumiko) from the YouTube channel. Nothing here is on production.",
             "# Browse: http://localhost:8000/shows/?domain=yallhearingthis.com", ""]
    for item, verdict, model in done:
        lines.append(f"show {verdict.get('show')} · {verdict.get('title', item['title'])}")
        if verdict.get("note"):
            lines += [f"  ({verdict['note']})", ""]
            continue
        lines.append(f"  /shows/{verdict.get('code', '')}/ · {item['format']} · {verdict.get('transcript_lines', 0)} caption lines"
                     f"{' · TRANSCRIPT DEFERRED (rate limited; run --deferred)' if verdict.get('transcript_deferred') else ''}"
                     f"{' · NO ENGLISH CAPTIONS (YouTube files it under another language)' if verdict.get('no_english') else ''}"
                     f"{'' if verdict.get('thumbnail') else ' · NO THUMBNAIL'}")
        lines.append(f"  artists: {', '.join(verdict.get('artists') or []) or '(none named)'}"
                     + (f" · new: {', '.join(verdict['new_artists'])}" if verdict.get("new_artists") else "")
                     + (f" · NOT ON WIKIPEDIA: {', '.join(verdict['no_wikipedia'])}" if verdict.get("no_wikipedia") else ""))
        if verdict.get("quote"):
            lines.append(f"  “{verdict['quote']}” ({verdict.get('quote_reason', '')}) [{model}]")
        if not verdict.get("ok", True):
            lines.append(f"  SAVE PROBLEM: {verdict.get('status', '')}")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return len(done)


if __name__ == "__main__":
    main()
