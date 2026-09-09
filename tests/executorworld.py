"""Genuine M8 task/lease doubles. No OS or provider-route proof is simulated.

The retained allocation ledger is shared across reconstructed providers;
handles themselves are process-local. This exercises the post-record law
without claiming a real subprocess, filesystem fence, or gateway exists.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorGrantPolicy,
    ExecutorLaunchIdentity,
    ExecutorOutcome,
    ExecutorProfile,
    TaskSpec,
)
from constructicon.core.grants import EffectiveGrants
from constructicon.core.identity import canonical_json, digest
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
    WorkspaceView,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.executors.fake import FakeExecutor


def policy() -> ExecutorGrantPolicy:
    return ExecutorGrantPolicy(
        tool_sets=((), ("read",), ("read", "search")),
        network_modes=("none",),
        network_access="none",
        environment_names=("SAFE_TEST",),
        workspace_required=False,
    )


def launch_identity(profile: ExecutorProfile) -> ExecutorLaunchIdentity:
    # These label a genuine fake, not installed Linux artifacts or evidence.
    return ExecutorLaunchIdentity(
        **{
            field: digest("m8-fake-content", 1, field)
            for field in (
                "executable_digest",
                "runtime_digest",
                "adapter_revision",
                "decoder_revision",
                "isolation_revision",
                "configuration_digest",
                "limits_digest",
            )
        },
        profile=profile,
        provider_route=None,
    )


@dataclass
class AllocationLedger:
    resources: set[str] = field(default_factory=set)
    closed: set[str] = field(default_factory=set)
    operations: list[tuple[str, str]] = field(default_factory=list)

    def allocate(self, key: str) -> None:
        if key in self.closed:
            raise ContractViolation("an externally closed acquisition cannot allocate")
        self.resources.add(key)
        self.operations.append(("allocate", key))

    def close(self, key: str) -> bool:
        present = key in self.resources
        self.closed.add(key)
        self.resources.discard(key)
        self.operations.append(("close", key))
        return present


class FakeExecutorHandle:
    def __init__(self, provider: FakeExecutorProvider, context: LeaseContext, key: str) -> None:
        self.provider = provider
        self.context = context
        self.key = key
        self.entered = False
        self.ready = False
        self.closed = False

    @property
    def profile(self) -> ExecutorProfile:
        return self.provider.executor.profile

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        return self.profile.grant_faults(grants)

    async def materialize(self) -> None:
        if self.closed:
            raise ContractViolation("a locally closed handle cannot materialize")
        self.entered = True
        if self.provider.before_materialize is not None:
            await self.provider.before_materialize(self)
        self.provider.ledger.allocate(self.key)
        self.ready = True

    async def execute(
        self, task: TaskSpec, *, workspace: WorkspaceView | None, grants: EffectiveGrants
    ) -> ExecutorOutcome:
        if not self.ready or self.closed or self.key in self.provider.ledger.closed:
            raise ContractViolation("executor handle is not open and materialized")
        if canonical_json(grants) != canonical_json(self.context.binding.effective_grants):
            raise ContractViolation("executor call differs from its sealed grants")
        return await self.provider.executor.execute(task, workspace=workspace, grants=grants)


class FakeExecutorProvider:
    def __init__(
        self,
        *,
        ledger: AllocationLedger | None = None,
        unavailable_reasons: tuple[str, ...] = (),
    ) -> None:
        self.executor = FakeExecutor({"test": {"text": "materialized"}}, grant_policy=policy())
        self._identity = launch_identity(self.executor.profile)
        self._unavailable_reasons = unavailable_reasons
        self.ledger = ledger if ledger is not None else AllocationLedger()
        self.handles: list[FakeExecutorHandle] = []
        self.before_materialize: Callable[[FakeExecutorHandle], Awaitable[None]] | None = None
        self.reconciled: list[str] = []

    @property
    def identity(self) -> ExecutorLaunchIdentity:
        return self._identity

    @property
    def unavailable_reasons(self) -> tuple[str, ...]:
        return self._unavailable_reasons

    def descriptor(self, capability_id: str = "complete-fake") -> CapabilityDescriptor:
        return CapabilityDescriptor(
            capability_id=capability_id,
            kind="executor",
            revision=self.identity.revision,
            executor_profile=self.identity.profile,
            leased=True,
        )

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        if self.unavailable_reasons:
            raise ContractViolation("an unavailable provider cannot acquire")
        lease_id = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        key = acquisition_id_for(lease_id, context.run_lease.epoch)
        handle = FakeExecutorHandle(self, context, key)
        self.handles.append(handle)
        return AcquiredCapability(
            resource=handle,
            lease_id=lease_id,
            acquisition_id=key,
            resource_ref=key,
            materialize=handle.materialize,
        )

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition
    ) -> LeaseClosure:
        handle = acquisition.resource
        assert isinstance(handle, FakeExecutorHandle)
        handle.closed = True
        if handle.entered:
            self.ledger.close(acquisition.resource_ref)
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...]
    ) -> LeaseReconciliation:
        reaped: list[str] = []
        for item in stale:
            key = item.lease.resource_ref
            assert key is not None
            if self.ledger.close(key):
                reaped.append(key)
            self.reconciled.append(key)
        return LeaseReconciliation(reaped=tuple(reaped))


async def execute_task(ctx: NodeContext, inputs: dict[str, Any]) -> dict[str, Any]:
    executor = ctx.capability("executor")
    assert isinstance(executor, FakeExecutorHandle)
    result = await executor.execute(TaskSpec(instruction="test"), workspace=None, grants=ctx.grants)
    assert result.status == "success"
    return {"summary": result.output}


async def register_component(
    system: Any, journal: Any, *, bindings: dict[str, str] | None = None
) -> Any:
    """Bootstrap through the real command law without launching recovery work."""
    from constructicon.core.component import CapabilityRequirement
    from constructicon.core.control import PromotionCommandResult, RegistrationCommandResult
    from constructicon.core.graph import Graph, GraphNode, Ref
    from tests.api.test_control_response_loss import LOCAL_ADMIN, _fresh_control, _PassiveHost
    from tests.conftest import ISSUE, SUMMARY, atomic

    bindings = {"executor": "complete-fake"} if bindings is None else bindings
    definition, _ = atomic("test/m8-executor", (ISSUE,), (SUMMARY,), execute_task)
    definition = definition.model_copy(
        update={
            "capability_requirements": tuple(
                CapabilityRequirement(alias=alias, kind="executor") for alias in sorted(bindings)
            )
        }
    )
    control = _fresh_control(system, journal, "m8-bootstrap", run_host=_PassiveHost())
    await control.startup()
    try:
        registered = await control.registry_register(
            LOCAL_ADMIN, definition=definition, idempotency_key="m8-register"
        )
        assert isinstance(registered, RegistrationCommandResult)
        promoted = await control.registry_promote_initial(
            LOCAL_ADMIN,
            component=registered.component,
            version=registered.version,
            idempotency_key="m8-promote",
        )
        assert isinstance(promoted, PromotionCommandResult)
    finally:
        await control.shutdown()
    return Graph(
        name="m8-execution",
        nodes=(GraphNode(id="worker", body=Ref(component=definition.name, bind=bindings)),),
        inputs=(ISSUE,),
        outputs=(SUMMARY,),
    )
