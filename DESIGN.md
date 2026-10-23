# game-optimiser design (v0.1, 23 Oct 2026, design only, no code yet)

A Linux tool that tunes a game's settings towards a goal ("3840x2160 at 90 fps") or a priority (quality, balanced, fps), the way the NVIDIA app's auto optimise does on Windows, but by editing config files and Steam launch options only and by measuring real frame logs on the real PC.

Every claim below is tagged:
[P] primary source read directly (upstream README, source code, raw config file).
[S] secondary source (search result quoting a page this container could not open).
[V] verified on Matthew's PC on the given date (from the bazzite-system skill).
[U] unverified, to be checked on the PC in Milestone 0 before any code depends on it.
Numbered references are in the Sources section at the end.

## 1. Scope and non-goals

In scope: Steam games on Bazzite, two first adapters (Warframe under Proton, CS2 native), settings in config files, Steam launch options, MangoHud frame logs, a small search that needs few play runs, full backup and one undo per run, no root.

Not in scope for v1: memory reading, injection, overlays other than MangoHud, driver or kernel changes, HDR tuning, changing KDE display modes, non Steam games, Flatpak Steam (the host Steam at ~/.local/share/Steam is the target; the Flatpak path is a detected and refused case in v1).

## 2. Target machine (default hardware profile)

From the bazzite-system skill, verified 23 Oct 2026 [V]: Ryzen 5 3600, RTX 3070 8 GB with the proprietary driver, Resizable BAR on (nvidia-smi BAR1 total 8192 MiB), 16 GB DDR4 3200, KDE Plasma 6.7.5 Wayland, Fedora 44 image bazzite-nvidia stable, Python 3.14.7 at /usr/bin/python3, Steam in /var/home/mpaylor/.local/share/Steam (~777 GiB), AOC AGON AG276UZD 3840x2160 240 Hz on DP-2 at scale 1.5, LG 2560x1440 144 Hz second screen. sudo is denied inside Claude Code on that PC, so the tool must never need it.

The tool re-detects all of this on every run (section 5) and refreshes its cache only when the fingerprint changes, so the profile above is only the default used for planning before the first probe.

## 3. Architecture

Python 3.14, standard library only (tomllib for data files, json, csv, hashlib, shutil, subprocess, statistics, argparse). No pip dependencies so nothing stale is installed on the host. Text VDF (Steam KeyValues) and Warframe's EE.cfg are parsed by small in-repo parsers (section 7) with round trip tests.

```
gopt/                       Python package (CLI entry point: gopt)
  cli.py                    argparse front end, dry run by default
  hwprobe.py                root-free hardware probe + fingerprint cache
  steam.py                  Steam paths, library folders, userdata id, localconfig.vdf, running checks
  adapters/base.py          Adapter interface
  adapters/warframe.py      EE.cfg reader/writer, launch profile experiments
  adapters/cs2.py           cs2_video.txt reader/writer
  parsers/eecfg.py          INI-like EE.cfg, lossless round trip
  parsers/keyvalues.py      Steam text KeyValues (localconfig.vdf, cs2_video.txt), lossless round trip
  mangohud.py               per-game MangoHud config, log discovery, CSV parsing
  metrics.py                avg fps, 1% low (two methods), 0.1% low, spikes, GPU/CPU bound classification
  model.py                  multiplicative cost model + learned costs
  search.py                 ladder bisection with predicted start (section 8)
  safety.py                 backups, manifest, sha256 verify, census, stale plan check, undo
  session.py                one tuning run: plan, apply, measure, adjust, report
data/adapters/warframe.toml Adapter data (section 6)
data/adapters/cs2.toml
tests/                      pytest, fixtures in tests/fixtures (section 11)
scripts/root-steps.sh       exists only if a root step is ever needed; none identified for v1
```

Data flow for one tuning run:

1. probe hardware (cache hit or refresh) and locate the game (section 5).
2. read current settings and launch options, refuse if any file is unreadable or unparseable (hard stop, never treated as empty).
3. build the plan: goal, ladder, predicted starting rung, files to change, backup locations. Write plan.json. In dry run mode stop here and print it.
4. apply one rung (game closed check, backup, write, re-read and sha verify, census).
5. Matthew plays the benchmark bit while MangoHud logs (section 9). The tool waits for the log file to stop growing.
6. compute metrics, update the model, pick the next rung or stop (section 8).
7. report: best rung found, whether the goal was met, every file changed, the undo command.

## 4. Safety rules (apply to every write)

These follow Matthew's standing dev rules (look, report, plan, OK, do, check).

- Dry run by default. `--apply` is required to write, and a typed YES is required for Steam's localconfig.vdf.
- The apply only does what the plan listed. plan.json stores the sha256 of every target file; if a file changed since planning, the apply refuses with "stale plan".
- Game closed check before touching its files: Warframe is `Warframe.x64.exe` and `Launcher.exe` under wine [U: exact process names as seen by `ps`], CS2 is `cs2` from `game/bin/linuxsteamrt64/` [S 29]. Steam itself must be closed before localconfig.vdf is edited, because Steam rewrites it and ignores edits made while running [S 20]. The tool refuses otherwise; it never kills processes.
- Backup before every write: `~/.local/share/game-optimiser/runs/<run-id>/backups/<sha-prefix>_<basename>` with `MANIFEST.json` (original path, backup path, size, mtime, sha256, reason). Copies use `shutil.copy2`, then the copy is re-read and its sha256 compared.
- Verify every write: re-read the file, re-parse it, and assert that the parsed tree differs from the original only in the planned keys.
- Census: file count and total bytes of the target set before and after; any decrease stops the run.
- One undo per run: `gopt undo <run-id>` restores every file in the manifest in reverse order and verifies the sha256. It refuses if the current file's sha256 is neither the tool's last write nor the backup (someone else changed it) unless `--force`. A second undo of the same run is refused (the manifest is marked restored).
- Nothing is deleted by the tool. Removing a launch option means rewriting the string; the old string is in the manifest. Old MangoHud logs are kept.
- Refuse paths outside the Steam root and `~/.config/MangoHud`. Never follow symlinks out of the root.
- No sudo anywhere. If a root step is ever needed it goes in `scripts/root-steps.sh` for Matthew to run once; none is needed for v1.

