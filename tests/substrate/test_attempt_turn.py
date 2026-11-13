"""The model's side of a maintenance attempt: one private file, exact or absent."""

import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from constructicon.core.attempt_content import ContentDigest
from constructicon.core.executor import ExecutorSuccess
from constructicon.substrate.executors import attempt_turn
from constructicon.substrate.executors.attempt_turn import TurnRecord, turn_path
from constructicon.substrate.executors.codex_protocol import (
    EMPTY_TURN,
    MAX_TOOL_CALLS,
    RECORD_BYTES,
    TOOL_PROGRAM_BYTES,
    RecordStream,
)
from constructicon.substrate.executors.linux import ProcessResult
from constructicon.substrate.journal import maintenance_evidence
from tests.substrate.test_codex_callback_observations import handle

EMPTY = {"version": 1, "calls": [], "completed": False, "reply": None}


def digest(text):
    raw = text.encode()
    return ContentDigest(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))


def stored(record):
    return json.loads(record.path.read_bytes())


def test_the_file_sits_beside_the_attempt_record_outside_every_captured_name(tmp_path):
    path = turn_path(tmp_path / "maintenance-attempt.json")
    assert path == tmp_path / "maintenance-attempt.turn.json"
    # The evidence capture copies fixed names only; the diagnostic reads that copy.
    assert path.name not in maintenance_evidence.FILES


def test_each_step_is_durable_so_a_death_leaves_the_exact_ordered_prefix(tmp_path):
    record = TurnRecord.reserve(tmp_path / "attempt.turn.json")
    assert stored(record) == EMPTY
    record.program("print(open('a').read())")
    # A death here: the program is on disk before anything ran it, with no output.
    assert stored(record) == EMPTY | {
        "calls": [{"program": "print(open('a').read())", "seen": None}]}
    record.seen(0, digest("contents\n"))
    record.program("raise SystemExit(1)")
    # A death here: the first call was answered, the second never was, no completion.
    assert [call["seen"] for call in stored(record)["calls"]] == [
        digest("contents\n").model_dump(), None]
    assert stored(record)["completed"] is False
    record.complete("done")
    record.complete("done")
    assert record.intact
    # The bytes are the replay record's own canonical form (tests/model_seat.py, Turn).
    assert record.path.read_bytes() == json.dumps({
        "version": 1, "completed": True, "reply": "done", "calls": [
            {"program": "print(open('a').read())", "seen": digest("contents\n").model_dump()},
            {"program": "raise SystemExit(1)", "seen": None},
        ]}, sort_keys=True, separators=(",", ":")).encode()
    assert sorted(item.name for item in tmp_path.iterdir()) == ["attempt.turn.json"]
    if os.name == "posix":
        assert record.path.stat().st_mode & 0o777 == 0o600


def test_a_turn_may_complete_without_a_message(tmp_path):
    record = TurnRecord.reserve(tmp_path / "attempt.turn.json")
    record.complete(None)
    assert record.intact and stored(record) == EMPTY | {"completed": True}


def test_an_existing_file_is_left_alone_and_nothing_is_kept(tmp_path):
    path = tmp_path / "attempt.turn.json"
    path.write_bytes(b"earlier evidence")
    record = TurnRecord.reserve(path)
    record.program("print(1)")
    record.complete("done")
    assert not record.intact and path.read_bytes() == b"earlier evidence"
    assert sorted(item.name for item in tmp_path.iterdir()) == ["attempt.turn.json"]


@pytest.mark.parametrize("step", ["reserve", "program"])
def test_the_path_only_ever_names_a_complete_document(tmp_path, monkeypatch, step):
    """A death at any point of a write leaves the previous whole file, or none."""
    path = tmp_path / "attempt.turn.json"
    record = TurnRecord.reserve(path) if step == "program" else None
    before = path.read_bytes() if record else None
    opened = []
    real_open, real_fsync = os.open, os.fsync

    def recording_open(target, *args, **kwargs):
        opened.append(os.fspath(target))
        return real_open(target, *args, **kwargs)

    class Killed(BaseException):
        pass

    def killed(fd):
        real_fsync(fd)
        raise Killed  # the body is written; nothing has placed it yet

    monkeypatch.setattr(attempt_turn.os, "open", recording_open)
    monkeypatch.setattr(attempt_turn.os, "fsync", killed)
    with pytest.raises(Killed):
        if record is None:
            TurnRecord.reserve(path)
        else:
            record.program("print(1)")
    monkeypatch.undo()
    # Only the sibling was ever opened for writing; the path holds what it held.
    assert opened[0] == str(path) + ".next" and str(path) not in opened
    assert (path.read_bytes() if path.exists() else None) == before
    json.loads((tmp_path / "attempt.turn.json.next").read_bytes())  # whole, and never read


