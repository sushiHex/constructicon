"""The scripted READ provider crosses the ordinary durable task/checkpoint seam."""

import asyncio

import pytest

from constructicon.api.control import ControlPlane
from constructicon.api.run_host import RunHost
from constructicon.core.address import GitSha
from constructicon.core.component import CapabilityRequirement
from constructicon.core.control import (
    PromotionCommandResult,
    RegistrationCommandResult,
    RunSubmission,
)
from constructicon.core.graph import Connection, Graph, GraphNode, Ref
from constructicon.core.run import RunStatus
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.pi_provider import PiReadHandle
from tests.api.test_control_response_loss import LOCAL_ADMIN, RUN_ACTOR
from tests.conftest import ANNOUNCED, SUMMARY, InjectedCrash, atomic, await_attempt_terminal
from tests.gateworld import ControlledGateProvider
from tests.pi_leaseworld import assemble, register_pi
from tests.substrate.test_pi_provider import world as world


async def test_real_control_host_checkpoints_scripted_workspace_read_and_releases_leases(world):
    system, journal, provider, workspace, launcher, _facts = world
    assert all(item.available for item in system.describe().capabilities)
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        graph = await register_pi(control)
        submitted = await control.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"issue": {"title": "scripted READ"}},
            idempotency_key="pi-read-start",
        )
        assert isinstance(submitted, RunSubmission), submitted
        terminal = await await_attempt_terminal(journal, submitted.run_id, baseline_event_seq=0,
                                                 timeout_s=60)
        assert terminal.kind == "RunSucceeded", journal.events(submitted.run_id)
    finally:
        await control.shutdown()
    rows = journal.capability_leases(submitted.run_id)
    assert {row.binding_id for row in rows} == {"executor", "workspace"}
    assert all(row.state == "closed" and row.disposition == "released" for row in rows)
    checkpoint = journal.checkpoint(submitted.run_id, rows[0].path)
    assert checkpoint is not None
    assert checkpoint.outputs["summary"].payload == "Read: leased workspace bytes"
    assert launcher.calls == 1 and launcher.joined and launcher.eof
    assert workspace.authority.read_ref("refs/heads/main") is not None
    assert not list(workspace.root.glob("payloads/*"))
    assert provider.unavailable_reasons == ("scripted READ provider acquisition is spent",)


async def wait_summary(ctx, inputs):
    await ctx.capability("gates").verify(GitSha("a" * 40))
    return {"receipt": inputs["summary"]}


async def restart_graph(control):
    read = await register_pi(control)
    receipt = SUMMARY.model_copy(update={"name": "receipt"})
    definition, _ = atomic("test/pi-read-wait", (SUMMARY,), (receipt,), wait_summary)
    definition = definition.model_copy(update={"capability_requirements": (
        CapabilityRequirement(alias="gates", kind="gates.contained"),
    )})
    registered = await control.registry_register(
        LOCAL_ADMIN, definition=definition, idempotency_key="pi-wait-register",
    )
    assert isinstance(registered, RegistrationCommandResult), registered
    promoted = await control.registry_promote_initial(
        LOCAL_ADMIN, component=definition.name, version=registered.version,
        idempotency_key="pi-wait-promote",
    )
    assert isinstance(promoted, PromotionCommandResult), promoted
    return Graph(name="pi-read-restart", inputs=read.inputs, outputs=(receipt,), nodes=(
        *read.nodes, GraphNode(id="wait", body=Ref(component=definition.name,
                                                  bind={"gates": "gate"})),
    ), connections=(Connection(src="worker", dst="wait"),))


async def until(predicate):
    async with asyncio.timeout(30):
        while not predicate():
            await asyncio.sleep(.01)


