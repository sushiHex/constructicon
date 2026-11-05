"""Credential-free durability proof at the executor metering journal boundary."""

from __future__ import annotations

import sqlite3
import subprocess
import sys

import pytest
from tests.run_worlds import sealed_test_manifest, start_test_run

from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.executor import ExecutorError, ExecutorFailure, ExecutorSuccess, Usage
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.manifest import CapabilityBinding, CapabilityLease, manifest_hash_for
from constructicon.core.run import CheckpointConflict, OwnershipLost
from constructicon.core.workspace import LeaseContext, lease_id_for
from constructicon.substrate.journal._sqlite_metering import (
    ERA_FAMILY,
    METERING_EVENT,
    RELATION_FAMILY,
)
from constructicon.substrate.journal.sqlite import SqliteJournal

RUN = RunId("metering-attempt")
MODEL = "gpt-test"
SOURCE = "codex_fresh_thread_total_v1"
CLAUDE = "claude_main_loop_v1"
SCOPE = ScopePath(segments=("loop", "body", "executor"))
BINDING = CapabilityBinding(
    scope=SCOPE, binding="executor", capability_id="executor.native", revision="sealed-revision",
    effective_grants=EffectiveGrants(
        posture=Posture.READ, model_selection=ModelSelection(kind="explicit", model=MODEL),
        effort="medium", allowed_tools=(), env_allowlist=(), network="allow", timeout_s=30,
    ),
)
SUCCESS = ExecutorSuccess(
    requested_model=MODEL, served_model="rerouted-model",
    usage=Usage(input_tokens=11, output_tokens=3),
)


def create(journal, run=RUN):
    manifest = sealed_test_manifest().model_copy(update={"capability_bindings": (BINDING,)})
    manifest = manifest.model_copy(update={"manifest_hash": manifest_hash_for(manifest)})
    journal.create_run(
        run, manifest_json=manifest.model_dump_json(), manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash, inputs={},
    )
    return manifest


def context_for(journal, owner, index=0, *, retain=True):
    manifest = create(journal, owner.run_id)
    path = ExecutionPath(
        scope=SCOPE,
        iterations=(IterationFrame(loop=ScopePath(segments=("loop",)), index=index),),
    )
    if retain:
        journal.record_capability_lease(owner, CapabilityLease(
            run_id=owner.run_id, lease_id=lease_id_for(owner.run_id, path, BINDING.binding),
            acquisition_epoch=owner.epoch, binding_id=BINDING.binding, path=path, state="active",
        ))
    return LeaseContext(
        run_lease=owner, binding=BINDING, path=path, manifest_hash=manifest.manifest_hash,
    )


def writer(journal, context, source=SOURCE, model=MODEL):
    return journal.executor_meter(
        context, revision=BINDING.revision, source=source, configured_model=model,
    )


def snapshot(journal, run=RUN, **page):
    head = journal.run_head(run)
    return journal.executor_metering_snapshot(run, through_event_seq=head.event_seq, **page)


def test_intent_outcome_are_write_once_and_a_later_outcome_does_not_change_old_cut(journal):
    create(journal)
    owner = start_test_run(journal, RUN, owner_id="owner")
    context = context_for(journal, owner)
    meter = writer(journal, context)
    with pytest.raises(ContractViolation, match="fenced writer"):
        journal.append_event(owner, METERING_EVENT)
    with pytest.raises(ContractViolation, match="sealed route"):
        writer(journal, context, model="different-model").intend()
    assert snapshot(journal).attempt_count == 0

    meter.intend()
    meter.check_dispatch()
    old = snapshot(journal, limit=1)
    assert old.attempt_count == old.groups[0].intent_only == 1
    assert old.groups[0].known_input_tokens is old.groups[0].known_output_tokens is None
    assert old.attempts[0].outcome is None
    replay = writer(journal, context)
    with pytest.raises(ContractViolation, match="replayed"):
        replay.intend()
    with pytest.raises(ContractViolation, match="no fresh"):
        replay.check_dispatch()

    meter.settle(SUCCESS)
    new = snapshot(journal, limit=1)
    meter.settle(SUCCESS)
    assert snapshot(journal, limit=1) == new
    with pytest.raises(CheckpointConflict, match="different facts"):
        meter.settle(None)
    assert journal.executor_metering_snapshot(RUN, through_event_seq=old.event_seq, limit=1) == old
    assert (new.groups[0].observed, new.groups[0].known_input_tokens,
            new.groups[0].known_output_tokens) == (1, 11, 3)
    assert new.attempts[0].intent_evidence == old.attempts[0].intent_evidence
    assert new.attempts[0].outcome_evidence.event_seq > old.event_seq
    assert new.attempts[0].outcome.served_model == "rerouted-model"


