"""The native mount is one narrow, positively checked launcher input."""

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.substrate.executors import linux


@pytest.fixture(autouse=True)
def platform_facts(monkeypatch):
    """Only the Linux platform facts; argv and spawn gating remain real."""
    def empty_nonblocking_pipe(fd, maximum):
        raise BlockingIOError

    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(linux, "os", SimpleNamespace(**{
        **vars(os), "getuid": lambda: 1000, "getgid": lambda: 1000,
        "set_blocking": lambda fd, blocking: None, "read": empty_nonblocking_pipe,
    }))


def mount(path, check, lock_fd=731):
    factory = getattr(linux, "NativeStoreMount", None)
    assert factory is not None, "the launcher has no native-store boundary"
    return factory(path=path, lock_fd=lock_fd, before_spawn=check)


def positive():
    from constructicon.substrate.executors.operator_store import BindingCheck

    return BindingCheck(binding_digest=digest("test-binding", 1, "public"))


def launcher(tmp_path):
    return linux.LinuxLauncher(
        runtime_root=tmp_path / "runtime", expected_runtime=digest("runtime", 1, "test"),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="0" * 64,
    )


def test_native_store_has_one_fixed_destination_and_keeps_home_disposable(tmp_path, monkeypatch):
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    store = mount(tmp_path / "protected" / "store", positive)
    argv = launcher(tmp_path).argv(
        ("/usr/bin/python3",), workspace=None, posture=Posture.READ, native_store=store,
    )
    assert "--bind" in argv, "the native store mount is missing"
    start = argv.index("--bind")
    assert argv[start:start + 3] == ["--bind", str(store.path), "/vendor-store"]
    assert argv.count("--bind") == 1
    assert argv[argv.index("HOME") + 1] == "/tmp/home"
    assert str(store.path.parent) not in argv
    assert "--unshare-net" in argv


def test_native_store_and_worker_workspace_are_mutually_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    caught = None
    try:
        launcher(tmp_path).argv(
            ("/usr/bin/python3",), workspace=tmp_path / "workspace", posture=Posture.READ,
            native_store=mount(tmp_path / "store", positive),
        )
    except ContractViolation as exc:
        caught = exc
    assert caught is not None, "one namespace received both store and workspace"


def test_native_store_requires_an_absolute_private_locator():
    caught = None
    try:
        mount(Path("relative-store"), positive)
    except ContractViolation as exc:
        caught = exc
    assert caught is not None


@pytest.mark.parametrize("result", ["positive", "missing", "refused"])
async def test_only_a_positive_post_probe_check_reaches_spawn(tmp_path, monkeypatch, result):
    events = []
    instance = launcher(tmp_path)
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))

    async def probe(self, **kwargs):
        events.append("probe")
        await asyncio.sleep(0)
        events.append("probe-complete")

    def verify():
        events.append("binding-check")
        assert events[:2] == ["probe", "probe-complete"]
        if result == "refused":
            raise ContractViolation("binding changed")
        return positive() if result == "positive" else None

    async def spawn(*args, **kwargs):
        events.append("spawn")
        raise OSError("test stops at spawn; no process is created")

    async def conversation(io):
        pytest.fail("the spawn observation never creates a channel")

    monkeypatch.setattr(linux.LinuxLauncher, "probe", probe)
    monkeypatch.setattr(linux.asyncio, "create_subprocess_exec", spawn)
    with (tmp_path / "guard").open("wb") as guard:
        caught = None
        try:
            await instance.exchange(
                ("/usr/bin/python3",), workspace=None, posture=Posture.READ,
                guard_fds=(guard.fileno(),), conversation=conversation, timeout_s=5,
                native_store=mount(tmp_path / "store", verify, guard.fileno()),
            )
        except (ContractViolation, OSError):
            caught = True
        assert caught
        assert os.fstat(guard.fileno())
    assert events == ["probe", "probe-complete", "binding-check"] + (
        ["spawn"] if result == "positive" else []
    )


async def test_a_native_mount_without_its_retained_lock_never_reaches_the_check(
    tmp_path, monkeypatch,
):
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    called = []

    def verify():
        called.append("checked without physical custody")
        return positive()

    async def spawn(*args, **kwargs):
        raise OSError("test stops at spawn; no process is created")

    monkeypatch.setattr(linux.asyncio, "create_subprocess_exec", spawn)

    with (tmp_path / "guard").open("wb") as guard:
        caught = None
        try:
            await launcher(tmp_path)._run(
                ("/usr/bin/python3",), workspace=None, posture=Posture.READ,
                guard_fds=(guard.fileno(),), deadline=asyncio.get_running_loop().time() + 5,
                native_store=mount(tmp_path / "store", verify, guard.fileno() + 999),
            )
        except (ContractViolation, OSError) as exc:
            caught = exc
        assert caught is not None
    assert called == []
