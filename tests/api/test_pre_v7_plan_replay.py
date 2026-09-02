"""A pre-v7 plan replays the answer it already gave.

A registry promotion refused after its plan, and a cancellation that found its
run already terminal, both recorded a response under schema 6 that schema 7
cannot re-derive: the promotion plan carries no `terminal_rejection_policy`,
the cancellation plan no `observed_event_seq`, because neither field existed.
The migration witnesses each such plan in the phase it finds it, and a terminal
witness binds the exact retained response — so the stored answer is the fact,
and the idempotency key that produced it keeps producing it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, cast

import pytest

from constructicon.api.run_host import RunHost
from constructicon.core.control import (
    CancellationResult,
    ControlCode,
    ControlRejected,
    command_id_for,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import canonical_json
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import (
    AUTHORITY_ACTOR,
    LOCAL_ADMIN,
    RUN_ACTOR,
    _candidate,
    _competing_candidate,
    _crash_at,
    _fresh_control,
    _PassiveHost,
    _prepare_failed_run,
    _prepare_terminal_run,
    _rewrite_terminal_fault,
)
from tests.conftest import (
    BRIEF,
    ISSUE,
    FakeAnnounceEffect,
    FakeClock,
    FakeExecutor,
    InjectedCrash,
    atomic,
    build_system,
    triage_impl,
)
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6


def _strip_after_downgrade(database: Path, command_id: str, field: str) -> None:
    """Rewrite one plan to the shape schema 6 actually wrote, on a schema-6 file."""

    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        plan = json.loads(row[0])
        assert plan["plan"].pop(field) is not None
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(plan), command_id),
        )
        connection.commit()


async def test_a_pre_v7_promotion_refusal_replays_after_migration(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    definition, implementation = atomic(
        "control/pre-v7-promotion-refusal",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    planned_version = world._register(definition, implementation)
    other_version = world._register(definition.model_copy(update={"role": "component"}))
    key = "pre-v7-promotion-refusal"
    command_id = command_id_for(LOCAL_ADMIN.actor_id, "registry_promote_initial", key)

    planner = _fresh_control(
        world,
        journal,
        "control-pre-v7-promotion-a",
        fault_probe=_crash_at("registry_promote_initial", "after_plan"),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await planner.registry_promote_initial(
            LOCAL_ADMIN,
            component=definition.name,
            version=planned_version,
            idempotency_key=key,
        )
    world._promote_initial(component=definition.name, version=other_version)
    clock.advance(31)
    refuser = _fresh_control(
        world,
        journal,
        "control-pre-v7-promotion-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    refused = await refuser.registry_promote_initial(
        LOCAL_ADMIN,
        component=definition.name,
        version=planned_version,
        idempotency_key=key,
    )
    assert isinstance(refused, ControlRejected)
    assert [fault.code for fault in refused.faults] == [ControlCode.REGISTRY_STABLE_MOVED]
    await planner.shutdown()
    await refuser.shutdown()

    # A schema-6 writer's refusal is not byte-identical to what today's law
    # derives — that is the whole reason it cannot be re-derived. Give the
    # retained response an older wording and reseal its terminal phase, then
    # make the store exactly what schema 6 wrote.
    older_wording = "promote through the evaluated path; stable already moved"
    _rewrite_terminal_fault(journal._db_path, command_id, repair=older_wording)
    _strip_after_downgrade(Path(journal._db_path), command_id, "terminal_rejection_policy")

    # A restarted process: the store migrates on open, and a new system is
    # assembled over exactly that journal.
    migrated = SqliteJournal(journal._db_path, now_fn=clock.now)
    witness = migrated.historical_domain_plan_evidence(command_id)
    assert witness is not None and witness.phase_at_migration == "terminal"
    restarted = build_system(migrated, fake_executor, announce_effect, owner_id="restarted")

    replayer = _fresh_control(
        restarted,
        migrated,
        "control-pre-v7-promotion-c",
        run_host=cast(RunHost, _PassiveHost()),
    )
    replayed = await replayer.registry_promote_initial(
        LOCAL_ADMIN,
        component=definition.name,
        version=planned_version,
        idempotency_key=key,
    )
    assert isinstance(replayed, ControlRejected)
    assert replayed.faults[0].code is ControlCode.REGISTRY_STABLE_MOVED
    assert replayed.faults[0].repair == older_wording
    await replayer.shutdown()


@pytest.mark.parametrize("status", [RunStatus.SUCCEEDED, RunStatus.FAILED])
async def test_a_pre_v7_already_terminal_cancellation_replays_after_migration(
    status: RunStatus,
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    """Both statuses: the witness makes the resumable one replayable too."""

    suffix = f"pre-v7-cancel-{status.value}"
    run_id = (
        _prepare_terminal_run(world, journal, suffix, status)
        if status is RunStatus.SUCCEEDED
        else _prepare_failed_run(world, journal, suffix)
    )
    key = suffix
    command_id = command_id_for(RUN_ACTOR.actor_id, "runs_cancel", key)
    control = _fresh_control(
        world,
        journal,
        f"control-{suffix}",
        run_host=cast(RunHost, _PassiveHost()),
    )
    first = await control.runs_cancel(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(first, CancellationResult)
    assert first.status == "already_terminal"
    await control.shutdown()

    _strip_after_downgrade(Path(journal._db_path), command_id, "observed_event_seq")

    migrated = SqliteJournal(journal._db_path, now_fn=clock.now)
    witness = migrated.historical_domain_plan_evidence(command_id)
    assert witness is not None and witness.phase_at_migration == "terminal"
    restarted = build_system(migrated, fake_executor, announce_effect, owner_id="restarted")

    replayer = _fresh_control(
        restarted,
        migrated,
        f"control-{suffix}-replay",
        run_host=cast(RunHost, _PassiveHost()),
    )
    replayed = await replayer.runs_cancel(RUN_ACTOR, run_id=run_id, idempotency_key=key)
    assert isinstance(replayed, CancellationResult)
    assert replayed.command.replayed
    assert replayed.status == "already_terminal"
    await replayer.shutdown()


def _rewrite_to_raw_promotion(database: Path, command_id: str) -> None:
    """Rewrite one typed promotion plan to the bare object the first writer stored."""

    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT plan_json FROM commands WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        assert row is not None and isinstance(row[0], str)
        inner = json.loads(row[0])["plan"]
        assert inner["kind"] == "promotion"
        raw = {
            "component": inner["component"],
            "baseline": inner["baseline"],
            "version": inner["target"],
            "attestation_id": inner["attestation_id"],
        }
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(raw), command_id),
        )
        connection.commit()


async def test_a_raw_pre_envelope_promotion_refusal_replays_after_migration(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    """The first registry writer stored bare objects; they are an era too."""

    component = "control/raw-promotion-refusal"
    v1, planned_version, planned_attestation = _candidate(world, component)
    key = "raw-promotion-refusal"
    command_id = command_id_for(AUTHORITY_ACTOR.actor_id, "registry_promote", key)
    planner = _fresh_control(
        world,
        journal,
        "control-raw-promotion-a",
        fault_probe=_crash_at("registry_promote", "after_plan"),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await planner.registry_promote(
            AUTHORITY_ACTOR,
            component=component,
            version=planned_version,
            attestation_id=planned_attestation,
            idempotency_key=key,
        )
    other_version, other_attestation = _competing_candidate(
        world,
        component,
        baseline=v1,
        role="harness",
    )
    world._promote_version(
        component=component,
        version=other_version,
        attestation_id=other_attestation,
        actor="competing-promotion",
    )
    clock.advance(31)
    refuser = _fresh_control(
        world,
        journal,
        "control-raw-promotion-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    refused = await refuser.registry_promote(
        AUTHORITY_ACTOR,
        component=component,
        version=planned_version,
        attestation_id=planned_attestation,
        idempotency_key=key,
    )
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.REGISTRY_STABLE_MOVED
    await planner.shutdown()
    await refuser.shutdown()

    older_wording = "the stable pointer moved; resubmit under a new key"
    _rewrite_terminal_fault(journal._db_path, command_id, repair=older_wording)
    _rewrite_to_raw_promotion(Path(journal._db_path), command_id)

    migrated = SqliteJournal(journal._db_path, now_fn=clock.now)
    witness = migrated.historical_domain_plan_evidence(command_id)
    assert witness is not None and witness.phase_at_migration == "terminal"
    restarted = build_system(migrated, fake_executor, announce_effect, owner_id="restarted")
    replayer = _fresh_control(
        restarted,
        migrated,
        "control-raw-promotion-c",
        run_host=cast(RunHost, _PassiveHost()),
    )
    replayed = await replayer.registry_promote(
        AUTHORITY_ACTOR,
        component=component,
        version=planned_version,
        attestation_id=planned_attestation,
        idempotency_key=key,
    )
    assert isinstance(replayed, ControlRejected)
    assert replayed.faults[0].code is ControlCode.REGISTRY_STABLE_MOVED
    assert replayed.faults[0].repair == older_wording
    await replayer.shutdown()


async def test_a_terminal_witness_excuses_the_wording_and_not_the_code(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    """Every writer that refused after a promotion plan refused for one reason.

    The witness binds bytes no law today can re-derive. The code is not among
    them: it is checkable without any bytes, and a witnessed refusal carrying
    a code no writer ever emitted is not history but a contradiction.
    """

    definition, implementation = atomic(
        "control/witnessed-unlawful-code",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    planned_version = world._register(definition, implementation)
    other_version = world._register(definition.model_copy(update={"role": "component"}))
    key = "witnessed-unlawful-code"
    command_id = command_id_for(LOCAL_ADMIN.actor_id, "registry_promote_initial", key)
    planner = _fresh_control(
        world,
        journal,
        "control-unlawful-code-a",
        fault_probe=_crash_at("registry_promote_initial", "after_plan"),
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(InjectedCrash):
        await planner.registry_promote_initial(
            LOCAL_ADMIN,
            component=definition.name,
            version=planned_version,
            idempotency_key=key,
        )
    world._promote_initial(component=definition.name, version=other_version)
    clock.advance(31)
    refuser = _fresh_control(
        world,
        journal,
        "control-unlawful-code-b",
        run_host=cast(RunHost, _PassiveHost()),
    )
    refused = await refuser.registry_promote_initial(
        LOCAL_ADMIN,
        component=definition.name,
        version=planned_version,
        idempotency_key=key,
    )
    assert isinstance(refused, ControlRejected)
    await planner.shutdown()
    await refuser.shutdown()

    _rewrite_terminal_fault(journal._db_path, command_id, code=ControlCode.RUN_UNKNOWN)
    _strip_after_downgrade(Path(journal._db_path), command_id, "terminal_rejection_policy")

    migrated = SqliteJournal(journal._db_path, now_fn=clock.now)
    witness = migrated.historical_domain_plan_evidence(command_id)
    assert witness is not None and witness.phase_at_migration == "terminal"
    restarted = build_system(migrated, fake_executor, announce_effect, owner_id="restarted")
    replayer = _fresh_control(
        restarted,
        migrated,
        "control-unlawful-code-c",
        run_host=cast(RunHost, _PassiveHost()),
    )
    with pytest.raises(JournalDamaged, match="unlawful code"):
        await replayer.registry_promote_initial(
            LOCAL_ADMIN,
            component=definition.name,
            version=planned_version,
            idempotency_key=key,
        )
    await replayer.shutdown()
