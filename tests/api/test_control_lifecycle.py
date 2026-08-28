"""ControlPlane owns one race-safe lifecycle around command admission."""

from __future__ import annotations

import asyncio
from typing import Any, cast

import pytest

from constructicon.api.control import ControlPlane, ControlPlaneClosed
from constructicon.api.run_host import RunHost
from constructicon.core.address import RunId
from constructicon.core.control import (
    OPERATE_SCOPE,
    READ_SCOPE,
    AuthenticatedActor,
    ControlRejected,
)
from constructicon.core.identity import Digest
from constructicon.substrate.journal.sqlite import SqliteJournal

OPERATE_ACTOR = AuthenticatedActor(
    actor_id="static:lifecycle-operator",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
)
READ_ACTOR = AuthenticatedActor(
    actor_id="static:lifecycle-reader",
    auth_method="static",
    scopes=frozenset({READ_SCOPE}),
)


class HostProbe:
    def __init__(self) -> None:
        self.startup_calls = 0
        self.abort_calls = 0
        self.shutdown_calls = 0
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.failures: list[BaseException] = []

    def _configure_committed_resumes(self, store: Any, decoder: Any) -> None:
        self.store = store
        self.decoder = decoder

    async def startup(self) -> None:
        self.startup_calls += 1
        self.entered.set()
        await self.release.wait()
        if self.failures:
            raise self.failures.pop(0)

    async def abort_startup(self) -> None:
        self.abort_calls += 1

    async def shutdown(self) -> None:
        self.shutdown_calls += 1


def _control(world: Any, journal: SqliteJournal, host: HostProbe) -> ControlPlane:
    return ControlPlane(
        system=world,
        store=journal,
        run_host=cast(RunHost, host),
    )


async def test_concurrent_startup_is_shared_and_waiter_cancellation_is_local(
    world: Any,
    journal: SqliteJournal,
) -> None:
    host = HostProbe()
    control = _control(world, journal, host)
    cancelled = asyncio.create_task(control.startup())
    survivor = asyncio.create_task(control.startup())
    await host.entered.wait()
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    host.release.set()
    await survivor
    await control.startup()
    assert host.startup_calls == 1
    await asyncio.gather(control.shutdown(), control.shutdown())
    assert host.shutdown_calls == 1


async def test_startup_failure_aborts_and_same_plane_can_retry(
    world: Any,
    journal: SqliteJournal,
) -> None:
    host = HostProbe()
    host.failures.append(RuntimeError("initial scan failed"))
    host.release.set()
    control = _control(world, journal, host)
    with pytest.raises(RuntimeError, match="initial scan failed"):
        await control.startup()
    assert host.abort_calls == 1
    await control.startup()
    assert host.startup_calls == 2
    await control.shutdown()


async def test_shutdown_wins_over_mutation_waiting_on_startup_without_claim(
    world: Any,
    journal: SqliteJournal,
) -> None:
    host = HostProbe()
    control = _control(world, journal, host)
    mutation = asyncio.create_task(
        control.runs_cancel(
            OPERATE_ACTOR,
            run_id=RunId("run-never-claimed"),
            idempotency_key="waiting-on-startup",
        )
    )
    await host.entered.wait()
    closing = asyncio.create_task(control.shutdown())
    host.release.set()
    with pytest.raises(ControlPlaneClosed):
        await mutation
    await closing
    assert journal.latest_command_key(operation="runs_cancel") is None


async def test_authorization_precedes_implicit_startup_and_claim(
    world: Any,
    journal: SqliteJournal,
) -> None:
    host = HostProbe()
    control = _control(world, journal, host)
    rejected = await control.runs_cancel(
        READ_ACTOR,
        run_id=RunId("run-not-authorized"),
        idempotency_key="not-authorized",
    )
    assert isinstance(rejected, ControlRejected)
    assert host.startup_calls == 0
    assert journal.latest_command_key(operation="runs_cancel") is None
    await control.shutdown()


async def test_stopped_state_precedes_authorization_but_reads_remain_available(
    world: Any,
    journal: SqliteJournal,
) -> None:
    host = HostProbe()
    host.release.set()
    control = _control(world, journal, host)
    await control.shutdown()
    with pytest.raises(ControlPlaneClosed):
        await control.runs_cancel(
            READ_ACTOR,
            run_id=RunId("run-after-close"),
            idempotency_key="after-close",
        )
    described = control.system_describe(READ_ACTOR)
    assert not isinstance(described, ControlRejected)


@pytest.mark.parametrize(
    ("operation", "arguments"),
    (
        (
            "runs_start",
            {"proposal": {}, "inputs": {}, "idempotency_key": "denied-start"},
        ),
        (
            "runs_cancel",
            {"run_id": RunId("run-denied"), "idempotency_key": "denied-cancel"},
        ),
        (
            "runs_resume",
            {"run_id": RunId("run-denied"), "idempotency_key": "denied-resume"},
        ),
        (
            "runs_reproduce",
            {"source_run_id": RunId("run-denied"), "idempotency_key": "denied-reproduce"},
        ),
        (
            "runs_counterfactual",
            {
                "source_run_id": RunId("run-denied"),
                "overrides": {},
                "idempotency_key": "denied-counterfactual",
            },
        ),
        (
            "runs_approve",
            {
                "run_id": RunId("run-denied"),
                "subject": cast(Any, None),
                "decision": "approved",
                "reason": None,
                "idempotency_key": "denied-approve",
            },
        ),
        (
            "registry_register",
            {"definition": cast(Any, None), "idempotency_key": "denied-register"},
        ),
        (
            "registry_promote_initial",
            {
                "component": "denied/component",
                "version": Digest("sha256:" + "0" * 64),
                "idempotency_key": "denied-initial",
            },
        ),
        (
            "registry_promote",
            {
                "component": "denied/component",
                "version": Digest("sha256:" + "0" * 64),
                "attestation_id": "att-denied",
                "idempotency_key": "denied-promote",
            },
        ),
        (
            "registry_rollback",
            {
                "component": "denied/component",
                "expected_stable": Digest("sha256:" + "0" * 64),
                "idempotency_key": "denied-rollback",
            },
        ),
    ),
)
async def test_every_mutation_authorizes_before_startup_or_claim(
    operation: str,
    arguments: dict[str, Any],
    world: Any,
    journal: SqliteJournal,
) -> None:
    host = HostProbe()
    control = _control(world, journal, host)
    result = await getattr(control, operation)(READ_ACTOR, **arguments)
    assert isinstance(result, ControlRejected)
    assert result.faults[0].code.value.startswith("control.auth.")
    assert host.startup_calls == 0
    assert journal.latest_command_key(operation=operation) is None
    await control.shutdown()
