# Adapter research: per setting cost tables (23 Oct 2026)

Companion to DESIGN.md. Tags: [P] primary source read directly, [S] secondary (search quotation of a page this container could not open), [U] unverified, to be confirmed on the PC by `gopt discover` or Milestone 0. "Cost" is the frametime multiplier the tool starts from (1.00 = the lowest level); the tool replaces it with measured values after the first runs, so these numbers decide only where the search starts.

Honest summary first: no controlled one setting at a time benchmark of Warframe exists in any source reachable here, and the only one for CS2 (Thour's test, reported by Bo3.gg) does not state its resolution or GPU. The tables therefore mix measured numbers, published estimates and ranked guesses, each labelled. The measure and adjust loop exists precisely because these tables are weak.

## 1. Warframe (Proton, app 230410)

### 1.1 Where things live
- Settings: `.../steamapps/compatdata/230410/pfx/drive_c/users/steamuser/AppData/Local/Warframe/EE.cfg` [S 10, S 9]. INI-like, `[Section,/EE/Types/...]` headers and `Key=Value` lines [S 12]. Non default keys only; missing key means default [S 11].
- Launcher choices (Graphics API DirectX 11 or 12, Graphics Engine Classic or Enhanced) are made in the launcher's Settings dialog [S 44]; storage key [U].
- Launch options: `localconfig.vdf` (DESIGN.md 7.4). Current stopgap uses gamescope; target state has none.
- Process names: `Warframe.x64.exe`, `Launcher.exe` [U].

### 1.2 Display options and levels (what exists)
From the wiki's Settings/Display page [S 13] and the Settings page [S 11]: Display Mode, Video Resolution, Refresh Rate, Aspect Ratio, Vertical Sync, Max Framerate, Brightness, Contrast, Field of View, Show FPS, Dynamic Lighting, Volumetric Lighting, Local Reflections, Quality Preset, Geometry Quality (Low, Medium, High, Ludicrous), Shadow Quality (Low, Medium, High, Ludicrous), Texture Memory (Low, Medium, High), GPU Particles (Disabled, Low, Medium, High, Ludicrous), Anti-Aliasing (EE.cfg values AA_DISABLED, AA_FXAA, AA_SMAA, AA_TEMPORAL), Upscaling (Off, FSR 2.2, DLSS; DLSS only on RTX cards; quality levels Auto to Ultra Performance; Sharpening slider), Dynamic Resolution (unavailable when upscaling is on), Optimized Flip-Model (not available on DirectX 12). Other toggles named by guides [S 45, S 46]: Depth of Field, Motion Blur, Bloom, Distortions, Glare, Film Grain, Ambient Occlusion, Particle System Quality (older guides) and the launcher's DirectX 12 (Beta) and Enhanced engine.

### 1.3 Table W1: settings, keys, initial costs
Key column: wiki or player file where tagged, otherwise a guess to be confirmed by `discover`.

| Menu option | EE.cfg key (status) | Levels low to high | Cost per level | CPU side | Visual value | Basis |
|---|---|---|---|---|---|---|
| Upscaling | Graphics.Upscaling [U] | Off, DLSS Quality, DLSS Balanced, DLSS Performance | 1.00 at DLSS Quality vs about 1.6 to 1.8 native 4K (render 1440p vs 2160p is 2.25x pixels) | no | DLSS Quality at 4K rated near native by guides [S 46] | pixel ratio; HotHardware tested the 1999 demo at 4K with Quality upscaling, which renders at 2560x1440 [S 47] |
| Dynamic Resolution | Graphics.DynamicResolution [U] | Off, On | not modelled (off during tuning so measurements are stable) | no | 2 | wiki: unavailable with upscaling [S 13] |
| Geometry Quality | Graphics.GeometryQuality [U] | Low, Medium, High, Ludicrous | 1.00, 1.03, 1.06, 1.12 | yes (draw calls) | 3 | ranked guess; no measured source |
| Shadow Quality | Graphics.ShadowQuality (key [S 11], value SQ_HIGH seen; SQ_LOW/SQ_MEDIUM/SQ_LUDICROUS [U]) | SQ_LOW, SQ_MEDIUM, SQ_HIGH, SQ_LUDICROUS | 1.00, 1.05, 1.10, 1.22 | partly | 4 | guides: high shadows cost the most for little gain [S 45]; CS2's measured shadow curve (Low to Very High minus 22 percent) used as the shape |
| Texture Memory | Graphics.TextureQuality (key seen as TQ_LOW [S 11]; menu name differs) | TQ_LOW, TQ_MEDIUM, TQ_HIGH | 1.00, 1.01, 1.02 unless VRAM is full | no | 4 | textures cost little fps until VRAM overflows; 8 GB card at 4K, so the ladder caps this when gpu_vram_used approaches 7.5 GB |
| GPU Particles | Graphics.GpuParticles [U]; Android guide shows a GPUParticlesQuality key with GPQ_LOW to GPQ_LUDICROUS values [S 12] | Disabled, Low, Medium, High, Ludicrous | 1.00, 1.03, 1.06, 1.10, 1.18 | no | 3 | players cut particles first in heavy missions [S 48]; shape from CS2 particle measurements (High minus 4.8 percent, Very High minus 10 percent) |
| Particle System Quality | [U] | Low, Medium | 1.00, 1.04 | yes | 2 | older guide [S 49] |
| Anti-Aliasing | Graphics.AntiAliasing [S 11] | AA_DISABLED, AA_FXAA, AA_SMAA, AA_TEMPORAL | 1.00, 1.01, 1.03, 1.05 | no | 4 (TAA needed for a clean 4K image, also feeds DLSS) | post process AA is cheap on a 3070; estimate |
| Ambient Occlusion | Graphics.AmbientOcclusion [U] | Off, On | 1.00, 1.06 | no | 3 | players report SSAO as a first cut [S 48]; CS2 AO measured minus 4.5 to 4.8 percent |
| Volumetric Lighting | Graphics.VolumetricLighting [U] | Off, On | 1.00, 1.06 | no | 3 | god rays; estimate |
| Local Reflections | Graphics.LocalReflections [U] | Off, On | 1.00, 1.05 | no | 3 | screen space reflections; estimate |
| Dynamic Lighting | Graphics.DynamicLighting [U] | Off, On | 1.00, 1.04 | partly | 3 | estimate |
| Depth of Field | Graphics.DepthOfField [U] | Off, On | 1.00, 1.02 | no | 1 | guides: enable for quality, cheap [S 45] |
| Motion Blur | Graphics.MotionBlur [U] | Off, On | 1.00, 1.02 | no | 0 (most players turn it off) | estimate |
| Bloom, Glare, Distortions, Film Grain | [U] | Off, On | 1.00, 1.01 each | no | 1, 0, 0, 0 | guides turn Distortions, Glare and Film Grain off and keep Bloom [S 45] |
| Max Framerate | Graphics.MaxFramerate [U] | number or off | forced off during runs, restored after | | | measurement needs the cap off |
| Vertical Sync | Graphics.VSync [U] | Off, On | forced off during runs | | | same |
| Display Mode and Resolution | Graphics.Fullscreen [U], Graphics.Resolution [U] | Fullscreen, 3840x2160 explicit | fixed by goal | | | ProtonDB: fullscreen works where borderless did not [S 33] |
| Graphics API (launcher) | [U], manual rung | DirectX 11, DirectX 12 | DX12 on NVIDIA via vkd3d-proton widely reported slower than Windows [S 41]; DX12 shader caching stutter reported [S 27] | | | the tool tests DX11 first, DX12 as a separate manual rung |
| Graphics Engine (launcher) | [U], manual rung | Classic, Enhanced | unknown | | Enhanced is the current renderer | guide: leave Enhanced unless struggling [S 44] |
| AutoDetect | Graphics.AutoDetectGraphicsSettings (0/1, default 1) [S 11] | 0 | set to 0 with the first write so the game stops overwriting edits [S 12] | | | |

### 1.4 Published performance anchors for Warframe
| Source | Hardware | Result | Use |
|---|---|---|---|
| Laptopmedia [S 50] | laptop RTX 3070 130 W, 1080p | Low 311 fps, High 264 fps (High costs about 15 percent) | preset to preset ratio at 1080p |
| Laptopmedia [S 50] | laptop RTX 3070 100 W, 1080p | Low 525 fps, High 374 fps (about 29 percent) | same, different power limit; shows the preset gap grows as the GPU gets tighter |
| HotHardware, Warframe 1999 demo [S 47] | 14 desktop GPUs, 4K fullscreen, High preset, Quality upscaling (DLSS or FSR 2.2, 1440p internal) | RX 7700 XT lands near RTX 3080 (no 3070 figure in the quotation) | a 3070 is below both, so 4K High with DLSS Quality is the realistic region for a 90 fps goal, not native 4K High |
| pcoptimizedsettings [S 51] | RTX 4090, i7-14700KF | 172 fps at 4K, 289 fps at 1440p | even a 4090 is far from 240 at 4K; a 1440p internal resolution is where the fps lives |
| NVIDIA forum thread [S 41] | various, Proton | DX12 games 10 to 30 percent slower than Windows on NVIDIA, anecdotal | why DX11 is tried first |

Prediction for the default goal (3840x2160 at 90 fps) on the RTX 3070: unlikely at native 4K High; plausible with DLSS Quality and shadows at Medium or High, GPU particles Medium, volumetrics on. The baseline run decides.

### 1.5 Benchmark method for Warframe
Captura (34 scenes, pausable camera, up to three spawned enemies) [S 25] as described in DESIGN.md 9: fixed spot, one slow full turn, spawn three enemies, fire for 20 s, 60 s total; ignore the first 10 s; headroom 1.25 until calibrated by one logged real mission. Max Framerate off and VSync off during runs.

### 1.5a Benchmark scene choice (23 Oct 2026)
Three heavy, repeatable Captura scenes are offered on the first run (Matthew picks; the choice is saved): Plains Of Eidolon Scene, Orb Vallis Scene, Deimos Cambion Drift Scene. All three are open world landscape tiles in WFCD's item data (unique names `PhotoboothTile...`, tradable) [P 50]; open world scenes are the heaviest (long draw distance, foliage, fog) and are the only ones with time of day and rain sliders, which are set the same every run [S 25]. Which of them Matthew owns is [U]; any other owned scene can be typed in instead. Dense alternatives if none is owned: Höllvanian Intersection In Winter Scene (1999 city) or Castle Town Scene (Duviri) [P 50].

### 1.6 Safe launch options for Warframe
- Allowed: `MANGOHUD_CONFIGFILE=<path> mangohud %command%` [P 1]; `%command% --in-process-gpu` (launcher fix under the Wine Wayland driver) [S 38]; `PROTON_ENABLE_WAYLAND=1` only with a Proton that exposes it (GE-Proton 10 or newer) [S 36].
- Removed: anything containing `gamescope` (the stopgap).
- Never set: `PROTON_USE_WINED3D` (OpenGL path, slower) [P 42], `LD_PRELOAD` hacks, anything that injects. Proton's documented variables do not change the prefix [P 42], so launch option experiments are fully reversible by rewriting the string.

### 1.7 DLSS under Proton on the NVIDIA proprietary driver (checked 23 Oct 2026)
- Policy: native first, DLSS Quality only when no native rung reaches the goal (DESIGN.md 8.2a).
- Proton 9.0 and newer ship DXVK-NVAPI and enable it by default for all titles except a short list [P 45]; Warframe (230410) is not on the `disablenvapi` list in the Proton 10 launcher script [P 44]. Older Proton needed `PROTON_ENABLE_NVAPI=1`; the plan prints this only when the mapped Proton is older than 9.
- DLSS also needs `nvngx.dll` and `_nvngx.dll` in the prefix's system32. Proton copies both from the driver's `nvidia/wine` folder next to `libGLX_nvidia.so.0` when NVAPI is on [P 44, P 46]. On Bazzite that folder is expected at `/usr/lib64/nvidia/wine/` [U].
- DXVK-NVAPI supports DLSS on D3D11 and D3D12 and needs a Turing or newer GPU on the proprietary driver [P 45]: the RTX 3070 (Ampere) qualifies. DLSS 1.x is not supported under Proton [P 46]; Warframe's DLSS is 2.x or newer [U].
- Whether Warframe offers DLSS in its Upscaling menu under DirectX 11 or only DirectX 12 was not found in any reachable source [U]; check the menu on the PC.
- Checks on the PC: `ls /usr/lib64/nvidia/wine/`, and after one launch `ls "$HOME/.local/share/Steam/steamapps/compatdata/230410/pfx/drive_c/windows/system32/" | grep -i nvngx`.

## 2. Counter-Strike 2 (native Linux, app 730)

### 2.1 Where things live
- Video settings: `{userdata}/730/local/cfg/cs2_video.txt`, with a game written `cs2_video.bak` beside it [S 14]. Steam KeyValues text. Keys from a real file [P 15]. Changing settings in game rewrites the file; `-autoconfig` or deleting it resets to defaults [S 16].
- Binary: `game/bin/linuxsteamrt64/cs2` [S 29]. Native Vulkan; no `-vulkan` flag is needed on the Linux build (the flag advice found is from a 2020 Proton era post) [S 52].
- Console log for the benchmark map's printout: `-condebug` appends to `console.log` [S 28]; CS2 Linux path [U] (expected under `game/csgo/`).

### 2.2 Table C1: cs2_video.txt keys and initial costs
Numeric level meanings marked [U] are confirmed by `discover` (change one menu option, diff the file).

| Menu option | Key [P 15] | Values | Cost per level | CPU side | Visual value | Basis |
|---|---|---|---|---|---|---|
| Resolution | setting.defaultres, setting.defaultresheight | 3840 x 2160 fixed by goal | fixed | | | guides: 1080p to 1280x960 is 44 percent fewer pixels for 30 to 50 percent more fps (estimate) [S 53] |
| Refresh | setting.refreshrate_numerator / denominator | 240000 / 1000 for 240 Hz [U format: a real file shows 165003 / 1000] | | | | [P 15] |
| Display mode | setting.fullscreen, setting.nowindowborder | 1 / 0 fullscreen | | | | [P 15] |
| VSync | setting.mat_vsync | 0 during runs | | | | |
| Global Shadow Quality | setting.videocfg_shadow_quality [U mapping 0..3 = Low..Very High] | Low, Medium, High, Very High | 1.00, 1.09, 1.15, 1.29 | partly | 4 (shadows carry information in CS2) | measured: 986.2 fps Low; Medium 906.5 (minus 8 percent); High 858.5 (minus 12.9 percent); Very High 764.6 (minus 22 percent); 1 percent lows flat at about 270 to 276 [S 54] |
| Dynamic Shadows | setting.videocfg_dynamic_shadows | 0 / 1 (All or Sun only) [U] | 1.00, 1.03 | yes | 2 | estimate |
| Model / Texture Detail | setting.videocfg_texture_detail [U 0..2] | Low, Medium, High | 1.00, 1.01, 1.03 unless VRAM is full | no | 3 | VRAM at 4K: Very High preset 10 GB, High 8.9, Medium 7.3, Low 6 [S 40]; 8 GB card, so cap at Medium unless measured VRAM allows |
| Texture Filtering | setting.r_texturefilteringquality [U 0..5, 5 = Anisotropic 16x] | Bilinear to Anisotropic 16x | 1.00 to 1.01 | no | 3 | negligible impact above 2x per the same test [S 40] |
| Shader Detail | setting.shaderquality [U 0/1] | Low, High | 1.00, 1.057 | no | 2 | measured: High 932.9 fps, minus 5.4 percent [S 54] |
| Particle Detail | setting.videocfg_particle_detail [U 0..3] | Low, Medium, High, Very High | 1.00, 1.02, 1.05, 1.11 | partly | 2 | measured: High 938 (minus 4.8 percent), Very High 886.1 (minus 10 percent) [S 54]; Medium interpolated |
| Ambient Occlusion | setting.videocfg_ao_detail [U 0..2] | Off, Medium, High | 1.00, 1.047, 1.05 | no | 2 | measured: Medium 941.3 (minus 4.5 percent), High 938.1 (minus 4.8 percent) [S 54] |
| High Dynamic Range | setting.videocfg_hdr_detail | -1 / 0 / 1 [U] | 1.00, 1.02 | no | 2 | estimate |
| FidelityFX Super Resolution | setting.videocfg_fsr_detail [U 0..4] | Disabled, Ultra Quality, Quality, Balanced, Performance | at 4K Very High: 180 native, 200, 215, 241 fps (minus 10, 16, 25 percent frametime) [S 40] | no | negative (guides call it grainy at lower resolutions) [S 53]; acceptable at 4K | measured anchors; placed near the bottom of the ladder, excluded by `--no-upscaling` |
| MSAA | setting.msaa_samples | 0, 2, 4, 8 | 1.00, 1.06, 1.12, 1.22 | no | 3 at 4K (2x or 4x) | guide estimate: disabling MSAA recovers 10 to 20 percent [S 53]; Thour's 2025 map tests ran 4x MSAA at 1080p [S 55] |
| CMAA2 | setting.r_csgo_cmaa_enable | 0 / 1 | 1.00, 1.01 | no | 2 | guide: minimal impact [S 56] |
| NVIDIA Reflex | setting.r_low_latency | 0, 1, 2 (Off, Enabled, Enabled + Boost) [U] | no fps cost, lowers latency | | | guides recommend Enabled + Boost [S 56]; kept as is |
| Boost Player Contrast | setting.gpu_level? [U, one guide maps gpu_level to shader quality 0..3 instead [S 57]] | | | | | learned by `discover`; not in the ladder until known |
| cpu_level, gpu_mem_level | setting.cpu_level, setting.gpu_mem_level | 0..3 [U] | | | | engine auto config tiers; left untouched |

### 2.3 Published anchors for CS2
| Source | Hardware | Result | Use |
|---|---|---|---|
| Thour via Bo3.gg [S 54] | not stated in the quotation; Thour's 2025 rig is a 9800X3D with RTX 5070 at 1080p [S 55] | per setting table above; 1 percent lows near 270 to 276 regardless of setting | the only one setting at a time data; the flat lows show the lows are CPU side on that rig |
| pcoptimizedsettings [S 40] | not stated | Low 295 fps vs Very High 179 fps; 4K VRAM by preset; FSR gains at 4K | preset gap and VRAM cap |
| PC Games Hardware [S 58] | CPU and GPU test | CS2 is light on the CPU, high three digit fps on every test machine | still, a Ryzen 5 3600 at 240 Hz is the weak link; the tool's bound check decides |
| csdb guide [S 53] | estimates | resolution 30 to 50 percent, MSAA 10 to 20 percent | rough ordering only |

Prediction for 3840x2160 at 240 fps on a 3600 and 3070: GPU bound at 4K with MSAA and Very High shadows, CPU bound once settings drop. Expect the tool to report a CPU limit somewhere between 150 and 240 fps and to recommend the highest quality rung that still reaches the CPU limit; Matthew then chooses between a lower goal and FSR.

### 2.4 Benchmark method for CS2
Workshop map 3240880604 "CS2 FPS BENCHMARK DUST2" by Angel: automated flythrough with grenades, smokes and gunfire, auto starts on load, last four bots stationary for consistency, prints Avg FPS and P1 to the console [S 17, S 18]. Steps printed by the tool: subscribe once, start the map from Workshop Maps, let it finish, quit to menu. MangoHud log is primary, console numbers (via `-condebug`) are a cross check. Ignore the first 10 s. A reported quirk: one user saw the map's number far below the overlay's with NVIDIA Smooth Motion enabled on Windows [S 18]; not applicable on Linux, but a large disagreement between the two numbers is flagged.

### 2.5 Safe launch options for CS2
- Allowed: `MANGOHUD_CONFIGFILE=<path> mangohud %command%` [P 1]; `-condebug` for the cross check; `-novid` (cosmetic, optional).
- Not added by the tool: `-high`, `-threads`, `+fps_max` (use the in game cap), `-vulkan` (native build is Vulkan already) [S 52], `-autoconfig` (resets settings) [S 16], any `LD_PRELOAD` [S 59].
- VAC: only config files and standard Steam launch options are touched; no injection, no memory access. The MangoHud wrapper is removed after tuning by default.

## 3. Verification list for Milestone 0 (on the PC, read only)
1. `cat` EE.cfg and record every Graphics.* key present; run `gopt discover warframe` for the [U] rows in W1.
2. Open the Warframe launcher, switch Graphics API, quit, diff EE.cfg: find the API and Engine keys.
3. `cat` cs2_video.txt; run `gopt discover cs2` for the numeric mappings in C1.
4. Read localconfig.vdf: confirm the top level key and the `LaunchOptions` key under `apps/230410` and `apps/730`.
5. `mangohud --version`; one 20 s manual log with `log_interval=50`; confirm the columns match P2.
6. `ps -eo comm,args | grep -i -E "warframe|launcher|cs2"` while each game runs: confirm process names.
7. Launch CS2 with `-condebug`, find `console.log`.
8. `kscreen-doctor -o` and `kscreen-doctor --json`: confirm the JSON flag exists on Plasma 6.7.5.
9. `ls steamapps/compatdata/230410/` for a `version` file; read `config/config.vdf` CompatToolMapping for 230410.

## Sources
P1, P2, P3, P15, P42, P44 to P51 as in DESIGN.md.
- S9 to S13, S14, S16, S17, S18, S25, S27, S28, S29, S33, S36, S38, S40, S41 as in DESIGN.md.
- S44 Escapist, Best Graphics Settings for Warframe, escapistmagazine.com/best-graphics-settings-for-warframe/ (launcher: DirectX 12 (Beta), Enhanced engine; Fullscreen).
- S45 dtgre, Best Graphics Settings for Warframe 1999 Patch, dtgre.com/2024/12/best-graphics-settings-for-warframe.html (shadows Medium, VSync off, DLSS Quality, Fullscreen) and Escapist (DoF on, Distortions, Glare, Film Grain off, Bloom on, Dynamic Resolution off).
- S46 1v9.gg Warframe graphics guide and Escapist on DLSS Quality vs Performance.
- S47 HotHardware, Digital Extremes' Warframe 1999 Demo Benchmarked: 14 GPUs Tested, hothardware.com/news/warframe-1999-demo-benchmarked, method via overclockers.ru mirror (4K, High, Quality upscaling at 1440p internal).
- S48 Steam Community Warframe performance thread (SSAO, particles, shadows, tessellation first cuts), steamcommunity.com/app/230410/discussions/0/1741094390462588864.
- S49 Warframe Forums, A Guide In Progress: PC Display Settings, forums.warframe.com/topic/322682 (Particle System Quality Low or Medium).
- S50 Laptopmedia Warframe FPS benchmarks, laptopmedia.com (RTX 3070 130 W vs 85 W; 3070 100 W vs 3060 100 W).
- S51 pcoptimizedsettings, Best Warframe 1999 settings with benchmarks, pcoptimizedsettings.com/best-warframe-1999-settings-pc-with-benchmarks-optimized-for-240-fps/.
- S52 Steam Community CS2 Linux thread (2020, Xubuntu, -vulkan with Proton), steamcommunity.com/app/730/discussions/0/4031349199266029073; Phoronix, Counter-Strike 2 now available with an initial Linux build, phoronix.com/news/Counter-Strike-2-Linux.
- S53 csdb, CS2 FPS Optimization Guide, csdb.gg/guides/fps-optimization-guide (resolution and MSAA estimates, FSR grain).
- S54 Bo3.gg, High Shadows and MSAA Reduce Your FPS in CS2, bo3.gg/news/high-shadows-and-msaa-smoothing-reduce-your-fps-in-cs2 (Thour's per setting numbers; Shader Detail test on Ancient per Thour's X post x.com/ThourCS2/status/1959911437918216201).
- S55 skin.club, CS2 FPS benchmark 2025 map performance (Thour: 9800X3D, RTX 5070, 1080p Low, 4x MSAA, Reflex), community.skin.club/en/news/cs2-fps-benchmark-2025-map-performance.
- S56 esports.net, Best CS2 NVIDIA settings (CMAA2 minimal impact, Reflex Enabled + Boost), esports.net/news/counter-strike/best-cs2-nvidia-settings/.
- S57 Steam guide mapping setting.gpu_level to shader quality 0..3, steamcommunity.com/sharedfiles/filedetails/?id=3307464347.
- S58 PC Games Hardware, Counter-Strike 2 Benchmarks und Fazit, pcgameshardware.de (CS2 light on CPU).
- S59 Steam Community CS2 thread on an LD_PRELOAD launch line for input lag (anecdotal; not adopted), steamcommunity.com/app/730/discussions/0/594020536868179202.
