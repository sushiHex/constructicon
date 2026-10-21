"""Finite Claude recipe; platform primitives only are substituted on Windows."""

import asyncio
import json
import os
import stat
import struct
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.substrate.executors import linux
from constructicon.substrate.executors.claude_startup import fixed_environment, fixed_policy
from constructicon.substrate.executors.operator_store import BindingCheck

EXPECTED_TREE = digest("fake-vendor", 1, "fixed bytes")


def recipe_module():
    from constructicon.substrate.executors import claude_native

    return claude_native


def test_successor_environment_is_finite_initial_and_uses_only_fixed_bridge():
    native = recipe_module()
    expected = {**fixed_environment(), "HTTPS_PROXY": "http://127.0.0.1:18080",
                "HOME": "/tmp/home", "PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
                "CLAUDE_CONFIG_DIR": native.CONFIG_ROOT,
                "CLAUDE_SECURESTORAGE_CONFIG_DIR": native.SECURE_ROOT,
                "ANTHROPIC_CONFIG_DIR": native.ANTHROPIC_ROOT,
                "CLAUDE_CODE_ENTRYPOINT": "sdk-cli"}
    assert native.native_environment() == expected
    assert fixed_environment()["HTTPS_PROXY"] == ""
    changed = native.native_environment()
    changed["ANTHROPIC_API_KEY"] = "fake-untrusted"
    assert native.native_environment() == expected


def test_fixed_command_has_no_prompt_or_expansion_and_seals_model_effort(tmp_path):
    native = recipe_module()
    vendor = native.ClaudeNativeVendor(tmp_path / "claude", model="model", effort="high",
                                       expected_tree=EXPECTED_TREE)
    assert vendor.command == (native.EXECUTABLE, "--print", "--input-format", "stream-json",
                              "--output-format", "stream-json", "--verbose", "--safe-mode",
                              "--tools", "", "--model", "model", "--effort", "high")
    assert replace(vendor, model="other").revision != vendor.revision
    assert replace(vendor, effort="low").revision != vendor.revision
    other_tree = replace(vendor, expected_tree=digest("fake-vendor", 1, "other"))
    assert other_tree.revision != vendor.revision


@pytest.mark.parametrize("selection", [
    {"model": ""}, {"model": "--model"}, {"model": "a/b"}, {"model": "a" * 129},
    {"effort": "auto"}, {"effort": ""}, {"model": True},
])
def test_unsealed_or_invalid_selection_refuses(tmp_path, selection):
    native = recipe_module()
    with pytest.raises(ContractViolation):
        native.ClaudeNativeVendor(tmp_path / "claude", expected_tree=EXPECTED_TREE, **{
            "model": "model", "effort": "high", **selection})


def test_layout_seals_only_fixed_admin_sources_and_closes_on_partial_failure(monkeypatch):
    native = recipe_module()
    sealed, closed = {}, []

    def seal(data):
        fd = len(sealed) + 701
        sealed[fd] = data
        return fd

    monkeypatch.setattr(linux, "sealed_data_fd", seal)
    monkeypatch.setattr(native.os, "close", closed.append)
    layout = native.ClaudeNativeLayout.seal()
    assert json.loads(sealed[layout.policy_fd]) == fixed_policy()
    assert json.loads(sealed[layout.mcp_fd]) == {"mcpServers": {}}
    assert layout.mount_fds == (layout.policy_fd, layout.mcp_fd)
    layout.close()
    assert closed == list(sealed)
    closed.clear()

    def fail_second(data):
        if data == native.MANAGED_MCP:
            raise OSError("fake seal failure")
        return 801

    monkeypatch.setattr(linux, "sealed_data_fd", fail_second)
    with pytest.raises(OSError, match="fake seal failure"):
        native.ClaudeNativeLayout.seal()
    assert closed == [801]


def test_store_has_exactly_one_persistent_mount_and_distinct_guard():
    native = recipe_module()
    store = native.ClaudeNativeStoreMount(731, 732, lambda: None)
    assert store.mount_fds == (732,)
    for lock, credential in [(1, 1), (-1, 2), (1, -2), (True, 2), (1, False)]:
        with pytest.raises(ContractViolation):
            native.ClaudeNativeStoreMount(lock, credential, lambda: None)
        with pytest.raises(ContractViolation):
            native.ClaudeNativeLayout(lock, credential)


