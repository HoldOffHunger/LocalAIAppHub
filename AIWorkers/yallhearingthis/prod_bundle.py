import argparse
import json
import shutil
import sys
import tarfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from int_site import IntSite  # noqa: E402

DATA = HERE.parent / "data" / "yallhearingthis"

SECTIONS = {
    "shows": {"fields": {"Title": "Shows", "Code": "shows", "Publish": "1", "ChildNoun": "Show", "ChildNounPlural": "Shows",
                         "Description": ["Every reaction, listening party and live show from the Y'all Hearing This?! channel, "
                                         "with the video's own description and a transcript of what was said."],
                         "description_Source": [""], "description_Language": ["en"]}},
    "artists": {"fields": {"Title": "Artists", "Code": "artists", "Publish": "1", "ChildNoun": "Artist", "ChildNounPlural": "Artists",
                           "Description": ["The groups, soloists and units we have reacted to, each with every show they appear in."],
                           "description_Source": [""], "description_Language": ["en"]}},
}


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bundle shows already on int, with their artists and pictures, for "
                                                 "push_bundle.php to put on another host (production, when Ben says so).")
    parser.add_argument("videos", nargs="+", help="YouTube ids of the shows to send")
    parser.add_argument("--out", default=str(DATA / "prod-bundle"), help="the bundle folder; a .tgz is made beside it")
    parser.add_argument("--domain", default="yallhearingthis.com")
    parser.add_argument("--database", default="yallhearingthis")
    parser.add_argument("--user", default="1", help="holdoffhunger; the site has two administrators")
    return parser.parse_args()


def windows_path(path: str) -> Path:
    # /mnt/e/AIWorkers/x.jpg, as the posted records name it for WSL, is E:\AIWorkers\x.jpg here
    if path.startswith("/mnt/") and len(path) > 6:
        return Path(f"{path[5].upper()}:\\" + path[7:].replace("/", "\\"))
    return Path(path)


def carry_files(record: dict, images: Path, prefix: str) -> dict:
    # Copied in with a prefix, since a show and an artist can share a code ("bts"), and so a file name
    files = {}
    for field, paths in record.get("files", {}).items():
        files[field] = []
        for path in paths:
            if not path:
                files[field].append("")
                continue
            source = windows_path(path)
            name = f"{prefix}-{source.name}"
            shutil.copyfile(source, images / name)
            files[field].append(name)
    return {**record, "files": files} if files else record


def main() -> None:
    args = options()
    site = IntSite(DATA / "records")
    out = Path(args.out)
    if out.exists():
        shutil.rmtree(out)
    (out / "images").mkdir(parents=True)
    shows, artists = [], {}
    for video in args.videos:
        posted = DATA / "records" / f"show-{video}.json"
        record = json.loads(posted.read_text(encoding="utf-8"))
        url = record["fields"]["URL"][0]
        entry = site.entry_with_link(url)
        if not entry:
            raise SystemExit(f"{video} isn't on int yet")
        codes = [row["Code"] for row in site.query(
            f"SELECT e.Code FROM Association s JOIN Entry e ON e.id = s.ChosenEntryid WHERE s.Entryid = {entry} ORDER BY s.id")]
        for code in codes:
            if code not in artists:
                artist = json.loads((DATA / "records" / f"artist-{code}.json").read_text(encoding="utf-8"))
                artist.pop("clear", None)  # a refresh's clear is for an Update; on the new host it's a Save
                artists[code] = carry_files(artist, out / "images", "artist")
        record.pop("clear", None)
        record["fields"]["Code"] = site.code_of(entry)  # the code int settled on, not the one first proposed
        shows.append({"code": site.code_of(entry), "url": url, "artists": codes, "record": carry_files(record, out / "images", "show")})
        print(f"show {entry} /shows/{site.code_of(entry)}/ · artists {', '.join(codes) or '(none)'}")
    manifest = {"domain": args.domain, "database": args.database, "user": args.user, "sections": SECTIONS,
                "artists": artists, "shows": shows}
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.copyfile(HERE / "push_bundle.php", out / "push_bundle.php")
    archive = out.with_suffix(".tgz")
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(out, arcname="yht-bundle")
    print(f"\n{len(shows)} shows, {len(artists)} artists -> {archive} ({archive.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
