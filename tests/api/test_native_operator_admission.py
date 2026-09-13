"""The schema-3 operator profile crosses the public assembly, admission and describe seam.

A fake exercises the same contract as a real native adapter would; it proves no
vendor account, no established egress, no store and no native process.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

import pytest
from pydantic import ValidationError

from constructicon.api.control import ControlPlane
from constructicon.api.system import DEFAULT_ROOT_GRANTS, Constructicon
from constructicon.core.address import ScopePath
from constructicon.core.admission import AdmissionAccepted, AdmissionCode, AdmissionRejected
from constructicon.core.control import RunSubmission
from constructicon.core.grants import ModelSelection, Posture
from constructicon.core.identity import canonical_json, digest
from constructicon.core.introspection import DESCRIPTION_SCHEMA_VERSION, SystemDescription
from constructicon.core.native_operator import NativeOperatorExecutorProfileV3
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.conftest import await_attempt_terminal
from tests.executorworld import FakeExecutorProvider
from tests.native_operator_world import (
    NATIVE_ROOT_GRANTS,
    FakeNativeOperatorProvider,
    native_profile,
    register_native_component,
)

INPUTS = {"issue": {"title": "operator mode"}}
CAPABILITY = "native-fake"
INGRESS_REASON = "private fixed-actor ingress is not established by assembly"


class _V3Description(SystemDescription):
    """A strict schema-3 reader must refuse the new assurance, not relabel it."""

    schema_version: Literal[3] = 3  # type: ignore[assignment]


def native_system(
    journal: SqliteJournal,
    provider: FakeNativeOperatorProvider,
    *,
    root_grants: Any = NATIVE_ROOT_GRANTS,
    injected: bool = True,
    owner: str = "n1-worker",
) -> Constructicon:
    return Constructicon(
        journal=journal,
        owner_id=owner,
        lease_ttl_s=30,
        catalog={CAPABILITY: provider.descriptor(CAPABILITY)},
        capabilities={CAPABILITY: provider} if injected else {},
        root_grants=root_grants,
    )


def test_assembly_accepts_a_coherent_native_descriptor_and_provider(journal) -> None:
    provider = FakeNativeOperatorProvider()
    described = native_system(journal, provider).describe().capabilities[0]
    assert described.available and described.unavailable_reasons == ()
    assert described.executor_profile == provider.identity.profile
    assert described.revision == provider.identity.revision
    assert provider.handles == []


def test_assembly_refuses_every_mixed_profile_version(journal) -> None:
    native = FakeNativeOperatorProvider()
    legacy = FakeExecutorProvider()
    mismatches = (
        (replace(native.descriptor(CAPABILITY), executor_profile=legacy.identity.profile), native),
        (replace(legacy.descriptor(CAPABILITY), executor_profile=native.identity.profile), legacy),
        (
            replace(
                native.descriptor(CAPABILITY),
                executor_profile=native.identity.profile.model_copy(
                    update={"structured_output": False}
                ),
            ),
            native,
        ),
    )
    for descriptor, provider in mismatches:
        with pytest.raises(ValueError, match="profile differs"):
            Constructicon(
                journal=journal,
                catalog={CAPABILITY: descriptor},
                capabilities={CAPABILITY: provider},
                root_grants=NATIVE_ROOT_GRANTS,
            )
    assert native.handles == [] and legacy.handles == []


@pytest.mark.parametrize(
    "change",
    [
        {"posture": Posture.WRITE},
        {"allowed_tools": ("search",)},
        {"network": "none"},
        {"env_allowlist": ("UNDECLARED",)},
        {"effort": None},
        {"model_selection": ModelSelection(kind="explicit", model="other-model")},
        {"model_selection": ModelSelection(kind="backend_default")},
    ],
)
async def test_native_admission_uses_the_shared_pure_grant_predicate(journal, change) -> None:
    provider = FakeNativeOperatorProvider()
    grants = NATIVE_ROOT_GRANTS.model_copy(update=change)
    system = native_system(journal, provider, root_grants=grants)
    graph = await register_native_component(system, journal)
    result = system.admit_graph(graph, INPUTS)
    assert isinstance(result, AdmissionRejected)
    expected = provider.executor.validate_grants(grants)
    assert expected
    assert [fault.message for fault in result.faults] == [
        f"executor {CAPABILITY!r}: {reason}" for reason in expected
    ]
    assert all(fault.code is AdmissionCode.GRAPH_CONTRACT_INVALID for fault in result.faults)
    assert all(fault.details["defect"] == "executor_grants" for fault in result.faults)
    assert all(
        fault.scope == ScopePath(segments=(graph.name, "worker")) for fault in result.faults
    )
    assert provider.handles == [] and provider.executor.calls == []


async def test_default_root_grants_produce_exactly_three_native_faults(journal) -> None:
    provider = FakeNativeOperatorProvider()
    system = native_system(journal, provider, root_grants=DEFAULT_ROOT_GRANTS)
    graph = await register_native_component(system, journal)
    result = system.admit_graph(graph, INPUTS)
    assert isinstance(result, AdmissionRejected)
    reasons = provider.identity.profile.grant_faults(DEFAULT_ROOT_GRANTS)
    assert len(reasons) == 3
    assert sorted(fault.message for fault in result.faults) == sorted(
        f"executor {CAPABILITY!r}: {reason}" for reason in reasons
    )
    assert reasons[0].startswith("network 'none' excludes model networking")
    assert reasons[1].startswith("executor requires an explicit listed effort")
    assert reasons[2] == "executor requires an explicit model from its finite inventory"


@pytest.mark.parametrize("injected", [False, True])
async def test_unestablished_ingress_is_described_and_refused(journal, injected) -> None:
    provider = FakeNativeOperatorProvider(ingress_established=False)
    system = native_system(journal, provider, injected=injected)
    graph = await register_native_component(system, journal)
    described = system.describe().capabilities[0]
    assert described.available is False
    assert described.unavailable_reasons == (
        (INGRESS_REASON,) if injected else ("no executor provider is assembled",)
    )
    result = system.admit_graph(graph, INPUTS)
    assert isinstance(result, AdmissionRejected)
    assert len(result.faults) == 1
    fault = result.faults[0]
    assert fault.code is AdmissionCode.GRAPH_CONTRACT_INVALID
    assert fault.details == {
        "defect": "executor_unavailable",
        "capability_id": CAPABILITY,
        "alias": "executor",
    }
    assert provider.handles == [] and provider.executor.calls == []


async def test_real_control_host_runs_the_native_fake_through_its_lease(journal: SqliteJournal):
    provider = FakeNativeOperatorProvider()
    system = native_system(journal, provider)
    graph = await register_native_component(system, journal)
    assert isinstance(system.admit_graph(graph, INPUTS), AdmissionAccepted)
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        submitted = await control.runs_start(
            RUN_ACTOR,
            proposal=graph,
            inputs=INPUTS,
            idempotency_key="native-fake-run",
        )
        assert isinstance(submitted, RunSubmission)
        terminal = await await_attempt_terminal(journal, submitted.run_id, baseline_event_seq=0)
        assert terminal.kind == "RunSucceeded"
    finally:
        await control.shutdown()
    assert len(provider.executor.calls) == len(provider.handles) == 1
    handle = provider.handles[0]
    assert handle.entered and handle.closed
    assert provider.ledger.resources == set()
    assert provider.ledger.operations == [("allocate", handle.key), ("close", handle.key)]
    rows = journal.capability_leases(submitted.run_id)
    assert [(row.state, row.disposition) for row in rows] == [("closed", "released")]


async def test_description_publishes_the_native_profile_in_schema_four(journal) -> None:
    provider = FakeNativeOperatorProvider()
    system = native_system(journal, provider)
    await register_native_component(system, journal)
    description = system.describe()
    assert DESCRIPTION_SCHEMA_VERSION == description.schema_version == 4
    capability = description.capabilities[0]
    profile = capability.executor_profile
    assert isinstance(profile, NativeOperatorExecutorProfileV3)
    assert profile.account_assurance == "operator_bound_vendor_identity_unverified"
    assert profile.authentication == "vendor_managed_subscription"
    assert capability.available and capability.unavailable_reasons == ()
    payload = description.model_dump(mode="json")
    published = payload["capabilities"][0]
    assert published["executor_profile"]["schema_version"] == 3
    assert published["unavailable_reasons"] == []
    rendered = canonical_json(published)
    for word in ("principal", "email", "tenant", "workspace_id"):
        assert word not in rendered
    assert SystemDescription.model_validate_json(description.model_dump_json()) == description
    with pytest.raises(ValidationError):
        _V3Description.model_validate(payload)
    body = {key: value for key, value in payload.items() if key != "description_digest"}
    assert description.description_digest == digest("system-description", 4, body)
    assert description.description_digest != digest("system-description", 3, body)


def test_overage_variants_are_two_distinct_described_capabilities(journal) -> None:
    forbidden = FakeNativeOperatorProvider(
        profile=native_profile(name="fake-native-forbidden", overage="forbidden")
    )
    authorized = FakeNativeOperatorProvider(
        profile=native_profile(name="fake-native-authorized", overage="operator_authorized")
    )
    system = Constructicon(
        journal=journal,
        catalog={
            "native-forbidden": forbidden.descriptor("native-forbidden"),
            "native-authorized": authorized.descriptor("native-authorized"),
        },
        capabilities={"native-forbidden": forbidden, "native-authorized": authorized},
        root_grants=NATIVE_ROOT_GRANTS,
    )
    described = {item.capability_id: item for item in system.describe().capabilities}
    assert len(described) == 2
    profiles = {
        key: item.executor_profile
        for key, item in described.items()
        if isinstance(item.executor_profile, NativeOperatorExecutorProfileV3)
    }
    assert profiles["native-forbidden"].subscription_overage == "forbidden"
    assert profiles["native-authorized"].subscription_overage == "operator_authorized"
    assert described["native-forbidden"].revision != described["native-authorized"].revision
