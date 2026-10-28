"""C fake wire conformance and distinct hosted native/READ-worker composition."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from constructicon.core.executor import ExecutorSuccess, TaskSpec, Usage
from constructicon.substrate.executors.claude_protocol import ClaudePlan
from constructicon.substrate.executors.claude_read import (
    ClaudeReadTransaction,
    _Refused,
    run_read_transaction,
)
from constructicon.substrate.executors.claude_read_worker import (
    READ_WORKER_LIMITS,
    ClaudeReadWorker,
)
from tests.gitworld import SEED_CALC
from tests.substrate.test_claude_native_containment import claude_launcher as claude_launcher
from tests.substrate.test_claude_native_containment import fake_mount
from tests.substrate.test_contained_workspace import context
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher
from tests.substrate.test_native_codex_mediation import write_evidence

MODELS = ("fixture-read", "fixture-zero")


@pytest.fixture(scope="module")
def wire_peer(tmp_path_factory):
    """Compile only the portable wire function, never the Linux boundary fixture."""
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("portable C fixture conformance needs a C compiler")
    directory = tmp_path_factory.mktemp("claude-wire")
    header = Path(__file__).parents[2] / "scripts/ci/m8_claude_wire.h"
    source = directory / "wire.c"
    source.write_text(
        f'#include "{header.as_posix()}"\n'
        'int main(int argc, char **argv) { setvbuf(stdout, NULL, _IONBF, 0); '
        'int result = claude_wire(argc, argv); return result < 0 ? 98 : result; }\n',
        encoding="utf-8",
    )
    binary = directory / ("wire.exe" if sys.platform == "win32" else "wire")
    compiled = subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2",
         str(source), "-o", str(binary)],
        stdin=subprocess.DEVNULL, capture_output=True, check=False, timeout=30,
    )
    assert compiled.returncode == 0, compiled.stderr.decode(errors="replace")
    return binary


@pytest.mark.parametrize("model", (*MODELS, "fixture-ready"))
async def test_compiled_fake_peer_completes_the_actual_bounded_read_protocol(wire_peer, model):
    """Portable wire/transaction evidence only; no isolation is claimed here."""
    command = (str(wire_peer), "--print", "--input-format", "stream-json", "--output-format",
               "stream-json", "--verbose", "--safe-mode", "--tools", "",
               "--permission-mode", "default",
               "--allowedTools", "mcp__constructicon_read__read_file", "--model", model,
               "--effort", "low")
    child = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    calls = []

    async def worker(path, remaining):
        calls.append((path, remaining))
        return "ready\n" if model == "fixture-ready" else SEED_CALC

    class Channel:
        async def read(self, maximum=8192):
            return await child.stdout.read(maximum)

        async def write(self, data):
            child.stdin.write(data)
            await child.stdin.drain()

        async def close_stdin(self):
            child.stdin.close()
            await child.stdin.wait_closed()

    transaction = ClaudeReadTransaction(
        TaskSpec(instruction="Read calc.py literally."), selected_plan=ClaudePlan.PRO,
        model=model, effort="low", worker=worker, input_limit=1024 * 1024,
        output_limit=1024 * 1024, deadline=asyncio.get_running_loop().time() + 10,
    )
    try:
        async with asyncio.timeout(10):
            await transaction(Channel())
            assert await child.wait() == 0
            assert await child.stderr.read() == b""
    finally:
        if child.returncode is None:
            child.kill()
        await child.wait()
    assert transaction._state == "drained" and transaction._handshake == 3
    assert transaction._calls_completed == (0 if model == "fixture-zero" else 1)
    assert transaction._reply == {"fixture-read": SEED_CALC, "fixture-ready": "ready\n",
                                  "fixture-zero": "zero-callback"}[model]
    assert len(calls) == (0 if model == "fixture-zero" else 1)
    if calls:
        assert calls[0][0] == ("ready.txt" if model == "fixture-ready" else "calc.py")
        assert 0 < calls[0][1] <= 10


@pytest.mark.parametrize("kinds", [("initialize",),
                                  ("initialize", "get_settings", "get_hooks_listing")])
def test_compiled_fake_peer_closes_after_maintenance_observations(wire_peer, kinds):
    command = (str(wire_peer), "--print", "--input-format", "stream-json", "--output-format",
               "stream-json", "--verbose", "--safe-mode", "--tools", "",
               "--permission-mode", "default",
               "--allowedTools", "mcp__constructicon_read__read_file", "--model",
               "fixture-ready", "--effort", "low")
    frames = b"".join((json.dumps({"type": "control_request", "request_id": str(index),
                                   "request": {"subtype": kind}}, separators=(",", ":"))
                       + "\n").encode() for index, kind in enumerate(kinds))
    result = subprocess.run(command, input=frames, capture_output=True, check=False, timeout=10)
    assert result.returncode == 0 and result.stderr == b""
    records = [json.loads(line) for line in result.stdout.splitlines()]
    assert [row["response"]["request_id"] for row in records] == [
        str(index) for index in range(len(kinds))
    ]


async def test_maintenance_eof_cannot_complete_a_read(wire_peer):
    command = (str(wire_peer), "--print", "--input-format", "stream-json", "--output-format",
               "stream-json", "--verbose", "--safe-mode", "--tools", "",
               "--permission-mode", "default",
               "--allowedTools", "mcp__constructicon_read__read_file", "--model",
               "fixture-ready", "--effort", "low")
    child = await asyncio.create_subprocess_exec(
        *command, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    calls = []

    async def worker(path, remaining):
        calls.append((path, remaining))
        return "ready\n"

    class EarlyClose:
        async def read(self, maximum=8192):
            return await child.stdout.read(maximum)

        async def write(self, data):
            if child.stdin.is_closing():
                return
            child.stdin.write(data)
            await child.stdin.drain()
            child.stdin.close()
            await child.stdin.wait_closed()

        async def close_stdin(self):
            child.stdin.close()

    transaction = ClaudeReadTransaction(
        TaskSpec(instruction="Read ready.txt."), selected_plan=ClaudePlan.PRO,
        model="fixture-ready", effort="low", worker=worker, input_limit=1024 * 1024,
        output_limit=1024 * 1024, deadline=asyncio.get_running_loop().time() + 10,
    )
    try:
        async with asyncio.timeout(10):
            with pytest.raises(_Refused):
                await transaction(EarlyClose())
            assert await child.wait() == 0
            assert await child.stderr.read() == b""
    finally:
        if child.returncode is None:
            child.kill()
        await child.wait()
    assert transaction._state == "refused" and not calls and transaction._reply is None


@pytest.mark.parametrize("model", MODELS)
async def test_actual_native_read_composition_joins_both_zones(
    claude_launcher, launcher, provider, tmp_path, model,
):
    """The same READ transaction uses the real native and worker launch recipes."""
    native = replace(claude_launcher, claude=replace(claude_launcher.claude, model=model))
    ctx = context()
    acquired = await provider.acquire(ctx)
    await acquired.materialize()
    worker_launcher = replace(launcher, limits=READ_WORKER_LIMITS)
    read = ClaudeReadWorker(provider=provider, context=ctx, workspace=acquired.resource,
                            launcher=worker_launcher)
    completed, bindings = [], []

    async def worker(path, remaining):
        text = await read(path, remaining)
        completed.append((path, text))
        return text

    directory = tmp_path / "fake-native-store"
    directory.mkdir()
    try:
        with fake_mount(directory) as (mount, credential, received, failures, peer):
            original = mount.before_spawn

            def checked_binding():
                checked = original()
                bindings.append(checked)
                return checked

            mount = replace(mount, before_spawn=checked_binding)
            outcome = await run_read_transaction(
                native, native.claude.command, TaskSpec(instruction="Read calc.py literally."),
                selected_plan=ClaudePlan.PRO, model=model, effort="low", worker=worker,
                guard_fds=(mount.lock_fd,), timeout_s=30, native_store=mount,
            )
            assert isinstance(outcome, ExecutorSuccess), outcome
            assert outcome.raw_reply == (SEED_CALC if model == "fixture-read" else "zero-callback")
            assert outcome.usage == Usage(input_tokens=1, output_tokens=1)
            assert outcome.served_model is None and 0 < outcome.elapsed_s <= 30
            assert completed == ([("calc.py", SEED_CALC)] if model == "fixture-read" else [])
            assert len(bindings) == 3 and bindings[0] == bindings[1] == bindings[2]
            assert peer.ident is None and received == [] and failures == []
            assert credential.read_bytes() == b"fake-initial\n"
            assert Path(acquired.resource.path, "calc.py").read_text() == SEED_CALC
    finally:
        closed = await provider.close(acquired, "discard")
    assert closed.disposition == "discarded"
    write_evidence(f"n6-claude-native-read-{model}.json", {
        "schema_version": 1, "scope": "fake_physical_native_read_composition",
        "production_available": False, "claude_qualified": False,
        "native_launch_revision": str(native.revision),
        "worker_launch_revision": str(worker_launcher.revision),
        "initial_and_terminal_observations": True, "actual_mcp_handshake": True,
        "correlated_terminal_and_eof": True, "joined_native_success": True,
        "completed_read_workers": len(completed), "workspace_discarded": True,
        "initial_spawn_terminal_binding_checks": len(bindings),
    })
