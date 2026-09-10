"""Real trusted-Git pumping, cancellation handoff, and native parser limits."""

from __future__ import annotations

import asyncio
import json
import shlex
import shutil
import sys
from dataclasses import replace

import pytest

from constructicon.core.errors import ContractViolation
from constructicon.substrate.executors.linux import ProcessLimits
from constructicon.substrate.git.process import GitProcess
from tests.substrate.test_contained_workspace import LINUX


async def test_cancel_during_real_spawn_joins_before_repeated_cancellation_returns(
    tmp_path,
    monkeypatch,
):
    started, release = asyncio.Event(), asyncio.Event()
    native_spawn = asyncio.create_subprocess_exec
    handles = []

    async def held_return(*args, **kwargs):
        process = await native_spawn(*args, **kwargs)
        handles.append(process)
        started.set()
        await release.wait()
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", held_return)
    task = asyncio.create_task(
        GitProcess(shutil.which("git"), ProcessLimits()).run(
            "hash-object",
            "--stdin",
            cwd=tmp_path,
        )
    )
    await started.wait()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    premature = task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    quiescent = all(
        h.returncode is not None and h.stdout.at_eof() and h.stderr.at_eof() for h in handles
    )
    # Also clean up a deliberately broken pump in mutation runs; that cleanup
    # cannot turn the captured observation into a quiescence proof.
    for handle in handles:
        if handle.returncode is None:
            handle.kill()
        await handle.communicate()
    assert not premature, "cancelled caller left the actual spawned process unowned"
    assert len(handles) == 1 and quiescent


async def test_trusted_git_pump_rejects_input_and_output_bounds(tmp_path):
    git = GitProcess(shutil.which("git"), replace(ProcessLimits(), artifact_bytes=8))
    with pytest.raises(ContractViolation, match="input exceeds"):
        await git.run("hash-object", "--stdin", cwd=tmp_path, stdin=b"too much data")
    with pytest.raises(ContractViolation, match="output exceeds"):
        await git.run("--version", cwd=tmp_path)


@LINUX
async def test_git_parser_limits_are_present_in_the_actual_child_before_parsing(tmp_path):
    # Trusted test-only alias: observe limits inherited through Git's own child
    # launcher, not a mocked return or just the trampoline's source text.
    script = (
        "import json,resource; "
        "print(json.dumps([resource.getrlimit(k) for k in "
        "(resource.RLIMIT_AS,resource.RLIMIT_FSIZE,resource.RLIMIT_CPU,resource.RLIMIT_CORE)]))"
    )
    alias = "!" + shlex.join((sys.executable, "-I", "-c", script))
    output = await GitProcess(shutil.which("git"), ProcessLimits()).run(
        "-c",
        "alias.probe=" + alias,
        "probe",
        cwd=tmp_path,
    )
    assert json.loads(output) == [
        [512 * 1024 * 1024] * 2,
        [128 * 1024 * 1024] * 2,
        [30, 30],
        [0, 0],
    ]
