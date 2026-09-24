"""The native mount is one narrow, positively checked launcher input."""

import asyncio
import os
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


CONFIGURATION_FD, CREDENTIAL_FD = 741, 742


def mount(check, lock_fd=731, *, configuration_fd=CONFIGURATION_FD, credential_fd=CREDENTIAL_FD):
    factory = getattr(linux, "NativeStoreMount", None)
    assert factory is not None, "the launcher has no native-store boundary"
    return factory(
        lock_fd=lock_fd, configuration_fd=configuration_fd, credential_fd=credential_fd,
        before_spawn=check,
    )


def positive():
    from constructicon.substrate.executors.operator_store import BindingCheck

    return BindingCheck(binding_digest=digest("test-binding", 1, "public"))


def launcher(tmp_path):
    return linux.LinuxLauncher(
        runtime_root=tmp_path / "runtime", expected_runtime=digest("runtime", 1, "test"),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="0" * 64,
    )


def test_the_native_layout_binds_two_descriptors_into_a_disposable_codex_home(
    tmp_path, monkeypatch,
):
    """M8-N4-state-review.md, section 1: two host objects, both by descriptor."""

    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    argv = launcher(tmp_path).argv(
        ("/usr/bin/python3",), workspace=None, posture=Posture.READ, native_store=mount(positive),
    )
    assert "/tmp/home/.codex" in argv, "the native layout is missing"
    start = argv.index("/tmp/home/.codex") - 1
    assert argv[start:start + 11] == [
        "--dir", "/tmp/home/.codex",
        "--ro-bind-data", str(CONFIGURATION_FD), "/tmp/home/.codex/config.toml",
        "--bind-fd", str(CREDENTIAL_FD), "/tmp/home/.codex/auth.json",
        "--setenv", "CODEX_HOME", "/tmp/home/.codex",
    ]
    # No path-based store mount remains, and the home itself stays disposable.
    assert "--bind" not in argv and "/vendor-store" not in argv
    assert argv.count("--bind-fd") == 1 and argv.count("--ro-bind-data") == 1
    assert argv[argv.index("HOME") + 1] == "/tmp/home"
    assert argv.index("--tmpfs") < start, "the codex home must sit inside the fresh tmpfs"
    assert "--unshare-net" in argv


def test_a_worker_launch_gets_no_codex_home(tmp_path, monkeypatch):
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    argv = launcher(tmp_path).argv(
        ("/usr/bin/python3",), workspace=tmp_path / "workspace", posture=Posture.WRITE,
    )
    assert "/tmp/home/.codex" not in argv and "CODEX_HOME" not in argv
    assert "--bind-fd" not in argv and "--ro-bind-data" not in argv


def test_native_store_and_worker_workspace_are_mutually_exclusive(tmp_path, monkeypatch):
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    caught = None
    try:
        launcher(tmp_path).argv(
            ("/usr/bin/python3",), workspace=tmp_path / "workspace", posture=Posture.READ,
            native_store=mount(positive),
        )
    except ContractViolation as exc:
        caught = exc
    assert caught is not None, "one namespace received both store and workspace"


@pytest.mark.parametrize("fds", [
    {"configuration_fd": 731}, {"credential_fd": 731},
    {"configuration_fd": CREDENTIAL_FD}, {"credential_fd": -1}, {"configuration_fd": True},
])
def test_the_native_layout_requires_three_distinct_descriptors(fds):
    with pytest.raises(ContractViolation, match="three distinct descriptors"):
        mount(positive, **fds)


def test_distinct_descriptors_are_the_accepting_twin():
    assert mount(positive).mount_fds == (CONFIGURATION_FD, CREDENTIAL_FD)


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
                native_store=mount(verify, guard.fileno()),
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
                native_store=mount(verify, guard.fileno() + 999),
            )
        except (ContractViolation, OSError) as exc:
            caught = exc
        assert caught is not None
    assert called == []


async def test_a_mount_descriptor_that_is_also_a_guard_never_reaches_the_check(
    tmp_path, monkeypatch,
):
    """A guard reaches only the supervisor; a mount descriptor reaches bwrap."""

    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    called = []

    def verify():
        called.append("checked")
        return positive()

    async def spawn(*args, **kwargs):
        raise OSError("test stops at spawn; no process is created")

    monkeypatch.setattr(linux.asyncio, "create_subprocess_exec", spawn)
    caught = None
    with (tmp_path / "guard").open("wb") as guard:
        store = mount(verify, guard.fileno(), credential_fd=guard.fileno() + 1)
        try:
            await launcher(tmp_path)._run(
                ("/usr/bin/python3",), workspace=None, posture=Posture.READ,
                guard_fds=(guard.fileno(), guard.fileno() + 1),
                deadline=asyncio.get_running_loop().time() + 5, native_store=store,
            )
        except (ContractViolation, OSError) as exc:
            caught = exc
    assert isinstance(caught, ContractViolation) and "cannot also be a guard" in str(caught)
    assert called == []


@pytest.mark.parametrize("native", [True, False], ids=["native", "worker"])
async def test_the_supervisor_alone_is_told_which_descriptors_bwrap_receives(
    tmp_path, monkeypatch, native,
):
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    spawned = []

    async def spawn(*args, **kwargs):
        spawned.append((args, kwargs))
        raise OSError("test stops at spawn; no process is created")

    monkeypatch.setattr(linux.asyncio, "create_subprocess_exec", spawn)
    with (tmp_path / "guard").open("wb") as guard, pytest.raises((ContractViolation, OSError)):
        await launcher(tmp_path)._run(
            ("/usr/bin/python3",), workspace=None, posture=Posture.READ,
            guard_fds=(guard.fileno(),), deadline=asyncio.get_running_loop().time() + 5,
            native_store=mount(positive, guard.fileno()) if native else None,
        )
    ((args, kwargs),) = spawned
    marker = f"--mount-fds={CONFIGURATION_FD},{CREDENTIAL_FD}"
    if native:
        # The flag follows the report descriptor and precedes bwrap's own argv.
        report = next(index for index, item in enumerate(args) if item.startswith("--report-fd="))
        assert args[report + 1] == marker
        assert args[report + 2].endswith("bwrap")
        assert {CONFIGURATION_FD, CREDENTIAL_FD} <= set(kwargs["pass_fds"])
    else:
        assert not any(str(item).startswith("--mount-fds=") for item in args)
        assert CONFIGURATION_FD not in kwargs["pass_fds"]


def test_sealed_native_data_refuses_off_linux(monkeypatch):
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="win32"))
    with pytest.raises(ContractViolation, match="requires Linux"):
        linux.sealed_data_fd(b"model = 'x'\n")
