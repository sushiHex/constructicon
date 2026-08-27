"""M6 counterfactuals pin source resolution and simulate every effect."""

from __future__ import annotations

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.control import (
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
    RunSubmission,
)
from constructicon.core.identity import Digest
from constructicon.core.run import RunStatus
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import (
    ISSUE,
    REVIEW,
    atomic,
    pipeline_graph,
    review_impl,
)

ACTOR = AuthenticatedActor(
    actor_id="static:counterfactual",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
)


async def _source_run(
    control: ControlPlane,
    host: RunHost,
    *,
    key: str,
) -> RunSubmission:
    source = await control.runs_start(
        ACTOR,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": key}},
        idempotency_key=key,
    )
    assert isinstance(source, RunSubmission)
    live_result = await host.wait(source.run_id)
    assert live_result is not None and live_result.status is RunStatus.SUCCEEDED
    return source


async def test_counterfactual_uses_distinct_simulated_effect_identity(
    world,
    journal: SqliteJournal,
    announce_effect: FakeAnnounceEffect,
) -> None:
    host = RunHost(world)
    control = ControlPlane(system=world, store=journal, run_host=host)
    source = await _source_run(control, host, key="source")
    assert len(announce_effect.executions) == 1

    replay = await control.runs_counterfactual(
        ACTOR,
        source_run_id=source.run_id,
        overrides={},
        idempotency_key="counterfactual",
    )
    assert isinstance(replay, RunSubmission)
    simulated_result = await host.wait(replay.run_id)
    assert simulated_result is not None
    assert simulated_result.status is RunStatus.SUCCEEDED
    assert len(announce_effect.executions) == 1
    assert len(announce_effect.simulations) == 1
    assert (
        announce_effect.executions[0].idempotency_key
        != announce_effect.simulations[0].idempotency_key
    )
    assert announce_effect.simulations[0].mode == "simulated"

    origin = journal.run_origin(replay.run_id)
    assert origin is not None
    assert origin.source_run_id == source.run_id
    assert origin.effects == "simulated"
    assert origin.capabilities == "discard"
    events = journal.events(replay.run_id, after_seq=0, limit=100)
    assert any(event.kind == "EffectSimulated" for event in events)
    receipt = journal.receipt_for(announce_effect.simulations[0].idempotency_key)
    assert receipt is not None and receipt.status == "simulated"
    await host.shutdown()


async def test_counterfactual_refuses_component_absent_from_source_world(
    world,
    journal: SqliteJournal,
    announce_effect: FakeAnnounceEffect,
) -> None:
    host = RunHost(world)
    control = ControlPlane(system=world, store=journal, run_host=host)
    source = await _source_run(control, host, key="source-missing-component")
    before_runs = len(journal.run_records(limit=100))

    rejected = await control.runs_counterfactual(
        ACTOR,
        source_run_id=source.run_id,
        overrides={"missing/component": Digest("sha256:" + "0" * 64)},
        idempotency_key="counterfactual-missing-component",
    )
    assert isinstance(rejected, ControlRejected)
    assert rejected.faults[0].code is ControlCode.COUNTERFACTUAL_OVERRIDE_INVALID
    assert len(journal.run_records(limit=100)) == before_runs
    assert len(announce_effect.simulations) == 0
    await host.shutdown()


async def test_counterfactual_refuses_unretained_exact_version(
    world,
    journal: SqliteJournal,
    announce_effect: FakeAnnounceEffect,
) -> None:
    host = RunHost(world)
    control = ControlPlane(system=world, store=journal, run_host=host)
    source = await _source_run(control, host, key="source-missing-version")
    before_runs = len(journal.run_records(limit=100))

    rejected = await control.runs_counterfactual(
        ACTOR,
        source_run_id=source.run_id,
        overrides={"test/triage": Digest("sha256:" + "0" * 64)},
        idempotency_key="counterfactual-missing-version",
    )
    assert isinstance(rejected, ControlRejected)
    assert rejected.faults[0].code is ControlCode.REGISTRY_VERSION_UNKNOWN
    assert len(journal.run_records(limit=100)) == before_runs
    assert len(announce_effect.simulations) == 0
    await host.shutdown()


async def test_counterfactual_refuses_contract_incompatible_retained_override(
    world,
    journal: SqliteJournal,
    announce_effect: FakeAnnounceEffect,
) -> None:
    host = RunHost(world)
    control = ControlPlane(system=world, store=journal, run_host=host)
    source = await _source_run(control, host, key="source-contract-mismatch")
    incompatible, impl = atomic("test/triage", (ISSUE,), (REVIEW,), review_impl)
    incompatible_version = world.register(incompatible, impl)
    before_runs = len(journal.run_records(limit=100))

    rejected = await control.runs_counterfactual(
        ACTOR,
        source_run_id=source.run_id,
        overrides={"test/triage": incompatible_version},
        idempotency_key="counterfactual-contract-mismatch",
    )
    assert isinstance(rejected, ControlRejected)
    assert rejected.faults[0].code is ControlCode.COUNTERFACTUAL_LOCK_MISMATCH
    assert len(journal.run_records(limit=100)) == before_runs
    assert len(announce_effect.simulations) == 0
    await host.shutdown()
