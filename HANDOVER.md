# HANDOVER (game-optimiser), 23 Oct 2026, late evening

## Summary (5 lines)
1. Matthew's read only PC checks (23 Oct 2026, about 21:15) answered six open items; each answer is now in the code with a regression test (tests/test_pc_answers.py).
2. Warframe adapter: upscaling is `Graphics.UpscaleMethod` plus companion `Graphics.UpscaleQuality` (UM_DLSS + UQ_QUALITY = DLSS Quality); `Graphics.Upscaling` is gone. EE.cfg is already MODE_BORDERLESS at 3840x2160 with DLSS Quality. Every key not in the file waits for `discover`, so Warframe is measure only until then.
3. localconfig.vdf: path lookups only descend into blocks, so the plain "230410" string before apps/230410 is skipped; the file is read with surrogateescape so binary bytes are written back byte for byte.
4. `kscreen-doctor -j` is the probe's first call (it was already; now pinned by a test); the LG's "max" is its fastest native mode and the HDMI 4K modes are listed as scaler modes. Proton Experimental 11 and the absence of GE-Proton are recorded and printed by `show` and `games`.
5. 147 passed, 1 skipped in the cloud (Python 3.13); `selftest` 20 checks. Nothing has touched the PC since the read only checks.

## Goal
Tune a Steam game's settings to an fps goal by editing config files and Steam launch options only, measuring MangoHud logs, with few play runs. Safety: dry run default, backups with sha256, whole file check after every write, census, stale plan refusal, one undo per run, game and Steam closed checks, no sudo.

## Current state
- Branch `claude/game-optimiser-fixes-2827ib`, pull request #1 into `main`.
- Code: `gopt/` (parsers eecfg, keyvalues, srccfg, jsontext, winreg; safety, steam, hwprobe, findsettings, mangohud, metrics, model, search, adapters, session, cli). Data: seven TOML files in `data/adapters/`.
- New this session: `Setting.extra_keys` (companion keys per level), `Adapter.needs_discover` (absent keys wait for discover), discover handles companion keys, asks "did the menu already show it?" when nothing changed and retries missing levels once, `Steam.compat_tools()`, `KeyValues.find` prefers blocks, `read_text_or_refuse(errors=...)`, probe `max_mode` at the native size plus `scaler_modes`.

## PC answers, 23 Oct 2026 (read only)
| Open item | Answer | Where it went |
|---|---|---|
| Which Proton, GE-Proton? | Proton Experimental (prefix 11.0-100, build experimental-11.0-20261014), no CompatToolMapping, compatibilitytools.d empty: GE-Proton not installed | ADAPTERS-RESEARCH 1.6, 1.7; DESIGN 10 (E3); `show`/`games` print it |
| localconfig.vdf layout | Top key `UserLocalConfigStore`; LaunchOptions at Software/Valve/Steam/apps/230410 (line 587); a plain "230410" string earlier (line 373) | DESIGN 6 and 7.4; parser fix |
| `kscreen-doctor --json` | `-j` and `--json` work; keys features, outputs, screen, tabletModeAvailable, tabletModeEngaged; DP-2 mode 34 3840x2160@240 scale 1.5; HDMI-A-1 mode 7 2560x1440@144 scale 1 | DESIGN 5 (already [V]); test |
| EE.cfg keys | Ten Graphics keys only; UpscaleMethod/UpscaleQuality, WindowMode=MODE_BORDERLESS, FullScreenSizeX/Y=3840/2160; no MaxFramerate, VSync or quality keys | warframe.toml; ADAPTERS-RESEARCH W1; DESIGN 7.1 |
| CS2 console.log | Not present until a `-condebug` run; expected `<install>/game/csgo/console.log`; CS2 native | ADAPTERS-RESEARCH 2; DESIGN 9 |
| Warframe process names | Warframe.x64.exe, Launcher.exe, RemoteCrashSender.exe exist in the install; live names not seen | ADAPTERS-RESEARCH 1.1 |

