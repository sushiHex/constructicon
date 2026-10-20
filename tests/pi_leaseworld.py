"""One ordinary graph and fixed scripted READ assembly, shared across proof lanes."""

from constructicon.api.system import Constructicon
from constructicon.core.component import CapabilityRequirement
from constructicon.core.control import PromotionCommandResult, RegistrationCommandResult
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.grants import Posture
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import digest
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.executors.pi_provider import PiReadHandle, PiReadProvider
from constructicon.substrate.git.authority import GitAuthority
from constructicon.substrate.git.contained import ContainedWorkspaceProvider
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import LOCAL_ADMIN
from tests.conftest import ISSUE, SUMMARY, atomic
from tests.piworld import peer_source
from tests.substrate.test_pi_read import grants


async def assemble(root, launcher, *, owner="pi-owner", lease_ttl_s=2, gate=None, effects=None):
    """Caller seeds root/authority.git; no vendor or provider fallback exists."""
    journal = SqliteJournal(root / "control.sqlite")
    authority = GitAuthority(root / "authority.git", root / "legacy")
    workspace = ContainedWorkspaceProvider(
        authority, root=root / "workspace", target_ref="refs/heads/main",
        provider_id="pi-workspace", posture=Posture.READ, launcher=launcher,
    )
    descriptor = CapabilityDescriptor(
        capability_id="pi-workspace", kind="workspace.snapshot", leased=True,
        revision=str(digest("pi-read-test-workspace", 1, "read-snapshot")),
        requires_posture=Posture.READ,
    )
    executor = PiReadProvider(
        launcher, ("/usr/bin/python3", "-I", "-c", peer_source()),
        workspace_provider=workspace, workspace_capability_id=descriptor.capability_id,
        workspace_revision=descriptor.revision, acquisition_root=root / "executor",
    )
    await executor.qualify()
    capabilities = {"pi-read-fixture": executor, "pi-workspace": workspace}
    catalog = {
        "pi-read-fixture": CapabilityDescriptor(
            capability_id="pi-read-fixture", kind="executor", leased=True,
            revision=executor.identity.revision, executor_profile=executor.profile,
        ),
        "pi-workspace": descriptor,
    }
    if gate is not None:
        capabilities["gate"] = gate
        catalog["gate"] = CapabilityDescriptor(
            capability_id="gate", kind="gates.contained", leased=True, revision=gate.revision,
        )
    system = Constructicon(
        journal=journal, owner_id=owner, lease_ttl_s=lease_ttl_s,
        heartbeat_interval_s=lease_ttl_s / 10, root_grants=grants(),
        capabilities=capabilities, catalog=catalog, effects=effects,
    )
    return system, journal, executor, workspace


async def read_task(ctx, inputs):
    executor = ctx.capability("executor")
    assert isinstance(executor, PiReadHandle)
    outcome = await executor.execute(
        TaskSpec(instruction="Analyze fixture.txt"), workspace=ctx.capability("workspace"),
        grants=ctx.grants,
    )
    if outcome.status != "success":
        raise ContractViolation("scripted READ task did not complete")
    return {"summary": outcome.output}


async def register_pi(control):
    # Resolve the importable module, including when called by a __main__ driver.
    from tests.pi_leaseworld import read_task as implementation

    definition, _ = atomic("test/pi-read", (ISSUE,), (SUMMARY,), implementation)
    definition = definition.model_copy(update={"capability_requirements": (
        CapabilityRequirement(alias="executor", kind="executor"),
        CapabilityRequirement(alias="workspace", kind="workspace.snapshot"),
    )})
    registered = await control.registry_register(
        LOCAL_ADMIN, definition=definition, idempotency_key="pi-register",
    )
    assert isinstance(registered, RegistrationCommandResult), registered
    promoted = await control.registry_promote_initial(
        LOCAL_ADMIN, component=definition.name, version=registered.version,
        idempotency_key="pi-promote",
    )
    assert isinstance(promoted, PromotionCommandResult), promoted
    return Graph(name="pi-read", inputs=(ISSUE,), outputs=(SUMMARY,), nodes=(
        GraphNode(id="worker", body=Ref(component=definition.name, bind={
            "executor": "pi-read-fixture", "workspace": "pi-workspace",
        })),
    ))
