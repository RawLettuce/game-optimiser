import os
import stat
from pathlib import Path

import pytest

from gopt import Refusal
from gopt.safety import (RunDir, write_file, read_text_or_refuse, sha256_of, census,
                         file_fingerprints, check_not_stale, within_roots)


def make_run(tmp_path):
    return RunDir(tmp_path / "runs", "20261023-120000-test").create()


def test_backup_then_undo_restores_original(tmp_path, steam):
    run = make_run(tmp_path)
    target = steam["cs2_video"]
    original = target.read_bytes()
    sha = write_file(run, target, target.read_text().replace('"4"', '"0"', 1), "test",
                     allowed_roots=[steam["root"]])
    assert target.read_bytes() != original
    entries = run.entries()
    assert len(entries) == 1
    assert entries[0].sha256 == sha256_of(Path(entries[0].backup))
    assert entries[0].written_sha256 == sha
    restored = run.undo()
    assert restored == [str(target)]
    assert target.read_bytes() == original


def test_second_undo_is_refused(tmp_path, steam):
    run = make_run(tmp_path)
    target = steam["cs2_video"]
    write_file(run, target, target.read_text() + "\n", "test", allowed_roots=[steam["root"]])
    run.undo()
    with pytest.raises(Refusal):
        run.undo()


def test_undo_refuses_when_file_changed_by_someone_else(tmp_path, steam):
    run = make_run(tmp_path)
    target = steam["cs2_video"]
    write_file(run, target, target.read_text() + "\n", "test", allowed_roots=[steam["root"]])
    target.write_text(target.read_text() + "// someone else\n")
    with pytest.raises(Refusal):
        run.undo()
    run.undo(force=True)
    assert "someone else" not in target.read_text()


def test_two_writes_keep_the_first_original(tmp_path, steam):
    run = make_run(tmp_path)
    target = steam["cs2_video"]
    original = target.read_bytes()
    write_file(run, target, target.read_text().replace('"4"', '"2"', 1), "a", allowed_roots=[steam["root"]])
    write_file(run, target, target.read_text().replace('"2"', '"0"', 1), "b", allowed_roots=[steam["root"]])
    assert len(run.entries()) == 1
    run.undo()
    assert target.read_bytes() == original


def test_refuses_outside_allowed_roots(tmp_path, steam):
    run = make_run(tmp_path)
    outside = tmp_path / "elsewhere.txt"
    outside.write_text("x\n")
    with pytest.raises(Refusal):
        write_file(run, outside, "y\n", "test", allowed_roots=[steam["root"]])
    assert outside.read_text() == "x\n"


def test_refuses_empty_and_shrunken_writes(tmp_path, steam):
    run = make_run(tmp_path)
    target = steam["cs2_video"]
    before = target.read_bytes()
    with pytest.raises(Refusal):
        write_file(run, target, "   \n", "test", allowed_roots=[steam["root"]])
    with pytest.raises(Refusal):
        write_file(run, target, '"video.cfg"\n{\n}\n', "test", allowed_roots=[steam["root"]])
    assert target.read_bytes() == before


def test_unreadable_file_is_hard_stop(tmp_path):
    p = tmp_path / "EE.cfg"
    p.write_text("x=1\n")
    os.chmod(p, 0)
    try:
        if os.access(p, os.R_OK):      # running as root: permissions do not bite
            pytest.skip("root can read anything")
        with pytest.raises(Refusal):
            read_text_or_refuse(p)
    finally:
        os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)


def test_missing_and_empty_files_are_hard_stops(tmp_path):
    with pytest.raises(Refusal):
        read_text_or_refuse(tmp_path / "nope.cfg")
    p = tmp_path / "empty.cfg"
    p.write_text("  \n")
    with pytest.raises(Refusal):
        read_text_or_refuse(p)


def test_undecodable_file_is_hard_stop(tmp_path):
    p = tmp_path / "bad.cfg"
    p.write_bytes(b"\xff\xfe\x00\x00garbage")
    with pytest.raises(Refusal):
        read_text_or_refuse(p)


def test_stale_plan_detection(tmp_path, steam):
    fp = file_fingerprints([steam["cs2_video"], steam["eecfg"]])
    check_not_stale(fp)
    steam["eecfg"].write_text(steam["eecfg"].read_text() + "\n")
    with pytest.raises(Refusal):
        check_not_stale(fp)


def test_census_counts_existing_files(tmp_path):
    a = tmp_path / "a"
    a.write_bytes(b"12345")
    assert census([a, tmp_path / "missing"]) == (1, 5)


def test_within_roots_rejects_symlink_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    link = root / "link.txt"
    link.symlink_to(outside)
    assert within_roots(root / "inner.txt", [root])
    assert not within_roots(link, [root])