## Still open (needs Matthew, his PC or a decision)
- The value Warframe writes for Upscaling Off (UM_NONE is a guess): `discover warframe` records it. Until then upscaling is not tuned.
- Every other Warframe Graphics key (Geometry, Shadow, Texture, GPU Particles, AA, AO, Volumetric, Reflections, Dynamic Lighting, DoF, Bloom) and the Max Framerate and VSync keys: absent from EE.cfg until changed in game; `discover warframe`.
- Live process names under `ps` while Warframe and CS2 run.
- CS2 `console.log` path: run CS2 once with `-condebug`.
- Which Captura scene he owns and prefers (asked on the first measure or tune).
- Whether Warframe offers DLSS under DirectX 11 or only DirectX 12 (it is on now; which API the launcher uses is unknown).
- KWin rule window class (`steam_app_230410` is from a secondary source): Detect Window Properties.
- E3 (Wine Wayland driver) needs GE-Proton installed, or a check whether Proton Experimental 11 exposes the Wayland driver [U]. Decision for Matthew, only if borderless loses focus.
- Garry's Mod native or Proton; Brotato Steam Cloud off before any write; CS2, Borderlands 3, Brotato, Bloons TD 6, Risk of Rain Returns discover and find-settings as before.
- No sudo step exists; `scripts/root-steps.sh` was not created because nothing needs root.

## First real run on the PC (Konsole on the host, no sudo)
1. Update the code and check it:
```
cd ~/Documents/game-optimiser
git fetch origin
git checkout claude/game-optimiser-fixes-2827ib
git pull
python3 -m gopt selftest
python3 -m gopt show warframe
```
   Expect: Upscaling `UM_DLSS` / `DLSS Quality` with `UQ_QUALITY`; the other settings "not in the file: not tuned until discover"; "Proton prefix version: 11.0-100"; "GE-Proton is not installed".
2. Discover (reads EE.cfg, writes only `data/adapters/warframe.learned.json`):
```
python3 -m gopt discover warframe
```
   For each prompt: change that one option in game, quit Warframe fully, press Enter. Upscaling first: for "DLSS Quality" change nothing, press Enter, answer `y`; for "Off (native)" set Upscaling Off. `s` skips a setting, `q` stops (progress is saved per level, run it again to continue). Then paste: `cat data/adapters/warframe.learned.json`
3. Launch options and window rule (manual, once): Steam > Warframe > Properties > Launch Options = `mangohud %command%` (Gamescope removed); add the KWin rule that `show warframe` prints.
4. One measure run (writes only `~/.config/MangoHud/wine-Warframe.x64.conf` for the run, restored afterwards; no game file is touched):
```
python3 -m gopt measure warframe
```
   Pick the Captura scene, follow the printed steps (Shift+F2 starts the 60 s log), quit the game, press Enter. Paste the printed metrics.

## How to verify (cloud)
`python3 -m pytest -q` from the repo root (pytest in a scratch venv; nothing installed on the host): 147 passed, 1 skipped (a permissions test that cannot run as root).

## Next steps (in order)
1. On the PC: the four steps above; record results in a dated `VERIFIED.md` and move facts from [U] to [V].
2. First Warframe tune once upscaling and the main quality keys are discovered: `python3 -m gopt tune warframe --goal 3840x2160@90` (dry run), then `--apply`.
3. CS2: `discover cs2`, then tune; Garry's Mod tune; the find-settings games.
4. Automate the headroom calibration (`measure --free-play` writing `learned.headroom`).
5. Per setting learned costs from runs that differ in one setting.

## more-adapters (23 Oct 2026, late; branch `claude/more-adapters-z901je`, based on PR #1's branch)

