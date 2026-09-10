"""New awaiting gate consumer and a controllable fake, never a containment claim."""

from __future__ import annotations

import asyncio

from constructicon.core.address import GitSha
from constructicon.core.component import CapabilityRequirement, ComponentDef
from constructicon.core.control import PromotionCommandResult, RegistrationCommandResult
from constructicon.core.effect import CheckResult
from constructicon.core.gates import MergeEvaluation, MergeGate
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.workspace import (
    AcquiredCapability,
    LeaseClosure,
    LeaseReconciliation,
    acquisition_id_for,
    lease_id_for,
)
from tests.api.test_control_response_loss import LOCAL_ADMIN
from tests.conftest import atomic
from tests.gitworld import CANDIDATE, EVALUATION


async def evaluate_candidate(ctx, inputs):
    gate = ctx.capability("gates")
    assert isinstance(gate, MergeGate)
    evaluation = await gate.verify(GitSha(inputs["candidate"]["commit"]))
    return {"evaluation": evaluation.model_dump(mode="json")}


async def register_gate(control):
    definition, _ = atomic("test/async-gate", (CANDIDATE,), (EVALUATION,), evaluate_candidate)
    definition = ComponentDef.model_validate({
        **definition.model_dump(),
        "capability_requirements": (CapabilityRequirement(alias="gates", kind="gates.contained"),),
    })
    registered = await control.registry_register(
        LOCAL_ADMIN, definition=definition, idempotency_key="register-async-gate",
    )
    assert isinstance(registered, RegistrationCommandResult), registered
    promoted = await control.registry_promote_initial(
        LOCAL_ADMIN, component=definition.name, version=registered.version,
        idempotency_key="promote-async-gate",
    )
    assert isinstance(promoted, PromotionCommandResult), promoted
    return Graph(name="gate", inputs=(CANDIDATE,), outputs=(EVALUATION,), nodes=(
        GraphNode(id="check", body=Ref(component=definition.name, bind={"gates": "gate"})),
    ))


class ControlledGate:
    target_ref = "refs/heads/main"

    def __init__(self, context):
        self.context = context
        self.started, self.allowed = asyncio.Event(), asyncio.Event()
        self.closed = False

    async def verify(self, candidate):
        self.context.check_control()
        self.started.set()
        while not self.allowed.is_set():
            await asyncio.sleep(0.01)
            self.context.check_control()
        self.context.check_control()
        return MergeEvaluation(subject=None, attestation_id=None, checks=(CheckResult(
            name="already-integrated", status="passed", detail="fake: no merge needed", elapsed_s=0,
        ),))


class ControlledGateProvider:
    revision = "controlled-async-gate-v1"

    def __init__(self):
        self.handles = []
        self.dispositions = []

    async def acquire(self, context):
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        handle = ControlledGate(context)
        self.handles.append(handle)
        acquired = acquisition_id_for(logical, context.run_lease.epoch)
        return AcquiredCapability(
            resource=handle, lease_id=logical, acquisition_id=acquired, resource_ref=acquired,
        )

    async def close(self, acquired, disposition):
        acquired.resource.closed = True
        self.dispositions.append(disposition)
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def reconcile(self, context, stale):
        self.dispositions.extend(item.disposition for item in stale)
        return LeaseReconciliation(reaped=tuple(item.lease.resource_ref for item in stale))