@pytest.mark.parametrize("damage", [None, "symlink", "directory-write", "file-write",
                                    "ancestor-link", "owner", "not-executable"])
def test_claude_vendor_custody_accepts_fixed_tree_and_refuses_each_widening(
    tmp_path, monkeypatch, damage,
):
    native = recipe_module()
    tree = tmp_path / "vendor"
    tree.mkdir()
    (tree / "claude").write_bytes(b"fake source, never executed")
    stat_path, lstat_path = os.stat, os.lstat

    def reported(path, *args, **kwargs):
        path = Path(path)
        info = lstat_path(path, *args, **kwargs)
        kind = stat.S_IFMT(info.st_mode)
        mode = 0o755 if stat.S_ISDIR(info.st_mode) or path == tree / "claude" else 0o444
        owner = 0
        if damage == "symlink" and path == tree / "claude":
            kind = stat.S_IFLNK
        if damage == "ancestor-link" and path == tree.parent:
            kind = stat.S_IFLNK
        if damage == "directory-write" and path == tree:
            mode = 0o777
        if damage == "file-write" and path == tree / "claude":
            mode = 0o777
        if damage == "owner" and path == tree / "claude":
            owner = 1000
        if damage == "not-executable" and path == tree / "claude":
            mode = 0o444
        return SimpleNamespace(st_mode=kind | mode, st_uid=owner)

    # Keep the real directory traversal, replace only reported Unix metadata.
    monkeypatch.setattr(native, "os", SimpleNamespace(**{
        **vars(os), "lstat": reported, "stat": stat_path,
    }))
    vendor = native.ClaudeNativeVendor(tree, model="model", effort="high",
                                       expected_tree=EXPECTED_TREE)
    if damage is None:
        vendor.check()
    else:
        with pytest.raises(ContractViolation):
            vendor.check()


def launcher(tmp_path):
    native = recipe_module()
    return linux.LinuxLauncher(
        runtime_root=tmp_path / "runtime", expected_runtime=digest("runtime", 1, "test"),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="0" * 64,
        claude=native.ClaudeNativeVendor(tmp_path / "claude", model="model", effort="high",
                                        expected_tree=EXPECTED_TREE),
    )


