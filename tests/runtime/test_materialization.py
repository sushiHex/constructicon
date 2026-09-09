"""Post-record materialization, exercised through the walker and real journal.

InjectedCrash is a unit seam, not a claim of Linux process-death containment.
The fake ledger survives reconstructed providers; local handles do not confer
recovery authority.
"""

from __future__ import annotations

import asyncio

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.errors import ContractViolation
from constructicon.core.run import CheckpointConflict, OwnershipLost, RunStatus
from tests.api.test_executor_admission import INPUTS, executor_system
from tests.conftest import LEASE_TTL_S, InjectedCrash
from tests.executorworld import FakeExecutorProvider, register_component


async def test_materialization_observes_its_durable_row_before_resource_exposure(journal):
    provider = FakeExecutorProvider()
    system = executor_system(journal, provider)
    graph = await register_component(system, journal)
    observed = []

    async def check_record(handle):
        rows = journal.capability_leases(handle.context.run_lease.run_id)
        assert len(rows) == 1 and rows[0].resource_ref == handle.key
        assert rows[0].state == "active"
        assert not handle.ready and provider.ledger.operations == []
        observed.append(handle.key)

    provider.before_materialize = check_record
    result = await system._start_direct(graph, INPUTS, run_id=RunId("materialize-order"))
    assert result.status is RunStatus.SUCCEEDED
    assert observed == [provider.handles[0].key]


@pytest.mark.parametrize("failure", [CheckpointConflict, OwnershipLost])
async def test_recording_failure_keeps_close_inert_and_forbids_late_entry(
    journal,
    monkeypatch,
    failure,
):
    provider = FakeExecutorProvider()
    system = executor_system(journal, provider)
    graph = await register_component(system, journal)

    def refuse(*args, **kwargs):
        raise failure("record refused")

    monkeypatch.setattr(journal, "record_capability_lease", refuse)
    run_id = RunId("inert-record-refused")
    with pytest.raises(failure, match="record refused"):
        await system._start_direct(graph, INPUTS, run_id=run_id)
    assert journal.capability_leases(run_id) == []
    assert provider.executor.calls == [] and provider.ledger.operations == []
    handle = provider.handles[0]
    assert handle.closed and not handle.entered
    with pytest.raises(ContractViolation, match="locally closed"):
        await handle.materialize()
    assert provider.ledger.operations == []


@pytest.mark.parametrize("partial", [False, True])
async def test_materialization_failure_discards_the_enrolled_acquisition(journal, partial):
    provider = FakeExecutorProvider()
    system = executor_system(journal, provider)
    graph = await register_component(system, journal)

    async def fail(handle):
        if partial:
            provider.ledger.allocate(handle.key)
        raise RuntimeError("materialization failed")

    provider.before_materialize = fail
    run_id = RunId("materialization-failed")
    result = await system._start_direct(graph, INPUTS, run_id=run_id)
    assert result.status is RunStatus.FAILED
    handle = provider.handles[0]
    assert handle.entered and handle.closed
    assert provider.ledger.resources == set() and provider.ledger.closed == {handle.key}
    assert provider.executor.calls == []
    assert journal.checkpoint(run_id, handle.context.path) is None
    assert [(row.state, row.disposition) for row in journal.capability_leases(run_id)] == [
        ("closed", "discarded"),
    ]


async def test_cancellation_during_materialization_discards_without_invoking(journal):
    provider = FakeExecutorProvider()
    system = executor_system(journal, provider)
    graph = await register_component(system, journal)
    entered = asyncio.Event()

    async def pause(handle):
        entered.set()
        await asyncio.Event().wait()

    provider.before_materialize = pause
    run_id = RunId("materialization-cancelled")
    running = asyncio.create_task(system._start_direct(graph, INPUTS, run_id=run_id))
    await asyncio.wait_for(entered.wait(), timeout=5)
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    handle = provider.handles[0]
    assert handle.closed and provider.executor.calls == []
    assert provider.ledger.closed == {handle.key}
    assert [(row.state, row.disposition) for row in journal.capability_leases(run_id)] == [
        ("closed", "discarded"),
    ]


