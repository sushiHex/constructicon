"""The egress leaf is one positively re-identified, read-only launcher input."""

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.substrate.executors import egress, linux
from constructicon.substrate.executors.egress import EgressSocket

IDENTITY = (41, 97)
SOCKET_MODE = stat.S_IFSOCK | 0o755
REGULAR_MODE = stat.S_IFREG | 0o644
FACTS = {
    "current": SimpleNamespace(st_mode=SOCKET_MODE, st_uid=1000, st_dev=41, st_ino=97),
    "identity": SimpleNamespace(st_mode=SOCKET_MODE, st_uid=1000, st_dev=41, st_ino=98),
    "regular-file": SimpleNamespace(st_mode=REGULAR_MODE, st_uid=1000, st_dev=41, st_ino=97),
    "foreign-owner": SimpleNamespace(st_mode=SOCKET_MODE, st_uid=0, st_dev=41, st_ino=97),
}


@pytest.fixture
def observed():
    return {"facts": FACTS["current"]}


@pytest.fixture(autouse=True)
def platform_facts(monkeypatch, observed):
    """Only the Linux platform facts; argv and the identity check stay real."""

    def lstat(path):
        facts = observed["facts"]
        if facts is None:
            raise FileNotFoundError(2, "No such file or directory", str(path))
        return facts

    for module in (linux, egress):
        monkeypatch.setattr(module, "sys", SimpleNamespace(platform="linux"))
        monkeypatch.setattr(module, "os", SimpleNamespace(**{
            **vars(os), "getuid": lambda: 1000, "getgid": lambda: 1000, "lstat": lstat,
        }))


def launcher(tmp_path):
    return linux.LinuxLauncher(
        runtime_root=tmp_path / "runtime", expected_runtime=digest("runtime", 1, "test"),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="0" * 64,
    )


def mount(tmp_path, socket=None):
    return linux.NativeStoreMount(
        path=tmp_path / "store", lock_fd=731, before_spawn=lambda: None, egress=socket,
    )


def argv(tmp_path, socket=None, workspace=None):
    return launcher(tmp_path).argv(
        ("/usr/bin/python3",), workspace=workspace, posture=Posture.READ,
        native_store=mount(tmp_path, socket),
    )


def test_a_current_egress_socket_gets_one_read_only_leaf(tmp_path):
    socket = EgressSocket(tmp_path / "payloads" / "acq-x" / "egress.sock", IDENTITY)
    args = argv(tmp_path, socket)
    assert "/vendor-egress.sock" in args, "the egress leaf is missing"
    start = args.index("/vendor-egress.sock") - 2
    assert args[start:start + 3] == ["--ro-bind", str(socket.path), "/vendor-egress.sock"]
    assert args.count("/vendor-egress.sock") == 1
    assert start < args.index("--")
    assert "--unshare-net" in args


def test_no_egress_socket_means_no_leaf_and_the_namespace_stays_unshared(tmp_path):
    args = argv(tmp_path)
    assert "/vendor-egress.sock" not in args
    assert "--unshare-net" in args


@pytest.mark.parametrize("case", ["identity", "regular-file", "foreign-owner", "missing"])
def test_a_changed_or_foreign_egress_socket_is_refused(tmp_path, observed, case):
    observed["facts"] = None if case == "missing" else FACTS[case]
    socket = EgressSocket(tmp_path / "payloads" / "acq-x" / "egress.sock", IDENTITY)
    caught = None
    try:
        argv(tmp_path, socket)
    except ContractViolation as exc:
        caught = exc
    assert caught is not None, "a changed socket reached the mount"
    assert str(tmp_path) not in str(caught)


def test_a_non_canonical_socket_locator_is_refused(tmp_path):
    socket = EgressSocket(tmp_path / "payloads" / ".." / "egress.sock", IDENTITY)
    with pytest.raises(ContractViolation):
        argv(tmp_path, socket)


def test_the_egress_leaf_never_joins_a_worker_workspace(tmp_path):
    socket = EgressSocket(tmp_path / "egress.sock", IDENTITY)
    with pytest.raises(ContractViolation, match="cannot share a namespace"):
        argv(tmp_path, socket, workspace=Path(tmp_path / "workspace"))
