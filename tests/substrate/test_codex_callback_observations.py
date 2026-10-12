"""Durable admitted-callback snapshots; no programs, outputs or credentials."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from constructicon.core import qualification_write as contracts
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.substrate.executors.attempt_record import AttemptRecord
from constructicon.substrate.executors.codex import CodexConversation, CodexOperatorHandle
from constructicon.substrate.executors.codex_protocol import (
    CONTAINED_PYTHON_CATALOG,
    MAX_TOOL_CALLS,
)
from constructicon.substrate.executors.linux import ProcessResult
from tests.substrate.test_codex_adapter import EXPECTED
from tests.substrate.test_codex_write import WRITE_GRANTS, WriteNative


def observation(**changes):
    model = getattr(contracts, "CallbackObservation", None)
    assert model is not None, "the bounded callback observation contract is absent"
    return model(**{"schema_version": 1, "admitted_started": 0, "admitted_completed": 0,
                    "worker_results": (), **changes})


def test_observation_accepts_zero_and_exact_closed_callback_bound():
    assert observation().admitted_started == 0
    value = observation(admitted_started=MAX_TOOL_CALLS, admitted_completed=MAX_TOOL_CALLS,
                        worker_results=("success",) * MAX_TOOL_CALLS)
    assert len(value.worker_results) == MAX_TOOL_CALLS
    with pytest.raises(ValidationError):
        observation(admitted_started=MAX_TOOL_CALLS + 1,
                    worker_results=(None,) * (MAX_TOOL_CALLS + 1))


@pytest.mark.parametrize("changes", [
    {"admitted_started": True}, {"admitted_completed": 1},
    {"admitted_started": 1}, {"worker_results": ("raw-output",)},
    {"admitted_started": 1, "admitted_completed": 1, "worker_results": (None,)},
    {"schema_version": True}, {"program": "secret"},
])
def test_observation_refuses_incoherent_or_unbounded_facts(changes):
    with pytest.raises(ValidationError):
        observation(**changes)


def test_progress_keeps_phase_and_final_outcome_preserves_exact_snapshot(tmp_path):
    path = tmp_path / "write.attempt"
    record = AttemptRecord.reserve(path, {"authorization_id": "fake"})
    record.enable_callbacks()
    assert json.loads(path.read_text())["phase"] == "acquired"
    assert json.loads(path.read_text())["callbacks"] == observation().model_dump(mode="json")
    assert record.intend() is None
    assert json.loads(path.read_text())["callbacks"] == observation().model_dump(mode="json")
    started = observation(admitted_started=1, worker_results=(None,))
    record.observe_callbacks(started)
    assert json.loads(path.read_text())["phase"] == "intent"
    result = observation(admitted_started=1, worker_results=("success",))
    record.observe_callbacks(result)
    completed = observation(admitted_started=1, admitted_completed=1, worker_results=("success",))
    record.observe_callbacks(completed)
    record.complete("completed", {"status": "success"})
    assert json.loads(path.read_text())["callbacks"] == completed.model_dump(mode="json")


@pytest.mark.parametrize("when", ["before", "after"])
def test_failed_progress_is_latched_and_finalization_cannot_overwrite_it(
    tmp_path, monkeypatch, when,
):
    path = tmp_path / "write.attempt"
    record = AttemptRecord.reserve(path, {})
    record.enable_callbacks()
    assert record.intend() is None
    replace = record._replace
    def failed(content):
        if when == "after":
            replace(content)  # Rename may have landed before directory fsync failed.
        raise OSError("secret path detail")
    monkeypatch.setattr(record, "_replace", failed)
    with pytest.raises(ContractViolation, match="callback observations could not be retained"):
        record.observe_callbacks(observation(admitted_started=1, worker_results=(None,)))
    before = path.read_bytes()
    assert json.loads(before)["phase"] == "intent"
    assert json.loads(before)["callbacks"]["admitted_started"] == (1 if when == "after" else 0)
    monkeypatch.setattr(record, "_replace", replace)
    record.complete("completed", {"status": "success"})
    assert path.read_bytes() == before
    with pytest.raises(ContractViolation):
        record.observe_callbacks(observation(admitted_started=1, worker_results=(None,)))
    assert path.read_bytes() == before


def test_legacy_attempts_never_acquire_callback_zero_facts(tmp_path):
    path = tmp_path / "read.attempt"
    record = AttemptRecord.reserve(path, {})
    assert record.intend() is None
    record.complete("completed", {"status": "success"})
    assert "callbacks" not in json.loads(path.read_text())


@pytest.mark.parametrize("field", [
    "schema_version", "admitted_started", "admitted_completed", "worker_results",
])
def test_missing_callback_fact_is_not_normalized_into_affirmative_zero(field):
    record = observation().model_dump(mode="json")
    del record[field]
    with pytest.raises(ValidationError):
        contracts.CallbackObservation.model_validate(record)


def handle(tmp_path, monkeypatch, result, *, cancel_result=False, later_validation=False):
    record = AttemptRecord.reserve(tmp_path / "write.attempt", {})
    record.enable_callbacks()
    assert record.intend() is None
    owner = object.__new__(CodexOperatorHandle)
    owner.attempt = record
    owner.worker_active = None
    entered = asyncio.Event()
    @asynccontextmanager
    async def use():
        yield 0
    workspace = SimpleNamespace(path=str(tmp_path), use=use)
    validations = 0
    def validated(self, value, grants):
        nonlocal validations
        validations += 1
        if later_validation and validations == 3:
            raise ContractViolation("workspace lost after result")
        return workspace
    monkeypatch.setattr(CodexOperatorHandle, "_validated_workspace", validated)
    async def run(*args, **kwargs):
        entered.set()
        if cancel_result:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return result  # Actual result arrives while cancellation is being joined.
        return result
    owner.provider = SimpleNamespace(launcher=SimpleNamespace(run=run))
    async def worker(program):
        return await owner._run_worker(program, workspace=workspace, grants=WRITE_GRANTS,
                                       deadline=asyncio.get_running_loop().time() + 5)
    return owner, record, entered, worker


@pytest.mark.parametrize("result,category", [
    (ProcessResult(0, b"secret-output", b"", 0, payload_returncode=0), "success"),
    (ProcessResult(1, b"", b"secret-error", 0, payload_returncode=1), "nonzero"),
    (ProcessResult(1, b"", b"", 0, timed_out=True, bound_exceeded="stdout_bytes"), "timeout"),
    (ProcessResult(1, b"", b"", 0, bound_exceeded="stdout_bytes"), "output_bound"),
    (ProcessResult(0, b"", b"", 0), "incomplete"),
    (ProcessResult(0, b"\xff", b"", 0, payload_returncode=0), "invalid_utf8"),
], ids=["success", "nonzero", "timeout-priority", "bound-priority", "incomplete", "utf8"])
async def test_worker_terminal_facts_are_observed_before_later_rejection(
    tmp_path, monkeypatch, result, category,
):
    owner, record, _, worker = handle(tmp_path, monkeypatch, result, later_validation=True)
    owner._observe_callbacks(1, 0)
    with pytest.raises(ContractViolation):
        await worker("secret-program")
    snapshot = json.loads(record.path.read_text())
    assert snapshot["callbacks"]["worker_results"] == [category]
    assert snapshot["callbacks"]["admitted_completed"] == 0
    assert "secret" not in json.dumps(snapshot)
    assert owner.worker_active is None


@pytest.mark.parametrize("seam", ["eof", "response", "cancel"])
async def test_worker_result_survives_read_response_and_cancellation_races(
    tmp_path, monkeypatch, seam,
):
    result = ProcessResult(0, b"secret-output", b"", 0, payload_returncode=0)
    owner, record, entered, worker = handle(
        tmp_path, monkeypatch, result, cancel_result=seam != "response",
    )
    conversation = CodexConversation(
        task=TaskSpec(instruction="fake"), grants=WRITE_GRANTS, expected=EXPECTED,
        input_limit=1 << 20, catalog=CONTAINED_PYTHON_CATALOG, worker=worker,
        deadline=asyncio.get_running_loop().time() + 5, observe_callbacks=owner._observe_callbacks,
    )
    conversation.thread_id, conversation.turn_id = "thread-n2", "turn-n2"
    async def read(io):
        await entered.wait()
        if seam == "eof":
            return None
        await asyncio.Event().wait()
    monkeypatch.setattr(conversation, "_read", read)
    class IO:
        async def write(self, raw):
            raise OSError("response stopped")
    running = asyncio.create_task(conversation._dispatch_tool(
        IO(), WriteNative._callback_for("request", "call", "secret-program"),
    ))
    if seam == "cancel":
        await entered.wait()
        running.cancel()
        with pytest.raises(asyncio.CancelledError):
            await running
    else:
        assert await asyncio.wait_for(running, 5) is False
    callbacks = json.loads(record.path.read_text())["callbacks"]
    assert callbacks == observation(admitted_started=1, worker_results=("success",)).model_dump(
        mode="json",
    )
    assert owner.worker_active is None


async def test_failed_admission_write_stops_before_worker_effect(tmp_path, monkeypatch):
    owner, record, entered, worker = handle(
        tmp_path, monkeypatch, ProcessResult(0, b"", b"", 0, payload_returncode=0),
    )
    def failed(content):
        raise OSError("write stopped")
    monkeypatch.setattr(record, "_replace", failed)
    conversation = CodexConversation(
        task=TaskSpec(instruction="fake"), grants=WRITE_GRANTS, expected=EXPECTED,
        input_limit=1 << 20, catalog=CONTAINED_PYTHON_CATALOG, worker=worker,
        deadline=asyncio.get_running_loop().time() + 5, observe_callbacks=owner._observe_callbacks,
    )
    conversation.thread_id, conversation.turn_id = "thread-n2", "turn-n2"
    with pytest.raises(ContractViolation, match="callback observations could not be retained"):
        await conversation._dispatch_tool(
            object(), WriteNative._callback_for("request", "call", "pass"),
        )
    assert not entered.is_set()


async def test_completed_observation_waits_for_entire_response_write(tmp_path, monkeypatch):
    result = ProcessResult(0, b"secret-output", b"", 0, payload_returncode=0)
    owner, record, _, worker = handle(tmp_path, monkeypatch, result)
    conversation = CodexConversation(
        task=TaskSpec(instruction="fake"), grants=WRITE_GRANTS, expected=EXPECTED,
        input_limit=1 << 20, catalog=CONTAINED_PYTHON_CATALOG, worker=worker,
        deadline=asyncio.get_running_loop().time() + 5, observe_callbacks=owner._observe_callbacks,
    )
    conversation.thread_id, conversation.turn_id = "thread-n2", "turn-n2"
    async def read(io):
        await asyncio.Event().wait()
    monkeypatch.setattr(conversation, "_read", read)
    writing, finish = asyncio.Event(), asyncio.Event()
    class IO:
        async def write(self, raw):
            writing.set()
            await finish.wait()
    running = asyncio.create_task(conversation._dispatch_tool(
        IO(), WriteNative._callback_for("request", "call", "secret-program"),
    ))
    await asyncio.wait_for(writing.wait(), 5)
    assert record.callbacks.admitted_started == 1
    assert record.callbacks.admitted_completed == 0
    assert record.callbacks.worker_results == ("success",)
    finish.set()
    assert await asyncio.wait_for(running, 5) is True
    record.complete("completed", {"status": "success"})
    written = json.loads(record.path.read_text())
    assert written["phase"] == "outcome"
    assert written["callbacks"]["admitted_completed"] == 1
    assert "secret" not in json.dumps(written)


def test_affirmative_final_zero_is_not_legacy_absence(tmp_path):
    record = AttemptRecord.reserve(tmp_path / "zero.attempt", {})
    record.enable_callbacks()
    assert record.intend() is None
    record.complete("completed", {"status": "success"})
    stored = json.loads(record.path.read_text())
    assert stored["phase"] == "outcome"
    assert stored["callbacks"] == observation().model_dump(mode="json")


@pytest.mark.parametrize("when", ["before", "after"])
def test_final_snapshot_publication_is_not_a_durability_acknowledgement(
    tmp_path, monkeypatch, when,
):
    record = AttemptRecord.reserve(tmp_path / "write.attempt", {})
    record.enable_callbacks()
    assert record.intend() is None
    complete = observation(admitted_started=1, admitted_completed=1, worker_results=("success",))
    record.observe_callbacks(complete)
    replace = record._replace
    def failed(content):
        if when == "after":
            replace(content)
        raise OSError("final write stopped")
    monkeypatch.setattr(record, "_replace", failed)
    with pytest.raises(OSError):
        record.complete("completed", {"status": "success"})
    stored = json.loads(record.path.read_text())
    assert stored["phase"] == ("outcome" if when == "after" else "intent")
    assert stored["callbacks"] == complete.model_dump(mode="json")
    # Both snapshots retain accurate counts; only actual outcome publication
    # supports the final-snapshot flag, never a claim about fsync/power-loss.


@pytest.mark.parametrize("kind", ["admission", "completion", "result"])
def test_retained_callback_facts_cannot_be_retracted(tmp_path, kind):
    record = AttemptRecord.reserve(tmp_path / "write.attempt", {})
    record.enable_callbacks()
    assert record.intend() is None
    record.observe_callbacks(observation(admitted_started=1, worker_results=("success",)))
    if kind == "completion":
        record.observe_callbacks(observation(
            admitted_started=1, admitted_completed=1, worker_results=("success",),
        ))
    before = record.path.read_bytes()
    following = {
        "admission": observation(),
        "completion": observation(admitted_started=1, worker_results=("success",)),
        "result": observation(admitted_started=1, worker_results=("timeout",)),
    }[kind]
    with pytest.raises(ContractViolation, match="cannot retract"):
        record.observe_callbacks(following)
    assert record.path.read_bytes() == before