def test_new_epochs_frames_and_same_world_runs_have_distinct_attempts(journal, clock):
    create(journal)
    original = start_test_run(journal, RUN, owner_id="owner", ttl_s=5)
    first = writer(journal, context_for(journal, original))
    first.intend()
    first.check_dispatch()
    clock.advance(6)
    current = journal.claim_run(RUN, owner_id="successor", ttl_s=30)
    with pytest.raises(OwnershipLost):
        first.settle(SUCCESS)
    second = writer(journal, context_for(journal, current))
    second.intend()
    second.check_dispatch()
    second.settle(SUCCESS)
    framed = writer(journal, context_for(journal, current, index=1), source=CLAUDE)
    framed.intend()
    framed.check_dispatch()
    framed.settle(ExecutorFailure(
        usage=Usage(input_tokens=17),
        error=ExecutorError(kind="exit", detail="secret internal refusal"),
    ))
    other_run = RunId("metering-same-world-other-run")
    assert create(journal, other_run) == create(journal)
    other_owner = start_test_run(journal, other_run, owner_id="other")
    other = writer(journal, context_for(journal, other_owner))
    other.intend()
    other.check_dispatch()
    other.settle(SUCCESS)

    result = snapshot(journal, limit=10)
    assert result.attempt_count == 3
    assert len({row.intent.acquisition_id for row in result.attempts}) == 3
    assert result.attempts[0].outcome is None
    assert "secret internal refusal" not in result.model_dump_json()
    claude, codex = result.groups
    assert (claude.source, claude.partial, claude.known_input_tokens,
            claude.known_output_tokens) == (CLAUDE, 1, 17, None)
    assert (codex.source, codex.intent_only, codex.observed,
            codex.known_input_tokens, codex.known_output_tokens) == (SOURCE, 1, 1, 11, 3)
    assert snapshot(journal, other_run, limit=1).attempt_count == 1
    first_page = snapshot(journal, limit=1)
    second_page = snapshot(
        journal, after_intent_seq=first_page.attempts[0].intent_evidence.event_seq, limit=1,
    )
    assert second_page.attempts[0] == result.attempts[1]


