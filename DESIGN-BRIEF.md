# Design brief: game-optimiser (design only, no code yet)
Design a Linux tool that tunes a game's settings to a goal, like the NVIDIA app's auto-optimise on Windows. Load the matthew-dev-rules and bazzite-system skills first. Research with real sources and cite them; nothing from memory alone. State your model in your first line.

My PC (default hardware profile; the tool re-detects on the PC and only refreshes its cache when hardware changes): Bazzite (Fedora atomic), KDE Plasma 6 Wayland, Steam + Proton, Ryzen 5 3600, RTX 3070 8 GB (proprietary NVIDIA driver, Resizable BAR on), 16 GB DDR4-3200. Main screen AOC AGON AG276UZD 3840x2160 240 Hz HDR on DP-2 (scale 1.5); second screen LG 2560x1440 144 Hz. Steam library ~/.local/share/Steam. Python 3.14 on the host. Games run on the AGON.

What it must do:
- Take a goal ("3840x2160 at 90 fps") or a priority (quality / balanced / fps), per game.
- Per-game adapters: where the settings live (Proton prefix or native), which settings exist, their fps cost and visual impact from real benchmarks/guides, and safe launch options. First games: Warframe (Proton, app 230410, EE.cfg; it currently uses a Gamescope launch option as a stopgap that I want gone; it has a fullscreen/keyboard-focus bug on KDE with 150% scaling) and CS2 (native Linux). Config files and Steam launch options only: no memory reading, injection or anything anti-cheat could object to. Games must be closed while their files are edited.
- Measure-and-adjust loop: apply a preset, I play a short repeatable bit (find a repeatable scene or benchmark map for each game), read the frame log (check current MangoHud logging docs and that Bazzite ships it), compute average fps, 1% lows and frametime spikes, adjust, repeat until the goal is met or report the best found. Keep the number of my play runs small; the search strategy matters.
- Safety: dry run by default, back up every file before changing it with a restore command, refuse on unreadable files, one undo per run.
- Hardware probe without root; no sudo anywhere (root steps, if any, go in one script I run).

Deliver DESIGN.md (architecture, adapter format, search strategy and why, benchmark method per game with sources, data files, CLI, test plan with fixtures, risks and limits) and ADAPTERS-RESEARCH.md (per-setting cost tables for both games, with sources). Commit and push both, then stop and print a 10-line summary for my review. No code yet.
