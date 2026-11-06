# App Hub

One page with a side panel for every app we built: Chat, Voice (Chat, spoken: talk aloud with a character and hear her answer), Images, Autonoma, AI Workers, Site Stats, Movies, JellyShim (our folder-first Jellyfin), Models (every AI model on the machine, by kind, with its maker, size and folder), Minis (two desktop companions: Claudia, showing what Claude Code is doing, and Bit, showing what the AI Workers are doing) and Chron Jobs (the jobs that run on their own each night, starting with the 3 AM memory backup; the AI Workers wait for them).

## Starting it

Run `E:\AppHub\start.bat`. It:

1. Starts the hub's own server on http://127.0.0.1:8700.
2. Starts every app that isn't already running, each in its own window, as before (Local Chat, Voice, Images, Autonoma, the Foreman, Site Stats, Models, the Minis, Chron Jobs). They start without opening their own browser tabs.
3. Opens the hub in your browser.

JellyShim is served by the Jellyfin Windows service, so the hub only shows it; it doesn't start it.

Closing the hub's window stops only the hub page. The apps keep running in their own windows.

## Using it

- Click an app in the panel. Each app stays loaded while you switch, so you come back to it as you left it.
- Green dot: running. Grey dot: off; its pane has a **Start it** button.
- Hover an app for ↻ (reload, with a fresh sign-in) and ↗ (open in its own tab).
- `http://127.0.0.1:8700/#movies` opens straight to an app.
- Open the hub as `127.0.0.1`, not `localhost`, so Autonoma's and the Foreman's sign-in cookies match.

## Files

| File | What it does |
|---|---|
| `start.bat` | The one start button. |
| `hub_server.py` | The hub's web server: the panel, the movie page, and starting apps. |
| `app_registry.py` | Checking whether an app is up, and starting it. |
| `movie_list.py` | Reads the movie data for the Movies page. |
| `data\app_list.json` | **The** app list: where each app lives, its port, and how it starts. It's the only copy, and the hub never writes to it. Edit it to add, remove or move an app; apps are picked by `id`. Set `"autostart": false` on an app to leave it off at start-up. A typo while editing doesn't lose anything: the hub keeps showing the last good list and says what's wrong in its window. |
| `static\` | The panel page. |
| `movies\` | The Movies page. |

## Movies

The Movies page reads `E:\MovieTheaterWithClaudia\data\movies.json`, the recommender's export: your tiers and comments, Claudia's script reads (click a "script n/10" badge), and her picks. Without that file it falls back to `E:\MovieTheaterWithClaudia\start.txt`. The export is a snapshot; ask the recommender session to copy its data folder again when it has new picks.

## The GPU desk: who has the card

One 8 GB card, several apps that want it. The hub keeps one record of who has it (`gpu_desk.py`), and the panel's bottom line shows it: **GPU: Chat, 4 min**, or **free**. Hover it for every lease.

- **What you're using now gets the card.** Chat asks before each reply, Images before each picture or clip, Autonoma before each reply when you're talking with her. The newest one takes it from the last.
- **A picture or clip already drawing finishes.** If you chat during one, Chat goes ahead, slower, beside it; ComfyUI lets go the moment it's done.
- **The AI Workers always yield.** The Foreman asks before each turn and only gets the card while nobody else holds a lease. When someone takes the card, the running worker steps aside and comes back once things go quiet.
- **Autonoma's free time comes before the workers.** A worker running when her free time starts steps aside, and the workers wait until she's done, whatever model she runs on.
- **Autonoma's free time yields to you.** Before each step of her free time she asks politely; while you're using the card she waits (her status line says "Waiting for the GPU: Chat has the GPU"). Waiting isn't a nap she chose, so it doesn't go into her memory, and her free time still ends on time.

- **The yellow "Kick Chat off GPU" button** shows under the GPU line while Chat holds the card. It drops Chat's lease and model now, and unless someone else you're using still holds the card, the Foreman stops waiting out the quiet time and its stepped-aside worker comes straight back.

When the card changes hands the desk makes room: Ollama drops the models the new holder doesn't need, ImageGen's ComfyUI lets go (or finishes first), and the Foreman holds its worker. A lease runs out on its own a few minutes after its app last asked, so a crashed app can't keep the card.

The API, for any app that wants to join in: `POST /api/gpu/claim` `{"app": "chat", "minutes": 5, "keep_models": ["qwen3:14b"]}` (add `"background": true` to ask politely), `POST /api/gpu/renew` `{"app": ..., "minutes": 2}` to keep a lease without taking the card back, `POST /api/gpu/release` `{"app": ...}`, `POST /api/gpu/kick` `{"app": ...}` (the yellow button), and `GET /api/gpu`. Every app falls back to its old ways if the hub isn't running.

How long the workers wait after your last chat message is `pause_workers_minutes` in `E:\local-chat\data\settings.json` (5; 0 turns Chat's asking off), and after your last picture the same setting in `E:\ImageGen\data\settings.json`. A worker stepped aside starts again with its original stop time, unless that time has already passed.