@pytest.mark.parametrize("fault,expected", (
    ("intent.before_commit", None),
    ("intent.after_commit", "intent"),
    ("outcome.before_commit", "intent"),
    ("outcome.after_commit", "outcome"),
))
def test_real_process_death_preserves_only_co_committed_phases(tmp_path, fault, expected):
    database = tmp_path / "metering-death.db"
    journal = SqliteJournal(database)
    create(journal)
    owner = start_test_run(journal, RUN, owner_id="child-owner", ttl_s=90)
    context_for(journal, owner)
    program = """
import os
import sys
from constructicon.core.run import RunLease
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.substrate.journal.test_executor_metering import SUCCESS, context_for, writer
journal = SqliteJournal(sys.argv[1])
owner = RunLease.model_validate_json(sys.argv[2])
def fault(name):
    if name == 'metering.' + sys.argv[3]:
        os._exit(91)
journal.fault_probe = fault
meter = writer(journal, context_for(journal, owner, retain=False))
meter.intend()
meter.check_dispatch()
meter.settle(SUCCESS)
raise AssertionError('metering seam not reached')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(database), owner.model_dump_json(), fault],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
    )
    assert result.returncode == 91, result.stderr.decode("utf-8", errors="replace")
    reopened = SqliteJournal(database)
    retained = snapshot(reopened, limit=1)
    if expected is None:
        assert retained.attempt_count == 0 and retained.coverage == "unmeasured"
    elif expected == "intent":
        assert retained.attempt_count == 1 and retained.attempts[0].outcome is None
        assert retained.groups[0].intent_only == 1
    else:
        assert retained.attempt_count == 1 and retained.groups[0].known_input_tokens == 11
        assert retained.attempts[0].outcome_evidence is not None
        assert reopened.checkpoint(RUN, retained.attempts[0].intent.path) is None


@pytest.mark.parametrize("damage", ("missing-era", "missing-relation", "moved-relation",
                                    "missing-event", "replaced-event"))
def test_both_inventory_directions_refuse_damage(journal, damage):
    create(journal)
    owner = start_test_run(journal, RUN, owner_id="owner")
    meter = writer(journal, context_for(journal, owner))
    meter.intend()
    meter.check_dispatch()
    meter.settle(SUCCESS)
    head = journal.run_head(RUN).event_seq
    with sqlite3.connect(journal._db_path) as connection:
        if damage == "missing-era":
            connection.execute("DELETE FROM durable_fact_seals WHERE family=?", (ERA_FAMILY,))
        elif damage == "missing-relation":
            connection.execute("DELETE FROM durable_fact_seals WHERE family=?", (RELATION_FAMILY,))
        elif damage == "moved-relation":
            connection.execute(
                "UPDATE durable_fact_seals SET fact_key=replace(fact_key, ?, 'foreign') "
                "WHERE family=?", (RUN, RELATION_FAMILY),
            )
        elif damage == "missing-event":
            connection.execute("DELETE FROM events WHERE run_id=? AND seq=?", (RUN, head))
        else:
            connection.execute("UPDATE events SET kind='Foreign' WHERE run_id=? AND seq=?",
                               (RUN, head))
    with pytest.raises(JournalDamaged):
        journal.executor_metering_snapshot(RUN, through_event_seq=head, limit=1)
    with pytest.raises(JournalDamaged):
        SqliteJournal(journal._db_path)


def test_migration_seals_preexisting_run_unmeasured_even_after_a_resume(tmp_path):
    database = tmp_path / "metering-migrate.db"
    journal = SqliteJournal(database)
    create(journal)
    old = start_test_run(journal, RUN, owner_id="old")
    journal.release_run(old)
    # This migration adds seals and no table or column. Removing the era seal
    # reproduces the prior writer's exact schema and event shape.
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM durable_fact_seals WHERE family=?", (ERA_FAMILY,))
        connection.execute("PRAGMA user_version=10")
    journal = SqliteJournal(database)
    resumed = journal.claim_run(RUN, owner_id="resumed", ttl_s=30)
    meter = writer(journal, context_for(journal, resumed))
    meter.intend()
    meter.check_dispatch()
    meter.settle(SUCCESS)
    projected = snapshot(journal, limit=1)
    assert projected.coverage == "legacy_unmeasured"
    assert projected.attempt_count == 0 and projected.groups == projected.attempts == ()
    with pytest.raises(JournalDamaged, match="outside"):
        journal.executor_metering_snapshot(RUN, through_event_seq=projected.event_seq + 1)


def test_historical_cut_rejects_orphan_relation_beyond_current_head(journal):
    from constructicon.core.identity import canonical_json
    from constructicon.substrate.journal._sqlite_execution_facts import event_fact_key

    create(journal)
    owner = start_test_run(journal, RUN, owner_id="owner")
    context = context_for(journal, owner)
    meter = writer(journal, context)
    meter.intend()
    earlier = snapshot(journal, limit=1)
    meter.check_dispatch()
    meter.settle(SUCCESS)
    assert journal.executor_metering_snapshot(
        RUN, through_event_seq=earlier.event_seq, limit=1,
    ) == earlier
    head = journal.run_head(RUN).event_seq
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "INSERT INTO durable_fact_seals(family, fact_key, selector, fact_hash)"
            " VALUES (?, ?, ?, ?)",
            (RELATION_FAMILY, event_fact_key(RUN, head + 1),
             canonical_json([RUN, "acq-phantom", "outcome"]), "sha256:" + "1" * 64),
        )
    with pytest.raises(JournalDamaged, match="beyond"):
        journal.executor_metering_snapshot(RUN, through_event_seq=earlier.event_seq, limit=1)
    with pytest.raises(JournalDamaged, match="beyond"):
        journal.executor_metering_snapshot(RUN, through_event_seq=head, limit=1)


def test_post_commit_owner_expiry_cannot_use_fresh_intent(journal, clock):
    create(journal)
    owner = start_test_run(journal, RUN, owner_id="owner", ttl_s=1)
    meter = writer(journal, context_for(journal, owner))

    def expire(name):
        if name == "metering.intent.after_commit":
            clock.advance(2)

    journal.fault_probe = expire
    meter.intend()
    with pytest.raises(OwnershipLost):
        meter.check_dispatch()
    with pytest.raises(ContractViolation, match="no fresh"):
        meter.check_dispatch()
    assert snapshot(journal).groups[0].intent_only == 1


@pytest.mark.parametrize("boundary", ("record", "input", "intent", "write"))
async def test_codex_actual_task_send_orders_bounds_intent_and_native_write(journal, boundary):
    from tests.substrate.test_codex_adapter import EXPECTED, GRANTS

    from constructicon.core.executor import TaskSpec
    from constructicon.substrate.executors.codex import CodexConversation
    from constructicon.substrate.executors.codex_protocol import RECORD_BYTES

    create(journal)
    owner = start_test_run(journal, RUN, owner_id="owner")
    meter = writer(journal, context_for(journal, owner))
    steps = []

    def before_task_write():
        steps.append("intent")
        meter.intend()
        meter.check_dispatch()

    def fault(name):
        if boundary == "intent" and name == "metering.intent.before_commit":
            raise ContractViolation("intent commit refused")

    journal.fault_probe = fault
    conversation = CodexConversation(
        task=TaskSpec(instruction="fixture"), grants=GRANTS, expected=EXPECTED,
        input_limit=64 if boundary == "input" else 2 * RECORD_BYTES,
        before_task_write=before_task_write,
    )

    class IO:
        async def write(self, raw):
            steps.append("native_write")
            assert snapshot(journal).groups[0].intent_only == 1
            assert b"turn/start" in raw
            raise OSError("the transport ended during its first write")

    length = RECORD_BYTES if boundary == "record" else 128
    payload = {"id": 1, "method": "turn/start", "params": {"fixture": "x" * length}}
    if boundary == "intent":
        with pytest.raises(ContractViolation, match="intent commit refused"):
            await conversation._send(IO(), payload)
        assert steps == ["intent"]
    else:
        assert not await conversation._send(IO(), payload)
    if boundary in ("record", "input"):
        assert steps == []
    if boundary == "write":
        assert steps == ["intent", "native_write"] and conversation.turn_sent
        assert snapshot(journal, limit=1).attempts[0].outcome is None
    else:
        assert not conversation.turn_sent
        assert snapshot(journal).attempt_count == 0


@pytest.mark.parametrize("seam", ("before_commit", "after_commit"))
def test_real_process_metering_migration_death_publishes_era_atomically(tmp_path, seam):
    database = tmp_path / "metering-migration-death.db"
    create(SqliteJournal(database))
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM durable_fact_seals WHERE family=?", (ERA_FAMILY,))
        connection.execute("PRAGMA user_version=10")
    program = """
import os
import sys
from constructicon.substrate.journal._sqlite_schema import _SqliteSchemaMixin
from constructicon.substrate.journal.sqlite import SqliteJournal
original = _SqliteSchemaMixin._migrate_m10_to_m11
def interrupted(self, connection):
    def fault(name):
        if name == 'metering_migration.' + sys.argv[2]:
            os._exit(91)
    self.fault_probe = fault
    original(self, connection)
_SqliteSchemaMixin._migrate_m10_to_m11 = interrupted
SqliteJournal(sys.argv[1])
raise AssertionError('metering migration seam not reached')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(database), seam],
        stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
    )
    assert result.returncode == 91, result.stderr.decode("utf-8", errors="replace")
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (
            11 if seam == "after_commit" else 10,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals WHERE family=?", (ERA_FAMILY,),
        ).fetchone() == (1 if seam == "after_commit" else 0,)
    assert snapshot(SqliteJournal(database)).coverage == "legacy_unmeasured"
