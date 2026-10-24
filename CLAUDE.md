# game-optimiser: project rules for Claude (23 Oct 2026, late evening)

Read DESIGN-BRIEF.md (the ask), DESIGN.md (the design) and ADAPTERS-RESEARCH.md (per setting tables) first. Matthew's standing rules in the matthew-dev-rules skill apply; this file adds the project specifics.

## State (23 Oct 2026, late evening)
- Built: `python3 -m gopt` with plan, tune, measure, undo, discover, find-settings, library, games, show, probe, selftest. 147 passed, 1 skipped (`python3 -m pytest -q`; the cloud container needs pytest in a scratch venv). See HANDOVER.md for the PC commands and open items.
- Adapters: cs2, garrysmod (tune); warframe (measure only until `discover`: its EE.cfg has only ten Graphics keys); borderlands3 (tune after discover); brotato, bloonstd6, riskofrainreturns (measure only until find-settings).
- First read only run on the PC 23 Oct 2026 found four bugs, all fixed with regression tests (fixtures from the PC's real kscreen-doctor output). The PC's read only answers (21:15) are in: EE.cfg keys, localconfig.vdf layout, `kscreen-doctor -j`, Proton Experimental 11, no GE-Proton (HANDOVER.md). Next on the PC: `discover warframe`, one Warframe `measure`.
- Decisions (Matthew, 23 Oct 2026): DLSS allowed, native first, DLSS Quality only if native cannot reach the goal; Warframe native borderless without Gamescope, KWin rule to DP-2; Captura scene picked on the first run.
- Tests redirect everything with env vars: GOPT_HOME, GOPT_STEAM_ROOT, GOPT_ADAPTER_DIR. Regenerate CSV fixtures with `python3 tests/fixtures/make_logs.py`. tests/fixtures/FIXTURES.md says which fixtures are real.
- New adapter keys or level values without a source get `guess = true` (never written until `discover` verifies them). A key absent from an existing settings file is never written until `discover` verifies it (`Adapter.needs_discover`), except in files the adapter creates.
- Warframe facts [V 23 Oct 2026]: upscaling is Graphics.UpscaleMethod (UM_DLSS) plus Graphics.UpscaleQuality (UQ_QUALITY), no Graphics.Upscaling; EE.cfg already WindowMode=MODE_BORDERLESS at 3840x2160 with DLSS Quality. localconfig.vdf has a plain "230410" string before apps/230410: KeyValues.find only descends into blocks, and localconfig is read with surrogateescape so binary bytes round trip.

## Rules for this repo
- Python 3.14 standard library only; no pip packages on the host. Own parsers for EE.cfg and Steam KeyValues with lossless round trip tests.
- Dry run by default, `--apply` to write, typed YES for localconfig.vdf. Back up every file before writing, verify sha256 after, one undo per run, census before and after. Refuse unreadable or unparseable files; never treat them as empty.
- Game must be closed to edit its files, Steam must be closed to edit localconfig.vdf. Never kill processes. No sudo anywhere; a root step, if ever needed, goes in scripts/root-steps.sh.
- Config files and Steam launch options only. No memory reading, injection or anything anti cheat could object to.
- Every fact in the docs carries a tag: [P] primary, [S] secondary, [V] verified on the PC with date, [U] unverified. Move a fact from [U] only after it is checked on the PC, and date it.
- Tests run in the cloud with fixtures (tests/fixtures); report the count ("41/41 green") before anything touches the PC.
- British spelling, no dashes as punctuation in documents, no Oxford commas.

## Known blockers from the cloud container (23 Oct 2026)
- These hosts are blocked here: wiki.warframe.com, steamcommunity.com, pcgamingwiki.com, docs.bazzite.gg, bo3.gg, forums.warframe.com, web.archive.org, warframe.fandom.com, pcgamer.com, techspot.com, logicalincrements.com, exputer.com, docs.unity3d.com, api.github.com. GitHub raw works (WFCD data, Proton, KDE and DXVK-NVAPI sources). Facts from the blocked hosts were taken from search engine quotations and are tagged [S].
