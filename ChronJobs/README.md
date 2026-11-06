# Chron Jobs

The jobs that run on their own at a set time each night. It starts with one: backing up Claude's memories at 3 AM.

## Starting it

Run `start.bat`, or press Start on its pane in the hub; the hub's `start.bat` starts it with everything else. Its page is http://127.0.0.1:8740/: each job, its time, how its last run went, a **Run now** button, and its log.

It has to be running at 3 AM for the 3 AM job to happen. If it wasn't (the PC was off, or the window was closed), the job runs as soon as Chron Jobs next starts.

## The AI Workers wait for it

The Foreman asks `GET /api/busy` before starting each night-shift turn, and starts nothing while a job is **due or running**. Due counts too, because the workers' window also opens at 3 AM and a turn mustn't slip in during the seconds before the backup starts. The Foreman's page says "Waiting: Chron Jobs is running Back up Claude's memories."

A worker already partway through a turn finishes it; only new turns wait. If Chron Jobs isn't running, the Foreman carries on as before.

## The memory backup

`jobs\backup_memories.py` copies every project's `memory` folder under `%USERPROFILE%\.claude\projects`, plus `CLAUDE.md` and `settings.json`, into a new dated folder in `E:\!!!BACKUPs\Claude Memories`, such as `2026-11-02_03-00-04`.

- **Snapshots, never a mirror.** Each night is a folder of its own, and nothing ever deletes one; a few hundred kilobytes a night. To restore, copy what you want back from whichever night was good.
- **Blank files are refused.** A memory file that is all zero bytes (what the 1 November shadow copy brought back) is left out, and the job fails, so the page shows it in red.
- **Each snapshot has a `manifest.json`**: every file's size and checksum, and any blanks. The log says how many files are new, changed or gone since the night before.
- A snapshot is made as `<date>.partial` and renamed when complete, so a half-made one never looks like a good one.

## Painting Talasia's races (3:05)

`jobs\paint_scene.py` paints one race with one subject a night from `data\race_scenes.json` (the Orcs' army, the Wood Elves' mages, a Dwarven fort): five versions, each in a different one of the file's twelve art styles, straight into the Images app's gallery. About 10 minutes a night. With 16 races and 36 subjects, that's 576 nights before it runs out.

- **Every race by every subject.** Each round paints every race once, each with a different subject; the next round moves every race on to its next subject. No two nights running share a race or a subject.
- **Edit `race_scenes.json` freely.** Each race has a look (`folk`) and its buildings (`architecture`); a subject's prompt says where they go with `{folk}` and `{architecture}`. All of it is a draft. New subjects join the line; a done pair stays done. To paint one again or out of turn: `python jobs\paint_scene.py --race Orcs --subject army`.
- **A failed night paints the same pair the next night.** Versions that did finish are found in the gallery by their `source` (`chron:race_scenes:orcs:army:<version>`) and not drawn again.

## Adding a job

Add an entry to `data\jobs.json`: an `id`, a `title`, a `description`, a time `at` ("HH:MM"), the `command` to run (`{python}` is this Python; paths are from this folder), and `minutes` before it's stopped. Chron Jobs rereads the file every ten seconds; a typo keeps the last good list and says so on the page. Jobs run one at a time.

**A progress bar:** a job that prints lines like `PROGRESS 40 Version 3 of 5` (a percent, then an optional note) fills a bar on its card while it runs; those lines stay out of the log. A job that prints none gets a sweeping bar instead. The log fills in live as the job writes it.

## Files

| File | What it does |
|---|---|
| `chron_jobs.py` | The scheduler and its page, on port 8740 |
| `start.bat` | Starts it |
| `data\jobs.json` | The jobs and their times |
| `data\state.json` | When each job last ran and how it went (written by Chron Jobs) |
| `data\logs\` | Each job's output, one file per job |
| `jobs\backup_memories.py` | The memory backup |
| `web\index.html` | Its page |
