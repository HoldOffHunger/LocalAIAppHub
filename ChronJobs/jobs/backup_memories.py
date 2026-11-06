# Chron Jobs' memory backup: a dated snapshot of Claude Code's memories into E:\!!!BACKUPs\Claude Memories\<date time>\
#
# Snapshots, never a mirror, and nothing here ever deletes. On 1 Nov 2026 an rm -rf reached %USERPROFILE%\.claude, and the
# shadow copy brought the memory files back as the right names over all-zero bytes. A mirror would have copied those blanks
# over the good ones. A blank file is left out of the snapshot and fails the job, so the page shows it in red.
#
#     backup_memories.py [--source <.claude folder>] [--to <backups folder>]

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

SOURCE = Path.home() / ".claude"
DESTINATION = Path(r"E:\!!!BACKUPs\Claude Memories")
SINGLE_FILES = ["CLAUDE.md", "settings.json"]  # beside the memories: the global instructions, and the plugins they switch on


def wanted(source):
    # Every project's memory folder, then the two files beside them; paths relative to the .claude folder
    found = []
    projects = source / "projects"
    if projects.is_dir():
        for memory in sorted(projects.glob("*/memory")):
            found += sorted(path for path in memory.rglob("*") if path.is_file())
    found += [source / name for name in SINGLE_FILES if (source / name).is_file()]
    return [path.relative_to(source) for path in found]


def is_blank(path):
    # Something there, and every byte of it zero
    with open(path, "rb") as handle:
        data = handle.read()
    return bool(data) and not data.strip(b"\0")


def previous_manifest(destination):
    snapshots = sorted(path for path in destination.glob("*") if not path.name.endswith(".partial") and (path / "manifest.json").is_file())
    if not snapshots:
        return {}
    return json.loads((snapshots[-1] / "manifest.json").read_text(encoding="utf-8")).get("files", {})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--to", type=Path, default=DESTINATION)
    options = parser.parse_args()

    files = wanted(options.source)
    if not files:
        print("Nothing to back up: no memory folders under %s." % options.source)
        return 1
    options.to.mkdir(parents=True, exist_ok=True)
    before = previous_manifest(options.to)

    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    taken = 1
    while (options.to / stamp).exists() or (options.to / (stamp + ".partial")).exists():  # two runs in one second
        taken += 1
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S") + "-%d" % taken
    partial = options.to / (stamp + ".partial")  # renamed when complete, so a half-made snapshot never looks like a good one
    manifest, blank = {}, []
    for relative in files:
        source = options.source / relative
        if is_blank(source):
            blank.append(relative.as_posix())
            continue
        target = partial / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        manifest[relative.as_posix()] = {"bytes": target.stat().st_size, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}

    (partial / "manifest.json").write_text(json.dumps({"made": datetime.now().astimezone().isoformat(timespec="seconds"),
                                                       "source": str(options.source), "files": manifest, "blank": blank},
                                                      indent=2), encoding="utf-8")
    os.rename(partial, options.to / stamp)

    gone = sorted(set(before) - set(manifest))
    changed = sum(1 for name, entry in manifest.items() if name in before and before[name]["sha256"] != entry["sha256"])
    added = sum(1 for name in manifest if name not in before)
    projects = len({name.split("/")[1] for name in manifest if name.startswith("projects/")})
    if gone:
        print("Not here since the last snapshot (%d): %s" % (len(gone), ", ".join(gone)))
    for name in blank:
        print("BLANK, left out: %s" % name)
    summary = "%d files from %d projects into %s: %d new, %d changed, %d gone." % (len(manifest), projects, options.to / stamp,
                                                                                  added, changed, len(gone))
    if blank:
        print("%d memory files are all zero bytes and were left out. %s" % (len(blank), summary))
        return 1
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