@pytest.mark.parametrize("phase", ["before_checkpoint", "after_checkpoint"])
async def test_fresh_control_reconstruction_replays_only_uncheckpointed_read(
    world, tmp_path, monkeypatch, phase,
):
    """Real host abandonment, not literal controller death or a physical claim."""
    launcher = world[4]
    gate_a = ControlledGateProvider()
    system_a, journal_a, provider_a, workspace_a = await assemble(
        tmp_path, launcher, owner="pi-first", gate=gate_a,
    )
    paused = asyncio.Event()
    original_execute = PiReadHandle.execute
    pause_once = True

    async def execute_at_boundary(handle, *args, **kwargs):
        nonlocal pause_once
        outcome = await original_execute(handle, *args, **kwargs)
        assert outcome.status == "success" and outcome.output == "Read: leased workspace bytes"
        if phase == "before_checkpoint" and pause_once:
            pause_once = False
            paused.set()
            await asyncio.Event().wait()  # Host shutdown owns and joins cancellation.
        return outcome

    monkeypatch.setattr(PiReadHandle, "execute", execute_at_boundary)
    first = ControlPlane(system=system_a, store=journal_a)
    second = None
    try:
        await first.startup()
        graph = await restart_graph(first)
        submitted = await first.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"issue": {"title": "scripted restart"}},
            idempotency_key="pi-restart",
        )
        assert isinstance(submitted, RunSubmission), submitted
        await until(paused.is_set if phase == "before_checkpoint" else
                    lambda: bool(gate_a.handles) and gate_a.handles[0].started.is_set())
        executor_row = next(row for row in journal_a.capability_leases(submitted.run_id)
                            if row.binding_id == "executor")
        assert (journal_a.checkpoint(submitted.run_id, executor_row.path) is not None) == (
            phase == "after_checkpoint"
        )
        assert launcher.calls == 1 and launcher.joined and launcher.eof
        await first.shutdown()
        assert journal_a.run_state(submitted.run_id).status is RunStatus.RUNNING
        assert not journal_a.cancel_requested(submitted.run_id)
        gate_b = ControlledGateProvider()
        system_b, journal_b, _provider_b, workspace_b = await assemble(
            tmp_path, launcher, owner="pi-second", gate=gate_b,
        )
        second = ControlPlane(system=system_b, store=journal_b)
        await second.startup()
        await until(lambda: (bool(gate_b.handles) and gate_b.handles[0].started.is_set())
                    or journal_b.run_state(submitted.run_id).status is RunStatus.FAILED)
        assert journal_b.run_state(submitted.run_id).status is RunStatus.RUNNING, (
            journal_b.events(submitted.run_id)
        )
        gate_b.handles[0].allowed.set()
        await until(lambda: journal_b.run_state(submitted.run_id).status in {
            RunStatus.SUCCEEDED, RunStatus.FAILED,
        })
        assert journal_b.run_state(submitted.run_id).status is RunStatus.SUCCEEDED
        assert launcher.calls == (2 if phase == "before_checkpoint" else 1)
        checkpoint = journal_b.checkpoint(submitted.run_id, executor_row.path)
        assert checkpoint.outputs["summary"].payload == "Read: leased workspace bytes"
        assert all(row.state == "closed" for row in
                   journal_b.capability_leases(submitted.run_id))
        assert not list(workspace_a.root.glob("payloads/*"))
        assert not list(workspace_b.root.glob("payloads/*"))
        assert provider_a.unavailable_reasons
    finally:
        if second is not None:
            await second.shutdown()
        await first.shutdown()


