"""M6 durable command law over the transport-neutral control plane."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import cast

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.component import LearningProfile
from constructicon.core.control import (
    ADMIN_SCOPE,
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
    RegistrationCommandResult,
    RunSubmission,
)
from constructicon.core.graph import Ref
from constructicon.core.identity import digest
from constructicon.core.run import RunStatus
from constructicon.runtime.registry import ComponentRegistry, InMemoryRegistryStore
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.control import InMemoryControlStore
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import (
    BRIEF,
    ISSUE,
    FakeClock,
    InjectedCrash,
    atomic,
    await_attempt_terminal,
    pipeline_graph,
    triage_impl,
)
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6

ACTOR = AuthenticatedActor(
    actor_id="static:test-agent",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
)
ADMIN = AuthenticatedActor(
    actor_id="static:test-admin",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, ADMIN_SCOPE}),
)


class _ValueEqualSqliteJournal(SqliteJournal):
    """A distinct ledger that defeats equality-based world checks."""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SqliteJournal)


class _ValueEqualComponentRegistry(ComponentRegistry):
    def __eq__(self, other: object) -> bool:
        return isinstance(other, ComponentRegistry)


class _ValueEqualConstructicon(Constructicon):
    def __eq__(self, other: object) -> bool:
        return isinstance(other, Constructicon)


def test_control_plane_refuses_a_store_that_cannot_commit_channel_exchanges(world) -> None:
    with pytest.raises(TypeError, match="co-locate command, approval, and channel"):
        ControlPlane(system=world, store=InMemoryControlStore())  # type: ignore[arg-type]


def test_control_plane_refuses_a_store_or_journal_from_another_world(
    tmp_path,
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    other = _ValueEqualSqliteJournal(tmp_path / "other-world.db")
    assert other == journal and other is not journal

    with pytest.raises(ValueError, match="store must be the exact journal"):
        ControlPlane(system=world, store=other)
    with pytest.raises(ValueError, match="journal must be the exact co-located store"):
        ControlPlane(system=world, store=journal, journal=other)


def test_control_plane_refuses_a_registry_or_host_from_another_world(
    tmp_path,
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    other = _ValueEqualSqliteJournal(tmp_path / "other-services.db")
    lookalike_registry = _ValueEqualComponentRegistry(store=journal)
    assert lookalike_registry == world._registry
    assert lookalike_registry is not world._registry

    with pytest.raises(ValueError, match="registry must be the exact registry"):
        ControlPlane(
            system=world,
            store=journal,
            registry=lookalike_registry,
        )
    with pytest.raises(ValueError, match="run host must serve the exact"):
        ControlPlane(
            system=world,
            store=journal,
            run_host=RunHost(world, journal=other),
        )
    lookalike_world = _ValueEqualConstructicon(journal=journal)
    assert lookalike_world == world and lookalike_world is not world
    with pytest.raises(ValueError, match="run host must serve the exact"):
        ControlPlane(
            system=world,
            store=journal,
            run_host=RunHost(lookalike_world, journal=journal),
        )
    with pytest.raises(TypeError, match="run host must be a RunHost"):
        ControlPlane(
            system=world,
            store=journal,
            run_host=cast(RunHost, object()),
        )


def test_control_plane_reuses_the_systems_legitimate_separate_registry(
    journal: SqliteJournal,
) -> None:
    system = Constructicon(journal=journal, store=InMemoryRegistryStore())
    control = ControlPlane(system=system, store=journal)

    assert control._commands._registry is system._registry
    assert control._queries._registry is system._registry


async def test_start_returns_immediately_and_retry_replays_one_run(
    world,
    journal: SqliteJournal,
) -> None:
    host = RunHost(world, journal=journal, max_concurrency=1)
    control = ControlPlane(system=world, store=journal, run_host=host, owner_id="control-a")

    first = await control.runs_start(
        ACTOR,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": "flaky"}},
        idempotency_key="start-one",
    )
    assert isinstance(first, RunSubmission)
    assert first.run_status is RunStatus.PENDING
    terminal = await await_attempt_terminal(journal, first.run_id, baseline_event_seq=0)
    assert terminal.kind == "RunSucceeded"

    replay = await control.runs_start(
        ACTOR,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": "flaky"}},
        idempotency_key="start-one",
    )
    assert isinstance(replay, RunSubmission)
    assert replay.run_id == first.run_id
    assert replay.command.replayed is True
    records = journal.run_records(limit=100)
    assert [record.run_id for record in records].count(first.run_id) == 1
    await host.shutdown()


async def test_same_key_different_request_is_conflict(world, journal: SqliteJournal) -> None:
    host = RunHost(world, journal=journal)
    control = ControlPlane(system=world, store=journal, run_host=host)
    first = await control.runs_start(
        ACTOR,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": "one"}},
        idempotency_key="conflict-key",
    )
    assert isinstance(first, RunSubmission)
    conflict = await control.runs_start(
        ACTOR,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": "two"}},
        idempotency_key="conflict-key",
    )
    assert isinstance(conflict, ControlRejected)
    assert conflict.faults[0].code is ControlCode.IDEMPOTENCY_CONFLICT
    await host.shutdown()


async def test_response_loss_after_run_creation_reconciles_from_plan(
    world,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    host_a = RunHost(world, journal=journal)

    def crash(name: str) -> None:
        if name == "runs_start.after_domain_mutation":
            raise InjectedCrash(name)

    control_a = ControlPlane(
        system=world,
        store=journal,
        run_host=host_a,
        owner_id="control-a",
        command_ttl_s=30,
        fault_probe=crash,
    )
    try:
        await control_a.runs_start(
            ACTOR,
            proposal=pipeline_graph(),
            inputs={"issue": {"title": "lost-response"}},
            idempotency_key="lost-response",
        )
    except InjectedCrash:
        pass
    else:  # pragma: no cover
        raise AssertionError("fault probe did not fire")

    # The deterministic planned run exists even though no command response did.
    assert len(journal.run_records(limit=100)) == 1
    clock.advance(31)
    host_b = RunHost(world, journal=journal)
    control_b = ControlPlane(
        system=world,
        store=journal,
        run_host=host_b,
        owner_id="control-b",
        command_ttl_s=30,
    )
    replay = await control_b.runs_start(
        ACTOR,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": "lost-response"}},
        idempotency_key="lost-response",
    )
    assert isinstance(replay, RunSubmission)
    assert replay.command.replayed is False  # first terminal response was recovered now
    terminal = await await_attempt_terminal(journal, replay.run_id, baseline_event_seq=0)
    assert terminal.kind == "RunSucceeded"
    assert len(journal.run_records(limit=100)) == 1
    await host_a.shutdown()
    await host_b.shutdown()


async def test_shutdown_abandons_without_cancelling(world, journal: SqliteJournal) -> None:
    # A PENDING run can be hosted and abandoned without ever setting cancel intent.
    manifest = world.validate(pipeline_graph(), {"issue": {"title": "abandon"}})
    run_id = RunId("run-abandon")
    world._prepare_run(manifest, run_id=run_id, inputs={"issue": {"title": "abandon"}})
    host = RunHost(world, journal=journal, max_concurrency=1)
    host.launch(run_id)
    await asyncio.sleep(0)
    await host.shutdown()
    record = journal.run_record(run_id)
    assert record is not None
    assert record.status is not RunStatus.CANCELLED
    assert record.cancel_requested is False


def test_scope_is_checked_before_command_claim(world, journal: SqliteJournal) -> None:
    actor = AuthenticatedActor(
        actor_id="static:reader",
        auth_method="static",
        scopes=frozenset({READ_SCOPE}),
    )
    control = ControlPlane(system=world, store=journal)
    rejected = asyncio.run(
        control.runs_cancel(
            actor,
            run_id=RunId("does-not-matter"),
            idempotency_key="not-claimed",
        )
    )
    assert isinstance(rejected, ControlRejected)
    assert rejected.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE


async def test_registration_reuses_a_row_retained_under_a_superseded_identity_law(
    world,
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    """A retained version keeps the identity it was written under.

    `content_hash` is a law, and laws move — this milestone's own
    `change_surfaces` serializer moved one. Re-registering a definition whose
    durable row predates the change must bind to that row, not recompute a
    fresh identity and declare the journal damaged.
    """

    definition, implementation = atomic(
        "control/superseded-identity",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    learning = LearningProfile(
        change_surfaces=frozenset({"code", "prompt"}),
        experience_policy=Ref(component="policy/experience"),
        evaluator=Ref(component="policy/evaluator"),
        promotion_policy=Ref(component="policy/promotion"),
    )
    definition = definition.model_copy(
        update={
            "metadata": definition.metadata.model_copy(update={"learning": learning})
        }
    )
    historical = definition.model_dump(mode="json")
    historical_metadata = historical["metadata"]
    assert isinstance(historical_metadata, dict)
    historical_learning = historical_metadata["learning"]
    assert isinstance(historical_learning, dict)
    # The pre-sort writer hashed and stored this retained array order.
    historical_learning["change_surfaces"] = ["prompt", "code"]
    superseded = digest(
        "component",
        1,
        {
            "role": historical["role"],
            "body": historical["body"],
            "inputs": historical["inputs"],
            "outputs": historical["outputs"],
            "learning": historical_learning,
        },
    )
    assert superseded != definition.content_hash()
    database = tmp_path / "journal.db"
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO components"
            " (name, content_hash, definition_json, registered_at)"
            " VALUES (?, ?, ?, ?)",
            (
                definition.name,
                str(superseded),
                json.dumps(historical, sort_keys=True, separators=(",", ":")),
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.commit()
    # Only migration may mint positive proof for a retained historical row.
    SqliteJournal(database)
    control = ControlPlane(
        system=world,
        store=journal,
        run_host=RunHost(world, journal=journal, max_concurrency=1),
        owner_id="control-superseded-identity",
    )
    bundle = DefinitionBundle(definition, implementation)

    registered = await control.registry_register(
        ADMIN,
        definition=bundle,
        idempotency_key="superseded-identity",
    )
    assert isinstance(registered, RegistrationCommandResult)
    assert registered.version == superseded

    replay = await control.registry_register(
        ADMIN,
        definition=bundle,
        idempotency_key="superseded-identity",
    )
    assert isinstance(replay, RegistrationCommandResult)
    assert replay.version == superseded and replay.command.replayed
    await control.shutdown()
