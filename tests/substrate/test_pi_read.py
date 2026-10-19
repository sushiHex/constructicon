"""Credential-free READ accepting path and finite protocol refusals."""

import asyncio
import json
from dataclasses import replace

import pytest

from constructicon.core.envelope import GitRef, TextContext
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.substrate.executors.pi_read import PI_LIMITS, PiReadExecutor
from tests.piworld import PeerIO, PeerLauncher, SubprocessLauncher


class Workspace:
    def __init__(self, path):
        self.path = str(path)

    def git_ref(self):
        return GitRef(repository="fixture", commit="a" * 40)


def grants(**changes):
    return EffectiveGrants(posture=Posture.READ, allowed_tools=("read",), network="none",
                           env_allowlist=(), effort="off", timeout_s=10,
                           model_selection=ModelSelection(kind="explicit", model="fixture/pi-read"),
                           **changes)


@pytest.fixture
def world(tmp_path):
    (tmp_path / "fixture.txt").write_text("real workspace bytes é", encoding="utf-8")
    workspace = Workspace(tmp_path)
    io = PeerIO(tmp_path)
    launcher = PeerLauncher(io)
    executor = PiReadExecutor(launcher, ("fixed-scripted-peer",), guard_fds=(17,))
    return workspace, io, launcher, executor


async def execute(world, *, task=None, selected=None, workspace=True):
    view, _io, _launcher, executor = world
    return await executor.execute(task or TaskSpec(instruction="Analyze fixture.txt"),
                                  workspace=view if workspace else None,
                                  grants=selected or grants())


@pytest.mark.parametrize("fragment", [1, 7, 8192])
async def test_workspace_read_accepts_early_completion_and_counts_usage_once(world, fragment):
    workspace, io, launcher, _executor = world
    io.fragment = fragment
    before = (workspace.git_ref(), (io.workspace / "fixture.txt").read_bytes())
    outcome = await execute(world)
    assert outcome.status == "success", outcome
    assert outcome.output == outcome.raw_reply == "Read: real workspace bytes é"
    assert outcome.usage.input_tokens == 6 and outcome.usage.output_tokens == 4
    assert outcome.served_model is outcome.rate_limit is None
    assert outcome.requested_model == "fixture/pi-read"
    assert before == (workspace.git_ref(), (io.workspace / "fixture.txt").read_bytes())
    assert launcher.joined and io.closed and io.eof
    assert [json.loads(data)["type"] for data in io.writes] == ["get_state", "prompt"]
    assert launcher.calls[0][1]["workspace"] == io.workspace
    assert launcher.calls[0][1]["guard_fds"] == (17,)
    assert launcher.calls[0][1]["posture"] is Posture.READ


async def test_actual_scripted_process_reads_workspace_with_same_adapter(world):
    from pathlib import Path

    from constructicon.substrate.git.authority import GitAuthority
    from tests.gitworld import seed_authority

    _workspace, io, _launcher, _executor = world
    text = "snapshot bytes"
    authority = GitAuthority(seed_authority(io.workspace, {"fixture.txt": text}),
                             io.workspace / "snapshots")
    head = authority.read_ref("refs/heads/main")
    assert head is not None
    workspace = authority.read_snapshot(head)
    launcher = SubprocessLauncher()
    executor = PiReadExecutor(launcher, ("scripted-peer",), guard_fds=(17,))
    fixture = Path(workspace.path) / "fixture.txt"
    before = fixture.read_bytes()
    outcome = await executor.execute(TaskSpec(instruction="Analyze fixture.txt"),
                                     workspace=workspace, grants=grants())
    assert outcome.status == "success", outcome
    assert outcome.output == "Read: " + before.decode("utf-8")
    assert fixture.read_bytes() == before
    assert authority.read_ref("refs/heads/main") == head
    assert launcher.joined and launcher.eof