@pytest.mark.parametrize("damage", [
    "program-over-bound", "ninth-program", "program-before-output", "program-after-completion",
    "seen-out-of-order", "seen-twice", "seen-unknown", "seen-after-completion",
    "reply-over-bound", "replace-fails",
])
def test_what_cannot_be_kept_exactly_stops_the_record_and_truncates_nothing(
    tmp_path, monkeypatch, damage,
):
    record = TurnRecord.reserve(tmp_path / "attempt.turn.json")
    record.program("print(1)")
    before = record.path.read_bytes()
    if damage == "program-over-bound":
        record.seen(0, digest("x"))
        before = record.path.read_bytes()
        record.program("é" * (TOOL_PROGRAM_BYTES // 2 + 1))
    elif damage == "ninth-program":
        for index in range(MAX_TOOL_CALLS - 1):
            record.seen(index, digest("x"))
            record.program("print(1)")
        record.seen(MAX_TOOL_CALLS - 1, digest("x"))
        assert record.intact and len(stored(record)["calls"]) == MAX_TOOL_CALLS
        before = record.path.read_bytes()
        record.program("print(9)")
    elif damage == "program-before-output":
        record.program("print(2)")
    elif damage == "program-after-completion":
        record.complete(None)
        before = record.path.read_bytes()
        record.program("print(2)")
    elif damage == "seen-out-of-order":
        record.seen(1, digest("x"))
    elif damage == "seen-twice":
        record.seen(0, digest("x"))
        before = record.path.read_bytes()
        record.seen(0, digest("y"))
    elif damage == "seen-unknown":
        record.seen(0, None)
    elif damage == "seen-after-completion":
        record.complete(None)
        before = record.path.read_bytes()
        record.seen(0, digest("x"))
    elif damage == "reply-over-bound":
        record.complete("x" * (RECORD_BYTES + 1))
    else:
        def refuse(source, target):
            raise OSError("no space")
        with monkeypatch.context() as patch:
            patch.setattr(attempt_turn.os, "replace", refuse)
            record.seen(0, digest("x"))
    assert not record.intact
    # The last exact state stays; later steps write nothing.
    record.seen(0, digest("z"))
    record.program("print(3)")
    record.complete("done")
    assert record.path.read_bytes() == before


def test_an_output_with_no_program_before_it_stops_the_record_without_raising(tmp_path):
    record = TurnRecord.reserve(tmp_path / "attempt.turn.json")
    record.seen(0, digest("x"))
    record.seen(-1, digest("x"))
    assert not record.intact and stored(record) == EMPTY


def test_the_bounds_are_the_producers_own_and_admit_their_exact_ceiling(tmp_path):
    record = TurnRecord.reserve(tmp_path / "attempt.turn.json")
    record.program("é" * (TOOL_PROGRAM_BYTES // 2))
    record.complete("x" * RECORD_BYTES)
    assert record.intact and len(stored(record)["reply"]) == RECORD_BYTES
    # The reply ceiling is the inbound framer's: no record, so no reply, reaches it.
    framer = RecordStream()
    assert framer.feed(b"x" * RECORD_BYTES) == [] and framer.damage is not None


async def test_the_handle_keeps_the_program_before_the_worker_runs_and_the_output_once_sent(
    tmp_path, monkeypatch,
):
    result = ProcessResult(0, b"shown-output", b"", 0, payload_returncode=0)
    owner, _, _, worker = handle(tmp_path, monkeypatch, result)
    owner._turn = TurnRecord.reserve(tmp_path / "attempt.turn.json")
    launched = []
    run = owner.provider.launcher.run

    async def observed(*args, **kwargs):
        # At launch the program is already durable: a hard kill now keeps it.
        launched.append(stored(owner._turn)["calls"])
        return await run(*args, **kwargs)

    owner.provider.launcher.run = observed
    owner._observe_callbacks(1, 0)
    assert await worker("the-program") == "shown-output"
    assert launched == [[{"program": "the-program", "seen": None}]]
    # The worker returned, but the response has not reached the model yet.
    assert stored(owner._turn)["calls"][0]["seen"] is None
    owner._observe_callbacks(1, 1)
    assert stored(owner._turn)["calls"] == [
        {"program": "the-program", "seen": digest("shown-output").model_dump()}]
    block = owner._content_digests(ExecutorSuccess(output="done"))
    assert block["callbacks"][0]["output"] == digest("shown-output").model_dump()
    # The attempt record still holds no text.
    assert "the-program" not in owner.attempt.path.read_text()


@pytest.mark.parametrize("terminal", [True, False])
def test_settlement_records_completion_only_from_the_terminal_record(
    tmp_path, monkeypatch, terminal,
):
    from dataclasses import replace

    owner, _, _, _ = handle(tmp_path, monkeypatch, None)
    owner._turn = TurnRecord.reserve(tmp_path / "attempt.turn.json")
    # A message completed before the turn ended is partial text, not a completion.
    observation = replace(EMPTY_TURN, output="last message", terminal=terminal)
    owner._conversation = SimpleNamespace(observation=observation, turn_sent=True)
    monkeypatch.setattr(type(owner), "_attempt_facts", lambda self, outcome: {})
    owner._settle_attempt(None)
    assert stored(owner._turn) == EMPTY | (
        {"completed": True, "reply": "last message"} if terminal else {})


async def test_a_turn_that_could_not_be_kept_makes_the_digest_block_unrecordable(
    tmp_path, monkeypatch,
):
    result = ProcessResult(0, b"shown-output", b"", 0, payload_returncode=0)
    owner, _, _, worker = handle(tmp_path, monkeypatch, result)
    (tmp_path / "attempt.turn.json").write_bytes(b"earlier evidence")
    owner._turn = TurnRecord.reserve(tmp_path / "attempt.turn.json")
    owner._observe_callbacks(1, 0)
    # Retention never fails the callback it describes.
    assert await worker("the-program") == "shown-output"
    owner._observe_callbacks(1, 1)
    assert owner._content_digests(ExecutorSuccess(output="done")) == "unrecordable"
    assert (tmp_path / "attempt.turn.json").read_bytes() == b"earlier evidence"
