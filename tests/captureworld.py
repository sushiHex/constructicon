"""Awaiting component versions and a controllable async-workspace contract double.

The double is not a containment proof. Native tests use the same components
with the contained provider and actual processes instead.
"""

from __future__ import annotations

import asyncio

from constructicon.api.system import Constructicon
from constructicon.core.address import GitSha
from constructicon.core.component import CapabilityRequirement
from constructicon.core.control import PromotionCommandResult, RegistrationCommandResult
from constructicon.core.envelope import GitRef
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorSuccess, TaskSpec
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.workspace import (
    AcquiredCapability,
    AsyncWriteWorkspace,
    LeaseClosure,
    LeaseReconciliation,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.runtime.registry import CapabilityDescriptor
from tests.api.test_control_response_loss import LOCAL_ADMIN
from tests.conftest import atomic
from tests.gitworld import CANDIDATE, GOAL, WRITE_GRANTS


def capture_system(journal, provider, *, executor=None, owner="capture-owner", lease_ttl_s=30):
    capabilities = {"capture": provider}
    catalog = {
        "capture": CapabilityDescriptor(
            capability_id="capture",
            kind="workspace.contained",
            revision=provider.revision,
            leased=True,
            requires_posture=WRITE_GRANTS.posture,
        )
    }
    if executor is not None:
        capabilities["recorded"] = executor
        catalog["recorded"] = executor.descriptor("recorded")
    return Constructicon(
        journal=journal,
        root_grants=WRITE_GRANTS,
        capabilities=capabilities,
        catalog=catalog,
        owner_id=owner,
        lease_ttl_s=lease_ttl_s,
        heartbeat_interval_s=min(1, lease_ttl_s / 5),
    )


async def capture_candidate(ctx, inputs):
    workspace = ctx.capability("workspace")
    assert isinstance(workspace, AsyncWriteWorkspace)
    await workspace.commit_all(inputs["goal"]["message"])
    return {"candidate": workspace.git_ref().model_dump(mode="json")}


async def propose_and_capture(ctx, inputs):
    workspace = ctx.capability("workspace")
    executor = ctx.capability("executor")
    result = await executor.execute(
        TaskSpec(instruction=inputs["goal"]["message"]),
        workspace=workspace,
        grants=ctx.grants,
    )
    if not isinstance(result, ExecutorSuccess):
        raise ContractViolation("recorded proposal did not succeed")
    await workspace.commit_all(inputs["goal"]["message"])
    return {"candidate": workspace.git_ref().model_dump(mode="json")}


async def register_capture(control, *, executor=False):
    implementation = propose_and_capture if executor else capture_candidate
    name = "test/contained-proposal" if executor else "test/async-capture"
    definition, _ = atomic(name, (GOAL,), (CANDIDATE,), implementation)
    requirements = [CapabilityRequirement(alias="workspace", kind="workspace.contained")]
    bindings = {"workspace": "capture"}
    if executor:
        requirements.append(CapabilityRequirement(alias="executor", kind="executor"))
        bindings["executor"] = "recorded"
    definition = definition.model_copy(update={"capability_requirements": tuple(requirements)})
    registered = await control.registry_register(
        LOCAL_ADMIN,
        definition=definition,
        idempotency_key="register-" + name,
    )
    assert isinstance(registered, RegistrationCommandResult), registered
    promoted = await control.registry_promote_initial(
        LOCAL_ADMIN,
        component=definition.name,
        version=registered.version,
        idempotency_key="promote-" + name,
    )
    assert isinstance(promoted, PromotionCommandResult), promoted
    return Graph(
        name="capture",
        inputs=(GOAL,),
        outputs=(CANDIDATE,),
        nodes=(GraphNode(id="writer", body=Ref(component=name, bind=bindings)),),
    )


class ControlledAsyncWorkspace:
    path = "<fake-workspace>"

    def __init__(self, context):
        self.context = context
        self.reference = GitRef(repository="fake-authority", commit=GitSha("a" * 40))
        self.reset_started, self.reset_allowed = asyncio.Event(), asyncio.Event()
        self.commit_started, self.commit_allowed = asyncio.Event(), asyncio.Event()
        self.ready = False
        self.closed = False

    async def materialize(self):
        self.ready = True

    def git_ref(self):
        return self.reference

    def check(self):
        if self.closed or not self.ready or self.context.check_control is None:
            raise ContractViolation("fake async workspace is not an open invocation")
        self.context.check_control()

    async def reset_to(self, ref):
        self.check()
        self.reset_started.set()
        await self.reset_allowed.wait()
        self.check()
        self.reference = ref

    async def commit_all(self, message):
        self.check()
        self.commit_started.set()
        await self.commit_allowed.wait()
        self.check()
        self.reference = self.reference.model_copy(update={"commit": GitSha("b" * 40)})
        return self.reference.commit


class ControlledWorkspaceProvider:
    def __init__(self):
        self.handles = []
        self.dispositions = []

    async def acquire(self, context):
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        acquired = acquisition_id_for(logical, context.run_lease.epoch)
        handle = ControlledAsyncWorkspace(context)
        self.handles.append(handle)
        return AcquiredCapability(
            resource=handle,
            lease_id=logical,
            acquisition_id=acquired,
            resource_ref=acquired,
            materialize=handle.materialize,
        )

    async def close(self, acquired, disposition):
        acquired.resource.closed = True
        self.dispositions.append(disposition)
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def reconcile(self, context, stale):
        self.dispositions.extend(item.disposition for item in stale)
        return LeaseReconciliation(reaped=tuple(item.lease.resource_ref for item in stale))
