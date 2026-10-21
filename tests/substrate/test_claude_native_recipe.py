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
    assert replace(vendor, expected_tree=digest("fake-vendor", 1, "other")).revision != vendor.revision


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
            return struct.pack("!i", 0)
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
    if ready == "cancel":
        with pytest.raises(asyncio.CancelledError):
            await subject._run(subject.claude.command, **arguments)
    elif ready in [b"\x00", b"", "exited", "ready-exit", "bound"]:
        with pytest.raises(linux.ProcessExchangeError):
            await subject._run(subject.claude.command, **arguments)
    else:
        result = await subject._run(subject.claude.command, **arguments)
        assert result.payload_returncode == 0
        assert result.timed_out == (ready == "deadline")
    assert "joined" in events and "stdin-closed" in events
    assert ("conversation" in events) == (ready == b"\x01")
    assert ("stdin" in events) == (ready == b"\x01")
    if ready == b"\x01":
        assert "ready" in events
        assert events.index("ready") < events.index("conversation") < events.index("stdin")
    assert read_sizes[0] == 1 and read_sizes[-1] == 5
