"""M6 durable command law over the transport-neutral control plane."""

from __future__ import annotations

import asyncio

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.address import RunId
from constructicon.core.control import (
    ADMIN_SCOPE,
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
    RunSubmission,
)
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock, InjectedCrash, pipeline_graph


ACTOR = AuthenticatedActor(
    actor_id="static:test-agent",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
)


async def test_start_returns_immediately_and_retry_replays_one_run(
    world,
    journal: SqliteJournal,
) -> None:
    host = RunHost(world, max_concurrency=1)
    control = ControlPlane(system=world, store=journal, run_host=host, owner_id="control-a")

    first = await control.runs_start(
        ACTOR,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": "flaky"}},
        idempotency_key="start-one",
    )
    assert isinstance(first, RunSubmission)
    assert first.run_status is RunStatus.PENDING
    result = await host.wait(first.run_id)
    assert result is not None and result.status is RunStatus.SUCCEEDED

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
    host = RunHost(world)
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
    host_a = RunHost(world)
    control_a = ControlPlane(
        system=world,
        store=journal,
        run_host=host_a,
        owner_id="control-a",
        command_ttl_s=30,
    )

    def crash(name: str) -> None:
        if name == "runs_start.after_domain_mutation":
            raise InjectedCrash(name)

    control_a.fault_probe = crash
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

    command_id = next(
        record.command_id
        for record in [journal.command(command_id) for command_id in []]
    ) if False else None
    # The deterministic planned run exists even though no command response did.
    assert len(journal.run_records(limit=100)) == 1
    clock.advance(31)
    host_b = RunHost(world)
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
    result = await host_b.wait(replay.run_id)
    assert result is not None and result.status is RunStatus.SUCCEEDED
    assert len(journal.run_records(limit=100)) == 1
    await host_a.shutdown()
    await host_b.shutdown()


async def test_shutdown_abandons_without_cancelling(world, journal: SqliteJournal) -> None:
    # A PENDING run can be hosted and abandoned without ever setting cancel intent.
    manifest = world.validate(pipeline_graph(), {"issue": {"title": "abandon"}})
    run_id = RunId("run-abandon")
    world.prepare(manifest, run_id=run_id, inputs={"issue": {"title": "abandon"}})
    host = RunHost(world, max_concurrency=1)
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
