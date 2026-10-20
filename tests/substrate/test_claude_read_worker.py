"""Portable custody/controller proofs and separately provisioned Linux proofs."""

from __future__ import annotations

import asyncio
import copy
import os
import subprocess
import sys
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.core.grants import Posture
from constructicon.core.identity import digest
from constructicon.substrate.executors import claude_read_worker as worker
from constructicon.substrate.executors.linux import LinuxLauncher, ProcessLimits, ProcessResult
from constructicon.substrate.git import contained
from tests.gitworld import SEED_CALC
from tests.substrate.test_contained_workspace import context
from tests.substrate.test_contained_workspace import provider as provider
from tests.substrate.test_linux_containment import launcher as launcher


@pytest.fixture
async def custody(provider, monkeypatch, tmp_path):
    state = {"held": 0, "calls": []}

    @asynccontextmanager
    async def fake_guard(paths):
        # Only the platform-bound flock is substituted. Git export and closure
        # checks below remain real; this is not physical containment evidence.
        state["held"] += 1
        try:
            yield 77
        finally:
            state["held"] -= 1

    monkeypatch.setattr(contained, "acquisition_guard", fake_guard)
    ctx = context()
    acquired = await provider.acquire(ctx)
    await acquired.materialize()
    launch = LinuxLauncher(
        runtime_root=tmp_path / "runtime", expected_runtime=digest("test", 1, "runtime"),
        bubblewrap=tmp_path / "bwrap", policy=tmp_path / "policy",
        expected_policy_sha256="0" * 64, limits=worker.READ_WORKER_LIMITS,
    )

    async def run(self, command, **kwargs):
        assert state["held"] == 1
        state["calls"].append((command, kwargs))
        return ProcessResult(0, b"file bytes", b"", 0.01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", run)
    return provider, ctx, acquired, launch, state


def reader(custody):
    provider, ctx, acquired, launch, _ = custody
    return worker.ClaudeReadWorker(provider=provider, context=ctx,
                                  workspace=acquired.resource, launcher=launch)


async def test_fixed_read_uses_owned_view_read_posture_empty_input_and_remaining_deadline(custody):
    read = reader(custody)
    assert await read("calc.py", 30) == "file bytes"
    provider, _, acquired, _, state = custody
    assert state["held"] == 0
    command, kwargs = state["calls"][0]
    assert command == ("/usr/bin/python3", "-I", "-c", worker.READ_PROGRAM, "calc.py")
    assert kwargs == {"workspace": Path(acquired.resource.path), "posture": Posture.READ,
                      "guard_fds": (77,), "stdin": b"", "input_kind": "task",
                      "timeout_s": kwargs["timeout_s"]}
    assert 0 < kwargs["timeout_s"] < 30
    assert not provider.closure.is_closed(acquired.resource.paths)
    assert await read("test_calc.py", 30) == "file bytes"


@pytest.mark.parametrize("path", ["", "/absolute", "a//b", ".", "..", "a/../b", "a/./b",
                                  "a/", "a\\b", "C:relative", "a\x00b", "\ud800",
                                  "x" * 1025, None, True])
def test_one_shared_path_law_refuses_escape_ambiguity_and_bounds(path):
    assert worker.validate_read_path(path) is False


def test_path_bound_binds_utf8_bytes_and_embedded_program_uses_same_law():
    assert worker.validate_read_path("x" * 1024)
    assert worker.validate_read_path("é" * 512)
    assert not worker.validate_read_path("é" * 513)
    assert "def validate_read_path(value: object) -> bool:" in worker.READ_PROGRAM


def test_path_type_is_exact_even_for_a_string_subclass():
    class StringSubclass(str):
        pass

    assert worker.validate_read_path(StringSubclass("calc.py")) is False


@pytest.mark.parametrize("remaining", [True, 0, -1, float("inf"), float("nan"), "30"])
async def test_invalid_call_is_effect_free_and_permanently_refuses(custody, remaining):
    read = reader(custody)
    with pytest.raises(ContractViolation):
        await read("calc.py", remaining)
    with pytest.raises(ContractViolation):
        await read("calc.py", 30)
    assert not custody[-1]["calls"]


@pytest.mark.parametrize("field,value", [
    ("returncode", False), ("returncode", 1), ("payload_returncode", None),
    ("payload_returncode", False), ("payload_returncode", 1), ("timed_out", True),
    ("timed_out", None), ("bound_exceeded", "stdout"), ("stdout", b"x" * 65537),
    ("stdout", bytearray(b"bytes")), ("stdout", b"\xff"), ("stderr", b"x" * 1025),
], ids=["supervisor-bool", "supervisor-nonzero", "payload-absent", "payload-bool",
        "payload-nonzero", "timeout", "timeout-unknown", "bound", "stdout-large",
        "stdout-bytearray", "stdout-utf8", "stderr-large"])
async def test_process_completion_bounds_and_utf8_are_affirmative(
    custody, monkeypatch, field, value,
):
    result = replace(ProcessResult(0, b"ok", b"", 0.01, payload_returncode=0), **{field: value})

    async def run(self, *args, **kwargs):
        return result

    monkeypatch.setattr(LinuxLauncher, "run", run)
    with pytest.raises(ContractViolation):
        await reader(custody)("calc.py", 30)
    assert custody[-1]["held"] == 0


async def test_read_limit_accepts_exactly_64k(custody, monkeypatch):
    async def run(self, *args, **kwargs):
        return ProcessResult(0, b"x" * 65536, b"", 0.01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", run)
    assert len(await reader(custody)("calc.py", 30)) == 65536


async def test_process_evidence_cannot_be_a_matching_duck(custody, monkeypatch):
    async def run(self, *args, **kwargs):
        return SimpleNamespace(returncode=0, payload_returncode=0, timed_out=False,
                               bound_exceeded=None, stdout=b"unproved", stderr=b"")

    monkeypatch.setattr(LinuxLauncher, "run", run)
    with pytest.raises(ContractViolation, match="process refused"):
        await reader(custody)("calc.py", 30)


async def test_overlap_poison_is_not_cleared_by_first_worker_completion(custody, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()

    async def run(self, *args, **kwargs):
        started.set()
        await release.wait()
        return ProcessResult(0, b"must not publish", b"", 0.01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", run)
    read = reader(custody)
    first = asyncio.create_task(read("calc.py", 30))
    await started.wait()
    second = asyncio.create_task(read("calc.py", 30))
    try:
        await asyncio.sleep(0)
        assert second.done(), "overlap did not refuse before another worker await"
    finally:
        release.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
    assert all(isinstance(result, ContractViolation) for result in results)
    with pytest.raises(ContractViolation):
        await read("calc.py", 30)
    assert custody[-1]["held"] == 0


async def test_repeated_cancellation_joins_worker_before_guard_release(custody, monkeypatch):
    started, release, joined = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def run(self, *args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await release.wait()
            joined.set()

    monkeypatch.setattr(LinuxLauncher, "run", run)
    read = reader(custody)
    task = asyncio.create_task(read("calc.py", 30))
    await started.wait()
    task.cancel()
    try:
        await asyncio.sleep(0)
        assert custody[-1]["held"] == 1 and not task.done()
        task.cancel()
    finally:
        release.set()
        results = await asyncio.gather(task, return_exceptions=True)
    assert isinstance(results[0], asyncio.CancelledError)
    assert joined.is_set() and custody[-1]["held"] == 0
    with pytest.raises(ContractViolation):
        await read("calc.py", 30)


async def test_authoritative_closure_after_worker_prevents_publication(custody, monkeypatch):
    provider, _, acquired, _, state = custody

    async def run(self, *args, **kwargs):
        provider.closure.commit(acquired.resource.paths)
        return ProcessResult(0, b"must not publish", b"", 0.01, payload_returncode=0)

    monkeypatch.setattr(LinuxLauncher, "run", run)
    with pytest.raises(ContractViolation, match="permanently closed"):
        await reader(custody)("calc.py", 30)
    assert state["held"] == 0


async def test_guard_release_closure_also_prevents_publication(custody, monkeypatch):
    provider, _, acquired, _, state = custody

    @asynccontextmanager
    async def closing_guard(paths):
        state["held"] += 1
        try:
            yield 77
        finally:
            state["held"] -= 1
            provider.closure.commit(paths)

    monkeypatch.setattr(contained, "acquisition_guard", closing_guard)
    with pytest.raises(ContractViolation, match="permanently closed"):
        await reader(custody)("calc.py", 30)
    assert state["held"] == 0
    assert provider.closure.is_closed(acquired.resource.paths)


async def test_cancellation_keeps_cleanup_failure_and_joins_before_releasing(custody, monkeypatch):
    started = asyncio.Event()

    async def run(self, *args, **kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            raise RuntimeError("worker cleanup failed")

    monkeypatch.setattr(LinuxLauncher, "run", run)
    task = asyncio.create_task(reader(custody)("calc.py", 30))
    await started.wait()
    task.cancel()
    with pytest.raises(BaseExceptionGroup) as caught:
        await task
    cancellation, other = caught.value.split(asyncio.CancelledError)
    assert cancellation is not None and other is not None
    assert custody[-1]["held"] == 0


async def test_cancellation_requests_worker_stop_instead_of_waiting_forever(custody, monkeypatch):
    started, joined = asyncio.Event(), asyncio.Event()
    inner = []

    async def run(self, *args, **kwargs):
        inner.append(asyncio.current_task())
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            joined.set()

    monkeypatch.setattr(LinuxLauncher, "run", run)
    task = asyncio.create_task(reader(custody)("calc.py", 30))
    await started.wait()
    task.cancel()
    try:
        done, _ = await asyncio.wait((task,), timeout=1)
        assert task in done, "worker stop was never requested"
        assert joined.is_set()
    finally:
        if not inner[0].done():
            inner[0].cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert custody[-1]["held"] == 0


async def test_wrong_owner_and_unbounded_or_native_launcher_refuse(custody):
    provider, ctx, acquired, launch, _ = custody
    other = replace(ctx, run_lease=ctx.run_lease.model_copy(update={"owner_id": "other"}))
    with pytest.raises(ContractViolation, match="lease owner"):
        worker.ClaudeReadWorker(provider=provider, context=other,
                               workspace=acquired.resource, launcher=launch)
    with pytest.raises(ContractViolation, match="fixed networkless"):
        worker.ClaudeReadWorker(provider=provider, context=ctx,
                               workspace=acquired.resource,
                               launcher=replace(launch, limits=ProcessLimits()))
    with pytest.raises(ContractViolation, match="fixed networkless"):
        worker.ClaudeReadWorker(provider=provider, context=ctx,
                               workspace=acquired.resource,
                               launcher=replace(launch, vendor=object()))
    with pytest.raises(ContractViolation, match="minted"):
        worker.ClaudeReadWorker(provider=provider, context=ctx,
                               workspace=copy.copy(acquired.resource), launcher=launch)


@pytest.mark.skipif(sys.platform != "linux", reason="Unix fd primitive proof requires Linux")
@pytest.mark.parametrize("kind", ["regular", "too-large", "invalid-utf8", "symlink", "directory",
                                  "symlink-parent", "fifo"])
def test_fixed_unix_reader_primitives_without_containment(tmp_path, kind):
    path = tmp_path / "data"
    (tmp_path / "elsewhere").write_bytes(b"must not follow")
    relative = "data"
    if kind == "regular":
        path.write_bytes(b"x" * 65536)
    elif kind == "too-large":
        path.write_bytes(b"x" * 65537)
    elif kind == "invalid-utf8":
        path.write_bytes(b"\xff")
    elif kind == "symlink":
        path.symlink_to("elsewhere")
    elif kind == "directory":
        path.mkdir()
    elif kind == "symlink-parent":
        path.symlink_to(tmp_path, target_is_directory=True)
        relative = "data/elsewhere"
    else:
        os.mkfifo(path)
    try:
        result = subprocess.run(
            [sys.executable, "-I", "-c", worker.READ_PROGRAM, relative], cwd=tmp_path,
            stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
        )
    except subprocess.TimeoutExpired:
        pytest.fail("fixed reader blocked on a nonregular input")
    assert result.returncode == (0 if kind == "regular" else 2)
    assert result.stdout == (b"x" * 65536 if kind == "regular" else b"")
    assert result.stderr == b""


async def test_physical_linux_read_worker_and_symlink_refusal(provider, launcher, tmp_path):
    """Real launcher/guard proof; not native-noexec/Claude composition proof."""
    ctx = context()
    acquired = await provider.acquire(ctx)
    await acquired.materialize()
    launch = replace(launcher, limits=worker.READ_WORKER_LIMITS)
    read = worker.ClaudeReadWorker(provider=provider, context=ctx,
                                   workspace=acquired.resource, launcher=launch)
    assert await read("calc.py", 30) == SEED_CALC
    # A readable target in the mounted workspace makes NOFOLLOW load-bearing;
    # an absent outside target would refuse even without the guard.
    Path(acquired.resource.path, "escape").symlink_to("calc.py")
    with pytest.raises(ContractViolation, match="process refused"):
        await read("escape", 30)
    await provider.close(acquired, "discard")
