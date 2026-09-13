"""Genuine schema-3 operator-mode doubles. No account, store, egress or process.

Every digest here labels a double, never an installed artifact or conformance
evidence. The provider mirrors ``tests.executorworld.FakeExecutorProvider`` so
the same acquire/record/materialize/close lease law is exercised end to end
without credentials, and shares its allocation ledger.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import ExecutorOutcome, TaskSpec
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.identity import canonical_json, digest
from constructicon.core.native_operator import (
    NativeEgressIdentityV1,
    NativeOperatorExecutorProfileV3,
    NativeOperatorGrantPolicyV3,
    NativeOperatorIsolationProfileV3,
    NativeOperatorLaunchIdentityV3,
    NativeOperatorStoreIdentityV1,
    operator_binding_digest,
)
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
from constructicon.substrate.executors.fake_native_operator import FakeNativeOperatorExecutor
from tests.executorworld import AllocationLedger

NATIVE_CAPABILITY = "native-fake"
NATIVE_MODELS = ("fake-native-model", "fake-native-model-mini")
NATIVE_EFFORTS = ("low", "medium")
INGRESS_NOT_ESTABLISHED = "private fixed-actor ingress is not established by assembly"

NATIVE_ROOT_GRANTS = EffectiveGrants(
    posture=Posture.READ,
    model_selection=ModelSelection(kind="explicit", model="fake-native-model"),
    effort="low",
    allowed_tools=("read",),
    env_allowlist=("SAFE_TEST",),
    network="allow",
    timeout_s=600,
)


def _content(field: str) -> Any:
    return digest("m8-native-fake-content", 1, field)


def native_policy() -> NativeOperatorGrantPolicyV3:
    return NativeOperatorGrantPolicyV3(
        tool_sets=((), ("read",), ("read", "search")),
        model_ids=NATIVE_MODELS,
        environment_names=("SAFE_TEST",),
        workspace_required=False,
        network_modes=("allow",),
        network_access="native_vendor_session_only",
        tool_path="mediated_callbacks_only",
    )


def native_isolation(posture: Posture = Posture.READ) -> NativeOperatorIsolationProfileV3:
    return NativeOperatorIsolationProfileV3(
        filesystem="none" if posture is Posture.READ else "workspace_only",
        process_tree_owned=True,
        environment_allowlisted=True,
        network_enforced=True,
        native_workspace="none",
        worker_network="none",
        credential_state="narrow_vendor_store_rw",
        zones="native_and_worker_separate",
    )


def native_profile(
    *,
    posture: Posture = Posture.READ,
    overage: Literal["forbidden", "operator_authorized"] = "forbidden",
    name: str = "fake-native",
) -> NativeOperatorExecutorProfileV3:
    return NativeOperatorExecutorProfileV3(
        name=name,
        posture=posture,
        structured_output=True,
        accepted_efforts=NATIVE_EFFORTS,
        grant_policy=native_policy(),
        isolation=native_isolation(posture),
        authentication="vendor_managed_subscription",
        account_assurance="operator_bound_vendor_identity_unverified",
        subscription_overage=overage,
    )


def native_egress() -> NativeEgressIdentityV1:
    return NativeEgressIdentityV1(
        **{
            field: _content(field)
            for field in (
                "enforcement_build_digest",
                "destination_policy_digest",
                "resolver_policy_digest",
                "tls_assumptions_digest",
                "configuration_digest",
                "physical_conformance_revision",
            )
        }
    )


def native_store(*, generation: int = 1) -> NativeOperatorStoreIdentityV1:
    return NativeOperatorStoreIdentityV1(
        operator_binding_digest=operator_binding_digest(
            "fake-operator", generation, "fake-store"
        ),
        **{
            field: _content(field)
            for field in (
                "layout_law_digest",
                "mount_lock_law_digest",
                "subscription_mode_adapter_revision",
                "store_conformance_revision",
            )
        },
    )


def native_launch_identity(
    profile: NativeOperatorExecutorProfileV3,
    *,
    generation: int = 1,
) -> NativeOperatorLaunchIdentityV3:
    return NativeOperatorLaunchIdentityV3(
        **{
            field: _content(field)
            for field in (
                "executable_digest",
                "runtime_digest",
                "adapter_revision",
                "decoder_revision",
                "isolation_revision",
                "configuration_digest",
                "limits_digest",
                "callback_protocol_revision",
                "callback_catalog_digest",
                "authenticated_startup_conformance_revision",
                "subscription_mode_conformance_revision",
            )
        },
        profile=profile,
        egress=native_egress(),
        store=native_store(generation=generation),
    )


class FakeNativeOperatorHandle:
    def __init__(
        self,
        provider: FakeNativeOperatorProvider,
        context: LeaseContext,
        key: str,
    ) -> None:
        self.provider = provider
        self.context = context
        self.key = key
        self.entered = False
        self.ready = False
        self.closed = False

    @property
    def profile(self) -> NativeOperatorExecutorProfileV3:
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


class FakeNativeOperatorProvider:
    """A leased schema-3 provider double; availability is an assembly fact only."""

    def __init__(
        self,
        *,
        profile: NativeOperatorExecutorProfileV3 | None = None,
        generation: int = 1,
        ingress_established: bool = True,
        vendor_principal_label: str | None = None,
        ledger: AllocationLedger | None = None,
    ) -> None:
        self.executor = FakeNativeOperatorExecutor(
            {"test": {"text": "materialized"}},
            profile=profile if profile is not None else native_profile(),
        )
        self._identity = native_launch_identity(self.executor.profile, generation=generation)
        self._ingress_established = ingress_established
        # Never serialized, dumped or digested: it exists only so a test can
        # prove two differently labelled providers publish identical identities.
        self._vendor_principal_label = vendor_principal_label
        self._refreshes = 0
        self.ledger = ledger if ledger is not None else AllocationLedger()
        self.handles: list[FakeNativeOperatorHandle] = []
        self.before_materialize: (
            Callable[[FakeNativeOperatorHandle], Awaitable[None]] | None
        ) = None
        self.reconciled: list[str] = []

    @property
    def identity(self) -> NativeOperatorLaunchIdentityV3:
        return self._identity

    @property
    def unavailable_reasons(self) -> tuple[str, ...]:
        # An assembly constructor fact: never derived from grants, task,
        # profile or a caller flag.
        if self._ingress_established:
            return ()
        return (INGRESS_NOT_ESTABLISHED,)

    def simulate_refresh(self) -> None:
        """A vendor-store refresh changes no published identity fact."""
        self._refreshes += 1

    def descriptor(self, capability_id: str = NATIVE_CAPABILITY) -> CapabilityDescriptor:
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
        handle = FakeNativeOperatorHandle(self, context, key)
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
        assert isinstance(handle, FakeNativeOperatorHandle)
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


async def native_execute_task(ctx: NodeContext, inputs: dict[str, Any]) -> dict[str, Any]:
    executor = ctx.capability("executor")
    assert isinstance(executor, FakeNativeOperatorHandle)
    result = await executor.execute(TaskSpec(instruction="test"), workspace=None, grants=ctx.grants)
    assert result.status == "success"
    return {"summary": result.output}


async def register_native_component(
    system: Any, journal: Any, *, bindings: dict[str, str] | None = None
) -> Any:
    """Bootstrap through the real command law without launching recovery work."""
    from constructicon.core.component import CapabilityRequirement
    from constructicon.core.control import PromotionCommandResult, RegistrationCommandResult
    from constructicon.core.graph import Graph, GraphNode, Ref
    from tests.api.test_control_response_loss import LOCAL_ADMIN, _fresh_control, _PassiveHost
    from tests.conftest import ISSUE, SUMMARY, atomic

    bindings = {"executor": NATIVE_CAPABILITY} if bindings is None else bindings
    definition, _ = atomic("test/n1-native-executor", (ISSUE,), (SUMMARY,), native_execute_task)
    definition = definition.model_copy(
        update={
            "capability_requirements": tuple(
                CapabilityRequirement(alias=alias, kind="executor") for alias in sorted(bindings)
            )
        }
    )
    control = _fresh_control(system, journal, "n1-bootstrap", run_host=_PassiveHost())
    await control.startup()
    try:
        registered = await control.registry_register(
            LOCAL_ADMIN, definition=definition, idempotency_key="n1-register"
        )
        assert isinstance(registered, RegistrationCommandResult)
        promoted = await control.registry_promote_initial(
            LOCAL_ADMIN,
            component=registered.component,
            version=registered.version,
            idempotency_key="n1-promote",
        )
        assert isinstance(promoted, PromotionCommandResult)
    finally:
        await control.shutdown()
    return Graph(
        name="n1-native-execution",
        nodes=(GraphNode(id="worker", body=Ref(component=definition.name, bind=bindings)),),
        inputs=(ISSUE,),
        outputs=(SUMMARY,),
    )