@pytest.mark.parametrize("change", [
    {"posture": Posture.WRITE}, {"allowed_tools": ()}, {"allowed_tools": ("bash",)},
    {"network": "allow"}, {"env_allowlist": ("PATH",)}, {"effort": None},
    {"effort": "high"}, {"model_selection": ModelSelection(kind="backend_default")},
    {"model_selection": ModelSelection(kind="explicit", model="real/model")},
])
async def test_exact_profile_refuses_before_launch(world, change):
    selected = grants().model_copy(update=change)
    outcome = await execute(world, selected=selected)
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert world[2].calls == []


@pytest.mark.parametrize("kind", ["workspace", "context", "schema"])
async def test_unsupported_task_refuses_before_launch(world, kind):
    task = TaskSpec(instruction="read", context=(TextContext(text="unsupported"),)) if (
        kind == "context"
    ) else TaskSpec(instruction="read", response_schema={} if kind == "schema" else None)
    outcome = await execute(world, task=task, workspace=kind != "workspace")
    assert outcome.status == "failure" and outcome.error.kind == "unavailable"
    assert world[2].calls == []


def edit_event(records, event, **fields):
    found = next(item for item in records if item["type"] == event)
    found.update(fields)
    return records


@pytest.mark.parametrize("event", ["agent_start", "message_end", "tool_execution_start",
                                    "tool_execution_end", "agent_end", "agent_settled"])
async def test_missing_completion_never_succeeds(world, event):
    world[1].transform = lambda records: [item for item in records if item["type"] != event]
    outcome = await execute(world, selected=grants().model_copy(update={"timeout_s": 0.1}))
    assert outcome.status != "success"
    assert world[2].joined
    assert world[1].eof or outcome.error.kind == "timeout"


@pytest.mark.parametrize("event,fields", [
    ("agent_settled", {"aborted": True}), ("agent_end", {"willRetry": True}),
    ("tool_execution_end", {"isError": True}),
    ("tool_execution_start", {"toolName": "bash"}),
    ("tool_execution_start", {"toolCallId": "wrong"}),
    ("tool_execution_end", {"toolCallId": "wrong"}),
    ("message_update", {"assistantMessageEvent": {"type": "new-authority"}}),
])
async def test_protocol_refusals_never_become_success(world, event, fields):
    world[1].transform = lambda records: edit_event(records, event, **fields)
    outcome = await execute(world)
    assert outcome.status != "success"


@pytest.mark.parametrize("extra", [
    {"type": "extension_ui_request"}, {"type": "auto_retry_start"},
    {"type": "compaction_start"}, {"type": "queue_update"},
    {"type": "agent_settled", "aborted": False},
])
async def test_trailing_authority_or_duplicate_settlement_refuses(world, extra):
    world[1].transform = lambda records: [*records, extra]
    assert (await execute(world)).status != "success"


@pytest.mark.parametrize("reason", ["pending", "length", "deferred", "error", "aborted", "toolUse"])
async def test_only_completed_stop_analysis_is_terminal(world, reason):
    def change(records):
        for item in records:
            if item["type"] == "message_end" and item["message"].get("stopReason") == "stop":
                item["message"]["stopReason"] = reason
        return records

    world[1].transform = change
    assert (await execute(world)).status != "success"


@pytest.mark.parametrize("field,value", [
    ("stderr", b"warning"), ("returncode", 1), ("payload_returncode", None),
    ("payload_returncode", 1), ("timed_out", True), ("bound_exceeded", "stdout"),
    ("returncode", False), ("payload_returncode", False), ("timed_out", None),
])
async def test_process_completion_is_independently_required(world, field, value):
    from constructicon.substrate.executors.linux import ProcessResult

    world[2].result = replace(ProcessResult(0, b"", b"", 0.1, payload_returncode=0),
                              **{field: value})
    outcome = await execute(world)
    assert outcome.status != "success"
    assert outcome.error.kind == ("timeout" if field == "timed_out" and value is True else "exit")


