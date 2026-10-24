"""Command line front end. Dry run by default. Exit codes: 0 done, 2 goal not met, 3 refused, 4 nothing to do."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from . import Refusal, __version__
from .adapters import Adapter
from . import hwprobe
from .hwprobe import update_cache, active_output
from .paths import Paths
from .safety import RunDir
from .session import Session
from .steam import Steam


def _steam(paths: Paths) -> Steam:
    cfg = paths.config()
    root = cfg.get("steam_root")
    return Steam(Path(root) if root else None)


def _probe(paths: Paths, refresh: bool = False) -> tuple[dict, str, bool]:
    data = hwprobe.probe()
    if refresh and paths.hardware_cache.exists():
        paths.hardware_cache.unlink()
    fp, refreshed = update_cache(data, paths.hardware_cache)
    return data, fp, refreshed


def _display_name(paths: Paths) -> str:
    return paths.config().get("display", "DP-2")


def fmt_size(b: int) -> str:
    return f"{b / 1e9:.1f} GB" if b else "-"


def fmt_date(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(ts)) if ts else "-"


# ---------------------------------------------------------------- commands

def cmd_probe(args, paths: Paths, out) -> int:
    data, fp, refreshed = _probe(paths, args.refresh)
    out(json.dumps(data, indent=2))
    out(f"fingerprint {fp}: cache {'refreshed' if refreshed else 'unchanged'} ({paths.hardware_cache})")
    disp = data.get("display", {})
    drm = {d["connector"]: d for d in disp.get("drm_connected", [])}
    for o in disp.get("outputs", []):
        d = drm.get(o.get("name"), {})
        scaler = d.get("above_preferred") or o.get("scaler_modes")
        extra = f", also accepts {', '.join(scaler)} (scaler, not native)" if scaler else ""
        out(f"output {o.get('name')}{' (' + d['monitor'] + ')' if d.get('monitor') else ''}: "
            f"{o.get('active_mode') or 'mode unknown'}, native {o.get('preferred_mode') or '?'}, "
            f"max {o.get('max_mode') or '?'}, scale {o.get('scale')}, priority {o.get('priority')}{extra}")
    name = _display_name(paths)
    o = active_output(data, name)
    if o and o.get("active_mode"):
        out(f"gaming display {o['name']}: {o['active_mode']} (native {o.get('preferred_mode') or '?'}) "
            f"scale {o.get('scale')} HDR {'on' if o.get('hdr') else 'off'} [from {disp.get('source')}]")
    elif o:
        out(f"gaming display {name}: found but its active mode could not be read [from {disp.get('source')}]; "
            f"pass --goal WxH@fps explicitly")
    else:
        out(f"gaming display {name}: not found among {[x['name'] for x in disp.get('outputs', [])]} "
            f"(set display = \"...\" in {paths.config_file})")
    return 0


def cmd_library(args, paths: Paths, out) -> int:
    steam = _steam(paths)
    apps = steam.apps()
    if args.json:
        out(json.dumps([a.as_dict() for a in apps], indent=2))
        return 0
    adapters = set(Adapter.available())
    ids = {Adapter.load(g).appid: g for g in adapters}
    out(f"{'appid':>8}  {'runtime':7}  {'size':>9}  {'last played':11}  {'adapter':8}  name  [library]")
    for a in apps:
        if args.games_only and (a.appid == 228980 or "Redistributables" in a.name or "Proton" in a.name
                                or "Steam Linux Runtime" in a.name or "Steamworks" in a.name):
            continue
        out(f"{a.appid:>8}  {a.runtime:7}  {fmt_size(a.size_bytes):>9}  {fmt_date(a.last_played):11}  "
            f"{ids.get(a.appid, '-'):8}  {a.name}  [{a.library}]")
    out(f"\n{len(apps)} installed apps in {len(steam.libraries())} libraries. Adapters: {', '.join(sorted(adapters))}.")
    return 0


def cmd_games(args, paths: Paths, out) -> int:
    steam = _steam(paths)
    procs = Steam.running_processes()
    for g in Adapter.available():
        ad = Adapter.load(g)
        app = steam.app(ad.appid)
        if app is None:
            out(f"{ad.name}: not installed")
            continue
        try:
            sp = ad.settings_path(steam)
            exists = sp.exists()
        except Refusal as e:
            sp, exists = str(e), False
        running = Steam.any_running(ad.processes, procs)
        out(f"{ad.name} (app {ad.appid}, {ad.runtime}{', ' + (steam.proton_version(ad.appid) or 'proton version unknown') if ad.runtime == 'proton' else ''})")
        out(f"  detected: {app.runtime} ({app.runtime_source})"
            + ("" if app.runtime.rstrip("?") == ad.runtime else f"  WARNING: the adapter says {ad.runtime}"))
        out(f"  install:  {app.install_path}")
        out(f"  settings: {sp} {'(found)' if exists else '(MISSING: run the game once)'}")
        out(f"  launch options: {steam.get_launch_options(ad.appid) or '(none)'}")
        out(f"  running: {', '.join(running) if running else 'no'}")
    out(_proton_line(steam))
    return 0


def _proton_line(steam: Steam) -> str:
    tools = steam.compat_tools()
    return (f"Proton builds: {', '.join(tools['valve']) or 'none'}; custom (compatibilitytools.d): "
            f"{', '.join(tools['custom']) or 'none, so GE-Proton is not installed (experiment E3 needs it)'}")


def cmd_show(args, paths: Paths, out) -> int:
    steam = _steam(paths)
    ad = Adapter.load(args.game)
    if not ad.has_settings_file:
        out(f"{ad.name}: settings file unknown ({ad.settings_note}); measure only. "
            f"Run `python3 -m gopt find-settings {ad.id}` to locate it.")
        out(f"launch options: {steam.get_launch_options(ad.appid) or '(none)'}")
        for a in ad.launch_advice:
            out(f"advice: {a}")
        return 0
    sp = ad.settings_path(steam)
    vals = ad.read_settings(sp)
    out(f"{ad.name}: {sp}")
    if ad.info_keys:
        doc = ad.load_doc(sp)
        for ik in ad.info_keys:
            out(f"{'[info] ' + ik['label']:40} {ik['key'].rsplit('::', 1)[-1]:52} {ad._get(doc, ik['key'])}")
    out(f"{'setting':28} {'key':40} {'value':16} level            status")
    for s in ad.settings:
        v = vals.get(s.key)
        lv = s.level_from(vals)
        label = s.labels[lv] if lv is not None else ("absent (default)" if v is None else "unrecognised")
        wait = ""
        if ad.needs_discover(s, vals, sp):
            wait = " (guessed key or value: not tuned until discover)" if not s.usable else " (not in the file: not tuned until discover)"
        out(f"{s.label:28} {s.key:40} {str(v):16} {label:16} {s.status}{wait}")
        for k in s.extra_keys:
            out(f"{'  with':28} {k:40} {str(vals.get(k)):16}")
    for o in ad.overrides:
        out(f"{'[override] ' + o.key:69} {str(vals.get(o.key)):16} wanted {o.value:9} {o.status}")
    out(f"launch options: {steam.get_launch_options(ad.appid) or '(none)'}")
    if ad.runtime == "proton":
        out(f"Proton prefix version: {steam.proton_version(ad.appid) or 'unknown'}")
        out(_proton_line(steam))
    for a in ad.launch_advice:
        out(f"advice: {a}")
    runs = sorted(p.name for p in paths.runs.glob(f"*-{ad.id}")) if paths.runs.exists() else []
    out(f"runs: {', '.join(runs[-5:]) if runs else 'none'}")
    return 0


def _common_plan(args, paths: Paths, out) -> tuple[Session, dict]:
    steam = _steam(paths)
    ad = Adapter.load(args.game)
    data, _, _ = _probe(paths)
    o = active_output(data, _display_name(paths))
    refresh = o.get("refresh_hz") if o else None
    pins = {}
    for p in args.pin or []:
        if "=" not in p:
            raise Refusal(f"--pin needs setting=value, got {p!r}")
        k, v = p.split("=", 1)
        pins[k] = v
    sess = Session(ad, steam, paths, out=out)
    plan = sess.plan(args.goal, args.priority, refresh, pins, args.no_upscaling, args.max_runs,
                     getattr(args, "write_launch_options", False), vram_mb=data.get("gpu", {}).get("vram_mb"),
                     active_mode=o.get("active_mode") if o else None)
    return sess, plan


def cmd_plan(args, paths: Paths, out) -> int:
    sess, plan = _common_plan(args, paths, out)
    out(sess.describe_plan(plan))
    if args.save:
        Path(args.save).write_text(json.dumps(plan, indent=2))
        out(f"plan saved to {args.save}")
    return 0


def cmd_tune(args, paths: Paths, out) -> int:
    sess, plan = _common_plan(args, paths, out)
    logs = [Path(p) for p in (args.log_file or [])]
    return sess.tune(plan, apply=args.apply, log_files=logs, yes=args.yes, keep_hud=args.keep_hud, scene=args.scene)


def cmd_apply(args, paths: Paths, out) -> int:
    plan = json.loads(Path(args.plan).read_text())
    steam = _steam(paths)
    ad = Adapter.load(plan["game"])
    sess = Session(ad, steam, paths, out=out)
    return sess.tune(plan, apply=args.apply, log_files=[Path(p) for p in (args.log_file or [])], yes=args.yes)


def cmd_measure(args, paths: Paths, out) -> int:
    steam = _steam(paths)
    ad = Adapter.load(args.game)
    sess = Session(ad, steam, paths, out=out)
    m = sess.measure(Path(args.log_file) if args.log_file else None, free_play=args.free_play)
    out(json.dumps(m.as_dict(), indent=2))
    return 0


def cmd_undo(args, paths: Paths, out) -> int:
    run = RunDir(paths.runs, args.run_id)
    if not run.manifest_path.exists():
        raise Refusal(f"no run {args.run_id} under {paths.runs}")
    restored = run.undo(force=args.force)
    for p in restored:
        out(f"restored {p}")
    out(f"{len(restored)} file(s) restored from {run.backups}")
    return 0


def cmd_report(args, paths: Paths, out) -> int:
    rp = paths.runs / args.run_id / "game-optimiser-report.txt"
    if not rp.exists():
        raise Refusal(f"no report for run {args.run_id}")
    out(rp.read_text())
    return 0


def cmd_discover(args, paths: Paths, out, ask=input) -> int:
    steam = _steam(paths)
    ad = Adapter.load(args.game)
    sess = Session(ad, steam, paths, out=out)
    if args.before and args.after:
        # non interactive: two saved copies of the settings file
        def flat(path):
            return Session.flat_for_discover(ad, ad.load_doc(Path(path)))
        diff = Session.discover_diff(flat(args.before), flat(args.after))
        data = sess.record_discovery(args.setting, args.label, diff)
        out(json.dumps(data.get("discover", {}).get(args.setting), indent=2))
        return 0
    if not ad.settings:
        raise Refusal(f"{ad.name} has no settings to discover yet; `python3 -m gopt find-settings {ad.id}` shows which "
                      f"file an in game change touches")
    sess.refuse_if_game_running()
    out(f"Discovery for {ad.name}. For each option: change exactly that option in the game's menu, quit the game fully, press Enter.")
    for s in ad.settings:
        if s.status == "V":
            continue
        # two passes: a level the menu already showed gives no change the first time; it is asked again at the end
        skip = False
        for attempt in (1, 2):
            missing = [l for l in s.labels if l not in ad.learned.get("discover", {}).get(s.id, {}).get("values", {})]
            if skip or not missing or (attempt == 2 and missing == s.labels):
                break
            if attempt == 2:
                out(f"  {s.label}: once more for {', '.join(missing)}")
            for label in missing:
                r = _discover_one(sess, s, label, ask, out)
                if r == "q":
                    out(f"saved to {ad.learned_path()}")
                    return 0
                if r == "s":
                    skip = True
                    break
    out(f"saved to {ad.learned_path()}")
    return 0


def _discover_one(sess: Session, s, label: str, ask, out) -> str:
    """One in game change for discover: 'ok', 'skip level', 's' (skip setting) or 'q' (quit)."""
    before = sess.snapshot()
    ans = ask(f"Set '{s.label}' to '{label}' in game, quit, then press Enter (s to skip this setting, q to quit): ")
    if ans.strip().lower() in ("q", "s"):
        return ans.strip().lower()
    after = sess.snapshot()
    diff = Session.discover_diff(before, after)
    if not diff:
        cur = after.get(s.key)
        if cur is not None and ask(f"  nothing changed. Did the menu already show '{label}'? y records "
                                   f"{s.key}={cur} for it: ").strip().lower() == "y":
            diff = {s.key: (cur, cur)}
        else:
            out("  no key changed (already at that value, or the game did not write the file); skipping this level")
            return "skip level"
    try:
        sess.record_discovery(s.id, label, diff)
        out(f"  {s.label} / {label} -> " + ", ".join(f"{k} = {v[1]}" for k, v in sorted(diff.items())))
    except Refusal as e:
        out(f"  {e}")
    return "ok"


def cmd_find_settings(args, paths: Paths, out) -> int:
    """Read only: which file and lines change when one option is changed in game."""
    from . import findsettings as fs
    steam = _steam(paths)
    if args.game.isdigit():
        appid, name = int(args.game), args.game
    else:
        ad = Adapter.load(args.game)
        appid, name = ad.appid, ad.id
    if args.before and args.after:
        before, after = fs.load(args.before), fs.load(args.after)
    else:
        procs = Steam.running_processes()
        roots = fs.roots_for(steam, appid)
        if not roots:
            raise Refusal(f"app {appid}: no prefix, install folder or userdata folder found")
        out("Looking in:\n  " + "\n  ".join(map(str, roots)))
        before = fs.snapshot(roots)
        out(f"{len(before)} files recorded. Start the game, change exactly ONE option in its settings menu, "
            f"quit the game fully, then press Enter.")
        input("Press Enter when the game is closed... ")
        after = fs.snapshot(roots)
    changes = fs.diff(before, after)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    report = paths.data_dir / "find-settings" / f"{name}-{stamp}.txt"
    lines = [f"game-optimiser {__version__} find-settings {name} (app {appid}) {stamp}"]
    if not changes:
        lines.append("no file changed (the option was already at that value, or the game saves on a later exit)")
    for ch in changes:
        lines.append(f"{ch['kind']}: {ch['path']}")
        lines += [f"    {ln}" for ln in ch["lines"]]
    for ln in lines:
        out(ln)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines) + "\n")
    out(f"saved to {report}")
    return 0 if changes else 4


def cmd_selftest(args, paths: Paths, out) -> int:
    """Stdlib only smoke test over the bundled fixtures (the full suite needs pytest)."""
    from .parsers.eecfg import EECfg
    from .parsers.keyvalues import KeyValues
    from .mangohud import parse_log
    from .metrics import compute
    fix = Path(__file__).resolve().parent.parent / "tests" / "fixtures"
    checks = 0
    for name in ("cs2_video.txt", "localconfig.vdf", "loginusers.vdf", "libraryfolders.vdf"):
        t = (fix / name).read_text(newline="")
        assert KeyValues(t).text == t, name
        checks += 1
    t = (fix / "EE.cfg").read_text(newline="")
    assert EECfg(t).text() == t
    checks += 1
    from .parsers.jsontext import JsonText
    from .parsers.srccfg import SrcCfg
    from .parsers.winreg import WinReg
    from .hwprobe import parse_kscreen, parse_kscreen_json
    for name, cls in (("GameUserSettings.ini", EECfg), ("autoexec.cfg", SrcCfg), ("brotato_save_v2.json", JsonText),
                      ("user.reg", WinReg)):
        t = (fix / name).read_bytes().decode("utf-8")
        assert cls(t).text() == t, name
        checks += 1
    for outs in (parse_kscreen((fix / "kscreen_doctor_o.txt").read_text()),
                 parse_kscreen_json((fix / "kscreen_doctor_j.json").read_text())):
        assert {o["name"]: o["active_mode"] for o in outs}["DP-2"] == "3840x2160@240"
        checks += 1
    for name in ("mangohud_warframe_gpu_bound.csv", "mangohud_cs2_cpu_bound.csv"):
        m = compute(parse_log(fix / name)["rows"])
        assert m.frames > 100 and m.avg_fps > 0
        checks += 1
    for g in Adapter.available():
        Adapter.load(g)
        checks += 1
    out(f"selftest: {checks} checks passed (python {sys.version.split()[0]}, gopt {__version__}). Full suite: python3 -m pytest -q")
    return 0


# ---------------------------------------------------------------- parser

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gopt", description="Tune a Steam game's settings towards an fps goal (dry run by default).")
    p.add_argument("--version", action="version", version=f"gopt {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("probe", help="hardware and environment probe (no root)")
    s.add_argument("--refresh", action="store_true")
    s.set_defaults(fn=cmd_probe)

    s = sub.add_parser("library", help="list installed Steam games")
    s.add_argument("--json", action="store_true")
    s.add_argument("--games-only", action="store_true", help="hide runtimes and redistributables")
    s.set_defaults(fn=cmd_library)

    s = sub.add_parser("games", help="supported games: paths, launch options, running state")
    s.set_defaults(fn=cmd_games)

    s = sub.add_parser("show", help="current settings of a game")
    s.add_argument("game")
    s.set_defaults(fn=cmd_show)

    for name, fn in (("plan", cmd_plan), ("tune", cmd_tune)):
        s = sub.add_parser(name, help="build the plan" if name == "plan" else "run the measure and adjust loop")
        s.add_argument("game")
        s.add_argument("--goal", help="e.g. 3840x2160@90 or 90")
        s.add_argument("--priority", choices=["quality", "balanced", "fps"])
        s.add_argument("--pin", action="append", help="setting=value, repeatable")
        s.add_argument("--no-upscaling", action="store_true")
        s.add_argument("--max-runs", type=int, default=6)
        s.add_argument("--write-launch-options", action="store_true", help="edit localconfig.vdf (Steam closed, typed YES)")
        if name == "plan":
            s.add_argument("--save", help="write plan.json here")
        else:
            s.add_argument("--apply", action="store_true", help="actually write files and run the loop")
            s.add_argument("--log-file", action="append", help="use these MangoHud CSVs instead of waiting (repeatable)")
            s.add_argument("--yes", action="store_true", help="answer YES to the launch option write prompt")
            s.add_argument("--keep-hud", action="store_true", help="leave the MangoHud per-app config in place")
            s.add_argument("--scene", help="benchmark scene: a number from the offered list or a scene name (saved)")
        s.set_defaults(fn=fn)

    s = sub.add_parser("apply", help="run a saved plan")
    s.add_argument("plan")
    s.add_argument("--apply", action="store_true")
    s.add_argument("--log-file", action="append")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_apply)

    s = sub.add_parser("measure", help="one logged run, metrics only")
    s.add_argument("game")
    s.add_argument("--log-file")
    s.add_argument("--free-play", action="store_true")
    s.set_defaults(fn=cmd_measure)

    for name in ("undo", "restore"):
        s = sub.add_parser(name, help="restore every file of a run from its backups (once)")
        s.add_argument("run_id")
        s.add_argument("--force", action="store_true")
        s.set_defaults(fn=cmd_undo)

    s = sub.add_parser("report", help="print a run's report")
    s.add_argument("run_id")
    s.set_defaults(fn=cmd_report)

    s = sub.add_parser("discover", help="learn key names by diffing the settings file after one in game change")
    s.add_argument("game")
    s.add_argument("--before", help="non interactive: settings file copy before the change")
    s.add_argument("--after", help="non interactive: settings file copy after the change")
    s.add_argument("--setting", help="setting id (see show)")
    s.add_argument("--label", help="menu label that was selected")
    s.set_defaults(fn=cmd_discover)

    s = sub.add_parser("find-settings", help="read only: which file changes when you change one option in game")
    s.add_argument("game", help="adapter id or any installed appid")
    s.add_argument("--before", help="non interactive: snapshot JSON before the change")
    s.add_argument("--after", help="non interactive: snapshot JSON after the change")
    s.set_defaults(fn=cmd_find_settings)

    s = sub.add_parser("selftest", help="stdlib smoke test over the bundled fixtures")
    s.set_defaults(fn=cmd_selftest)
    return p


def main(argv: list[str] | None = None, out=print, paths: Paths | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = paths or Paths()
    try:
        return int(args.fn(args, paths, out) or 0)
    except Refusal as e:
        out(f"REFUSED: {e}")
        return 3
    except KeyboardInterrupt:
        out("interrupted")
        return 130
