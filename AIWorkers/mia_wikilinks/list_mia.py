"""Lists the Marxists Internet Archive's English sections over SFTP: every file's size, date and path, into one text file.

Read-only: it opens directories and reads their listings, and never downloads, writes or changes anything on the server.
Ben volunteers for MIA and holds the login; the password is asked for at its own prompt and kept nowhere.

    list_mia.py [--user acarloff] [--out E:\\mia\\mia-files.txt] [--sections archive reference ...]

The server's key must already be in ~/.ssh/known_hosts (it is, from Ben's first sftp login on 2 Nov 2026); an unknown or
changed key is refused, never accepted on trust.
"""

import argparse
import getpass
import stat
import sys
import time
from collections import Counter
from pathlib import Path, PurePosixPath

import paramiko

HOST = "ftp.marxists.org"
ROOT = "/www/mia"  # the web root: marxists.org/<path> is /www/mia/<path>
SECTIONS = ["archive", "reference", "subject", "history", "glossary", "encyclopedia"]  # what English Wikipedia cites


def options() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List MIA's English sections over SFTP, read-only.")
    parser.add_argument("--user", default="acarloff")
    parser.add_argument("--out", type=Path, default=Path(r"E:\mia\mia-files.txt"))
    parser.add_argument("--sections", nargs="+", default=SECTIONS)
    return parser.parse_args()


def connect(user: str) -> paramiko.SFTPClient:
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    client.connect(HOST, username=user, password=getpass.getpass(f"{user}@{HOST}'s password: "),
                   look_for_keys=False, allow_agent=False, timeout=30)
    return client.open_sftp()


def walk(sftp: paramiko.SFTPClient, section: str, out, counts: Counter, sizes: Counter) -> int:
    # Depth first, one directory listing at a time; symlinked directories are listed as links, never followed, so a loop
    # can't trap it; a directory it may not read is noted and passed over
    files, waiting = 0, [section]
    while waiting:
        folder = waiting.pop()
        try:
            entries = sftp.listdir_attr(f"{ROOT}/{folder}")
        except OSError as problem:
            out.write(f"#\tunreadable\t{folder}/\t{problem}\n")
            continue
        for entry in sorted(entries, key=lambda e: e.filename, reverse=True):
            path = f"{folder}/{entry.filename}"
            if stat.S_ISDIR(entry.st_mode):
                waiting.append(path)
                continue
            kind = "link" if stat.S_ISLNK(entry.st_mode) else "file"
            day = time.strftime("%Y-%m-%d", time.gmtime(entry.st_mtime or 0))
            out.write(f"{entry.st_size}\t{day}\t{path}{' (link)' if kind == 'link' else ''}\n")
            suffix = PurePosixPath(entry.filename).suffix.lower() or "(none)"
            counts[suffix] += 1
            sizes[suffix] += entry.st_size or 0
            files += 1
            if files % 5000 == 0:
                print(f"  {section}: {files:,} files so far, now in {folder}", flush=True)
    return files


def main() -> None:
    args = options()
    sftp = connect(args.user)
    counts, sizes = Counter(), Counter()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    partial = args.out.with_suffix(".partial")
    with partial.open("w", encoding="utf-8", newline="\n") as out:
        out.write(f"# size\tchanged\tpath under {ROOT} (= https://www.marxists.org/<path>), listed {time.strftime('%Y-%m-%d %H:%M')}\n")
        for section in args.sections:
            started = time.time()
            print(f"listing {section}/ ...", flush=True)
            found = walk(sftp, section, out, counts, sizes)
            print(f"  {section}: {found:,} files in {time.time() - started:.0f} s", flush=True)
    partial.replace(args.out)
    total = sum(sizes.values())
    print(f"\nwrote {args.out}: {sum(counts.values()):,} files, {total / 1e9:.1f} GB")
    for suffix, size in sizes.most_common(12):
        print(f"  {suffix:8} {counts[suffix]:>9,} files {size / 1e9:8.2f} GB")


if __name__ == "__main__":
    try:
        main()
    except paramiko.SSHException as problem:
        sys.exit(f"Couldn't connect: {problem}")
