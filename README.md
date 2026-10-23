# game-optimiser

A Linux tool that tunes a Steam game's settings towards an fps goal, the way the NVIDIA app's auto optimise does on Windows, but by editing config files and Steam launch options only and by measuring MangoHud frame logs on the real PC. Dry run by default, every file backed up, one undo per run, no sudo.

Docs: DESIGN-BRIEF.md (the ask), DESIGN.md (architecture), ADAPTERS-RESEARCH.md (per setting cost tables with sources), REVIEW.md (self review), HANDOVER.md (state, commands for the PC, open items).

## Run it (no install, standard library only)

```
python3 -m gopt selftest                      # smoke test over the bundled fixtures
python3 -m gopt probe                         # hardware and display, no root
python3 -m gopt library --games-only          # every installed Steam game
python3 -m gopt games                         # the supported games and their files
python3 -m gopt show warframe                 # current settings and launch options
python3 -m gopt plan warframe --goal 3840x2160@90
python3 -m gopt tune warframe --goal 3840x2160@90 --apply
python3 -m gopt undo <run-id>
```

Full test suite: `python3 -m pytest -q` (pytest needed; the tool itself has no dependencies).

Supported games: Warframe (Proton, EE.cfg) and Counter-Strike 2 (native, cs2_video.txt) with full tuning; Garry's Mod (autoexec.cfg cvars) with tuning; Borderlands 3 (tuning after `discover` confirms its keys), Brotato, Bloons TD 6 and Risk of Rain Returns (measure only until their settings are found on the PC). New games are a TOML file in `data/adapters/`.

Find where any game keeps a setting: `python3 -m gopt find-settings <game or appid>` (read only).

How to use it, in plain English: USER-GUIDE.md. Tests run on GitHub Actions for every push and pull request (Python 3.12 to 3.14).
