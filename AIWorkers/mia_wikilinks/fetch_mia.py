"""Downloads the text pages of MIA's English sections over SFTP: every .htm and .html in list_mia.py's listing, nothing else.

Read-only on the server: it reads files and never writes, renames or deletes anything there. Ben volunteers for MIA and holds
the login; the password is asked for at its own prompt and kept nowhere. The PDFs, images and audio (about 1 TB of the 1.03)
are never fetched: a page's title and author are all the catalogue needs.

    fetch_mia.py [--user acarloff] [--listing E:\\mia\\mia-files.txt] [--into E:\\mia\\site]

Resumable: a page already here at the listed size is skipped, so after a dropped connection the same command carries on.
"""

import argparse
import re
import sys
import time
from pathlib import Path, PurePosixPath

import paramiko

from list_mia import ROOT, connect

TEXT = (".htm", ".html")
# encyclopedia/ is the glossary again under a second name (2 Nov 2026: all 4,383 paths the same), so it's fetched once
SKIP_SECTIONS = ("encyclopedia/",)
NOT_WINDOWS = re.compile(r'[<>:"|?*\\]')


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download MIA's English text pages over SFTP, read-only.")
    parser.add_argument("--user", default="acarloff")
    parser.add_argument("--listing", type=Path, default=Path(r"E:\mia\mia-files.txt"))
    parser.add_argument("--into", type=Path, default=Path(r"E:\mia\site"))
    return parser.parse_args()


def pages(listing: Path) -> list[tuple[int, str]]:
    wanted = []
    for line in listing.read_text(encoding="utf-8").splitlines():
        if line.startswith("#"):
            continue
        size, _, path = line.split("\t", 2)
        parts = PurePosixPath(path).parts
        # A link's target is listed in its own right; nothing may climb out of the folder it lands in
        if path.endswith(" (link)") or ".." in parts or path.startswith(SKIP_SECTIONS):
            continue
        if path.lower().endswith(TEXT):
            wanted.append((int(size), path))
    return wanted


def main() -> None:
    args = options()
    wanted = pages(args.listing)
    total = sum(size for size, _ in wanted)
    todo = [(size, path) for size, path in wanted
            if not ((args.into / path).exists() and (args.into / path).stat().st_size == size)]
    print(f"{len(wanted):,} text pages, {total / 1e9:.2f} GB; {len(wanted) - len(todo):,} already here, "
          f"{len(todo):,} to fetch ({sum(size for size, _ in todo) / 1e9:.2f} GB)", flush=True)
    if not todo:
        return
    sftp = connect(args.user)
    started, fetched, got, failed = time.time(), 0, 0, []
    for size, path in todo:
        local = args.into / path
        partial = local.with_name(local.name + ".partial")
        try:
            if NOT_WINDOWS.search(path):  # "janfeb_09/</html>.html": a stray file on the server Windows can't name
                raise OSError("its name can't be a Windows path")
            local.parent.mkdir(parents=True, exist_ok=True)
            sftp.get(f"{ROOT}/{path}", str(partial))
            partial.replace(local)
        except OSError as problem:  # one unreadable page is noted and passed over
            failed.append(f"{path}\t{problem}")
            continue
        fetched += 1
        got += size
        if fetched % 1000 == 0:
            rate = got / max(time.time() - started, 1)
            left = (sum(s for s, _ in todo) - got) / max(rate, 1)
            print(f"  {fetched:,} of {len(todo):,}, {got / 1e9:.2f} GB, about {left / 60:.0f} min left, now in "
                  f"{PurePosixPath(path).parent}", flush=True)
    print(f"\nfetched {fetched:,} pages ({got / 1e9:.2f} GB) into {args.into} in {(time.time() - started) / 60:.0f} min")
    if failed:
        report = args.into / "fetch-failures.txt"
        report.write_text("\n".join(failed) + "\n", encoding="utf-8")
        print(f"{len(failed):,} couldn't be read; listed in {report}")


if __name__ == "__main__":
    try:
        main()
    except (paramiko.SSHException, EOFError) as problem:
        sys.exit(f"The connection dropped ({problem}); run the same command again and it carries on where it stopped.")
