"""The codex provider under a qualification authorization (M8 N5 Stage 1).

The provider stays unavailable and says so; the authorization lets exactly one
run acquire and materialize, and no handle it mints ever dispatches.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import TaskSpec
from constructicon.core.identity import digest
from constructicon.core.manifest import CapabilityBinding, CapabilityLease
from constructicon.core.qualification import QualificationAuthorization
from constructicon.core.run import RunLease
from constructicon.core.workspace import LeaseContext, StaleAcquisition
from constructicon.substrate.executors.codex import (
    UNQUALIFIED_PREREQUISITES,
    CodexOperatorHandle,
    CodexOperatorProvider,
)
from tests.substrate import test_codex_adapter as adapter
from tests.substrate.test_codex_adapter import (
    BINARY,
    CAPABILITY,
    CONFIGURATION,
    EXPECTED,
    GRANTS,
    bare_launcher,
    codex_profile,
    identity_for,
)

# The adapter suite's credential-free store and guard, reused as fixtures.
portable_binding = adapter.portable_binding
substituted_guard = adapter.substituted_guard

GRAPH = digest("test-graph", 1, "qualification")
SCOPE = ScopePath(segments=("qualification", "qualify"))


def provider(tmp_path, binding, qualification=None) -> CodexOperatorProvider:
    launcher = bare_launcher()
    return CodexOperatorProvider(
        launcher=launcher, profile=codex_profile(),
        identity=identity_for(launcher, store_identity=binding[1].sealed),
        expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION, catalog=(),
        acquisition_root=tmp_path / "acquisitions",
        binding_store=binding[1], closure=binding[2], qualification=qualification,
    )


def authorization(plain: CodexOperatorProvider, **changes) -> QualificationAuthorization:
    fields = {
        "authorization_id": "ci-fixture",
        "stage": "qualification-no-dispatch",
        "actor_id": "operator",
        "idempotency_key": "stage1",
        "scope": SCOPE,
        "binding": "executor",
        "source_graph_hash": GRAPH,
        "capability_id": CAPABILITY,
        "revision": plain.identity.revision,
        "operator_binding_digest": plain.identity.store.operator_binding_digest,
        "journal": "/var/lib/constructicon/qualification.sqlite",
        "max_epoch": 1,
        "not_after": datetime.now(UTC) + timedelta(hours=1),
    }
    return QualificationAuthorization(**{**fields, **changes})


def qualifying(tmp_path, binding, **changes):
    granted = authorization(provider(tmp_path, binding), **changes)
    return provider(tmp_path, binding, granted), granted


def context(granted, *, epoch=1, **changes) -> LeaseContext:
    fields = {
        "run_lease": RunLease(
            run_id=granted.run_id, owner_id=f"owner-{epoch}", epoch=epoch,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        ),
        "binding": CapabilityBinding(
            scope=SCOPE, binding="executor", capability_id=CAPABILITY,
            revision=granted.revision, effective_grants=GRANTS,
        ),
        "path": ExecutionPath(scope=SCOPE),
        "manifest_hash": digest("test-manifest", 1, "qualification"),
        "check_control": lambda: None,
        "source_graph_hash": GRAPH,
    }
    return LeaseContext(**{**fields, **changes})


def test_the_published_reasons_are_unchanged(tmp_path, portable_binding):
    qualified, _ = qualifying(tmp_path, portable_binding)
    assert qualified.unavailable_reasons == UNQUALIFIED_PREREQUISITES
    assert qualified.unavailable_reasons == provider(tmp_path, portable_binding).unavailable_reasons


@pytest.mark.parametrize("change", ["revision", "operator_binding_digest", "no-binding"])
def test_an_authorization_naming_another_provider_is_refused_at_assembly(
    tmp_path, portable_binding, change
):
    plain = provider(tmp_path, portable_binding)
    if change == "no-binding":
        launcher = bare_launcher()
        with pytest.raises(ContractViolation, match="must name this provider"):
            CodexOperatorProvider(
                launcher=launcher, profile=codex_profile(), identity=identity_for(launcher),
                expected_account=EXPECTED, binary=BINARY, configuration=CONFIGURATION,
                catalog=(), acquisition_root=tmp_path / "acquisitions",
                qualification=authorization(plain),
            )
        return
    other = digest("test-other", 1, change)
    granted = authorization(plain, **{change: str(other) if change == "revision" else other})
    with pytest.raises(ContractViolation, match="must name this provider"):
        provider(tmp_path, portable_binding, granted)


def test_admission_is_answered_only_for_the_authorized_graph(tmp_path, portable_binding):
    qualified, _ = qualifying(tmp_path, portable_binding)
    assert qualified.authorizes_admission(source_graph_hash=GRAPH, capability_id=CAPABILITY)
    assert not qualified.authorizes_admission(
        source_graph_hash=digest("test-graph", 1, "other"), capability_id=CAPABILITY,
    )
    assert not qualified.authorizes_admission(source_graph_hash=GRAPH, capability_id="other")
    plain = provider(tmp_path, portable_binding)
    assert not plain.authorizes_admission(source_graph_hash=GRAPH, capability_id=CAPABILITY)


async def test_the_authorized_acquisition_materializes_and_never_dispatches(
    tmp_path, portable_binding, substituted_guard
):
    qualified, granted = qualifying(tmp_path, portable_binding)
    acquired = await qualified.acquire(context(granted))
    handle = acquired.resource
    assert isinstance(handle, CodexOperatorHandle) and handle.dispatch is False
    await acquired.materialize()
    assert handle.ready and handle._store_lock is not None
    with pytest.raises(ContractViolation, match="never dispatches"):
        await handle.execute(TaskSpec(instruction="x"), workspace=None, grants=GRANTS)
    assert not handle.executed and handle.active is None
    closure = await qualified.close(acquired, "release")
    assert closure.disposition == "released" and handle._store_lock is None


@pytest.mark.parametrize(
    ("change", "fault"),
    [
        ({"run_lease": RunLease(
            run_id=RunId("run-not-authorized"), owner_id="owner-1", epoch=1,
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )}, "a different run"),
        ({"path": ExecutionPath(scope=SCOPE.child("inner"))}, "a different invocation"),
        ({"source_graph_hash": None}, "a different source graph"),
    ],
)
async def test_any_other_acquisition_is_refused_before_a_handle_exists(
    tmp_path, portable_binding, change, fault
):
    qualified, granted = qualifying(tmp_path, portable_binding)
    with pytest.raises(ContractViolation, match=fault):
        await qualified.acquire(context(granted, **change))
    assert qualified.handles == []


async def test_an_epoch_beyond_the_authorization_mints_nothing(tmp_path, portable_binding):
    qualified, granted = qualifying(tmp_path, portable_binding)
    with pytest.raises(ContractViolation, match="beyond the authorized epochs"):
        await qualified.acquire(context(granted, epoch=2))
    assert qualified.handles == []


async def test_an_expired_authorization_refuses_acquisition_but_not_cleanup(
    tmp_path, portable_binding, substituted_guard
):
    """Expiry bounds new acquisitions only: close and reconcile never consult it."""
    qualified, granted = qualifying(tmp_path, portable_binding)
    acquired = await qualified.acquire(context(granted))
    await acquired.materialize()
    qualified.qualification = granted.model_copy(
        update={"not_after": datetime.now(UTC) - timedelta(seconds=1)}
    )
    with pytest.raises(ContractViolation, match="expired"):
        await qualified.acquire(context(granted))
    await qualified.close(acquired, "discard")

    successor, _ = qualifying(tmp_path, portable_binding)
    successor.qualification = qualified.qualification
    row = CapabilityLease(
        lease_id=acquired.lease_id, acquisition_epoch=1, run_id=granted.run_id,
        binding_id="executor", path=ExecutionPath(scope=SCOPE), state="active",
        resource_ref=acquired.resource_ref,
    )
    outcome = await successor.reconcile(
        context(granted, epoch=2), (StaleAcquisition(lease=row, disposition="discard"),)
    )
    assert outcome.reaped == (acquired.resource_ref,)


async def test_an_ordinary_provider_still_dispatches_and_still_refuses_unavailable(
    tmp_path, portable_binding
):
    plain = provider(tmp_path, portable_binding)
    _, granted = qualifying(tmp_path, portable_binding)
    with pytest.raises(ContractViolation, match="unavailable operator provider cannot acquire"):
        await plain.acquire(context(granted))