async def test_real_walker_reconciles_recorded_before_materialization_crash(
    world, tmp_path, monkeypatch,
):
    from constructicon.core.workspace import acquisition_id_for
    from constructicon.substrate.git.acquisition import AcquisitionPaths

    system_a, journal_a, provider_a, _workspace_a, launcher, _facts = world
    recorded = asyncio.Event()
    original_record = journal_a.record_capability_lease

    def record_then_crash(lease, row):
        original_record(lease, row)
        if row.binding_id == "executor":
            recorded.set()
            raise InjectedCrash("after real executor acquisition record, before materialization")

    monkeypatch.setattr(journal_a, "record_capability_lease", record_then_crash)
    crashes = []
    first = ControlPlane(system=system_a, store=journal_a, run_host=RunHost(
        system_a, journal=journal_a, on_failure=lambda run_id, error: crashes.append(error),
    ))
    second = None
    try:
        await first.startup()
        graph = await register_pi(first)
        submitted = await first.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"issue": {"title": "record then crash"}},
            idempotency_key="pi-recorded-crash",
        )
        assert isinstance(submitted, RunSubmission), submitted
        await until(recorded.is_set)
        await until(lambda: bool(crashes))
        assert isinstance(crashes[0], InjectedCrash)
        await first.shutdown()
        rows = journal_a.capability_leases(submitted.run_id)
        assert len(rows) == 1 and rows[0].binding_id == "executor"
        assert rows[0].state == "active" and rows[0].resource_ref
        assert not provider_a.acquisition_root.exists() and not launcher.calls
        assert journal_a.run_state(submitted.run_id).status is RunStatus.RUNNING
        system_b, journal_b, provider_b, _workspace_b = await assemble(
            tmp_path, launcher, owner="pi-crash-successor",
        )
        failures = []
        second = ControlPlane(system=system_b, store=journal_b, run_host=RunHost(
            system_b, journal=journal_b,
            on_failure=lambda run_id, error: failures.append(error),
        ))
        await second.startup()
        await until(lambda: failures or journal_b.run_state(submitted.run_id).status in {
            RunStatus.SUCCEEDED, RunStatus.FAILED,
        })
        assert not failures, failures
        assert journal_b.run_state(submitted.run_id).status is RunStatus.SUCCEEDED, (
            journal_b.events(submitted.run_id)
        )
        assert launcher.calls == 1 and launcher.joined and launcher.eof
        old = next(row for row in journal_b.capability_leases(submitted.run_id)
                   if row.acquisition_epoch == rows[0].acquisition_epoch)
        assert old.state == "closed" and old.disposition == "discarded"
        assert provider_b.closure.is_closed(AcquisitionPaths(
            provider_b.acquisition_root, acquisition_id_for(old.lease_id, old.acquisition_epoch),
        ))
    finally:
        if second is not None:
            await second.shutdown()
        await first.shutdown()


async def announce_read_summary(ctx, inputs):
    receipt = await ctx.effect("announce", {"summary": inputs["summary"]})
    return {"announced": {"status": receipt.status}}


