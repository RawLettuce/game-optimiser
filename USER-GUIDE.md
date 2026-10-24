# game-optimiser: user guide

A plain English guide for Matthew (23 Oct 2026). It does for Linux what the NVIDIA app's auto optimise does on Windows: you give a game and a goal (for example 3840x2160 at 90 fps), it changes the game's settings file, you play a short fixed scene with MangoHud logging, and it keeps the best looking settings that still reach the goal. It only ever edits config files and Steam launch options.

Every command below runs in **Konsole on the host** (not inside a distrobox), from the repo folder:

```
cd ~/Documents/game-optimiser
git pull
python3 -m gopt selftest
```

`selftest` should end with "checks passed". If it does not, stop and send the output.

## How it keeps your files safe

- Nothing is written unless you add `--apply`. Without it every command only reads and prints what it would do.
- Before any write the game must be closed (and Steam too, for the rare launch option write). The tool never closes anything for you; it refuses instead.
- Every file is backed up before it is written, checked byte for byte after the write, and the whole file is compared so that only the planned lines can change. If anything else changed, the write is undone.
- Each tuning session is one run with its own id. `undo <run-id>` puts every file of that run back exactly as it was.
- A file it cannot read or parse is never treated as empty: the tool stops.
- No sudo, no memory reading, no injection. Only files and launch options, so anti cheat has nothing to object to.
- A key the tool is not sure about (marked "guessed key") is never written until `discover` has confirmed it on your PC.

## The commands, in the order you would use them

### 1. probe: what hardware and display it sees
```
python3 -m gopt probe
```
Shows the CPU, GPU, VRAM, driver and every display with its mode. The goal defaults to the gaming display (DP-2, the AGON). It caches the result and only probes again when something changed (`--refresh` forces it).

### 2. library: what is installed
```
python3 -m gopt library --games-only
```
One line per game: appid, Proton or native, size, last played and which adapter (if any) supports it. `python3 -m gopt games` then shows each supported game's settings file, launch options and whether it is running. `python3 -m gopt show <game>` prints the current value of every setting the tool knows for that game.

### 3. find-settings and discover: teach it a game
Some games still need their settings file or key names confirmed on your PC (see the table at the end).

`find-settings` finds the file. It takes a snapshot, you change exactly one option in the game's menu and quit, then press Enter; it prints which file and which lines changed:
```
python3 -m gopt find-settings riskofrain2
```
The result is saved under `~/.local/share/game-optimiser/find-settings/`; paste the text back to Claude.

`discover` learns the key names inside a known file. It asks you to set each option to each level in game, quit, and press Enter; it records which key changed:
```
python3 -m gopt discover witcher3
```
What it learns goes in `data/adapters/<game>.learned.json` and the guessed keys become usable. Change only the option it asks for each time.

### 4. plan: see what it would do (read only)
```
python3 -m gopt plan cs2 --goal 3840x2160@240
```
Prints the goal, the settings ladder (from lowest to highest quality), where it will start, the launch option it wants (paste it into Steam > game > Properties > Launch Options) and any manual steps such as turning VSync off. Useful options: `--priority quality|balanced|fps` instead of a fixed goal, `--pin shadows=High` to keep a setting fixed, `--no-upscaling` to refuse DLSS or FSR (native resolution is always tried first anyway).

### 5. tune: the measure and adjust loop
```
python3 -m gopt tune cs2 --goal 3840x2160@240           # dry run: shows the plan
python3 -m gopt tune cs2 --goal 3840x2160@240 --apply   # does it
```
With `--apply` it writes the starting settings, then for each run it tells you the scene to play. You start the game from Steam, press left Shift+F2 when the scene starts (MangoHud logs for the scene's length, usually 60 s, and stops by itself), quit the game fully and press Enter. It reads the log, decides whether the goal was met and moves up or down the ladder. Usually 3 to 5 runs, never more than 6. At the end it keeps the best rung that passed and writes a report:
```
python3 -m gopt report <run-id>
```

### 6. measure: one logged run, nothing changed
```
python3 -m gopt measure darktide
python3 -m gopt measure deeprockgalactic --free-play
```
Logs one run and prints average fps, 1% lows and frame time spikes. Use it for games that cannot be tuned yet, or with `--free-play` (a 10 minute log of normal play) to see how much heavier real play is than the benchmark scene.

### 7. undo: put everything back
```
python3 -m gopt undo <run-id>
```
Restores every file the run touched from its backups. Each run can be undone once. `python3 -m gopt show <game>` lists the last run ids.

## Exit codes
0 finished; 3 the tool refused (the line starting REFUSED says why: game running, file missing, unreadable file and so on); 4 find-settings saw no change.

## What each game can do today

| Level | Games | What works |
|---|---|---|
| Tunes now | Counter-Strike 2, Garry's Mod | plan, tune, measure, undo |
| Tunes after `discover` | Warframe (keys absent from EE.cfg until changed in game), Borderlands 3, Deep Rock Galactic, The Witcher 3, XCOM 2 | the settings file is known; the key names must be confirmed first; measure works now |
| Measure only, file known | Brotato, Bloons TD 6, Disco Elysium, Dishonored | `show` reads the file; nothing is written |
| Measure only, format not supported yet | Hades, Darktide, Vermintide 2 | measure |
| Needs `find-settings` | Risk of Rain Returns, LEGO The Lord of the Rings, Detroit, Hotline Miami, Lethal Company, Megabonk, Monster Hunter Stories 2, Risk of Rain 2, Slime Rancher, Tactical Breach Wizards, Terraria, Mechanicus | measure |

Every game's details and sources are in ADAPTERS-RESEARCH.md. If a run says "no MangoHud log appeared", the game's process name in its adapter is probably wrong: run `ps -eo comm,args | grep -i <game>` while it is running and send the output.
