# HANDOVER (game-optimiser), 23 Oct 2026

## Summary (5 lines)
1. Built as designed: `python3 -m gopt` with plan, tune (measure and adjust loop), measure, undo, discover, library, games, show, probe, selftest. Standard library only, Python 3.11+.
2. 88 tests green in the cloud (Python 3.13) against fixture copies of EE.cfg, cs2_video.txt, localconfig.vdf, appmanifests and five generated MangoHud CSV logs; a simulated search meets the goal in 4.4 runs on average.
3. Nothing has touched the PC yet. Launch options are printed for pasting into Steam by default; file writes need `--apply`, back up everything, and `undo <run-id>` restores them once.
4. Many EE.cfg key names and the CS2 numeric level meanings are still unverified ([U]); `gopt discover` learns them on the PC by diffing the file after one in game change. Run it before the first real tune.
5. Commands for the PC are below; items that need Matthew, his PC or a decision are listed at the end.

## Goal
Tune a Steam game's settings to an fps goal by editing config files and Steam launch options only, measuring MangoHud logs, with few play runs. Safety: dry run default, backups with sha256, census, stale plan refusal, one undo per run, game and Steam closed checks, no sudo.

## Current state (what exists)
- Design docs: DESIGN.md, ADAPTERS-RESEARCH.md, REVIEW.md (what the self review changed and why).
- Code: `gopt/` (parsers, safety, steam, hwprobe, mangohud, metrics, model, search, adapters, session, cli). Data: `data/adapters/warframe.toml`, `data/adapters/cs2.toml`.
- Tests: `tests/` with fixtures in `tests/fixtures/` (`make_logs.py` regenerates the CSVs).
- Branch `claude/design-brief-9l3xau`, pushed after each milestone.

## Exact commands for the PC (Konsole on the host, no sudo anywhere)

Get the code:
```
cd ~/Documents
git clone -b claude/design-brief-9l3xau https://github.com/RawLettuce/game-optimiser.git
cd ~/Documents/game-optimiser
python3 -m gopt selftest
```

Milestone 0, read only verification (nothing is written):
```
python3 -m gopt probe
python3 -m gopt library --games-only
python3 -m gopt games
python3 -m gopt show warframe
python3 -m gopt show cs2
grep -n "Graphics\." "$HOME/.local/share/Steam/steamapps/compatdata/230410/pfx/drive_c/users/steamuser/AppData/Local/Warframe/EE.cfg"
grep -n "^\[" "$HOME/.local/share/Steam/steamapps/compatdata/230410/pfx/drive_c/users/steamuser/AppData/Local/Warframe/EE.cfg"
grep -n -B2 -A6 '"230410"' "$HOME"/.local/share/Steam/userdata/*/config/localconfig.vdf | head -40
head -3 "$HOME"/.local/share/Steam/userdata/*/config/localconfig.vdf
mangohud --version
kscreen-doctor --json 2>&1 | head -c 400; echo
ls "$HOME/.local/share/Steam/steamapps/compatdata/230410/"
```
While Warframe runs (to confirm process names), in a second Konsole:
```
ps -eo comm,args | grep -iE "warframe|launcher\.exe" | grep -v grep
```
While CS2 runs:
```
ps -eo comm,args | grep -iE "linuxsteamrt64/cs2" | grep -v grep
find "$HOME/.local/share/Steam/steamapps/common/Counter-Strike Global Offensive" -name console.log 2>/dev/null
```

Learn the unverified keys (change one menu option at a time when asked, quit the game, press Enter):
```
python3 -m gopt discover cs2
python3 -m gopt discover warframe
python3 -m gopt show warframe
```

First tuning session (dry run first, then apply). Before `--apply`, paste the printed launch option into Steam > game > Properties > Launch Options (this also removes the gamescope stopgap for Warframe):
```
python3 -m gopt tune cs2 --goal 3840x2160@240
python3 -m gopt tune cs2 --goal 3840x2160@240 --apply
python3 -m gopt tune warframe --goal 3840x2160@90
python3 -m gopt tune warframe --goal 3840x2160@90 --apply
python3 -m gopt report <run-id>
python3 -m gopt undo <run-id>
```
Optional: calibrate the Warframe headroom with one logged real mission: `python3 -m gopt measure warframe --free-play`, then compare with the Captura run in the report (the tool prints both; the learned headroom is written by hand into `data/adapters/warframe.learned.json` as `"headroom": <mission avg / captura avg>` until the automatic step is added).

Full test suite on the PC needs pytest (not installed by default; `python3 -m pytest -q` if present, otherwise `selftest` covers the parsers, logs and adapters).

## How to verify (cloud)
`python3 -m pytest -q` from the repo root: 88 passed, 1 skipped (a permissions test that cannot run as root).

## Next steps (in order)
1. Milestone 0 on the PC (commands above). Record results in a dated `VERIFIED.md`, move facts from [U] to [V] in the TOML files and ADAPTERS-RESEARCH.md.
2. `discover` for both games, commit the `.learned.json` files.
3. First `tune` for CS2 (simpler), then Warframe with the launch profile experiments (DESIGN.md section 10; E2 and E3 are still manual steps the tool prints).
4. Automate the headroom calibration (`measure --free-play` writing `learned.headroom`).
5. Per setting learned costs from runs that differ in one setting (currently the model learns scale and slope only).
6. Next adapters from `gopt library --games-only`.

## Needs Matthew, his PC or a decision (skipped here)
- Every [U] key name and value in ADAPTERS-RESEARCH.md tables W1 and C1 (the `discover` command fills them).
- localconfig.vdf: confirm the top level key `UserLocalConfigStore` and that `LaunchOptions` sits under `apps/<appid>` (only matters with `--write-launch-options`; the default is to paste).
- Process names as seen by `ps` for Warframe under Proton (`Warframe.x64.exe`, `Launcher.exe` assumed).
- CS2 `console.log` path on Linux (the `-condebug` cross check).
- Whether `kscreen-doctor --json` exists on Plasma 6.7.5 (the tool parses `-o` text otherwise).
- Which Proton Warframe uses and whether GE-Proton 10+ is installed (needed for experiment E3, `PROTON_ENABLE_WAYLAND=1`).
- Decision: is DLSS upscaling acceptable for the "3840x2160 at 90" goal? Default yes; `--no-upscaling` refuses it.
- Decision: the Captura scene to standardise on for Warframe (any owned scene; the same one every run).
- Decision: whether the Warframe Max Framerate and VSync keys should be learned by `discover` (they are run overrides with unverified keys; until then the tool prints the manual step).
- The brief asked for Python 3.14 on the host; the cloud has 3.13. The code uses nothing newer than 3.11, so both work, but the PC run is the real test.
- No sudo step exists; `scripts/root-steps.sh` was not created because nothing needs root.
