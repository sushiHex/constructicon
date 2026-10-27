"""Portable custody and diagnostic regressions; not hosted installation proof."""
from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.substrate import _claude_read_rehearsal_host as host


class RootDirectory:
    """Real directory and inode, with root ownership and Windows POSIX mode views."""

    def __init__(self, path: Path):
        self.path = path
        self.mode = 0o777
        path.mkdir()
        path.chmod(self.mode)

    def lstat(self):
        info = self.path.lstat()
        return SimpleNamespace(
            st_mode=(stat.S_IFMT(info.st_mode) | self.mode) if os.name == "nt" else info.st_mode,
            st_uid=0, st_gid=0, st_dev=info.st_dev, st_ino=info.st_ino,
        )

    def resolve(self, strict=True):
        resolved = self.path.resolve(strict=strict)
        return self if resolved == self.path else resolved

    def chmod(self, mode):
        self.path.chmod(mode)
        self.mode = mode


@pytest.fixture
def custody(tmp_path, monkeypatch):
    root = tmp_path / "custody"
    root.mkdir()
    (root / "owned.json").write_text(
        '{"schema_version":1,"scope":"fake-read-rehearsal"}', encoding="utf-8",
    )
    opt = RootDirectory(tmp_path / "opt")
    monkeypatch.setattr(host, "ROOT", root)
    monkeypatch.setattr(host, "OPT", opt)
    monkeypatch.setattr(host, "HOME", tmp_path / "home")
    monkeypatch.setattr(host, "SESSION_PATHS", ())
    for name in ("INSTALLED", "CONTROLLER_ROOT", "QUALIFICATION_ROOT", "STORES", "CHECKERS",
                 "WORK", "DRIFT", "CLAUDE_POLICY", "D2_POLICY"):
        monkeypatch.setattr(host, name, tmp_path / name)
    original_stat = Path.stat

    def root_owner(path, *args, **kwargs):
        info = original_stat(path, *args, **kwargs)
        if path == root:
            fields = list(info[:10])
            fields[4:6] = (0, 0)
            return os.stat_result(fields)
        return info

    monkeypatch.setattr(Path, "stat", root_owner)
    chowns, synced = [], []

    def ownership(argv, **kwargs):
        # Only the Linux root-ownership primitive is replaced; write(), file
        # fsync, serialized state, chmod, all custody checks and cleanup are real.
        assert argv == ["/usr/bin/chown", "root:root", str(root / "opt-custody.json")]
        chowns.append(argv)
        return b""

    def directory_sync(path):
        # Windows cannot fsync a directory. Affirm state exists before chmod.
        assert path == root and opt.mode == 0o777
        record = json.loads((root / "opt-custody.json").read_bytes())
        assert record["original_mode"] == 0o777 and record["inode"] == opt.lstat().st_ino
        synced.append(path)

    def missing_account(name):
        assert name == "m8-probe"
        raise KeyError(name)

    monkeypatch.setattr(host, "command", ownership)
    monkeypatch.setattr(host, "_sync_directory", directory_sync)
    monkeypatch.setitem(sys.modules, "pwd", SimpleNamespace(getpwnam=missing_account))
    return root, opt, chowns, synced


def _allow_windows_root_cleanup(root):
    # Windows read-only files require write permission even when their parent is
    # writable; a Linux root can unlink this same 0444 fixture state directly.
    if os.name == "nt":
        (root / "opt-custody.json").chmod(0o600)


def test_hardening_records_identity_then_restores_after_owned_roots_removed(
    custody, capsys, monkeypatch,
):
    root, opt, chowns, synced = custody
    before = opt.lstat()
    host.protect_opt()
    assert opt.mode == 0o755 and stat.S_IMODE(opt.lstat().st_mode) == 0o755
    assert len(chowns) == 1 and synced == [root]
    assert json.loads((root / "opt-custody.json").read_bytes()) == {
        "original_mode": 0o777, "device": before.st_dev, "inode": before.st_ino,
        "uid": 0, "gid": 0,
    }
    assert json.loads(capsys.readouterr().out) == {
        "operation": "hosted-opt-custody", "before_mode": "0o777", "after_mode": "0o755",
        "root_owned": True, "same_directory": True,
    }
    host.CONTROLLER_ROOT.mkdir()
    (host.CONTROLLER_ROOT / "owned").write_bytes(b"fixture bytes")
    chmod = opt.chmod

    def ordered_restoration(mode):
        assert mode == 0o777 and not host.CONTROLLER_ROOT.exists()
        chmod(mode)

    monkeypatch.setattr(opt, "chmod", ordered_restoration)
    _allow_windows_root_cleanup(root)
    host.cleanup()
    assert not host.CONTROLLER_ROOT.exists() and not root.exists()
    assert opt.mode == 0o777 and stat.S_IMODE(opt.lstat().st_mode) == 0o777


def test_cleanup_refuses_replaced_directory_identity(custody):
    root, opt, _, _ = custody
    host.protect_opt()
    original = opt.lstat().st_ino
    opt.path.rename(opt.path.with_name("retained-original"))
    opt.path.mkdir()
    opt.chmod(0o755)
    assert opt.lstat().st_ino != original
    _allow_windows_root_cleanup(root)
    with pytest.raises(ValueError, match="cleanup hosted /opt custody refused"):
        host.cleanup()
    assert root.exists() and stat.S_IMODE(opt.lstat().st_mode) == 0o755


def test_failed_real_child_retains_operation_and_bounded_stdout_stderr(tmp_path):
    with pytest.raises(ValueError) as failed:
        host.command(
            [sys.executable, "-c", "import sys;sys.stdout.write('S'*5000);"
             "sys.stderr.write('E'*5000);sys.exit(17)"],
            cwd=tmp_path, operation="judge workspace=/fixture/d2",
        )
    message = str(failed.value)
    assert "judge workspace=/fixture/d2" in message and "returncode=17" in message
    assert "argv=" in message and "stdout (5000 bytes):" in message
    assert "stderr (5000 bytes):" in message
    assert "S" * 4096 in message and "S" * 4097 not in message
    assert "E" * 4096 in message and "E" * 4097 not in message
    assert message.count("[truncated; 5000 bytes total]") == 2
    assert len(message) < 10000