@pytest.fixture
def on_linux(monkeypatch):
    monkeypatch.setattr(linux, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(linux, "os", SimpleNamespace(**{
        **vars(os), "getuid": lambda: 1000, "getgid": lambda: 1000,
    }))


@pytest.mark.parametrize("drift", [False, True])
def test_artifact_check_seals_actual_vendor_bytes_before_native_launch(
    tmp_path, on_linux, monkeypatch, drift,
):
    native = recipe_module()
    subject = launcher(tmp_path)
    subject.root.mkdir()
    subject.claude.tree.mkdir()
    executable = subject.claude.tree / "claude"
    executable.write_bytes(b"fixed nonvendor bytes, never executed")
    actual_digest, actual_sha = linux.runtime_digest, linux._sha
    expected_runtime = actual_digest(subject.root, require_immutable=False)
    subject = replace(subject, expected_runtime=expected_runtime,
                      claude=replace(subject.claude, expected_tree=actual_digest(
                          subject.claude.tree, require_immutable=False)))
    checked = []
    monkeypatch.setattr(native.ClaudeNativeVendor, "check", lambda self: checked.append(True))
    monkeypatch.setattr(linux, "runtime_digest", lambda root: actual_digest(
        root, require_immutable=False))
    monkeypatch.setattr(linux, "require_fixed_artifact", lambda path: None)
    monkeypatch.setattr(linux, "_sha", lambda path: (
        linux.BWRAP_SHA256 if path == subject.bubblewrap
        else "0" * 64 if path == subject.policy else actual_sha(path)))
    monkeypatch.setattr(linux.Path, "read_text", lambda self: "1\n")
    if drift:
        executable.write_bytes(b"different nonvendor bytes, never executed")
        with pytest.raises(ContractViolation, match="Claude vendor content"):
            subject.check_artifacts()
    else:
        subject.check_artifacts()
    assert checked == [True]


def test_a_claude_launch_requires_its_egress_bridge(tmp_path, on_linux):
    native = recipe_module()
    subject = launcher(tmp_path)
    store = native.ClaudeNativeStoreMount(731, 732, lambda: None)
    with pytest.raises(ContractViolation, match="egress"):
        subject.argv(subject.claude.command, workspace=None, posture=Posture.READ,
                     native_store=store, layout=native.ClaudeNativeLayout(733, 734))


def egress(tmp_path, events):
    return SimpleNamespace(path=tmp_path / "leaf", require_current=lambda: events.append("leaf"))


def test_accepting_mount_recipe_has_one_persistent_file_and_disjoint_admin_ancestors(
    tmp_path, on_linux,
):
    native = recipe_module()
    subject = launcher(tmp_path)
    events = []
    store = native.ClaudeNativeStoreMount(731, 732, lambda: None, egress(tmp_path, events))
    args = subject.argv(subject.claude.command, workspace=None, posture=Posture.READ,
                        native_store=store, layout=native.ClaudeNativeLayout(733, 734))
    assert args.count("--bind-fd") == 1 and "--bind" not in args
    assert args[args.index("--bind-fd"):args.index("--bind-fd") + 3] == [
        "--bind-fd", "732", native.CREDENTIAL_MOUNT]
    for directory in [native.CONFIG_ROOT, native.STORAGE_PARENT, native.SECURE_ROOT,
                      native.ANTHROPIC_ROOT]:
        index = args.index(directory)
        assert args[index - 3:index] == ["--perms", "0700", "--dir"]
        assert not native.ADMIN_ROOT.startswith(directory + "/")
    assert args.count("--ro-bind-data") == 2
    assert args[args.index("--"):][1:] == [
        "/usr/bin/python3", "-I", linux.BRIDGE_SCRIPT, *subject.claude.command]
    assert "/workspace" not in args and "CODEX_HOME" not in args
    actual_env = {args[index + 1]: args[index + 2]
                  for index, item in enumerate(args) if item == "--setenv"}
    assert actual_env == native.native_environment()
    assert events == ["leaf"]


@pytest.mark.parametrize("damage", ["workspace", "command", "codex-store", "codex-layout"])
def test_mixed_or_widened_native_recipe_refuses(tmp_path, on_linux, damage):
    native = recipe_module()
    subject = launcher(tmp_path)
    store = native.ClaudeNativeStoreMount(731, 732, lambda: None, egress(tmp_path, []))
    arguments = {"workspace": None, "posture": Posture.READ,
                 "native_store": store, "layout": native.ClaudeNativeLayout(733, 734)}
    command = subject.claude.command
    if damage == "workspace":
        arguments["workspace"] = tmp_path
    elif damage == "command":
        command += ("--resume", "untrusted")
    elif damage == "codex-store":
        arguments["native_store"] = linux.NativeStoreMount(731, 732, 735, lambda: None)
    else:
        arguments["layout"] = linux.NativeLayout(733, None)
    with pytest.raises(ContractViolation):
        subject.argv(command, **arguments)


@pytest.mark.parametrize("damage", ["absent-lock", "guard-as-mount", "duplicate-mount"])
async def test_native_guards_never_cross_mount_custody(tmp_path, on_linux, damage):
    native = recipe_module()
    subject = launcher(tmp_path)
    checked = []
    store = native.ClaudeNativeStoreMount(731, 732, lambda: checked.append(True),
                                         egress(tmp_path, []))
    layout = native.ClaudeNativeLayout(733, 734)
    guards = (731,)
    if damage == "absent-lock":
        guards = (735,)
    elif damage == "guard-as-mount":
        guards = (731, 732)
    else:
        layout = native.ClaudeNativeLayout(732, 734)
    with pytest.raises(ContractViolation):
        await subject._run(
            subject.claude.command, workspace=None, posture=Posture.READ,
            guard_fds=guards, deadline=asyncio.get_running_loop().time() + 2,
            native_store=store, layout=layout,
        )
    assert checked == []


@pytest.mark.parametrize("ready", [b"\x01", b"\x00", b"", "exited", "ready-exit",
                                  "deadline", "bound", "cancel"])
async def test_conversation_waits_for_private_transition_and_joins_all_paths(
    tmp_path, on_linux, monkeypatch, ready,
):
    native = recipe_module()
    subject = launcher(tmp_path)
    events, read_sizes = [], []
    authorized, polls = False, 0

    class Writer:
        def write(self, data):
            events.append("stdin")

        async def drain(self):
            await asyncio.sleep(0)

        def close(self):
            events.append("stdin-closed")

    process = SimpleNamespace(stdin=Writer(), stdout=asyncio.StreamReader(),
                              stderr=asyncio.StreamReader(), returncode=None)
    process.stdout.feed_data(b"before readiness\n")
    process.stdout.feed_eof()
    process.stderr.feed_eof()

    async def wait():
        events.append("joined")
        process.returncode = 0
        return 0

    process.wait = wait

    async def spawn(*args, **kwargs):
        assert f"--native-label={native.CLAUDE_PROFILE}" in args
        assert {732, 733, 734} <= set(kwargs["pass_fds"])
        events.append("spawn")
        return process

    def read(fd, maximum):
        nonlocal polls
        read_sizes.append(maximum)
        if maximum != 1:
            value = struct.pack("!i", 0)
            return value[1:] if ready == b"\x00" else value
        assert authorized, "trusted bootstrap must first receive owned-start authorization"
        polls += 1
        if polls == 1:
            if ready == "cancel":
                asyncio.get_running_loop().call_soon(asyncio.current_task().cancel)
            raise BlockingIOError
        if ready == "deadline":
            raise BlockingIOError
        if ready == "exited":
            process.returncode = 125
            raise BlockingIOError
        if ready == "bound":
            raise BlockingIOError
        events.append("ready")
        if ready == "ready-exit":
            process.returncode = 125
            return b"\x01"
        return ready

    def write(fd, data):
        nonlocal authorized
        assert data == b"\x01"
        authorized = True
        return 1

    async def conversation(io):
        events.append("conversation")
        assert await io.read() == b"before readiness\n"
        assert await io.read() == b""
        await io.write(b"request")

    monkeypatch.setattr(linux.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(linux.os, "set_blocking", lambda fd, blocking: None, raising=False)
    monkeypatch.setattr(linux.os, "read", read)
    monkeypatch.setattr(linux.os, "write", write)
    if ready == "bound":
        subject = replace(subject, limits=replace(subject.limits, stdout_bytes=1))
    store = native.ClaudeNativeStoreMount(731, 732, lambda: BindingCheck(
        binding_digest=digest("test-binding", 1, "fake")), egress(tmp_path, []))
    deadline = asyncio.get_running_loop().time() + (.04 if ready == "deadline" else 2)
    arguments = dict(workspace=None, posture=Posture.READ, guard_fds=(731,), deadline=deadline,
                     conversation=conversation, native_store=store,
                     layout=native.ClaudeNativeLayout(733, 734))
    try:
        outcome = await subject._run(subject.claude.command, **arguments)
    except BaseException as failure:
        outcome = failure
    # Assert the actual completion class, including malformed cleanup failures.
    # An unexpected exception is a failed contract assertion, not a harness error
    # that hides the accepting/refusing controls in other parameter cases.
    if ready == "cancel":
        assert isinstance(outcome, asyncio.CancelledError)
    elif ready in [b"\x00", b"", "exited", "ready-exit", "bound"]:
        assert isinstance(outcome, linux.ProcessExchangeError)
    else:
        assert isinstance(outcome, linux.ProcessResult)
        assert outcome.payload_returncode == 0
        assert outcome.timed_out == (ready == "deadline")
    assert "joined" in events and "stdin-closed" in events
    assert ("conversation" in events) == (ready == b"\x01")
    assert ("stdin" in events) == (ready == b"\x01")
    if ready == b"\x01":
        assert "ready" in events
        assert events.index("ready") < events.index("conversation") < events.index("stdin")
    last_read = 5 if ready in [b"\x00", b"\x01", "ready-exit"] else 6
    assert read_sizes[0] == 1 and read_sizes[-1] == last_read


@pytest.mark.parametrize("reported", [0, 125, 126, "truncated", "surplus", "invalid-code"])
async def test_exit_record_before_readiness_is_preserved_and_damage_still_refuses(
    tmp_path, on_linux, monkeypatch, reported,
):
    """Use a real pipe: one readiness read consumes the exit record's first byte."""
    native = recipe_module()
    subject = launcher(tmp_path)
    events = []
    report = struct.pack("!i", reported if type(reported) is int else 125)
    if reported == "truncated":
        report = report[:-1]
    elif reported == "surplus":
        report += b"x"
    elif reported == "invalid-code":
        report = struct.pack("!i", 256)

    class Writer:
        def close(self):
            events.append("stdin-closed")

    process = SimpleNamespace(stdin=Writer(), stdout=asyncio.StreamReader(),
                              stderr=asyncio.StreamReader(), returncode=None)
    process.stdout.feed_eof()
    process.stderr.feed_data(b"constructicon egress bridge refused: exec\n")
    process.stderr.feed_eof()

    async def wait():
        events.append("joined")
        process.returncode = 125
        return 125

    process.wait = wait

    async def spawn(*args, **kwargs):
        report_fd = int(next(arg.split("=", 1)[1] for arg in args
                             if arg.startswith("--report-fd=")))
        assert os.write(report_fd, report) == len(report)
        return process

    async def conversation(_io):
        events.append("conversation")

    monkeypatch.setattr(linux.asyncio, "create_subprocess_exec", spawn)
    # Every real pipe read below has bytes waiting. Windows Python 3.11 lacks
    # the Linux pipe nonblocking primitive; no pipe data or read is substituted.
    monkeypatch.setattr(linux.os, "set_blocking", lambda fd, blocking: None, raising=False)
    store = native.ClaudeNativeStoreMount(731, 732, lambda: BindingCheck(
        binding_digest=digest("test-binding", 1, "fake")), egress(tmp_path, []))
    arguments = dict(workspace=None, posture=Posture.READ, guard_fds=(731,),
                     deadline=asyncio.get_running_loop().time() + 2,
                     conversation=conversation, native_store=store,
                     layout=native.ClaudeNativeLayout(733, 734))
    if type(reported) is int:
        refusal = None
        try:
            await subject._run(subject.claude.command, **arguments)
        except Exception as exc:
            refusal = exc
        assert isinstance(refusal, linux.ProcessExchangeError), refusal
        assert refusal.result.returncode == 125
        assert refusal.result.payload_returncode == reported
        assert isinstance(refusal.__cause__, ContractViolation)
        assert str(refusal.__cause__) == "native transition was not affirmed"
    else:
        with pytest.raises(ExceptionGroup) as damaged:
            await subject._run(subject.claude.command, **arguments)
        failures = damaged.value.exceptions
        assert len(failures) == 2 and all(isinstance(f, ContractViolation) for f in failures)
        assert str(failures[0]) == "native transition was not affirmed"
        expected = "invalid" if reported == "invalid-code" else "malformed"
        assert str(failures[1]) == f"{expected} private payload exit report"
    assert events == ["stdin-closed", "joined"]


@pytest.mark.parametrize("stop", ["cancel", "deadline", "bound"])
@pytest.mark.parametrize("frame", ["valid", "duplicate", "surplus", "truncated", "ready-only"])
async def test_late_private_readiness_is_transport_only_and_damage_stays_damage(
    tmp_path, on_linux, monkeypatch, stop, frame,
):
    """Actual late bytes arrive in the pipe only when joined shutdown starts."""
    native = recipe_module()
    subject = launcher(tmp_path)
    events = []
    private_fd = None
    actual_read = os.read
    loop = asyncio.get_running_loop()
    actual_time = loop.time
    clock_offset = 0.0
    if stop == "deadline":
        monkeypatch.setattr(loop, "time", lambda: actual_time() + clock_offset)
    report = b"\x01" + struct.pack("!i", 125)
    if frame == "duplicate":
        report = b"\x01" + report
    elif frame == "surplus":
        report += b"x"
    elif frame == "truncated":
        report = report[:-1]
    elif frame == "ready-only":
        report = report[:1]

    class Writer:
        def close(self):
            events.append("stdin-closed")

    process = SimpleNamespace(stdin=Writer(), stdout=asyncio.StreamReader(),
                              stderr=asyncio.StreamReader(), returncode=None)
    if stop != "bound":
        process.stdout.feed_eof()
    process.stderr.feed_eof()

    async def wait():
        events.append("joined")
        assert os.write(private_fd, report) == len(report)
        process.returncode = 125
        return 125

    process.wait = wait

    async def spawn(*args, **kwargs):
        nonlocal private_fd
        private_fd = int(next(arg.split("=", 1)[1] for arg in args
                              if arg.startswith("--report-fd=")))
        return process

    def read(fd, maximum):
        nonlocal clock_offset
        if maximum == 1:
            if not events:
                events.append("readiness-pending")
                if stop == "cancel":
                    asyncio.current_task().cancel()
                elif stop == "deadline":
                    # Expire only after entering the intended readiness await.
                    clock_offset = 61.0
                elif stop == "bound":
                    process.stdout.feed_data(b"xx")
                    process.stdout.feed_eof()
            raise BlockingIOError
        return actual_read(fd, maximum)

    async def conversation(_io):
        events.append("conversation")

    monkeypatch.setattr(linux.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(linux.os, "set_blocking", lambda *args: None, raising=False)
    monkeypatch.setattr(linux.os, "read", read)
    if stop == "bound":
        subject = replace(subject, limits=replace(subject.limits, stdout_bytes=1))
    store = native.ClaudeNativeStoreMount(731, 732, lambda: BindingCheck(
        binding_digest=digest("test-binding", 1, "fake")), egress(tmp_path, []))
    failure, result = None, None
    try:
        result = await subject._run(
            subject.claude.command, workspace=None, posture=Posture.READ,
            guard_fds=(731,), deadline=loop.time() + (60 if stop == "deadline" else 2),
            conversation=conversation, native_store=store,
            layout=native.ClaudeNativeLayout(733, 734),
        )
    except BaseException as exc:
        failure = exc
    finally:
        clock_offset = 0.0
    assert events[0] == "readiness-pending" and events.count("joined") == 1
    assert set(events) == {"readiness-pending", "stdin-closed", "joined"}
    assert events.index("stdin-closed") < events.index("joined")
    if frame in {"valid", "ready-only"}:
        expected_exit = 125 if frame == "valid" else None
        if stop == "cancel":
            assert isinstance(failure, asyncio.CancelledError), failure
        elif stop == "deadline":
            assert failure is None, failure
            assert result.timed_out and result.payload_returncode == expected_exit
        else:
            assert isinstance(failure, linux.ProcessExchangeError), failure
            assert failure.result.bound_exceeded == "stdout"
            assert failure.result.payload_returncode == expected_exit
    else:
        if stop == "deadline":
            assert isinstance(failure, ContractViolation), failure
            failures = (failure,)
        else:
            assert isinstance(failure, BaseExceptionGroup), failure
            failures = failure.exceptions
            assert len(failures) == 2
        assert any(isinstance(item, ContractViolation)
                   and str(item) == "malformed private payload exit report" for item in failures)


async def test_consumed_readiness_cannot_hide_a_duplicate_frame_during_cleanup(
    tmp_path, on_linux, monkeypatch,
):
    native = recipe_module()
    subject = launcher(tmp_path)
    events = []
    private_fd = None

    class Writer:
        def close(self):
            events.append("stdin-closed")

    process = SimpleNamespace(stdin=Writer(), stdout=asyncio.StreamReader(),
                              stderr=asyncio.StreamReader(), returncode=None)
    process.stdout.feed_eof()
    process.stderr.feed_eof()

    async def wait():
        events.append("joined")
        assert os.write(private_fd, b"\x01" + struct.pack("!i", 125)) == 5
        process.returncode = 125
        return 125

    process.wait = wait

    async def spawn(*args, **kwargs):
        nonlocal private_fd
        private_fd = int(next(arg.split("=", 1)[1] for arg in args
                              if arg.startswith("--report-fd=")))
        assert os.write(private_fd, b"\x01") == 1
        return process

    async def conversation(_io):
        events.append("conversation")
        raise asyncio.CancelledError

    monkeypatch.setattr(linux.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(linux.os, "set_blocking", lambda *args: None, raising=False)
    store = native.ClaudeNativeStoreMount(731, 732, lambda: BindingCheck(
        binding_digest=digest("test-binding", 1, "fake")), egress(tmp_path, []))
    failure = None
    try:
        await subject._run(
            subject.claude.command, workspace=None, posture=Posture.READ,
            guard_fds=(731,), deadline=asyncio.get_running_loop().time() + 2,
            conversation=conversation, native_store=store,
            layout=native.ClaudeNativeLayout(733, 734),
        )
    except BaseException as exc:
        failure = exc
    assert isinstance(failure, BaseExceptionGroup), failure
    assert len(failure.exceptions) == 2
    assert isinstance(failure.exceptions[0], asyncio.CancelledError)
    assert isinstance(failure.exceptions[1], ContractViolation)
    assert str(failure.exceptions[1]) == "malformed private payload exit report"
    assert events[0] == "conversation" and events.count("joined") == 1
    assert set(events) == {"conversation", "stdin-closed", "joined"}
    assert events.index("stdin-closed") < events.index("joined")
