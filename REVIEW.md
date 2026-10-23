# Adversarial self-review of DESIGN.md against DESIGN-BRIEF.md (23 Oct 2026)

Method: each line of the brief was checked against the design, then the design was attacked for ways it could fail on the PC, waste play runs or damage files. Findings are listed with the change made. Changes are already applied to DESIGN.md and ADAPTERS-RESEARCH.md.

## Findings that changed the design

1. **Editing localconfig.vdf is the riskiest write and it was on the default path.** Steam must be closed, a corrupt file silently resets preferences, and the top level key is unverified. The brief only requires that launch options be *used*, not that the tool writes them. Change: by default the tool prints the exact launch option string and Matthew pastes it into the game's Properties dialog in Steam (no Steam restart, no file risk). `--write-launch-options` keeps the file edit for when he wants it, with the typed YES, Steam closed check, backup and tree comparison. Removing the gamescope stopgap is the same: the tool shows the current string (read only) and the replacement.

2. **The launch option changed per run (MANGOHUD_CONFIGFILE per run id).** That would mean a Steam edit per run. Change: the launch option is constant (`mangohud %command%`) and the per run settings go in MangoHud's per application config file, `~/.config/MangoHud/wine-Warframe.x64.conf` for Proton apps and `~/.config/MangoHud/cs2.conf` for the native binary, which the README documents [P1]. The tool backs that file up like any other and restores it at the end of the session.

3. **EE.cfg section name was assumed.** Only an Android header (`[Android_Config,/EE/Types/Base/Config]`) was seen. Change: the writer picks the section that already contains a `Graphics.` key, else the section whose header ends in `_Config,/EE/Types/Base/Config`, else refuses. `discover` records the header it saw.

4. **Bisection assumed measured fps is monotone along the ladder.** Noise can make a higher rung pass while a lower one failed. Change: the search uses measured pass or fail only, never the model, to decide the answer; an inversion is treated as noise, the lower rung is preferred, and the confirmation run must pass on the final rung or the tool steps down one rung and says so. A failing rung is never reported as passing.

5. **MangoHud's `elapsed` column units are unknown.** Change: elapsed time is computed as the cumulative sum of frametimes; the `elapsed` column is ignored.

6. **Forcing the fps cap and VSync off needs keys that are unverified for Warframe.** Change: if the key is not yet known (not in the learned map), the tool prints the manual step and asks for confirmation instead of guessing a key name.

7. **No way to test the loop without a game.** Change: `tune` and `measure` accept `--log-file <csv>` (repeatable) to feed logs instead of waiting for MangoHud, and `--yes` to answer the launch profile question. The whole loop is exercised in the test suite with the fixture CSVs.

8. **Python version.** The cloud container has Python 3.13, the PC has 3.14. Change: the code targets 3.11+ (tomllib) and uses nothing newer than 3.13; the test suite runs here and `python3 -m gopt selftest` runs on the PC.

9. **Steam library listing was missing** (asked for in the follow up). Change: `gopt library` reads `libraryfolders.vdf` and every `appmanifest_*.acf`, prints appid, name, library path, size, Proton or native (by `compatdata/<appid>` existing) and whether an adapter exists.

10. **The priority mode goal depended on "the display refresh rate" without saying which display.** Change: the active mode of the output named in config (`display = "DP-2"` default) from the probe; if the probe cannot read it, the tool asks for `--goal` explicitly.

## Findings checked and left as designed

- Dry run default, backups with sha256, one undo per run, refuse unreadable files, census, stale plan: all present and all covered by tests.
- Games closed while their files are edited: present; the tool never kills processes.
- No sudo: no step needs it. `scripts/root-steps.sh` does not exist because nothing goes in it.
- Hardware re-detection with cache refresh only on change: present.
- Few play runs: baseline, predicted rung, one or two bisection steps, confirmation. Budget 3 to 5, hard cap 6.
- Repeatable scene per game: Captura for Warframe (offline, no enemies unless spawned), workshop benchmark map for CS2. The Warframe headroom factor remains a stated assumption until calibrated.
- Benchmark cost tables: honestly weak for Warframe; the loop exists to replace them. Left as is, labelled.

## Things only Matthew or his PC can settle (skipped, listed in HANDOVER.md)

- Every [U] key name and value in ADAPTERS-RESEARCH.md tables W1 and C1.
- The localconfig.vdf top level key and whether `LaunchOptions` sits directly under the appid.
- Process names as seen by `ps` for Warframe under Proton.
- The CS2 `console.log` path on Linux.
- Whether `kscreen-doctor --json` exists on Plasma 6.7.5.
- Whether GE-Proton is installed (for experiment E3) and which Proton Warframe currently uses.
- The decision whether DLSS upscaling counts as acceptable for a "3840x2160 at 90" goal (default yes; `--no-upscaling` to refuse).