async def test_scripted_read_counterfactual_simulates_effects_and_discards_both_leases(
    world, tmp_path, monkeypatch,
):
    """Fresh single-use fixture assemblies; model computation is not called free."""
    effect = FakeAnnounceEffect()
    calls = []
    for name in ("execute", "reconcile", "simulate"):
        original = getattr(effect, name)

        async def observed(request, *, name=name, original=original):
            calls.append((name, request.run_id))
            return await original(request)

        monkeypatch.setattr(effect, name, observed)
    launcher = world[4]
    first_system, journal, _provider, workspace = await assemble(
        tmp_path, launcher, owner="pi-source", effects={"announce": effect},
    )
    before = workspace.authority.read_ref("refs/heads/main")
    first = ControlPlane(system=first_system, store=journal)
    second = None
    try:
        await first.startup()
        read = await register_pi(first)
        definition, _ = atomic("test/pi-read-announce", (SUMMARY,), (ANNOUNCED,),
                               announce_read_summary)
        registered = await first.registry_register(
            LOCAL_ADMIN, definition=definition, idempotency_key="pi-announce-register",
        )
        assert isinstance(registered, RegistrationCommandResult), registered
        promoted = await first.registry_promote_initial(
            LOCAL_ADMIN, component=definition.name, version=registered.version,
            idempotency_key="pi-announce-promote",
        )
        assert isinstance(promoted, PromotionCommandResult), promoted
        graph = Graph(name="pi-read-counterfactual", inputs=read.inputs, outputs=(ANNOUNCED,),
                      nodes=(*read.nodes, GraphNode(id="announce", body=Ref(
                          component=definition.name,
                      ))), connections=(Connection(src="worker", dst="announce"),))
        source = await first.runs_start(
            RUN_ACTOR, proposal=graph, inputs={"issue": {"title": "read and announce"}},
            idempotency_key="pi-counterfactual-source",
        )
        assert isinstance(source, RunSubmission), source
        await until(lambda: journal.run_state(source.run_id).status in {
            RunStatus.SUCCEEDED, RunStatus.FAILED,
        })
        assert journal.run_state(source.run_id).status is RunStatus.SUCCEEDED, (
            journal.events(source.run_id)
        )
        assert any(event.kind == "RunSucceeded" for event in journal.events(source.run_id))
        source_rows = journal.capability_leases(source.run_id)
        assert {row.binding_id for row in source_rows} == {"executor", "workspace"}
        assert all(row.state == "closed" and row.disposition == "released" for row in source_rows)
        assert calls == [("reconcile", source.run_id), ("execute", source.run_id)]
        assert len(effect.executions) == 1 and not effect.simulations
        assert launcher.calls == 1 and launcher.joined and launcher.eof
        await first.shutdown()

        next_system, next_journal, next_provider, next_workspace = await assemble(
            tmp_path, launcher, owner="pi-counterfactual", effects={"announce": effect},
        )
        second = ControlPlane(system=next_system, store=next_journal)
        await second.startup()
        replay = await second.runs_counterfactual(
            RUN_ACTOR, source_run_id=source.run_id, overrides={},
            idempotency_key="pi-counterfactual-replay",
        )
        assert isinstance(replay, RunSubmission), replay
        await until(lambda: next_journal.run_state(replay.run_id).status in {
            RunStatus.SUCCEEDED, RunStatus.FAILED,
        })
        assert next_journal.run_state(replay.run_id).status is RunStatus.SUCCEEDED, (
            next_journal.events(replay.run_id)
        )
        assert any(event.kind == "EffectSimulated" for event in next_journal.events(replay.run_id))
        assert calls == [("reconcile", source.run_id), ("execute", source.run_id),
                         ("simulate", replay.run_id)]
        assert len(effect.executions) == len(effect.simulations) == 1
        live_request, simulated_request = effect.executions[0], effect.simulations[0]
        assert simulated_request.mode == "simulated"
        assert simulated_request.idempotency_key != live_request.idempotency_key
        simulated = next_journal.receipt_for(simulated_request.idempotency_key)
        committed = next_journal.receipt_for(live_request.idempotency_key)
        assert simulated is not None and simulated.status == "simulated"
        assert committed is not None and committed.status == "committed"
        origin = next_journal.run_origin(replay.run_id)
        assert origin is not None and origin.source_run_id == source.run_id
        assert origin.effects == "simulated" and origin.capabilities == "discard"
        replay_rows = next_journal.capability_leases(replay.run_id)
        assert {row.binding_id for row in replay_rows} == {"executor", "workspace"}
        assert all(row.state == "closed" and row.disposition == "discarded" for row in replay_rows)
        assert {(row.lease_id, row.acquisition_epoch) for row in replay_rows}.isdisjoint(
            (row.lease_id, row.acquisition_epoch) for row in source_rows
        )
        assert launcher.calls == 2 and launcher.joined and launcher.eof
        assert not list(next_workspace.root.glob("payloads/*"))
        assert not list(next_provider.acquisition_root.glob("payloads/*"))
        assert next_workspace.authority.read_ref("refs/heads/main") == before
        assert workspace.authority.read_ref("refs/heads/main") == before
        assert all(row.state == "closed" and row.disposition == "released"
                   for row in next_journal.capability_leases(source.run_id))
    finally:
        if second is not None:
            await second.shutdown()
        await first.shutdown()
