"""One tuning session: plan, apply, measure, adjust, report (DESIGN.md sections 3, 8, 9, 12)."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import Refusal, __version__
from .adapters import Adapter
from .mangohud import app_config_path, config_text, parse_log, wait_for_log
from .metrics import Metrics, compute, classify_bound
from .paths import Paths
from .safety import RunDir, write_file, file_fingerprints, check_not_stale, read_text_or_refuse, sha256_of
from .search import Search, build_ladder, describe_rung, nearest_rung
from .steam import Steam, rewrite_launch_options

GOAL_RE = re.compile(r"^(?:(\d{3,4})x(\d{3,4})@)?(\d{2,3}(?:\.\d+)?)$")
PRIORITY = {"quality": (0.5, 0.6), "balanced": (0.75, 0.7), "fps": (1.0, 0.8)}


def parse_goal(goal: str | None, priority: str | None, refresh_hz: int | None) -> tuple[float, float, tuple[int, int] | None, str]:
    """(goal_fps, low_ratio, resolution or None, explanation)."""
    if goal:
        m = GOAL_RE.match(goal.strip().lower().replace(" ", ""))
        if not m:
            raise Refusal(f"goal must look like 3840x2160@90 or 90, got {goal!r}")
        res = (int(m.group(1)), int(m.group(2))) if m.group(1) else None
        return float(m.group(3)), 0.75, res, f"goal {m.group(3)} fps" + (f" at {res[0]}x{res[1]}" if res else "")
    if priority:
        if priority not in PRIORITY:
            raise Refusal(f"priority must be one of {', '.join(PRIORITY)}")
        if not refresh_hz:
            raise Refusal("priority mode needs the display refresh rate from the probe; pass --goal explicitly instead")
        frac, low = PRIORITY[priority]
        fps = round(refresh_hz * frac)
        return float(fps), low, None, f"priority {priority}: {refresh_hz} Hz x {frac} = {fps} fps, 1% low ratio {low}"
    raise Refusal("give --goal (e.g. 3840x2160@90) or --priority quality|balanced|fps")


class Session:
    def __init__(self, adapter: Adapter, steam: Steam, paths: Paths, out=print, ask=input,
                 processes=None, clock=time.time, sleep=time.sleep):
        self.ad = adapter
        self.steam = steam
        self.paths = paths
        self.out = out
        self.ask = ask
        self.processes = processes or Steam.running_processes
        self.clock = clock
        self.sleep = sleep
        self.run: RunDir | None = None
        self.log_lines: list[str] = []

    # ---- helpers ------------------------------------------------------
    def say(self, msg: str):
        self.log_lines.append(f"{time.strftime('%H:%M:%S')} {msg}")
        self.out(msg)
        if self.run is not None:
            try:
                with open(self.run.path / "game-optimiser.log", "a", encoding="utf-8") as f:
                    f.write(self.log_lines[-1] + "\n")
            except OSError:
                pass

    def refuse_if_game_running(self):
        found = Steam.any_running(self.ad.processes, self.processes())
        if found:
            raise Refusal(f"{self.ad.name} is running ({', '.join(found)}); close it fully before its files are edited")

    def refuse_if_steam_running(self):
        if Steam.steam_running(self.processes()):
            raise Refusal("Steam is running; close it fully before localconfig.vdf is edited")

    def settings_path(self) -> Path:
        return self.ad.settings_path(self.steam)

    def mangohud_path(self) -> Path:
        return app_config_path(self.paths.mangohud_dir, self.ad.program, self.ad.runtime == "proton")

    def launch_option_target(self) -> str:
        current = self.steam.get_launch_options(self.ad.appid)
        return rewrite_launch_options(current, self.ad.launch_remove, self.ad.launch_prefix, self.ad.launch_args)

    # ---- plan ---------------------------------------------------------
    def plan(self, goal: str | None, priority: str | None, refresh_hz: int | None, pins: dict[str, str] | None = None,
             no_upscaling: bool = False, max_runs: int = 6, write_launch_options: bool = False,
             vram_mb: int | None = None, active_mode: str | None = None) -> dict:
        goal_fps, low_ratio, res, why = parse_goal(goal, priority, refresh_hz)
        spath = self.settings_path()
        values = self.ad.read_settings(spath)
        levels = self.ad.current_levels(values)
        pin_levels = {}
        for sid, val in (pins or {}).items():
            s = self.ad.setting(sid)
            lv = s.level_of(val)
            if lv is None:
                try:
                    lv = s.labels.index(val)
                except ValueError:
                    raise Refusal(f"pin {sid}={val}: not one of {s.levels} / {s.labels}")
            pin_levels[sid] = lv
        vram_cap = vram_mb * 0.92 if vram_mb else None
        ladder = build_ladder(self.ad.settings, pin_levels, no_upscaling, vram_cap)
        start = nearest_rung(ladder, levels)
        current_lo = self.steam.get_launch_options(self.ad.appid)
        auto_over, manual_over = self.ad.override_changes(values)
        warnings = []
        if res and active_mode and not active_mode.startswith(f"{res[0]}x{res[1]}"):
            warnings.append(f"goal resolution {res[0]}x{res[1]} differs from the active mode {active_mode}; the tool does not change display modes")
        unknown = [s.id for s in self.ad.settings if levels.get(s.id) is None]
        if unknown:
            warnings.append(f"current value unknown for: {', '.join(unknown)} (missing key or unrecognised value); "
                            f"the start rung is estimated from the known ones")
        plan = {
            "version": __version__, "game": self.ad.id, "appid": self.ad.appid, "goal": why, "goal_fps": goal_fps,
            "low_ratio": low_ratio, "headroom": self.ad.headroom, "max_runs": max_runs, "no_upscaling": no_upscaling,
            "pins": pin_levels, "ladder": ladder, "start_idx": start, "current_levels": levels,
            "settings_file": str(spath), "mangohud_config": str(self.mangohud_path()),
            "launch_options_current": current_lo, "launch_options_target": self.launch_option_target(),
            "write_launch_options": write_launch_options, "overrides_auto": auto_over,
            "overrides_manual": [{"key": o.key, "value": o.value, "manual": o.manual, "why": o.why} for o in manual_over],
            "fingerprints": file_fingerprints([spath] + ([self.steam.localconfig_path()] if write_launch_options else [])),
            "warnings": warnings, "benchmark": self.ad.benchmark,
        }
        return plan

    def describe_plan(self, plan: dict) -> str:
        ladder = plan["ladder"]
        lines = [f"Plan for {self.ad.name}: {plan['goal']} (headroom x{plan['headroom']}, 1% low ratio {plan['low_ratio']})",
                 f"  settings file: {plan['settings_file']}",
                 f"  ladder: {len(ladder)} rungs, start at rung {plan['start_idx']} (closest to the current settings)",
                 f"  rung {plan['start_idx']}: {describe_rung(self.ad, ladder[plan['start_idx']])}",
                 f"  launch options now: {plan['launch_options_current'] or '(none)'}",
                 f"  launch options wanted: {plan['launch_options_target']}"
                 + ("  (will be written to localconfig.vdf with Steam closed)" if plan["write_launch_options"]
                    else "  (paste this into Steam > game > Properties > Launch Options)")]
        if plan["overrides_auto"]:
            lines.append("  keys forced for the session: " + ", ".join(f"{k}={v}" for k, v in plan["overrides_auto"].items()))
        for o in plan["overrides_manual"]:
            lines.append(f"  MANUAL (key unverified): {o['manual']}")
        for w in plan["warnings"]:
            lines.append(f"  warning: {w}")
        lines.append(f"  run budget: {plan['max_runs']} play runs of about {plan['benchmark'].get('duration_s', 60)} s")
        return "\n".join(lines)

    # ---- apply --------------------------------------------------------
    def _apply_changes(self, changes: dict[str, str], reason: str) -> str | None:
        if not changes:
            return None
        self.refuse_if_game_running()
        spath = self.settings_path()
        doc = self.ad.load_doc(spath)
        new_doc = self.ad.apply_changes(doc, changes)
        new_text = self.ad.doc_text(new_doc)
        before = self.ad.read_settings(spath)
        sha = write_file(self.run, spath, new_text, reason, self.paths.allowed_write_roots(self.steam.root))
        after = self.ad.read_settings(spath)
        changed = {k for k in set(before) | set(after) if before.get(k) != after.get(k)}
        unexpected = changed - set(changes)
        if unexpected:
            raise Refusal(f"write changed keys outside the plan: {sorted(unexpected)}; the backup is in {self.run.backups}")
        for k, v in changes.items():
            if (after.get(k) or "").strip() != v:
                raise Refusal(f"verification failed: {k} is {after.get(k)!r}, wanted {v!r}")
        self.say(f"  wrote {len(changes)} key(s) to {spath.name}: " + ", ".join(f"{k}={v}" for k, v in changes.items()))
        return sha

    def _write_mangohud_config(self, duration_s: int):
        mp = self.mangohud_path()
        self.paths.mangohud_dir.mkdir(parents=True, exist_ok=True)
        if not mp.exists():
            mp.write_text("# created by game-optimiser; safe to delete\n")
            self.say(f"  created {mp} (undo leaves this one line comment in place)")
        text = config_text(self.run.logs, duration_s)
        write_file(self.run, mp, text, "mangohud per-app config", self.paths.allowed_write_roots(self.steam.root))
        self.say(f"  MangoHud config written: {mp} (logs to {self.run.logs})")

    def _write_launch_options(self, target: str, yes: bool):
        self.refuse_if_steam_running()
        lcp = self.steam.localconfig_path()
        if not yes:
            ans = self.ask(f"Type YES to write launch options for {self.ad.name} into {lcp}: ")
            if ans.strip() != "YES":
                raise Refusal("launch options not written (YES not typed)")
        old, new = self.steam.launch_options_text(self.ad.appid, target)
        write_file(self.run, lcp, new, "launch options", self.paths.allowed_write_roots(self.steam.root), min_ratio=0.9)
        self.say(f"  launch options written: {target}")

    # ---- the loop -----------------------------------------------------
    def tune(self, plan: dict, apply: bool, log_files: list[Path] | None = None, yes: bool = False,
             keep_hud: bool = False) -> int:
        self.out(self.describe_plan(plan))
        if not apply:
            self.out("\nDry run: nothing written. Add --apply to run the loop.")
            return 0
        check_not_stale(plan["fingerprints"])
        self.refuse_if_game_running()
        self.run = RunDir(self.paths.runs, RunDir.new_id(self.ad.id)).create()
        (self.run.path / "plan.json").write_text(json.dumps(plan, indent=2))
        self.say(f"run {self.run.run_id}: folder {self.run.path}")
        ladder = plan["ladder"]
        search = Search(self.ad, ladder, plan["goal_fps"], plan["start_idx"], low_ratio=plan["low_ratio"],
                        max_runs=plan["max_runs"], headroom=plan["headroom"])
        duration = int(plan["benchmark"].get("duration_s", 60))
        self._write_mangohud_config(duration)
        if plan["write_launch_options"]:
            self._write_launch_options(plan["launch_options_target"], yes)
        else:
            self.say(f"  Steam > {self.ad.name} > Properties > Launch Options must be exactly:\n      {plan['launch_options_target']}")
        for o in plan["overrides_manual"]:
            self.say(f"  MANUAL before the first run: {o['manual']}")
        logs = list(log_files or [])
        last_sha = None
        try:
            while (idx := search.next_rung()) is not None:
                rung = ladder[idx]
                values = self.ad.read_settings(self.settings_path())
                changes = dict(plan["overrides_auto"]) if not search.results else {}
                changes.update(self.ad.changes_for_rung(rung, values))
                if last_sha is not None and sha256_of(self.settings_path()) != last_sha:
                    self.say("  note: the settings file changed since the tool last wrote it (the game rewrote it); re-applying")
                sha = self._apply_changes(changes, f"rung {idx}")
                last_sha = sha or sha256_of(self.settings_path())
                confirm = " (confirmation run)" if search._confirm_pending == idx else ""
                self.say(f"\nRun {len(search.results) + 1}/{plan['max_runs']}: rung {idx}/{len(ladder) - 1}{confirm}\n  {describe_rung(self.ad, rung)}")
                m = self._obtain_metrics(logs, duration)
                rr = search.record(idx, m)
                verdict = "PASS" if rr.passed else "FAIL (" + "; ".join(rr.reasons) + ")"
                self.say(f"  avg {m.avg_fps} fps, 1% low {m.low1_avg_fps}, 0.1% low {m.low01_avg_fps}, spikes/min {m.spikes_per_min}, "
                         f"GPU {m.median_gpu_load}% CPU {m.median_cpu_load}% -> {verdict}")
                self._print_new_notes(search)
            self._print_new_notes(search)
            return self._finish(plan, search, keep_hud)
        except Refusal as e:
            self.say(f"REFUSED: {e}")
            self._write_report(plan, search, None, refused=str(e))
            raise

    def _print_new_notes(self, search: Search):
        seen = getattr(self, "_seen_notes", 0)
        for n in search.notes[seen:]:
            self.say(f"  note: {n}")
        self._seen_notes = len(search.notes)

    def _obtain_metrics(self, logs: list[Path], duration: int) -> Metrics:
        if logs:
            path = logs.pop(0)
            self.say(f"  using log file {path}")
        else:
            self.out(self.ad.benchmark.get("instructions", ""))
            self.ask("Press Enter when the game is closed and the run is done (the tool then waits for the log to settle)... ")
            path = wait_for_log(self.run.logs, self.ad.program, since=self.clock() - duration * 4, quiet_s=15.0,
                                timeout_s=120.0, sleep=self.sleep, clock=self.clock)
        parsed = parse_log(path)
        try:
            return compute(parsed["rows"], skip_s=10.0)
        except ValueError as e:
            raise Refusal(f"log {path} unusable: {e}")

    def _finish(self, plan: dict, search: Search, keep_hud: bool) -> int:
        ladder = plan["ladder"]
        final = search.final_rung()
        if final is not None:
            values = self.ad.read_settings(self.settings_path())
            changes = self.ad.changes_for_rung(ladder[final], values)
            if changes:
                self.say(f"\nApplying the final rung {final}: {describe_rung(self.ad, ladder[final])}")
                self._apply_changes(changes, f"final rung {final}")
            self.say(f"\nGOAL MET at rung {final}/{len(ladder) - 1}: {describe_rung(self.ad, ladder[final])}")
            goal_met = True
        else:
            goal_met = False
            best_fail = max(search.results, key=lambda r: r.metrics.avg_fps) if search.results else None
            if best_fail is not None:
                self.say(f"\nGoal not met. Best measured: rung {best_fail.rung_idx} at {best_fail.metrics.avg_fps} fps "
                         f"({describe_rung(self.ad, ladder[best_fail.rung_idx])}). Leaving the lowest measured rung applied.")
                lowest = min(search.results, key=lambda r: r.rung_idx).rung_idx
                values = self.ad.read_settings(self.settings_path())
                ch = self.ad.changes_for_rung(ladder[lowest], values)
                if ch:
                    self._apply_changes(ch, f"best effort rung {lowest}")
        if not keep_hud:
            self._restore_mangohud()
        self._save_learned(search)
        self._write_report(plan, search, final)
        self.say(f"\nUndo everything from this run: python3 -m gopt undo {self.run.run_id}")
        return 0 if goal_met else 2

    def _restore_mangohud(self):
        mp = str(self.mangohud_path())
        for e in self.run.entries():
            if e.original == mp and not e.restored:
                import shutil
                shutil.copy2(e.backup, mp)
                self.say(f"  MangoHud config restored from backup ({mp})")

    def _save_learned(self, search: Search):
        data = dict(self.ad.learned)
        data["model"] = {"bound": search.bound, "scale_ms": search.model.scale, "beta": search.model.beta,
                         "observations": search.model.observations, "date": time.strftime("%Y-%m-%d")}
        try:
            self.ad.save_learned(data)
        except OSError as e:
            self.say(f"  could not save learned model: {e}")

    def _write_report(self, plan: dict, search: Search, final: int | None, refused: str | None = None):
        if self.run is None:
            return
        ladder = plan["ladder"]
        lines = [f"game-optimiser {__version__} report, run {self.run.run_id}, {time.strftime('%Y-%m-%d %H:%M:%S')}",
                 f"game: {self.ad.name}  goal: {plan['goal']}  headroom x{plan['headroom']}",
                 f"bound: {search.bound}  noise margin: {search.margin:.3f}  runs: {len(search.results)}/{plan['max_runs']}", ""]
        for i, r in enumerate(search.results, 1):
            m = r.metrics
            lines.append(f"run {i}: rung {r.rung_idx} {'confirm ' if r.confirm else ''}{'PASS' if r.passed else 'FAIL'} "
                         f"avg {m.avg_fps} low1 {m.low1_avg_fps} low01 {m.low01_avg_fps} spikes/min {m.spikes_per_min} "
                         f"gpu {m.median_gpu_load} cpu {m.median_cpu_load} vram {m.max_vram_mb}")
            lines.append(f"       {describe_rung(self.ad, ladder[r.rung_idx])}")
            if r.reasons:
                lines.append(f"       reasons: {'; '.join(r.reasons)}")
        lines.append("")
        for n in search.notes:
            lines.append(f"note: {n}")
        if refused:
            lines.append(f"REFUSED: {refused}")
        elif final is not None:
            lines.append(f"result: GOAL MET at rung {final}: {describe_rung(self.ad, ladder[final])}")
        else:
            lines.append("result: goal not met; see notes")
        lines.append("")
        lines.append("files changed (backups in MANIFEST.json):")
        for e in self.run.entries():
            lines.append(f"  {e.original}  <- {e.backup}")
        lines.append(f"undo: python3 -m gopt undo {self.run.run_id}")
        (self.run.path / "game-optimiser-report.txt").write_text("\n".join(lines) + "\n")
        (self.run.path / "metrics.json").write_text(json.dumps(
            {"runs": [{"rung": r.rung_idx, "passed": r.passed, "confirm": r.confirm, "metrics": r.metrics.as_dict()} for r in search.results],
             "notes": search.notes, "final": final, "bound": search.bound}, indent=2))

    # ---- measure only -------------------------------------------------
    def measure(self, log_file: Path | None, duration: int = 60, free_play: bool = False) -> Metrics:
        if log_file is None:
            self.refuse_if_game_running()
            self.run = RunDir(self.paths.runs, RunDir.new_id(self.ad.id + "-measure")).create()
            self._write_mangohud_config(duration if not free_play else 600)
            self.say(f"  Steam launch options must contain: {self.launch_option_target()}")
            self.out(self.ad.benchmark.get("instructions", "") if not free_play else "Play normally; Shift+F2 starts the log.")
            self.ask("Press Enter when the game is closed... ")
            path = wait_for_log(self.run.logs, self.ad.program, since=0, quiet_s=15.0, timeout_s=120.0,
                                sleep=self.sleep, clock=self.clock)
            self._restore_mangohud()
        else:
            path = log_file
        parsed = parse_log(path)
        return compute(parsed["rows"], skip_s=10.0)

    # ---- discover -----------------------------------------------------
    @staticmethod
    def discover_diff(before: dict[str, str], after: dict[str, str]) -> dict[str, tuple[str | None, str | None]]:
        """Keys whose values differ between two flat snapshots: key -> (old, new)."""
        out = {}
        for k in set(before) | set(after):
            if before.get(k) != after.get(k):
                out[k] = (before.get(k), after.get(k))
        return out

    def snapshot(self) -> dict[str, str]:
        doc = self.ad.load_doc(self.settings_path())
        if self.ad.settings_format == "eecfg":
            return {k.split("::", 1)[1]: v for k, v in doc.flat().items()}
        obj = doc.to_obj()
        root = obj.get(self.ad.keyroot, obj) if self.ad.keyroot else obj
        return {k: v for k, v in root.items() if isinstance(v, str)}

    def record_discovery(self, setting_id: str, label: str, diff: dict) -> dict:
        """Record one discovered (setting, label) -> (key, value) and update the learned file."""
        if len(diff) != 1:
            raise Refusal(f"expected exactly one changed key, saw {len(diff)}: {sorted(diff)}; change one option at a time")
        key, (old, new) = next(iter(diff.items()))
        data = dict(self.ad.learned)
        disc = data.setdefault("discover", {}).setdefault(setting_id, {"key": key, "values": {}})
        if disc["key"] != key:
            raise Refusal(f"{setting_id} was previously mapped to {disc['key']}, now {key} changed; check the option")
        disc["values"][label] = new
        s = self.ad.setting(setting_id)
        if set(disc["values"]) >= set(s.labels):
            data.setdefault("keys", {})[setting_id] = {"key": key, "levels": [disc["values"][l] for l in s.labels],
                                                       "status": "V", "date": time.strftime("%Y-%m-%d")}
        if self.ad.settings_format == "eecfg":
            doc = self.ad.load_doc(self.settings_path())
            sec = doc.graphics_section()
            if sec is not None:
                data["section"] = sec.header
        self.ad.save_learned(data)
        return data
