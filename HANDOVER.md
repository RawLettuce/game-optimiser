# HANDOVER (game-optimiser), 23 Oct 2026, evening

## Summary (5 lines)
1. The four bugs from the first PC run are fixed, each with a regression test built from the PC's real output: the library listed every game twice, CS2 showed as Proton, the probe printed "DP-2: None", and the DRM mode lists repeated (and the LG's 4K entries looked native).
2. The search is now native first; DLSS Quality (FSR Quality for CS2) is only tried when no native rung reaches the goal. Proton 9+ needs nothing extra for DLSS. Warframe advice is native borderless without Gamescope plus a KWin rule pinning it to DP-2. The first Warframe run offers three Captura scenes.
3. Five more adapters: Borderlands 3, Garry's Mod, Brotato, Bloons TD 6, Risk of Rain Returns. Only Garry's Mod tunes straight away. The others measure until their settings are confirmed on the PC with the new read only `find-settings` and `discover`.
4. 127 passed, 1 skipped in the cloud (Python 3.13); `selftest` 20 checks. Nothing has touched the PC since the first read only run.
5. Commands for the PC are below; items that need Matthew, his PC or a decision are listed at the end.

## Goal
Tune a Steam game's settings to an fps goal by editing config files and Steam launch options only, measuring MangoHud logs, with few play runs. Safety: dry run default, backups with sha256, whole file check after every write, census, stale plan refusal, one undo per run, game and Steam closed checks, no sudo.

## Current state
- Branch `claude/game-optimiser-fixes-2827ib` (from `claude/design-brief-9l3xau`), pull request into `main`.
- Code: `gopt/` (parsers eecfg, keyvalues, srccfg, jsontext, winreg; safety, steam, hwprobe, findsettings, mangohud, metrics, model, search, adapters, session, cli). Data: seven TOML files in `data/adapters/`.
- What changed this session and why: DESIGN.md (5, 6, 7.3a, 8.2a, 9, 10, 13) and ADAPTERS-RESEARCH.md (1.5a, 1.7, sections 3 to 7, sources S60 to S81 and P44 to P51).

## Exact commands for the PC (Konsole on the host, no sudo anywhere)

Update the code (first time: clone; afterwards: pull):
```
cd ~/Documents/game-optimiser
git fetch origin
git checkout claude/game-optimiser-fixes-2827ib
git pull
python3 -m gopt selftest
```

Re-check the four fixed bugs (read only):
```
python3 -m gopt library --games-only
python3 -m gopt probe | tail -6
python3 -m gopt games
```
Expected: each game once; CS2 `native`; "gaming display DP-2: 3840x2160@240 (native 3840x2160@60) scale 1.5 HDR on [from kscreen-doctor -j]"; the LG line names the monitor from its EDID and lists 3840x2160 under "also accepts ... (scaler, not native)".

DLSS check (read only):
```
ls /usr/lib64/nvidia/wine/
ls "$HOME/.local/share/Steam/steamapps/compatdata/230410/pfx/drive_c/windows/system32/" | grep -i nvngx
```

Warframe launch options and display (manual, once): paste the printed launch option (`mangohud %command%`, Gamescope gone); in game Display Mode = Borderless Fullscreen at 3840x2160; add the KWin rule that `python3 -m gopt show warframe` prints (Window Rules, class `steam_app_230410`, Screen Force = AGON).

Learn keys and settings files (one in game change each time, quit, press Enter):
```
python3 -m gopt discover cs2
python3 -m gopt discover warframe
python3 -m gopt discover borderlands3
python3 -m gopt find-settings riskofrainreturns
python3 -m gopt find-settings brotato
python3 -m gopt find-settings bloonstd6
```
`find-settings` saves its result under `~/.local/share/game-optimiser/find-settings/`; commit nothing from there, paste the text back.

Tuning (dry run first, then apply):
```
python3 -m gopt tune cs2 --goal 3840x2160@240
python3 -m gopt tune cs2 --goal 3840x2160@240 --apply
python3 -m gopt tune warframe --goal 3840x2160@90 --apply        # asks which Captura scene, once
python3 -m gopt tune garrysmod --goal 3840x2160@240 --apply
python3 -m gopt report <run-id>
python3 -m gopt undo <run-id>
```

## How to verify (cloud)
`python3 -m pytest -q` from the repo root: 127 passed, 1 skipped (a permissions test that cannot run as root).

## Next steps (in order)
1. On the PC: the re-check commands above, then `discover` and `find-settings`; record results in a dated `VERIFIED.md` and move facts from [U] to [V].
2. Fill the Risk of Rain Returns and Brotato settings from `find-settings` (path, format, keys) and the Borderlands 3 keys from `discover` (they land in `borderlands3.learned.json` automatically).
3. First tune of CS2, then Warframe (borderless, then E1b and E3 only if focus breaks), then Garry's Mod.
4. Automate the headroom calibration (`measure --free-play` writing `learned.headroom`).
5. Per setting learned costs from runs that differ in one setting.

## Needs Matthew, his PC or a decision (skipped here)
- Every [U] key, process name and file name in ADAPTERS-RESEARCH.md (tables W1, C1, B1, G1, sections 5 to 7).
- Which of the three Captura scenes he owns and prefers (asked on the first run).
- Whether Warframe offers DLSS under DirectX 11 or only DirectX 12 (look at Options > Display > Upscaling).
- Confirm the KWin rule's window class with Detect Window Properties (`steam_app_230410` is from a secondary source).
- Garry's Mod: confirm native or Proton (the new `library` says which) and the process name; whether to try `gmod_mcore_test 1` (advice only, community reports instability).
- Brotato: turn Steam Cloud off before any write to save_v2.json (none happens until keys are confirmed).
- localconfig.vdf top level key (only for `--write-launch-options`; the default is to paste).
- No sudo step exists; `scripts/root-steps.sh` was not created because nothing needs root.
