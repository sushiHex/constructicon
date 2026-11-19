"""Immutable-world reuse belongs to one owned read, never its connection."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from copy import deepcopy

import pytest
from tests.conftest import await_attempt_terminal, pipeline_graph
from tests.run_worlds import create_test_run, start_test_run

from constructicon.api.control import ControlPlane
from constructicon.core.address import RunId
from constructicon.core.control import (
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    RunSubmission,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.run import RunStatus
from constructicon.substrate.journal import _sqlite_base as snapshots
from constructicon.substrate.journal import _sqlite_runs as runs
from constructicon.substrate.journal._sqlite_execution_facts import event_fact_hash, event_fact_key
from constructicon.substrate.journal._sqlite_fact_seals import require_durable_fact_seal
from constructicon.substrate.journal.sqlite import SqliteJournal

ACTOR = AuthenticatedActor(
    actor_id="static:snapshot-proof-producer", auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
)
WORLD_FIELDS = (
    "run_id", "manifest_hash", "input_hash", "inputs_json", "created_at",
    "creation_command_id", "origin_json",
)


@pytest.fixture
async def created_worlds(world, journal):
    """A genuine command-backed creation plan and an originless retained world."""
    inputs = {"issue": {"title": "owned read proof", "nested": {"value": "original"}}}
    control = ControlPlane(system=world, store=journal)
    try:
        submission = await control.runs_start(
            ACTOR, proposal=pipeline_graph(), inputs=inputs, idempotency_key="proof-producer",
        )
        assert isinstance(submission, RunSubmission)
        terminal = await await_attempt_terminal(journal, submission.run_id, baseline_event_seq=0)
        assert terminal.kind == "RunSucceeded"
        command = control.commands_status(ACTOR, submission.command.command_id)
        assert command.state == "committed"
    finally:
        await control.shutdown()
    legacy = RunId("run-legacy-snapshot-proof")
    create_test_run(journal, legacy, inputs={"legacy": {"value": "original"}})
    return submission.run_id, legacy


def world_row(connection, run_id):
    row = connection.execute(
        "SELECT r.*, o.origin_json FROM runs AS r"
        " LEFT JOIN run_origins AS o ON o.run_id = r.run_id WHERE r.run_id = ?",
        (run_id,),
    ).fetchone()
    assert row is not None
    return row


def count_uncached(monkeypatch):
    calls = []
    original = runs._validated_run_world_uncached

    def counted(connection, row):
        calls.append((connection, row["run_id"]))
        return original(connection, row)

    monkeypatch.setattr(runs, "_validated_run_world_uncached", counted)
    return calls


def connection_counts(calls, connection):
    return Counter(run_id for observed, run_id in calls if observed is connection)


@pytest.mark.parametrize("order,expected", [("AABB", {"A": 1, "B": 1}),
                                             ("ABA", {"A": 2, "B": 1})])
def test_one_recent_success_is_reused_but_every_distinct_world_is_actually_proven(
    created_worlds, journal, monkeypatch, order, expected,
) -> None:
    identifiers = dict(zip("AB", created_worlds, strict=True))
    calls = count_uncached(monkeypatch)
    with journal._read() as connection:
        proofs = snapshots._read_snapshot_proofs(connection)
        assert proofs is not None and connection.in_transaction
        for label in order:
            actual = runs.validated_run_world(connection, world_row(connection, identifiers[label]))
            assert actual.run_id == identifiers[label]
            if label == "A":
                assert actual.origin is not None and actual.creation_plan is not None
                assert actual.creation_plan.inputs == actual.inputs
            else:
                assert actual.origin is None and actual.creation_plan is None
            # Two distinct successful worlds make this memory bound bind.
            assert len(proofs.worlds) == 1
        assert connection_counts(calls, connection) == Counter({
            identifiers[label]: count for label, count in expected.items()
        })
    assert proofs.active is False and proofs.worlds == {}
    assert snapshots._READ_SNAPSHOT_PROOFS.get() is None


def test_publish_and_hit_copies_protect_nested_inputs_manifest_and_creation_plan(
    created_worlds, journal, monkeypatch,
) -> None:
    run_id, _legacy = created_worlds
    calls = count_uncached(monkeypatch)
    with journal._read() as connection:
        row = world_row(connection, run_id)
        first = runs.validated_run_world(connection, row)
        assert first.creation_plan is not None
        expected_inputs = deepcopy(first.inputs)
        expected_manifest = first.manifest.model_dump(mode="json")
        expected_plan = first.creation_plan.model_dump(mode="json")

        def poison(value):
            value.inputs["issue"]["nested"]["value"] = "consumer mutation"
            value.manifest.source_graph.connections[0].map["poison"] = "$input.issue"
            value.creation_plan.inputs["issue"]["title"] = "plan mutation"
            value.creation_plan.manifest.source_graph.connections[0].map["poison"] = "x.y"

        poison(first)
        for _ in range(2):
            subsequent = runs.validated_run_world(connection, row)
            assert subsequent.inputs == expected_inputs
            assert subsequent.manifest.model_dump(mode="json") == expected_manifest
            assert subsequent.creation_plan.model_dump(mode="json") == expected_plan
            poison(subsequent)
        assert connection_counts(calls, connection) == {run_id: 1}


@pytest.mark.parametrize("dependency", ["manifest", "command"])
def test_own_write_invalidates_even_when_all_seven_world_fields_stay_unchanged(
    created_worlds, journal, monkeypatch, dependency,
) -> None:
    run_id, _legacy = created_worlds
    calls = count_uncached(monkeypatch)
    connection = journal._connect()
    try:
        with snapshots.read_snapshot(connection):
            row = world_row(connection, run_id)
            before = tuple(row[name] for name in WORLD_FIELDS)
            proven = runs.validated_run_world(connection, row)
            proofs = snapshots._read_snapshot_proofs(connection)
            assert proofs is not None and len(proofs.worlds) == 1
            if dependency == "manifest":
                old = connection.execute(
                    "SELECT manifest_json FROM manifests WHERE manifest_hash = ?",
                    (row["manifest_hash"],),
                ).fetchone()[0]
                changed = json.loads(old)
                changed["source_graph"]["name"] = "rewritten-dependent-manifest"
                sql = "UPDATE manifests SET manifest_json = ? WHERE manifest_hash = ?"
                key = row["manifest_hash"]
                replacement = json.dumps(changed)
            else:
                assert proven.origin is not None
                key = proven.origin.command_id
                old = connection.execute(
                    "SELECT request_json FROM commands WHERE command_id = ?", (key,),
                ).fetchone()[0]
                sql = "UPDATE commands SET request_json = ? WHERE command_id = ?"
                replacement = "{}"
            connection.execute(sql, (replacement, key))
            assert tuple(world_row(connection, run_id)[name] for name in WORLD_FIELDS) == before
            with pytest.raises(JournalDamaged):
                runs.validated_run_world(connection, row)
            assert proofs.disabled is True and proofs.worlds == {}
            assert snapshots._read_snapshot_proofs(connection) is None

            # Restoring valid bytes cannot re-enable a view that performed DML.
            connection.execute(sql, (old, key))
            assert runs.validated_run_world(connection, row).run_id == run_id
            assert runs.validated_run_world(connection, row).run_id == run_id
            assert connection_counts(calls, connection) == {run_id: 4}
            assert proofs.worlds == {} and proofs.disabled is True
        with snapshots.read_snapshot(connection):
            fresh = snapshots._read_snapshot_proofs(connection)
            assert fresh is not None and fresh is not proofs and fresh.disabled is False
            fresh_row = world_row(connection, run_id)
            assert runs.validated_run_world(connection, fresh_row).run_id == run_id
            assert runs.validated_run_world(connection, fresh_row).run_id == run_id
            assert connection_counts(calls, connection) == {run_id: 5}
    finally:
        connection.close()


def test_failed_world_proofs_are_never_published_or_reused(created_worlds, journal, monkeypatch):
    damaged_id, good_id = created_worlds
    with sqlite3.connect(journal._db_path) as writer:
        writer.execute("UPDATE runs SET inputs_json = '{}' WHERE run_id = ?", (damaged_id,))
    calls = count_uncached(monkeypatch)
    with journal._read() as connection:
        good = world_row(connection, good_id)
        assert runs.validated_run_world(connection, good).run_id == good_id
        damaged = world_row(connection, damaged_id)
        for _ in range(2):
            with pytest.raises(JournalDamaged):
                runs.validated_run_world(connection, damaged)
        assert runs.validated_run_world(connection, good).run_id == good_id
        assert connection_counts(calls, connection) == {good_id: 1, damaged_id: 2}
        proofs = snapshots._read_snapshot_proofs(connection)
        assert proofs is not None and len(proofs.worlds) == 1
        assert {value.run_id for value in proofs.worlds.values()} == {good_id}


def test_warmed_public_world_read_refuses_dependent_corruption_in_a_fresh_view(
    created_worlds, journal,
) -> None:
    run_id, _legacy = created_worlds
    original = journal.run_inputs(run_id)
    assert original["issue"]["nested"]["value"] == "original"
    with sqlite3.connect(journal._db_path) as writer:
        writer.execute(
            "UPDATE commands SET request_json = '{}' WHERE command_id ="
            " (SELECT creation_command_id FROM runs WHERE run_id = ?)", (run_id,),
        )
    with pytest.raises(JournalDamaged):
        journal.run_inputs(run_id)


def test_external_commit_is_real_while_old_view_and_second_view_remain_distinct(
    journal, monkeypatch,
) -> None:
    run_id = RunId("run-proof-wal-writer")
    create_test_run(journal, run_id)
    worker = start_test_run(journal, run_id, owner_id="wal-proof-worker")
    writer = SqliteJournal(journal._db_path)
    calls = count_uncached(monkeypatch)
    connection = journal._connect()
    try:
        with snapshots.read_snapshot(connection):
            first_proofs = snapshots._read_snapshot_proofs(connection)
            assert first_proofs is not None and connection.in_transaction
            old = runs.run_projection_for_id(connection, run_id, observe=journal._now)
            assert old is not None and old[0].status is RunStatus.RUNNING
            saved_context = copy_context()
            writer.transition_run(
                worker, expected=frozenset({RunStatus.RUNNING}), target=RunStatus.FAILED,
                event_kind="RunFailed", payload={"witness": "external commit"},
            )
            committed = writer.latest_terminal_event(run_id)
            assert committed is not None and committed.kind == "RunFailed"
            assert committed.seq == old[2] + 1
            # Independent fresh connection: prove both the exact row and its
            # positive seal exist before releasing the reader's older WAL view.
            with writer._read() as witness:
                stored = witness.execute(
                    "SELECT * FROM events WHERE run_id = ? AND seq = ?",
                    (run_id, committed.seq),
                ).fetchone()
                assert stored is not None and stored["kind"] == "RunFailed"
                assert json.loads(stored["payload"]) == {"witness": "external commit"}
                seal = require_durable_fact_seal(
                    witness, family="event", fact_key=event_fact_key(run_id, committed.seq),
                    selector=json.dumps(
                        {"event": {"run_id": str(run_id), "seq": committed.seq}},
                        sort_keys=True, separators=(",", ":"),
                    ), fact_hash=event_fact_hash(stored),
                )
                assert seal.fact_key == event_fact_key(run_id, committed.seq)
            again = runs.run_projection_for_id(connection, run_id, observe=journal._now)
            assert again == old
            assert connection_counts(calls, connection) == {run_id: 1}
        assert first_proofs.active is False and first_proofs.worlds == {}

        # Both views use the SAME connection inside this one enclosing call.
        with snapshots.read_snapshot(connection):
            second_proofs = snapshots._read_snapshot_proofs(connection)
            assert second_proofs is not None and second_proofs is not first_proofs
            fresh = runs.run_projection_for_id(connection, run_id, observe=journal._now)
            assert fresh is not None and fresh[0].status is RunStatus.FAILED
            assert fresh[2] == committed.seq
            assert connection_counts(calls, connection) == {run_id: 2}
            assert saved_context.run(snapshots._read_snapshot_proofs, connection) is None
            replayed = saved_context.run(
                runs.validated_run_world, connection, world_row(connection, run_id),
            )
            assert replayed.run_id == run_id
            assert connection_counts(calls, connection) == {run_id: 3}
            assert runs.validated_run_world(connection, world_row(connection, run_id)) == replayed
            assert connection_counts(calls, connection) == {run_id: 3}
    finally:
        connection.close()


def test_nested_connection_and_exception_exit_never_alias_the_owning_proof(
    created_worlds, journal, monkeypatch,
) -> None:
    run_id, _legacy = created_worlds
    calls = count_uncached(monkeypatch)
    with journal._read() as outer:
        outer_proofs = snapshots._read_snapshot_proofs(outer)
        assert outer_proofs is not None
        assert runs.validated_run_world(outer, world_row(outer, run_id)).run_id == run_id
        with pytest.raises(RuntimeError, match="leave inner view"), journal._read() as inner:
            inner_proofs = snapshots._read_snapshot_proofs(inner)
            assert inner_proofs is not None and inner_proofs is not outer_proofs
            assert snapshots._read_snapshot_proofs(outer) is None
            assert runs.validated_run_world(inner, world_row(inner, run_id)).run_id == run_id
            assert runs.validated_run_world(outer, world_row(outer, run_id)).run_id == run_id
            saved_inner = copy_context()
            raise RuntimeError("leave inner view")
        assert inner_proofs.active is False and inner_proofs.worlds == {}
        assert saved_inner.run(snapshots._read_snapshot_proofs, inner) is None
        assert snapshots._read_snapshot_proofs(outer) is outer_proofs
        assert runs.validated_run_world(outer, world_row(outer, run_id)).run_id == run_id
        assert connection_counts(calls, outer) == {run_id: 2}
        assert connection_counts(calls, inner) == {run_id: 1}
    assert outer_proofs.active is False and outer_proofs.worlds == {}
    assert snapshots._READ_SNAPSHOT_PROOFS.get() is None


def test_a_copied_context_on_another_thread_cannot_hit_or_touch_the_owned_connection(
    created_worlds, journal, monkeypatch,
) -> None:
    run_id, _legacy = created_worlds
    calls = count_uncached(monkeypatch)
    with journal._read() as connection:
        row = world_row(connection, run_id)
        assert runs.validated_run_world(connection, row).run_id == run_id
        inherited = copy_context()

        def in_other_thread():
            try:
                proof = snapshots._read_snapshot_proofs(connection)
            except Exception as exc:
                return "accessor touched foreign connection", exc
            try:
                outcome = runs.validated_run_world(connection, row)
            except Exception as exc:
                outcome = exc
            return proof, outcome

        with ThreadPoolExecutor(max_workers=1) as executor:
            proof, outcome = executor.submit(inherited.run, in_other_thread).result(timeout=5)
        assert proof is None
        assert isinstance(outcome, sqlite3.ProgrammingError)
        assert connection_counts(calls, connection) == {run_id: 2}
        assert runs.validated_run_world(connection, row).run_id == run_id
        assert connection_counts(calls, connection) == {run_id: 2}


def test_a_write_transaction_never_owns_world_reuse(created_worlds, journal, monkeypatch) -> None:
    run_id, _legacy = created_worlds
    calls = count_uncached(monkeypatch)
    with journal._txn() as connection:
        assert connection.in_transaction
        assert snapshots._read_snapshot_proofs(connection) is None
        row = world_row(connection, run_id)
        assert runs.validated_run_world(connection, row).run_id == run_id
        assert runs.validated_run_world(connection, row).run_id == run_id
        assert connection_counts(calls, connection) == {run_id: 2}


def test_complete_open_audit_still_refuses_a_corrupt_nonworld_fact(created_worlds, journal) -> None:
    run_id, _legacy = created_worlds
    produced = next(event for event in journal.events(run_id) if event.kind == "NodeCompleted")
    with sqlite3.connect(journal._db_path) as writer:
        writer.execute(
            "UPDATE events SET payload = ? WHERE run_id = ? AND seq = ?",
            (json.dumps({"rewritten": True}), run_id, produced.seq),
        )
    with pytest.raises(JournalDamaged):
        SqliteJournal(journal._db_path)
