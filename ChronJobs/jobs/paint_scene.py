# Chron Jobs' nightly painting: one race and one subject from data\race_scenes.json a night (the Orcs' army, the Wood
# Elves' mages), all its versions, each in a different art style, into the Images app's gallery (ImageGen, port 8730).
#
# Every race is painted with every subject. The nights go round by round: each round paints every race once, each with a
# different subject, and the next round moves every race on to its next subject, so consecutive nights change both race
# and subject. A night that fails paints the same pair the next night; any of its versions that did finish are found in
# the gallery by their "source" and not drawn again. The AI Workers are waiting while this runs, so the pictures claim
# the card at the hub's GPU desk like any picture of Ben's.
#
#     paint_scene.py [--race <race> --subject <id>]     one pair by name, painted again even if it was done before

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
BOOK_PATH = HERE / "data" / "race_scenes.json"
DONE_PATH = HERE / "data" / "race_scenes_done.json"
IMAGEGEN = os.environ.get("IMAGEGEN_URL", "http://127.0.0.1:8730")
IMAGEGEN_FOLDER = Path(r"E:\ImageGen")
SOURCE = "chron:race_scenes"


def load(path, fallback):
    return json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).exists() else fallback


def pair_id(race, subject):
    return "%s:%s" % (race.lower().replace(" ", "-"), subject["id"])


def order(book):
    # Round m gives the i-th race subject m + i, so within a round every race has a different subject, and over all the
    # rounds every race has every subject. Returns (index, race, subject); the index picks the styles.
    races, subjects = list(book["folk"]), book["subjects"]
    lined_up = []
    for m in range(len(subjects)):
        for i, race in enumerate(races):
            lined_up.append((len(lined_up), race, subjects[(m + i) % len(subjects)]))
    return lined_up


def style_for(index, version, styles):
    # Version n of night i: consecutive styles from a starting point that moves on 5 for each night, so a night's
    # versions are all different and neighbouring nights don't share the same set
    return styles[(index * 5 + version - 1) % len(styles)]


def prompt_for(race, subject, book, style):
    text = subject["prompt"].replace("{folk}", book["folk"][race]).replace("{architecture}", book["architecture"][race])
    return "%s %s. %s" % (text[0].upper() + text[1:], style, book["finish"])


def call(path, body=None, timeout=30):
    request = urllib.request.Request(IMAGEGEN + path, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def imagegen_up():
    try:
        with socket.create_connection(("127.0.0.1", int(IMAGEGEN.rsplit(":", 1)[1])), timeout=1):
            return True
    except OSError:
        return False


def wake_imagegen():
    # The hub starts it with everything else; if it's been closed, its own start script, as the hub runs it
    if imagegen_up():
        return True
    print("ImageGen isn't running; starting it.", flush=True)
    subprocess.Popen([str(IMAGEGEN_FOLDER / "start.bat"), "--no-browser"], cwd=IMAGEGEN_FOLDER,
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    for _ in range(60):
        time.sleep(1)
        if imagegen_up():
            return True
    return False


def report(finished, drawing, versions, shown):
    # Moves Chron Jobs' progress bar: whole versions finished plus how far through the rest ImageGen is. Printed only when
    # it changes, since Chron Jobs reads every line
    percent = min(100, (finished * 100 + drawing) // versions)
    line = "PROGRESS %d Version %d of %d" % (percent, min(finished + 1, versions), versions)
    if line != shown:
        print(line, flush=True)
    return line


def paint(index, race, subject, book):
    # Asks for every version not already in the gallery, all at once (ImageGen draws them one by one), then waits for them
    already = {entry.get("source"): entry for entry in call("/api/gallery") if entry.get("source", "").startswith(SOURCE)}
    jobs, made, failed = {}, {}, []
    for version in range(1, book["versions"] + 1):
        source = "%s:%s:%d" % (SOURCE, pair_id(race, subject), version)
        if source in already:
            made[version] = already[source]["id"]
            continue
        style = style_for(index, version, book["styles"])
        reply = call("/api/generate", {"prompt": prompt_for(race, subject, book, style), "width": book["width"],
                                       "height": book["height"], "source": source})
        jobs[version] = reply["job"]
    started, shown = time.time(), None
    while jobs and time.time() - started < 60 * 60:
        time.sleep(3)
        drawing = 0  # percent through the versions still out, one at a time, as ImageGen reports it
        for version, job in list(jobs.items()):
            state = call("/api/jobs/" + job)
            if state.get("state") == "done":
                made[version] = state["picture"]
                del jobs[version]
                print("  version %d: %s" % (version, style_for(index, version, book["styles"]).split(" with ")[0]), flush=True)
            elif state.get("state") == "failed":
                failed.append("version %d: %s" % (version, state.get("message")))
                del jobs[version]
            else:
                drawing += state.get("percent") or 0
        shown = report(len(made) + len(failed), drawing, book["versions"], shown)
    failed += ["version %d: not finished after an hour" % version for version in jobs]
    return made, failed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--race", default="")
    parser.add_argument("--subject", default="")
    options = parser.parse_args()

    book = load(BOOK_PATH, None)
    done = load(DONE_PATH, {})
    lined_up = order(book)
    if options.race or options.subject:
        lined_up = [row for row in lined_up if row[1].lower() == options.race.lower() and row[2]["id"] == options.subject]
        if not lined_up:
            print("There's no race %r with a subject %r in %s; give both." % (options.race, options.subject, BOOK_PATH))
            return 1
    else:
        lined_up = [row for row in lined_up if pair_id(row[1], row[2]) not in done]
        if not lined_up:
            print("Every race has been painted with every subject in race_scenes.json; add more to keep this going.")
            return 0
    index, race, subject = lined_up[0]
    print("Tonight: %s, %s, %d versions." % (race, subject["id"], book["versions"]), flush=True)

    if not wake_imagegen():
        print("ImageGen didn't start, so nothing was painted; the same pair is next tomorrow.")
        return 1
    made, failed = paint(index, race, subject, book)
    for problem in failed:
        print("  failed, %s" % problem, flush=True)
    if len(made) < book["versions"]:
        print("Painted %d of %d versions of %s, %s; the rest are tried again tomorrow night." % (len(made), book["versions"], race, subject["id"]))
        return 1
    done[pair_id(race, subject)] = {"painted": datetime.now().astimezone().isoformat(timespec="seconds"), "pictures": [made[v] for v in sorted(made)]}
    DONE_PATH.write_text(json.dumps(done, indent=2), encoding="utf-8")
    left = sum(1 for _index, r, s in order(book) if pair_id(r, s) not in done)
    print("Painted %s, %s: %d pictures in the Images gallery. %d nights to go." % (race, subject["id"], len(made), left))
    return 0


if __name__ == "__main__":
    sys.exit(main())
