"""A mutation's scope is enough to complete it (M7 PR C).

Every mutating response carries a `DetailRef` the system mints onto it. That
pointer is not a read the caller asked for: it is part of the answer an actor
already earned by holding the mutation's scope. Locking it would make
`runs_approve` require `constructicon:read` in fact while requiring
`constructicon:approve` on paper — and worse, fail *after* committing.

The lock therefore sits at the doors a caller reaches, and these are the roles
that prove it: approve, operate, and promote, each holding nothing else.
"""

from __future__ import annotations

from typing import Any, cast

from constructicon.api.control import ControlPlane
from constructicon.api.detail import DetailAddress
from constructicon.api.run_host import RunHost
from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.control import (
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    PROMOTE_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    ControlCode,
    ControlRejected,
    PromotionCommandResult,
    RunSubmission,
)
from constructicon.core.effect import ComponentProofSubject
from constructicon.core.identity import Digest
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_v1_replay_upgrade import _candidate
from tests.conftest import pipeline_graph

SUBJECT = ComponentProofSubject(
    component="test/triage",
    version=Digest("sha256:" + "f" * 64),
    baseline_version=None,
)


def _only(actor_id: str, scope: str) -> AuthenticatedActor:
    """One scope and nothing else — no read, no admin."""

    return AuthenticatedActor(
        actor_id=actor_id,
        auth_method="static",
        scopes=frozenset({scope}),
    )


APPROVE_ONLY = _only("static:approve-only", APPROVE_SCOPE)
OPERATE_ONLY = _only("static:operate-only", OPERATE_SCOPE)
PROMOTE_ONLY = _only("static:promote-only", PROMOTE_SCOPE)


class _PassiveHost:
    def __init__(self) -> None:
        self.launches: list[RunId] = []

    def _configure_committed_resumes(self, store: Any, decoder: Any) -> None:
        return None

    async def startup(self) -> None:
        return None

    async def abort_startup(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    def launch(self, run_id: RunId, **kwargs: Any) -> str:
        self.launches.append(run_id)
        return "queued"


def _control(world: Constructicon, journal: SqliteJournal) -> ControlPlane:
    return ControlPlane(
        system=world,
        store=journal,
        run_host=cast(RunHost, _PassiveHost()),
    )


async def test_an_operate_only_actor_can_start_a_run(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """`runs_start` requires operate. It must not require read to answer."""

    control = _control(world, journal)
    submitted = await control.runs_start(
        OPERATE_ONLY,
        proposal=pipeline_graph(),
        inputs={"issue": {"title": "narrow"}},
        idempotency_key="operate-only",
    )
    assert isinstance(submitted, RunSubmission)
    assert submitted.run_status is RunStatus.PENDING


async def test_an_approve_only_actor_can_record_a_decision(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    """The pointer onto its own response is part of the answer, not a read."""

    control = _control(world, journal)
    inputs = {"issue": {"title": "approve-only"}}
    run_id = RunId("run-approve-only")
    world._prepare_run(world.validate(pipeline_graph(), inputs), run_id=run_id, inputs=inputs)

    decided = await control.runs_approve(
        APPROVE_ONLY,
        run_id=run_id,
        subject=SUBJECT,
        decision="approved",
        reason=None,
        idempotency_key="approve-only",
    )
    assert isinstance(decided, ApprovalCommandResult)
    assert decided.detail.uri == DetailAddress.approval(decided.approval_id)

    # ...and it still may not read anything the read scope owns.
    refused = control.resource_read(APPROVE_ONLY, DetailAddress.manifest(run_id))
    assert isinstance(refused, ControlRejected)
    assert refused.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE

    # Not even the detail its own response just handed it: reading is a read.
    read_back = control.details_read(APPROVE_ONLY, decided.detail)
    assert isinstance(read_back, ControlRejected)
    assert read_back.faults[0].code is ControlCode.AUTH_REQUIRED_SCOPE


async def test_a_promote_only_actor_can_promote(
    world: Constructicon,
    journal: SqliteJournal,
) -> None:
    control = _control(world, journal)
    component = "control/narrow-promote"
    candidate, attestation_id = _candidate(world, component)

    promoted = await control.registry_promote(
        PROMOTE_ONLY,
        component=component,
        version=candidate,
        attestation_id=attestation_id,
        idempotency_key="promote-only",
    )
    assert isinstance(promoted, PromotionCommandResult)
    assert promoted.detail.uri == DetailAddress.component(component, candidate)