## 5. Hardware and environment probe (no root)

All commands run as the normal user. Fingerprint = sha256 of the probe JSON minus volatile fields (temperatures, clocks, free memory). The cache lives at `~/.cache/game-optimiser/hardware.json`; the probe always runs (it takes well under a second) and the cache is rewritten only when the fingerprint changes, with the old one kept as `hardware.prev.json`.

| Item | Source (no root) | Status |
|---|---|---|
| CPU model, cores, threads | `/proc/cpuinfo`, `lscpu -J` | standard |
| RAM total | `/proc/meminfo` MemTotal | standard |
| GPU name, VRAM, driver | `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader` (read only queries need no root) [S 22] | V on PC |
| Resizable BAR | `nvidia-smi -q -d MEMORY` BAR1 total 8192 MiB on this PC [V]; fallback `/sys/bus/pci/devices/<gpu>/resource` region 1 size | V |
| Outputs, active mode, refresh, scale | `kscreen-doctor -j` first (exists on Plasma 6.7.5, seen 23 Oct 2026 [V]), `kscreen-doctor -o` text as fallback; both parsers tested on the PC's real output [P 47] | V |
| Connected connectors and modes | `/sys/class/drm/card*-*/{status,modes,edid}`: sizes deduplicated, preferred (native) size first, EDID monitor name; sizes above native are scaler inputs (the LG's EDID offers 3840x2160 over HDMI [V 23 Oct 2026]; its panel is 2560x1440) | V |
| Native or Proton per game | `config/config.vdf` CompatToolMapping per appid [P 51], else the install folder's binaries (Linux ELF executable: native; only `.exe`: Proton), else `compatdata/<appid>` shown as `proton?`. A compatdata folder alone misled the first version: CS2 is native but has one [V 23 Oct 2026] | P |
| Steam root and libraries | `~/.local/share/Steam`, then `steamapps/libraryfolders.vdf` paths [S 19] | S |
| Steam user | `config/loginusers.vdf`, entry with `mostrecent 1`; steamid3 = steamid64 minus 76561197960265728 [S 19] | S |
| Proton version per game | `steamapps/compatdata/<appid>/version` [U] and `config/config.vdf` CompatToolMapping [U] | U |
| MangoHud present | `which mangohud`, `mangohud --version` [U flag]; Bazzite ships MangoHud, vkBasalt and OBS VkCapture by default [P 3] | P |
| Desktop | `XDG_CURRENT_DESKTOP`, `XDG_SESSION_TYPE` (wayland) | standard |

The probe is read only. The tool never calls kscreen-doctor with a mode or scale argument.

## 6. Adapter format

One TOML file per game in `data/adapters/`. Everything the search needs is data, so a new game is a new TOML plus (if its file format is new) a parser.

```toml
[game]
id = "warframe"
name = "Warframe"
appid = 230410
runtime = "proton"                 # or "native"
processes = ["Warframe.x64.exe", "Launcher.exe"]
headroom = 1.25                    # measured fps must exceed goal x headroom when the scene is lighter than real play (section 9)

[files.settings]
path = "{compatdata}/pfx/drive_c/users/steamuser/AppData/Local/Warframe/EE.cfg"
format = "eecfg"
must_be_closed = ["game"]

[files.launch_options]
path = "{userdata}/config/localconfig.vdf"
format = "keyvalues"
keypath = ["UserLocalConfigStore", "Software", "Valve", "Steam", "apps", "{appid}", "LaunchOptions"]   # [S 20] walks Software/Valve/Steam/apps; the root name and the LaunchOptions key are [U]
must_be_closed = ["steam"]

[launch_options]
remove_patterns = ["gamescope"]          # the stopgap Matthew wants gone
allow_add = ["mangohud", "MANGOHUD_CONFIGFILE=", "PROTON_ENABLE_WAYLAND=1", "--in-process-gpu"]
forbid = ["PROTON_USE_WINED3D", "-high", "LD_PRELOAD"]

[[settings]]
key = "Graphics.ShadowQuality"
label = "Shadow Quality"
levels = ["SQ_LOW", "SQ_MEDIUM", "SQ_HIGH", "SQ_LUDICROUS"]   # values [U] except SQ_HIGH [S 11]
cost = [1.00, 1.05, 1.10, 1.20]        # relative frametime multiplier per level, GPU side, initial estimate (ADAPTERS-RESEARCH.md)
cpu = false                            # does the setting also cost CPU time (learned if unknown)
visual = 4                             # 0..5 how much the step from low to high is worth to the eye
source = ["R11", "R13"]
status = "U"

[ladder]
# ordered from lowest quality (rung 0) to highest; each rung names the level of every setting.
# Built by the tool from cost/visual ratios unless pinned here.

[benchmark]
scene = "captura"
instructions = "..."                   # printed to Matthew before each run
duration_s = 60
confirm_duration_s = 90
```

Adapter interface (`adapters/base.py`): `locate(probe) -> paths`, `read() -> Settings`, `write(settings, plan)`, `running() -> bool`, `launch_profile(rung) -> str`, `mangohud_config(run) -> str`, `log_glob(run) -> pattern`, `discover()` (section 7.3).

Learned costs are written to `data/adapters/<game>.learned.json` (dated, per hardware fingerprint) and override the TOML estimates on later runs. The TOML keeps the published estimates and their sources.

## 7. File formats and parsers

### 7.1 Warframe EE.cfg
Location under Proton: `~/.local/share/Steam/steamapps/compatdata/230410/pfx/drive_c/users/steamuser/AppData/Local/Warframe/EE.cfg` [S 9, S 10]. Shape: INI-like sections such as `[Name,/EE/Types/...]` with `Key=Value` lines [S 12]. The graphics section header is [U]; the writer uses the section that already holds a `Graphics.` key, else the one whose header ends in `_Config,/EE/Types/Base/Config`, else refuses. Only non default settings are written; a key left at default disappears from the file, so the writer must add missing keys rather than only editing existing ones [S 11]. Deleting the file resets everything to defaults [S 11]. `Graphics.AutoDetectGraphicsSettings=0` stops the game re-detecting and overwriting edits on launch (wiki lists the key with values 0/1 and default 1; the overwrite claim is from one community guide) [S 11, S 12]. The parser is lossless: unknown lines, order and blank lines are preserved and only planned keys change.

Known keys and values: Graphics.AntiAliasing in {AA_DISABLED, AA_FXAA, AA_SMAA, AA_TEMPORAL} [S 11], Graphics.ShadowQuality=SQ_HIGH and Graphics.TextureQuality=TQ_LOW seen in a player's file [S 11], Graphics.AutoDetectGraphicsSettings 0/1 [S 11]. Everything else in ADAPTERS-RESEARCH.md table W1 is [U] and is learned by `gopt discover` (7.3). The wiki (wiki.warframe.com/w/Settings/Config) could not be opened from this container; Matthew's PC can.

Where the launcher's Graphics API (DirectX 11 or 12) and Graphics Engine (Classic or Enhanced) choices are stored is [U]. Until `discover` finds the key, that rung is "manual": the tool prints the launcher step and asks for confirmation.

### 7.2 CS2 cs2_video.txt
Steam KeyValues text. Location: `{userdata}/730/local/cfg/cs2_video.txt` (Windows path confirmed by players, the Linux userdata equivalent is the same relative path) [S 14]. Full key list read from a real file [P 15]: defaultres, defaultresheight, refreshrate_numerator/denominator, fullscreen, nowindowborder, mat_vsync, monitor_index, cpu_level, gpu_level, gpu_mem_level, videocfg_shadow_quality, videocfg_texture_detail, videocfg_ao_detail, videocfg_particle_detail, videocfg_fsr_detail, videocfg_hdr_detail, videocfg_dynamic_shadows, r_texturefilteringquality, r_low_latency, r_csgo_cmaa_enable, shaderquality, msaa_samples, aspectratiomode, high_dpi, fullscreen_min_on_focus_loss, coop_fullscreen, plus Version, VendorID, DeviceID, Autoconfig. Numeric level meanings are [U] and are confirmed by `discover`. Changing a setting in game overwrites the file, and `-autoconfig` or deleting it resets to defaults [S 14, S 16]. Beside it is `cs2_video.bak` written by the game [S 14]; the tool never touches it.

### 7.3 `gopt discover <game>`: learning keys on the PC
Because the wikis are partly unreachable from the cloud and value names drift between game versions, the adapter learns its key map empirically: the tool snapshots the settings file, asks Matthew to change exactly one named option in the game's menu and quit, then diffs the file and records `menu option -> key, old value, new value` in `data/adapters/<game>.learned.json`. One pass through the Warframe and CS2 video menus (about 15 minutes each) fills the [U] cells. This is a read only operation plus a JSON write in the tool's own data folder.

### 7.4 Steam localconfig.vdf
`{userdata}/config/localconfig.vdf`, text KeyValues. Tools that set launch options walk `Software > Valve > Steam > apps > <appid>` and write `LaunchOptions` under the app [S 20]; the top level key name is [U] and is confirmed on the PC in Milestone 0 by reading the file. Steam must be closed [S 20]. A corrupted file silently resets preferences [S 20].

Default behaviour (changed after the self review, see REVIEW.md): the tool only reads this file. It prints the current launch options and the exact replacement string (`mangohud %command%`, gamescope removed) for Matthew to paste into the game's Properties dialog in Steam, which needs no Steam restart. `--write-launch-options` enables the file edit: typed YES, Steam closed check, backup, a minimal textual edit of one quoted value inside the located block, then re-parse and tree comparison. The launch option is constant across a session because per run MangoHud settings live in MangoHud's per application config file (section 9), not in the launch option.

## 8. Search strategy and why

Each play run costs Matthew about two minutes, so the search is designed around a budget of 3 to 5 runs per game, with a hard `--max-runs` (default 6).

### 8.1 Why not the usual methods
- One factor at a time needs a run per setting (15 to 20 runs). Rejected.
- Bayesian optimisation over a discrete, noisy space with 5 evaluations has nothing to learn from. Rejected.
- Successive halving (Jamieson and Talwalkar 2016 [P 23]) is the right shape for "many candidates, cheap screens, few long confirmations", and the plan borrows its two tier budget (short screening runs, one long confirmation), but the candidates are ordered, which lets us do better than random halving.

### 8.2 The method: ladder bisection with a predicted start
1. Ladder. The adapter's settings are combined into a total order of rungs from lowest to highest quality. Rungs are built greedily: starting from everything low, repeatedly raise the setting with the best visual value per predicted frametime cost. Resolution is fixed by the goal. Upscaling (DLSS or FSR) appears as rungs near the low end for Warframe (DLSS Quality at 4K is a good trade) and is excluded with `--no-upscaling`. Pins (`--pin Graphics.ShadowQuality=SQ_HIGH`) fix a setting across all rungs. Because fps along the ladder is monotone (by construction), "meets the goal" is monotone too, so the best rung is found by bisection: log2(N) runs for N rungs, about 4 for 16 rungs.
2. Run 1, baseline: current settings with the fps cap removed and VSync off. Gives measured fps, the GPU bound or CPU bound classification (median gpu_load above 85 percent while below goal means GPU bound; both low means the game or the API is the limit), and a noise estimate (the run is split in halves; the margin is max(5 percent, the half to half difference)).
3. Model. Predicted frametime = baseline frametime x product over settings of cost(level) / cost(baseline level), GPU side costs only when GPU bound, CPU flagged costs only when CPU bound. Costs start from the published tables in ADAPTERS-RESEARCH.md and are replaced by learned values after each run (least squares over the runs so far; with one run the global scale is fitted, with two the ladder slope).
4. Run 2: the highest rung whose predicted fps is at least goal x headroom x (1 + margin). This is usually within one or two rungs of the answer.
5. Runs 3 and 4: bisection between the last passing and last failing rung, with the model choosing the probe point (secant step) instead of the midpoint when the last prediction error was small.
6. Final run: 90 s confirmation on the chosen rung. If it fails, step down one rung without another run and say so.
Measured pass or fail decides, never the model. If a higher rung passed while a lower one failed (noise), the lower rung is preferred and the inversion is reported. A failing rung is never reported as passing.
7. Stop early when the top rung passes (goal met at max quality) or the bottom rung fails (report the best found and the bound classification). In the CPU bound case the tool says plainly that graphics settings cannot reach the goal and reports what the GPU side headroom is worth instead.

### 8.2a Native first, upscaling only as a fallback (Matthew's decision, 23 Oct 2026)
DLSS is allowed, but native resolution comes first. For an adapter whose upscaling setting names a `fallback` level (Warframe: DLSS Quality; CS2: FSR Quality), the plan holds two ladders: the native ladder (upscaler pinned Off) and the fallback ladder (upscaler pinned at the fallback level, never Balanced or Performance). The search runs the native ladder first; only when no native rung passes (the bottom rung fails) does it move to the fallback ladder with the remaining run budget, starting where the cost model calibrated on the native runs predicts the goal is met. When the baseline shows the goal is far out of reach (nothing in the bracket is predicted to pass) the bottom rung is measured next, so an unreachable native goal costs one run rather than a bisection. A CPU bound result skips the fallback (an upscaler only removes GPU work). `--no-upscaling` keeps the native ladder only; `--pin upscaling=...` replaces both with one ladder. If neither ladder reaches the goal, the fastest measured configuration is left applied (ties go to the fallback ladder's lowest rung). [V on PC: not yet]

Priority mode (quality, balanced, fps) with no numeric goal maps to a goal of the display refresh rate x {0.5, 0.75, 1.0} and a 1 percent low ratio of {0.6, 0.7, 0.8}; the tool prints the derived goal before planning.

### 8.3 Pass criteria
A rung passes when average fps >= goal, 1 percent low (average of the slowest 1 percent of frames, the CapFrameX "x% low average" definition [S 24]) >= 0.75 x goal (`--low-ratio`), and frametime spikes <= 3 per minute, where a spike is a frame longer than max(2 x median frametime, median + 10 ms). The 0.1 percent low and the CapFrameX "integral" variant are reported but not used for the decision.

## 9. Measurement with MangoHud

MangoHud ships on Bazzite [P 3]. The launch option is the constant `mangohud %command%` [P 1]. The per run settings go in MangoHud's per application config file, `~/.config/MangoHud/wine-Warframe.x64.conf` for the Proton app and `~/.config/MangoHud/cs2.conf` for the native binary (README: `~/.config/MangoHud/<application_name>.conf` for native applications, `wine-<application_name>.conf` for wine or Proton apps) [P 1]. That file is backed up and restored like any other. Config written per run:

```
output_folder=/var/home/mpaylor/.local/share/game-optimiser/runs/<run-id>/logs
log_duration=60
autostart_log=0
log_interval=50
toggle_logging=Shift_L+F2
no_display
benchmark_percentiles=97,AVG,1,0.1
log_versioning
```

Facts from the README and logging.cpp [P 1, P 2]: `output_folder` is required for logging; `log_duration` is seconds; `autostart_log` starts after N seconds from init (0 disables); `log_interval` is ms; `toggle_logging` default Shift_L+F2; the CSV is named `<program>_<YYYY-mm-dd_HH-MM-SS>.csv` with a system info row (`os,cpu,gpu,ram,kernel,driver,cpuscheduler`) and per sample columns `fps,frametime,cpu_load,cpu_power,gpu_load,cpu_temp,gpu_temp,gpu_core_clock,gpu_mem_clock,gpu_vram_used,gpu_power,ram_used,swap_used,process_rss,cpu_mhz,elapsed`; frametime is in ms (average fps is computed as 1000 / mean frametime); a `_summary.csv` holds 0.1 percent, 1 percent, 97th percentile and average. In logging.cpp a `log_interval` of 0 starts no logging thread, while README snapshots disagree on the default (0 or 100) [P 2, S 4], so the tool always sets it explicitly to 50 and Milestone 0 confirms that per sample rows appear. The tool parses the frame rows itself and only uses `_summary.csv` as a cross check.

Per game notes:
- Warframe runs through a launcher before `Warframe.x64.exe`; both are under the wrapper, so a second log may appear. The tool picks the log whose program name matches the game binary and has the most rows. MangoHud's per app config name for Proton apps is `wine-<app>.conf` [P 1], but the explicit `MANGOHUD_CONFIGFILE` avoids guessing.
- CS2 is native Vulkan, one process, one log. MangoHud is the same tool behind the Steam Deck's performance overlay [S 5], so it is in wide use with CS2 on Linux; the wrapper is still removed from the launch options at the end of a session by default.

Benchmark scenes (sections per game):
- Warframe scene choice (23 Oct 2026): on the first tuning run the tool offers three heavy, repeatable Captura scenes (Plains Of Eidolon, Orb Vallis, Deimos Cambion Drift: open world landscape tiles per WFCD's item data [P 50], with the time of day and rain sliders fixed every run) or any other owned scene by name, and stores the choice in `warframe.learned.json` (`--scene` changes it). The run instructions name the chosen scene.
- Warframe. No built in benchmark. Captura has 34 scenes, a movable camera while paused, slow motion, and can spawn up to three enemies from completed scans [S 25], so it is repeatable and offline. Proposed scene: one owned Captura scene, standing at a marked spot, one slow full turn, then spawn three enemies and fire for 20 s; 60 s total, same every run. Because missions with four players and heavy effects are heavier than Captura, the adapter applies `headroom = 1.25` by default, calibrated once by letting MangoHud log a real mission (`gopt measure warframe --free-play`) and comparing its average with the Captura run; the learned headroom replaces the default. Reviewers discard the first run after a settings change and expect about 1 percent spread between repeats [S 26]; the tool therefore ignores the first 10 s of every log (shader compile, DX12 shader caching stutter is reported for Warframe [S 27]).
- CS2. Workshop map "CS2 FPS BENCHMARK DUST2" (id 3240880604, by Angel, created 6 May 2024) runs an automated flythrough with grenades, smokes and gunfire, starts automatically on map load, has its last four bots stationary for consistency and prints Avg FPS and P1 (1 percent low) to the console [S 17, S 18]. MangoHud is the primary measurement so both games use one method; the map's console numbers are a cross check, captured with `-condebug` to `console.log` (its CS2 Linux path is [U]) [S 28]. Runs are 60 s to 90 s and the first 10 s are ignored.

Elapsed time within a log is the cumulative sum of frametimes; the `elapsed` column's unit is not documented and is ignored. The tool detects run completion by waiting for the CSV to stop growing for 15 s or for `log_duration` to elapse (or takes `--log-file` in tests and non interactive use), then asks Matthew one question when a launch profile experiment is active (section 10): "fullscreen on the AGON and keyboard working? y/n".

## 10. Warframe launch profile experiments (removing gamescope, fixing the KDE focus bug)

Facts: gamescope presents exactly the resolution it is told regardless of the compositor's scale factor, which is why it works around fractional scaling problems [S 30]. KDE's "Legacy applications (X11)" setting has two modes, "Scaled by the system" (compositor scales XWayland windows, blurry) and "Apply scaling themselves" (added in Plasma 5.26) [S 31]. Wine's Wayland driver marks fullscreen windows and relies on the compositor to scale and place them, and KWin did not implement that yet per a WineHQ report [S 32]. Players report Warframe fullscreen works where borderless did not, with the resolution set explicitly [S 33]; a Plasma 6.3 report describes a frozen screen until a click, only in fullscreen or borderless [S 34]; a Plasma 6.6.2 bug about fullscreen windows staying on top exists [S 35]. GE-Proton 10 exposes `PROTON_ENABLE_WAYLAND=1` (and `PROTON_ENABLE_HDR=1`), Valve does not endorse it [S 36]; stock Proton 10 does not expose the Wayland driver per Wikipedia's table [S 37, treat as U]. Warframe's launcher needs `%command% --in-process-gpu` under the Wayland driver [S 38] and Proton 10.0-2 fixed its title bar [S 39].

Experiments, run in this order, each one its own rung confirmed by Matthew's y/n, each reversible by undo:

| E | Launch options | Game settings | KDE setting (manual) | Expectation |
|---|---|---|---|---|
| E1 | gamescope removed, `mangohud %command%` | Display Mode Borderless Fullscreen, resolution 3840x2160, Max Framerate off | KWin window rule: class `steam_app_230410` (substring), Screen Force = AGON (DP-2) | native borderless on the AGON with a free cursor (Matthew's target, 23 Oct 2026) |
| E1b | as E1 | Display Mode Fullscreen | same rule | only if borderless loses keyboard focus at 150 percent scaling [S 33] |
| E2 | as E1 | as E1 | Legacy applications (X11): Apply scaling themselves | removes compositor scaling of the game window; may make other X11 apps small |
| E3 | `PROTON_ENABLE_WAYLAND=1 MANGOHUD_CONFIGFILE=... mangohud %command% --in-process-gpu` with GE-Proton 10 or newer selected in Steam by Matthew | as E1 | back to default | native Wayland, no XWayland scaling; NVIDIA plus Wine Wayland maturity is the risk |
| E4 | gamescope kept with minimal flags (`-W 3840 -H 2160 -r 240 -f`, never `--force-grab-cursor`) | as E1 | default | fallback only, with Matthew's explicit OK, since he wants gamescope gone |

Seen on the PC, 23 Oct 2026 [V]: with the gamescope stopgap Warframe opened on the LG (HDMI-A-1, left, position 0,0) and `--force-grab-cursor` kept the cursor grabbed. XWayland games tend to open at the origin of the X screen, which is the LG's top left here, hence the KWin rule. KWin stores the rule's screen as an integer index (`screen`, `screenrule` in rulesettings.kcfg [P 48]), so the rule is made in System Settings, whose dropdown shows the output names, not written by the tool. Proton windows carry the class `steam_app_<appid>` [S 49]; confirm with Detect Window Properties. The adapter prints these steps with every plan (`advice` in warframe.toml) and `--force-grab-cursor` is now a forbidden launch token, stripped with a warning.

The first experiment that passes the y/n becomes the launch profile for the rest of the tuning run. E2 is a KDE System Settings change Matthew makes by hand; the tool prints the step and records the answer, it does not edit kwinrc.

## 11. Data files

| File | Purpose |
|---|---|
| `data/adapters/<game>.toml` | adapter definition with published cost estimates and sources |
| `data/adapters/<game>.learned.json` | keys discovered on the PC, learned costs, learned headroom, dated, keyed by hardware fingerprint |
| `~/.config/game-optimiser/config.toml` | Steam root override, default priority, low ratio, keep hud |
| `~/.cache/game-optimiser/hardware.json` (+ `.prev.json`) | probe cache and previous fingerprint |
| `~/.local/share/game-optimiser/runs/<run-id>/plan.json` | goal, ladder, target files with sha256, predicted start |
| `.../runs/<run-id>/backups/` + `MANIFEST.json` | every original file, restore route |
| `.../runs/<run-id>/logs/*.csv` | MangoHud logs, kept |
| `.../runs/<run-id>/metrics.json` | per run metrics and model state |
| `.../runs/<run-id>/game-optimiser-report.txt` + `.log` | report with the tool version on line 1, as every tool of Matthew's does |

Run id is `YYYYMMDD-HHMMSS-<game>`.

## 12. CLI

```
gopt probe [--refresh]                       hardware and environment, prints fingerprint and cache status
gopt games                                   installed supported games, config paths, running state, Proton version
gopt library                                 every installed Steam game from libraryfolders.vdf and appmanifest_*.acf, with adapter status
gopt selftest                                runs the bundled test suite on the PC
gopt show <game>                             current settings, launch options, last run and backups
gopt discover <game>                         learn key names and values by diffing after one in game change (loop)
gopt plan <game> --goal 3840x2160@90 | --priority quality|balanced|fps [--pin KEY=VAL]... [--no-upscaling] [--max-runs 6]
gopt tune <game> (same options) [--apply] [--log-file CSV]... [--yes] [--write-launch-options]
                                             the measure and adjust loop; dry run prints the plan and the first rung only
gopt measure <game> [--free-play]            one logged run at current settings, metrics only, no writes except the MangoHud config
gopt apply <plan.json> --apply               apply a saved plan (typed YES for localconfig.vdf)
gopt undo <run-id> [--force]                 restore every file from the run's manifest, once
gopt restore <run-id>                        alias of undo
gopt report <run-id>                         print the report
```

Exit codes: 0 done, 2 goal not met (best found applied or reported), 3 refused (game running, Steam running, unreadable, stale plan), 4 nothing to do.

## 13. Milestones

Status 23 Oct 2026: milestones 1 to 5 are built and tested in the cloud (88 tests); milestone 0 still has to run on the PC, and the Warframe launch profile experiments E2 and E3 are printed as manual steps rather than automated.

0. Verification on the PC (no writes): read EE.cfg, cs2_video.txt and localconfig.vdf, confirm key names marked [U], confirm MangoHud version and that `log_interval=50` yields per sample rows, confirm process names, find `console.log`. Output: a dated `VERIFIED.md` and updated TOML statuses.
1. Parsers, safety layer, probe, tests with fixtures. No game writes yet.
2. `measure` with MangoHud for both games (manual settings), metrics, report.
3. `discover`, learned keys, `plan` and dry run.
4. `tune` loop for CS2 (simpler: native, one process, benchmark map).
5. `tune` loop for Warframe including the launch profile experiments.

## 14. Test plan with fixtures

Fixtures in `tests/fixtures/` are synthetic files with the real structure (no personal data): `EE.cfg` (sections and Graphics.* lines in the documented shape), `cs2_video.txt` (the key set from the real file), `localconfig.vdf` (a cut down KeyValues tree with two apps), `mangohud_warframe.csv` and `mangohud_cs2.csv` (the exact logging.cpp columns, 1200 rows, one planted 80 ms spike, half to half noise), `loginusers.vdf`, `libraryfolders.vdf`, a fake Steam root built in a temp dir by a fixture factory.

| Test | Asserts |
|---|---|
| parsers round trip | load then dump of each fixture is byte identical |
| targeted edit | changing one key produces a one line diff and the re-parsed tree differs only in that key |
| missing key | writer adds `Graphics.X=...` into the right section when absent |
| unreadable file | chmod 000 or truncated file is a hard stop, exit 3, nothing written |
| game running | fake process list containing `Warframe.x64.exe` or `cs2` refuses writes |
| steam running | fake `steam` process refuses the localconfig edit only |
| backup and restore | sha256 of the backup equals the original, undo restores it, a second undo is refused |
| undo with foreign change | current file differs from both shas, undo refuses without `--force` |
| stale plan | target file modified after planning, apply refuses |
| census | a write that shrinks the target set stops the run |
| dry run | `tune` without `--apply` leaves the fake Steam root byte identical |
| metrics | avg, 1 percent low (both methods), 0.1 percent low and spike count match hand computed values on a 20 row table, including the CapFrameX rounding note |
| bound classification | gpu_load 95 percent -> GPU bound, 40 percent with cpu_load 90 -> CPU bound |
| search simulation | a synthetic fps model (monotone ladder, 3 percent noise) is tuned to a goal in at most 5 runs for 50 random goals, never reports a failing rung as passing |
| launch options | gamescope removed, wrapper added, forbidden tokens rejected, Steam closed check |
| probe cache | same fingerprint keeps the cache file untouched (mtime), a changed GPU driver string refreshes it and keeps `.prev.json` |
| discover | two fixture snapshots differing in one key record the mapping |
| report | line 1 is the version, every changed file and the undo command appear |

Target: run the whole suite in the cloud session (no game needed) and report the count, for example "41/41 green", before anything touches the PC.

## 15. Risks and limits

- Keys and value names marked [U] may differ from the tables; `discover` and Milestone 0 exist for this. Nothing is written to a game file until its keys are confirmed on the PC.
- Warframe rewrites EE.cfg on exit and may re-detect settings; `Graphics.AutoDetectGraphicsSettings=0` is set with the first write [S 12]. CS2 rewrites cs2_video.txt when settings change in game [S 16]. Both are why the game must be closed and why the tool re-reads after each run and warns if the file changed outside the plan.
- Steam must be closed to edit launch options [S 20]; batching to two edits per session keeps this bearable. A corrupted localconfig.vdf resets preferences [S 20], hence minimal textual edits and tree comparison.
- CPU bound games: a Ryzen 5 3600 at 240 Hz in CS2 will often be CPU bound; graphics settings cannot fix that and the tool says so rather than searching.
- 8 GB VRAM at 4K: CS2 Very High used 10 GB at 4K in one test, 6 GB at Low [S 40]; Warframe's Texture Memory High is the equivalent lever. The ladder caps texture settings when `gpu_vram_used` in the log approaches the probe's VRAM total.
- Benchmark representativeness: Captura is lighter than a four player mission; the headroom factor is a stated assumption until calibrated.
- Noise: run to run spread of a few percent is normal [S 26]; the margin rule and the 90 s confirmation cover it, but a one off stutter from shader compilation can still fail a rung; the first 10 s are ignored.
- DirectX 12 under vkd3d-proton on NVIDIA is widely reported slower than Windows [S 41]; the DX11 versus DX12 launcher choice is a manual rung until its key is known.
- MangoHud and anti cheat: config edits and launch options are ordinary; the Vulkan layer is the same component as the Steam Deck overlay. Still, the wrapper is removed after tuning by default.
- The 150 percent scaling bug: E1 to E3 are hypotheses from general KDE and Wine reports, none is a confirmed Warframe fix; E3 depends on GE-Proton and NVIDIA's Wayland maturity.
- HDR is out of scope; `PROTON_ENABLE_HDR` requires the Wayland driver [S 36].
- Wikis blocked from this container (wiki.warframe.com, Steam Community, PCGamingWiki, bo3.gg, docs.bazzite.gg): the [S] facts were taken from search engine quotations and must be re-read on the PC.
- The tool never changes display modes or scale; the game must run on the AGON (DP-2), which the probe reports but cannot enforce.

## Sources

Primary (read directly):
- P1 MangoHud README, raw.githubusercontent.com/flightlessmango/MangoHud/master/README.md (logging options, keybind, launch option, config paths, env vars).
- P2 MangoHud src/logging.cpp, raw.githubusercontent.com/flightlessmango/MangoHud/master/src/logging.cpp (CSV columns, file naming, summary, interval and duration semantics).
- P3 Bazzite README, raw.githubusercontent.com/ublue-os/bazzite/main/README.md ("vkBasalt, MangoHud, and OBS VkCapture installed and available by default").
- P15 real cs2_video.txt, raw.githubusercontent.com/gucu112/cs2-config/master/cs2_video.txt.
- P23 Jamieson and Talwalkar, Non-stochastic Best Arm Identification and Hyperparameter Optimization, PMLR 51:240-248, 2016, proceedings.mlr.press/v51/jamieson16.html.
- P42 Proton README (proton_10.0 branch), raw.githubusercontent.com/ValveSoftware/Proton/proton_10.0/README.md (PROTON_LOG, PROTON_USE_WINED3D, PROTON_NO_ESYNC, user_settings.py; runtime options do not change the prefix).
- P44 Proton launcher script, proton_10.0 branch, raw.githubusercontent.com/ValveSoftware/Proton/proton_10.0/proton (NVAPI on unless `disablenvapi`; copies `nvngx.dll` and `_nvngx.dll` from `<libGLX_nvidia dir>/nvidia/wine` into the prefix's system32; Warframe 230410 is not on the disable list).
- P45 DXVK-NVAPI README, raw.githubusercontent.com/jp7677/dxvk-nvapi/master/README.md ("Proton 9.0 or newer includes DXVK-NVAPI and enables it by default for all titles with a few exceptions"; DLSS for D3D11 and D3D12; Turing or newer on the proprietary driver).
- P46 DXVK-NVAPI wiki, Tips and tricks, raw.githubusercontent.com/wiki/jp7677/dxvk-nvapi/Tips-and-tricks-for-usage-with-DXVK-NVAPI.md (nvngx.dll in system32, copied by Proton; NGXCore FullPath registry key).
- P47 libkscreen ConfigSerializer and kscreen-doctor, raw.githubusercontent.com/KDE/libkscreen/master/src/configserializer.cpp and src/doctor/doctor.cpp (JSON keys `currentModeId`, `preferredModes`, `modes[].refreshRate`; text modes printed `id:WxH@RR.RR` with `*` current and `!` preferred).
- P48 KWin rule settings, raw.githubusercontent.com/KDE/kwin/master/src/rulesettings.kcfg (`wmclass`, `screen` is an Int index, `screenrule`).
- P50 WFCD warframe-items Misc.json, raw.githubusercontent.com/WFCD/warframe-items/master/data/json/Misc.json (Captura scene items and their unique names).
- P51 protontricks steam.py, raw.githubusercontent.com/Matoking/protontricks/master/src/protontricks/steam.py (CompatToolMapping under InstallConfigStore/Software/Valve/Steam in config/config.vdf; "0" is the global default).
- P43 ValvePython vdf README, raw.githubusercontent.com/ValvePython/vdf/master/README.rst (reference for the KeyValues format if a dependency is ever accepted).

Secondary (search engine quotations of pages this container could not open):
- S4 MangoHud README mirrors (log_interval default 0 vs 100), github.com/vuurvoske/MangoHud and git.blob42.xyz/Archives/MangoHud.
- S5 Bazzite forum: MangoHud is the tool behind the Steam Deck performance stats, universal-blue.discourse.group/t/overlay-with-cpu-and-gpu-info/179.
- S6 Bazzite docs, Launch Options and Environment Variables, docs.bazzite.gg/Gaming/launch-options-env-variables/ (%command%, environment.d, MangoHud frame limits in MangoHud.conf or MANGOHUD_CONFIG).
- S9 PCGamingWiki Warframe, pcgamingwiki.com/wiki/Warframe (config under compatdata/230410/pfx, recommends Proton-GE).
- S10 Warframe Forums, Configuration file location on Linux, forums.warframe.com/topic/1419958 (full EE.cfg path under the prefix).
- S11 Warframe Wiki Settings/Config and Settings, wiki.warframe.com/w/Settings/Config, wiki.warframe.com/w/Settings (EE.cfg path, AA values, AutoDetectGraphicsSettings, defaults omitted; forum file showing SQ_HIGH and TQ_LOW: forums.warframe.com/topic/57987).
- S12 Warframe Android EE.cfg guide, publish.obsidian.md/vildavedo/lab/guides/android/warframe-android-better-graphics (section header shape, AutoDetect=0 overwrite note).
- S13 Warframe Wiki Settings/Display, wiki.warframe.com/w/Settings/Display (option list and levels, upscaling, dynamic resolution, flip model note).
- S14 Steam Community CS2 threads on cs2_video.txt location and .bak, steamcommunity.com/app/730/discussions/0/3881597253356393539 and 3821921664845031432.
- S16 Steam guide CS2 Resolution + Refresh Rate Fix, steamcommunity.com/sharedfiles/filedetails/?id=3043638905; Tom's Hardware forum on -autoconfig, forums.tomshardware.com/threads/counter-strike-2-broken-need-help.3847134.
- S17 Workshop changelog, steamcommunity.com/sharedfiles/filedetails/changelog/3240880604 (created 6 May 2024, auto start, stationary bots).
- S18 escorenews, How to test FPS in CS2 using a workshop map, escorenews.com/en/csgo/article/58368 (Avg FPS and P1 in console, run several times).
- S19 Steam userdata and library layout, smithery.ai/skills/fx/steam-linux; steamid3 arithmetic and loginusers mostrecent, steamcommunity.com/discussions/forum/7/1754652753779683755.
- S20 Fincer steam-launchoptions script, fjordtek.com/git/Fincer/steam-launchoptions (localconfig.vdf per account, Steam must be closed); protontweaks steam/mod.rs, ribbon-studios.codeberg.page/protontweaks/src/utils/steam/mod.rs.html (Software > Valve > Steam > apps); corruption report, steamcommunity.com/groups/SteamClientBeta/discussions/0/828934424079311716.
- S21 kscreen-doctor usage, linuxcommandlibrary.com/man/kscreen-doctor; discuss.kde.org/t/kde-6-with-tv-resolution-default-to-4096x2160-24hz/14692.
- S22 nvidia-smi query fields, linuxcommandlibrary.com/man/nvidia-smi and Dell KB 000190243.
- S24 CapFrameX, Explanation of different performance metrics, capframex.com/blog/post/Explanation of different performance metrics (x% low average vs integral, rounding).
- S25 Warframe Wiki Captura, wiki.warframe.com/w/Captura (34 scenes, camera while paused, spawn up to three enemies).
- S26 Benchmark repeatability, tomshardware.com/news/what-makes-a-good-game-benchmark and bit-tech GPU review methodology.
- S27 Warframe DX12 shader caching stutter note (2026), gaming-st.com/pc-games/warframe-pc-settings-open-world-stutter-fps/.
- S28 -condebug behaviour (appends to console.log), community.tcadmin.com/topic/7773-commandline-option-condebug.
- S29 CS2 Linux binary game/bin/linuxsteamrt64/cs2, steamcommunity.com/discussions/forum/14/4361249562712815719 and ionos.co.uk CS2 Linux server guide.
- S30 gamescope presents the given resolution regardless of host scale, linuxfordevices.com/tutorials/linux/games-not-scaling-on-wayland-fix.
- S31 Plasma 5.26 Legacy applications (X11) scaling option, phoronix.com/news/Plasma-5.26-Crisper-XWayland.
- S32 Wine Wayland fullscreen relies on compositor scaling, WineHQ bug 57456 thread, list.winehq.org.
- S33 ProtonDB Warframe reports (fullscreen works where borderless did not; --in-process-gpu; GE recommended), protondb.com/app/230410.
- S34 Manjaro forum, screen freezes until click in fullscreen or borderless under Proton on Plasma 6.3, forum.manjaro.org/t/178025.
- S35 KDE bug 517249 (fullscreen window stays on top, Plasma 6.6.2), bugs.kde.org/show_bug.cgi?id=517249.
- S36 GE-Proton10-1 release notes (PROTON_ENABLE_WAYLAND, PROTON_ENABLE_HDR, not endorsed by Valve), github.com/GloriousEggroll/proton-ge-custom/releases.
- S37 Wikipedia Proton (software) table on Wayland driver access in Proton 10, en.wikipedia.org/wiki/Proton_(software).
- S38 WineHQ bug 57635 thread, Warframe launcher fixed by `%command% --in-process-gpu`, list.winehq.org.
- S39 Proton 10.0-2 RC notes, gamingonlinux.com/2025/07/proton-10-0-2-gets-a-small-release-candidate-update-for-linux-steamos-steam-deck.
- S40 CS2 VRAM by preset at 4K and FSR gains, pcoptimizedsettings.com/counter-strike-2-optimization-2024-cs2-optimized-settings/.
- S49 Proton window class `steam_app_<appid>`, NixOS wiki Steam page, wiki.nixos.org/wiki/Steam (StartupWMClass for Proton games).
- S41 NVIDIA developer forum, DirectX12 performance is terrible on Linux, forums.developer.nvidia.com/t/directx12-performance-is-terrible-on-linux/303207.