async def test_pending_write_is_read_concurrently_and_reentry_poison_is_permanent(world):
    world[1].block = "prompt"
    pending = asyncio.create_task(execute(world))
    await asyncio.wait_for(world[1].entered.wait(), 2)
    assert world[1].history  # Reader drained while the write was suspended.
    with pytest.raises(ContractViolation):
        await execute(world)
    world[1].release.set()
    assert (await pending).status != "success"
    assert len(world[1].writes) == 2 and world[2].joined


async def test_cancellation_propagates_after_reader_join(world):
    world[1].block = "prompt"
    pending = asyncio.create_task(execute(world))
    await asyncio.wait_for(world[1].entered.wait(), 2)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert world[2].joined
    assert not [task for task in asyncio.all_tasks() if task.get_name() == "pi-read-reader"]


def test_narrow_process_limits_are_explicit():
    assert (PI_LIMITS.input_bytes, PI_LIMITS.stdout_bytes, PI_LIMITS.record_bytes,
            PI_LIMITS.stderr_bytes) == (65536, 1048576, 65536, 16384)


async def test_cleanup_oserror_escapes_instead_of_claiming_spawn_failure(world):
    async def failed_close(*args, **kwargs):
        raise OSError("cleanup failed")

    world[2].exchange = failed_close
    with pytest.raises(OSError, match="cleanup failed"):
        await execute(world)


async def test_cancel_with_pending_write_keeps_already_failed_reader_as_cause(world):
    io = world[1]
    io.block = "prompt"
    failed = asyncio.Event()
    original_read = io.read

    async def read_then_fail(maximum=8192):
        chunk = await original_read(maximum)
        if len(io.writes) == 2 and not io.buffer:
            failed.set()
            raise OSError("scripted reader failure")
        return chunk

    io.read = read_then_fail
    pending = asyncio.create_task(execute(world))
    await asyncio.wait_for(io.entered.wait(), 2)
    await asyncio.wait_for(failed.wait(), 2)
    assert not pending.done()  # Positively witnessed pending write and failed reader.
    pending.cancel()
    observed = None
    try:
        await pending
    except BaseException as error:
        observed = error
    assert isinstance(observed, asyncio.CancelledError)
    assert isinstance(observed.__cause__, OSError)
    assert world[2].joined


@pytest.mark.parametrize("extra", [0, 1])
async def test_input_budget_counts_both_commands_before_delivery(world, extra):
    from constructicon.substrate.executors.pi_protocol import encoded

    overhead = sum(len(encoded(payload)) + 1 for payload in (
        {"type": "get_state", "id": "0" * 32},
        {"type": "prompt", "id": "0" * 32, "message": ""},
    ))
    instruction = "x" * (PI_LIMITS.input_bytes - overhead + extra)
    outcome = await execute(world, task=TaskSpec(instruction=instruction))
    delivered = sum(map(len, world[1].writes))
    if extra:
        assert len(world[1].writes) == 1 and delivered < PI_LIMITS.input_bytes
        assert outcome.status == "failure"
    else:
        assert len(world[1].writes) == 2 and delivered == PI_LIMITS.input_bytes
    assert world[2].joined


@pytest.mark.parametrize("changed", ["limits", "vendor"])
async def test_fixture_launch_inputs_are_rechecked_before_exchange(world, changed):
    if changed == "limits":
        world[2].limits = replace(PI_LIMITS, stdout_bytes=PI_LIMITS.stdout_bytes + 1)
    else:
        world[2].vendor = object()
    assert (await execute(world)).error.kind == "unavailable"
    assert world[2].calls == []


async def test_ownership_control_is_rechecked_after_join_before_publishing(world):
    checked = []

    def control():
        checked.append(True)
        if len(checked) == 2:
            assert world[2].joined
            raise ContractViolation("ownership lost")

    world[3].check_control = control
    with pytest.raises(ContractViolation, match="ownership lost"):
        await execute(world)
    assert len(checked) == 2
