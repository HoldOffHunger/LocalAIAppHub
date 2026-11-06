# Minis

Two small companions floating on top of everything, so you can watch a film or play a game and glance down to see what's going on: **Claudia**, showing what Claude Code is doing, and **Bit**, showing what the AI Workers are doing. One program runs both (`ClaudiaMini.exe`); the hub's 🐾 Minis pane has a panel for each.

## Bit

Bit floats just left of Claudia and keeps an eye on the card. Every two seconds he asks the hub's GPU desk (`/api/gpu` on 8700) and Ollama (`/api/ps` on 11434):

| He says | Shape | When |
|---|---|---|
| Undecided | Pale blue, many-faceted (an icosahedron), turning slowly | Nothing loaded in Ollama |
| No | Red spiky star, shaking his head now and then | A model is loaded, but no worker's turn is running (Local Chat's or Autonoma's models count too) |
| Yes | Yellow octahedron, bouncing and pulsing | The AI Workers hold a lease at the GPU desk, which they do for every turn |

He's drawn live as flat-shaded polyhedra with glowing edges, rendered at twice the size and averaged, so there are no sprites and he's sharp at any size. When he changes his mind the old shape shrinks away and the new one pops out. Drag him anywhere; double-click him for the App Hub, opened on the AI Workers' pane; right-click him for size (Small 64, Medium 96, Large 128, Huge 176), the Minis page, hiding him, restarting and quitting. Claudia's right-click menu has **Show Bit** to bring him back. His size, position and whether he's shown are `bit_size`, `bit_x`, `bit_y` and `bit_shown` in `data\settings.json`.

## Claudia

## Starting her

Run `start.bat`, or press Start on her pane in the hub. She appears in the bottom-right corner. Drag her anywhere; double-click her to bring the Claude app up and into focus (or open it, if it's closed to the tray); right-click her for size, the chime, click-through, her page, restarting and quitting. Her page is http://127.0.0.1:8780/ (her AppHub pane), with the same switches, a Restart button, the sessions she's watching, and buttons to preview each pose. A restart reloads her sprites, so it's how new art reaches her.

## What she shows

Every local Claude Code session (the desktop app's Code tab, the terminal, the IDE extensions) reports to her through the `claudia-mini` plugin. With several sessions open, the most important state wins:

| State | Pose | When |
|---|---|---|
| Needs you | Needs-You | Claude is waiting on a permission or a question. Chimes once |
| Stuck | Needs-You | The turn stopped on an API error. Chimes once |
| Out of mana | Asleep | Usage limit or billing stopped the turn. Chimes once |
| Oops | Oops | 3 failed tools within 2 minutes, or Claude reporting her own mistake. Lasts 20 seconds |
| Casting a spell | Spellcasting | Claude is working |
| Done | Done | Claude finished. Relaxes into Idle after 90 seconds |
| Idle | Idle | A session is open and waiting for your next prompt. Dozes into Asleep after 30 minutes |
| Asleep | Asleep | No sessions open, or all of them long quiet |

The timings and the Oops threshold are in `data\settings.json` (written the first time you change a setting; restart her after editing it by hand).

Cloud sessions and claude.ai project threads run off this machine, so they can't move her.

## Her art

`tools\make_sprites.py` turns the generated poses into pixel art: cuts away the backdrop, shrinks to true pixels (99 x 117), and draws every frame from one shared 48-colour palette. Which folder feeds which state, and the sprite width and palette size, are in `data\sprite_sources.json`. Rerun the script and restart her after changing any art.

Pictures with a whole scene behind her (the sleeping ones were a couch, a park bench, a bed) go through `tools\cut_backgrounds.py` first. It uses the BiRefNet background-removal model, from its own Python environment at `D:\venvs\claudia-rembg` with the model in `E:\AIModels\rembg`, and writes transparent PNGs. `make_sprites.py` uses those as they are, crops each to her, and stands her on the bottom edge. The Asleep poses come from `output\claudia\asleep`, made this way from the Grok Asleep folder.

## Files

| File | What it does |
|---|---|
| `ClaudiaMini.exe` | The Minis: both windows, the UDP ear on port 8781, Bit's watching thread, and the page on port 8780 |
| `src\overlay.cpp` | Its source |
| `src\signal.cpp` | `claudia-signal.exe`, which the plugin's hooks run: one UDP packet per event, then it exits |
| `build.bat` | Builds both with Visual Studio 2022 and copies `claudia-signal.exe` into the plugin |
| `marketplace\` | A local plugin marketplace holding the `claudia-mini` plugin. Claude Code reads it straight from here, so a rebuild reaches new sessions without reinstalling |
| `web\index.html` | The Minis page, with a Claudia panel and a Bit panel |
| `tools\make_sprites.py` | Bakes the pose folders into `art\sprites\` |
| `tools\cut_backgrounds.py` | Cuts her out of pictures with a scene behind her |
| `art\sprites\` | The baked sprites, one folder per pose set |

The plugin was installed with `claude plugin marketplace add E:\AppHub\ClaudiaMini\marketplace` and `claude plugin install claudia-mini@claudia-local`; it sits in `~\.claude\settings.json` as `extraKnownMarketplaces` and `enabledPlugins`.