### What this branch adds
1. Nineteen adapters, one for every installed game that had none (Wallpaper Engine, Proton, runtimes and redistributables skipped): LEGO The Lord of the Rings, Deep Rock Galactic, Detroit, Disco Elysium, Dishonored, Hades, Hotline Miami, Lethal Company, Megabonk, Monster Hunter Stories 2, Risk of Rain 2, Slime Rancher, Tactical Breach Wizards, Terraria, The Witcher 3, Darktide, Mechanicus, Vermintide 2, XCOM 2. Each TOML has a `confidence` tag; research and sources in ADAPTERS-RESEARCH.md section 9 (S82 to S103).
2. `tests/test_more_adapters.py` (46 tests) and five synthetic fixtures (tests/fixtures/FIXTURES.md says what they are).
3. GitHub Actions CI (`.github/workflows/tests.yml`): the full suite plus `selftest` on Python 3.12, 3.13 and 3.14 for every push and pull request. Only pytest is installed, and only in CI.
4. A Python 3.12 fix: `Path.read_text(newline=)` exists only from 3.13, so `selftest` and nine tests failed on 3.12; they now read bytes and decode.
5. USER-GUIDE.md: the plain English guide (probe, library, discover, plan, tune, measure, undo, safety).
6. Files of PR #1 touched: `gopt/cli.py` (two selftest lines), `tests/test_parsers.py` and `tests/test_new_adapters.py` (the same read change), `tests/test_adapters.py` (the adapter list check is now "the original seven are present"), ADAPTERS-RESEARCH.md (section 9, item 11 in section 8, sources), FIXTURES.md, this section. No parser, search, Warframe or CS2 code changed.

### State
- After merging PR #1's latest commit (83b7d5b, PC answers): 193 passed, 1 skipped on Python 3.13 and on 3.12 (the skipped test needs a non root user; it passes as `nobody`, 194/194). `selftest` 39 checks. CI green on GitHub Actions.
- Confidence: tunes after `discover` (file known, keys guessed): Deep Rock Galactic, The Witcher 3, XCOM 2. Measure only with the file known: Disco Elysium, Dishonored. Measure only because the format (SJSON) is unsupported: Hades, Darktide, Vermintide 2. Needs `find-settings`: the other eleven.

### Exact commands for the PC (Konsole on the host, after PR #1's commands; all read only)
```
cd ~/Documents/game-optimiser
git fetch origin
git checkout claude/more-adapters-z901je
python3 -m gopt selftest
python3 -m gopt library --games-only
python3 -m gopt games
```
Expected: `library` names an adapter on every game row except Wallpaper Engine; `games` prints no WARNING line about the runtime.

Then, for each game you want to tune, after launching it once:
```
python3 -m gopt discover deeprockgalactic
python3 -m gopt discover witcher3
python3 -m gopt discover xcom2
python3 -m gopt find-settings riskofrain2        # likewise for any "needs discover: file" game
```
While each new game runs: `ps -eo comm,args | grep -i <name>` and paste it back (every process name is [U]).

### Next steps
1. On the PC: the commands above; record results in VERIFIED.md and move facts from [U] to [V].
2. Correct each adapter's `program` from the `ps` output first: MangoHud's per app config file (`wine-<program>.conf`) and the log search both use it, so a wrong name means no log.
3. Add a `{home}` path placeholder and the native games' data folders as write roots (Terraria config.json, Unity prefs), once PR #1 has merged. Then Terraria can tune.
4. An SJSON reader (Stingray user_settings.config for Darktide and Vermintide 2, Hades' Profile1.sjson), with lossless round trip tests like the other parsers.

### Needs Matthew, his PC or a decision (skipped here)
- The Witcher 3: DirectX 11 or 12. The adapter edits dx12user.settings (the default; a report says DirectX 12 is about half as fast under Proton and DirectX 11 is going away). If you play DirectX 11, the path changes to user.settings.
- XCOM 2: base game or War of the Chosen (different My Games folder [U]).
- Every [U] in ADAPTERS-RESEARCH.md section 9, above all the process names and the Disco Elysium company folder spelling.
- Deep Rock Galactic: DirectX 11 or 12 at launch (players disagree on which is faster).
- Steam Cloud: Disco Elysium, Slime Rancher, Tactical Breach Wizards and Darktide sync settings; turn it off for a game before any future write to its files.
- The branch is `claude/more-adapters-z901je` (the session's assigned branch); `claude/more-adapters` on GitHub still points at PR #1's last commit.