@pytest.mark.parametrize("cancelled", [False, True])
async def test_later_materialization_failure_closes_earlier_recorded_siblings(journal, cancelled):
    first = FakeExecutorProvider()
    second = FakeExecutorProvider(ledger=first.ledger)
    system = Constructicon(
        journal=journal,
        owner_id="siblings",
        capabilities={"first": first, "second": second},
        catalog={"first": first.descriptor("first"), "second": second.descriptor("second")},
    )
    graph = await register_component(system, journal, bindings={"executor": "first", "z": "second"})

    async def fail(handle):
        if cancelled:
            raise asyncio.CancelledError()
        raise RuntimeError("later acquisition failed")

    second.before_materialize = fail
    run_id = RunId("materialization-siblings")
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await system._start_direct(graph, INPUTS, run_id=run_id)
    else:
        assert (await system._start_direct(graph, INPUTS, run_id=run_id)).status is RunStatus.FAILED
    assert first.ledger.resources == set()
    assert first.ledger.closed == {first.handles[0].key, second.handles[0].key}
    assert first.executor.calls == second.executor.calls == []
    assert [(row.state, row.disposition) for row in journal.capability_leases(run_id)] == [
        ("closed", "discarded"),
        ("closed", "discarded"),
    ]


@pytest.mark.parametrize("seam", ["after_record", "during_materialization", "partial_allocation"])
async def test_recovery_fences_a_recorded_acquisition_even_if_it_never_started(
    journal,
    clock,
    monkeypatch,
    seam,
):
    first = FakeExecutorProvider()
    system = executor_system(journal, first)
    graph = await register_component(system, journal)
    record = journal.record_capability_lease

    def record_then_die(*args, **kwargs):
        record(*args, **kwargs)
        raise InjectedCrash("after record")

    async def die_during_materialization(handle):
        if seam == "partial_allocation":
            first.ledger.allocate(handle.key)
        raise InjectedCrash("during materialization")

    if seam == "after_record":
        monkeypatch.setattr(journal, "record_capability_lease", record_then_die)
    else:
        first.before_materialize = die_during_materialization
    run_id = RunId(f"recover-{seam}")
    with pytest.raises(InjectedCrash):
        await system._start_direct(graph, INPUTS, run_id=run_id)
    monkeypatch.setattr(journal, "record_capability_lease", record)
    old = first.handles[0]
    assert journal.capability_leases(run_id)[0].state == "active"
    assert old.entered is (seam != "after_record")
    assert (old.key in first.ledger.resources) is (seam == "partial_allocation")

    clock.advance(LEASE_TTL_S + 1)
    second = FakeExecutorProvider(ledger=first.ledger)
    recovered = executor_system(journal, second, owner="m8-successor")
    result = await recovered._resume_direct(run_id)
    assert result.status is RunStatus.SUCCEEDED
    assert second.reconciled == [old.key]
    assert second.handles[0].key != old.key
    assert second.ledger.resources == set()
    assert old.key in second.ledger.closed
    assert [(row.state, row.disposition) for row in journal.capability_leases(run_id)] == [
        ("closed", "discarded"),
        ("closed", "released"),
    ]
    assert first.executor.calls == [] and len(second.executor.calls) == 1
    # An old local handle cannot override the independently retained fence.
    first.before_materialize = None
    with pytest.raises(ContractViolation, match="externally closed"):
        await old.materialize()
    assert second.ledger.resources == set()


async def test_ownership_loss_during_materialization_leaves_reconciliation_to_successor(
    journal,
    clock,
):
    first = FakeExecutorProvider()
    system = executor_system(journal, first)
    graph = await register_component(system, journal)

    async def lose(handle):
        first.ledger.allocate(handle.key)
        raise OwnershipLost("successor owns cleanup")

    first.before_materialize = lose
    run_id = RunId("materialization-lost")
    with pytest.raises(OwnershipLost, match="successor owns cleanup"):
        await system._start_direct(graph, INPUTS, run_id=run_id)
    assert first.ledger.closed == set()
    assert first.ledger.resources == {first.handles[0].key}
    assert journal.capability_leases(run_id)[0].state == "active"
    clock.advance(LEASE_TTL_S + 1)
    second = FakeExecutorProvider(ledger=first.ledger)
    recovered = executor_system(journal, second, owner="m8-successor")
    assert (await recovered._resume_direct(run_id)).status is RunStatus.SUCCEEDED
    assert second.reconciled == [first.handles[0].key]
    assert second.ledger.resources == set()
