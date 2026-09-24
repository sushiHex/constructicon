"""The launch set's vendor tree and catalog: bound read-only, custody-checked.

Portable: only the Linux platform facts and the ownership and mode that
``stat`` reports are substituted. The tree walk, the custody rule and argv
stay production code (M8-N4-state-review.md, host-runtime interface item 1).
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.substrate.executors import linux
from tests.substrate.test_native_store_launch import mount, positive


class Host:
    """Real files; ``stat`` reports root ownership and the modes a test sets."""

    def __init__(self, tmp_path: Path) -> None:
        self.tree = tmp_path / "native-codex"
        (self.tree / "bin").mkdir(parents=True)
        (self.tree / "bin" / "codex").write_bytes(b"pinned binary")
        (self.tree / "share").mkdir()
        (self.tree / "share" / "notes").write_bytes(b"pinned notes")
        self.catalog = tmp_path / "codex-models.json"
        self.catalog.write_bytes(b"{}")
        self.modes: dict[str, int] = {str(self.catalog): 0o444}
        self.owners: dict[str, int] = {}
        self.kinds: dict[str, int] = {}

    def fake(self, real):
        def reported(path, *args, **kwargs):
            info = real(path, *args, **kwargs)
            key = str(path)
            kind = self.kinds.get(key, stat.S_IFMT(info.st_mode))
            return SimpleNamespace(
                st_mode=kind | self.modes.get(key, 0o755), st_uid=self.owners.get(key, 0),
            )

        return reported

    def install(self, monkeypatch) -> linux.NativeVendor:
        monkeypatch.setattr(linux, "os", SimpleNamespace(**{
            **vars(os), "stat": self.fake(os.stat), "lstat": self.fake(os.lstat),
        }))
        return linux.NativeVendor(self.tree, self.catalog)


def test_the_installed_vendor_tree_and_catalog_pass(tmp_path, monkeypatch):
    Host(tmp_path).install(monkeypatch).check()


REFUSALS = {
    "file-not-root": lambda host: host.owners.update({str(host.tree / "bin" / "codex"): 1000}),
    "directory-not-root": lambda host: host.owners.update({str(host.tree / "share"): 1000}),
    "tree-not-root": lambda host: host.owners.update({str(host.tree): 1000}),
    "group-writable-file": lambda host: host.modes.update(
        {str(host.tree / "share" / "notes"): 0o775},
    ),
    "other-writable-directory": lambda host: host.modes.update({str(host.tree / "bin"): 0o757}),
    "set-id-file": lambda host: host.modes.update({str(host.tree / "bin" / "codex"): 0o4755}),
    "link-in-tree": lambda host: host.kinds.update(
        {str(host.tree / "bin" / "codex"): stat.S_IFLNK},
    ),
    "tree-is-a-file": lambda host: host.kinds.update({str(host.tree): stat.S_IFREG}),
    "catalog-not-root": lambda host: host.owners.update({str(host.catalog): 1000}),
    "group-writable-catalog": lambda host: host.modes.update({str(host.catalog): 0o464}),
    "catalog-is-a-link": lambda host: host.kinds.update({str(host.catalog): stat.S_IFLNK}),
    "writable-ancestor": lambda host: host.modes.update({str(host.tree.parent): 0o777}),
    "ancestor-not-root": lambda host: host.owners.update({str(host.tree.parent): 1000}),
}


@pytest.mark.parametrize("change", REFUSALS)
def test_a_vendor_tree_or_catalog_out_of_root_custody_refuses(tmp_path, monkeypatch, change):
    host = Host(tmp_path)
    REFUSALS[change](host)
    with pytest.raises(ContractViolation):
        host.install(monkeypatch).check()


def test_relative_vendor_paths_refuse(tmp_path, monkeypatch):
    Host(tmp_path).install(monkeypatch)
    with pytest.raises(ContractViolation):
        linux.NativeVendor(Path("native-codex"), Path("codex-models.json")).check()


def launcher(tmp_path, vendor=None):
    return linux.LinuxLauncher(
        runtime_root=tmp_path / "runtime", expected_runtime=digest("runtime", 1, "test"),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="0" * 64, vendor=vendor,
    )


@pytest.fixture
def on_linux(monkeypatch):
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(linux.os, "getuid", lambda: 1000, raising=False)
    monkeypatch.setattr(linux.os, "getgid", lambda: 1000, raising=False)


def test_a_native_launch_binds_the_vendor_tree_and_catalog_read_only(tmp_path, on_linux):
    vendor = linux.NativeVendor(tmp_path / "native-codex", tmp_path / "codex-models.json")
    argv = launcher(tmp_path, vendor).argv(
        ("/opt/codex/bin/codex",), workspace=None, posture=Posture.READ,
        native_store=mount(positive),
    )
    start = argv.index(linux.VENDOR_MOUNT) - 2
    assert argv[start:start + 6] == [
        "--ro-bind", str(vendor.tree), "/opt/codex",
        "--ro-bind", str(vendor.catalog), "/opt/codex-models.json",
    ]
    assert argv.index("CODEX_HOME") < start < argv.index("--chdir")
    assert argv.count(str(vendor.tree)) == 1 and "--bind" not in argv


def test_a_worker_launch_never_sees_the_vendor(tmp_path, on_linux):
    vendor = linux.NativeVendor(tmp_path / "native-codex", tmp_path / "codex-models.json")
    argv = launcher(tmp_path, vendor).argv(
        ("/usr/bin/git",), workspace=tmp_path, posture=Posture.READ,
    )
    assert str(vendor.tree) not in argv and linux.VENDOR_MOUNT not in argv


def test_no_vendor_means_no_bind(tmp_path, on_linux):
    argv = launcher(tmp_path).argv(
        ("/usr/bin/python3",), workspace=None, posture=Posture.READ, native_store=mount(positive),
    )
    assert linux.VENDOR_MOUNT not in argv and linux.CATALOG_MOUNT not in argv


def test_the_launch_revision_names_the_bound_vendor(tmp_path):
    vendor = linux.NativeVendor(tmp_path / "native-codex", tmp_path / "codex-models.json")
    other = linux.NativeVendor(tmp_path / "other", tmp_path / "codex-models.json")
    revisions = {launcher(tmp_path).revision, launcher(tmp_path, vendor).revision,
                 launcher(tmp_path, other).revision}
    assert len(revisions) == 3


def test_every_probe_checks_the_vendor_custody(tmp_path, monkeypatch):
    checked = []
    vendor = SimpleNamespace(check=lambda: checked.append(True))
    subject = launcher(tmp_path, vendor)
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(linux, "os", SimpleNamespace(**{**vars(os), "getuid": lambda: 1000}))
    monkeypatch.setattr(linux, "require_fixed_artifact", lambda path: None)
    monkeypatch.setattr(linux, "_sha", lambda path: (
        linux.BWRAP_SHA256 if path == subject.bubblewrap else "0" * 64
    ))
    monkeypatch.setattr(linux, "runtime_digest", lambda root: subject.expected_runtime)
    monkeypatch.setattr(linux.Path, "read_text", lambda self, *a, **k: "1\n")
    subject.check_artifacts()
    assert checked == [True]
