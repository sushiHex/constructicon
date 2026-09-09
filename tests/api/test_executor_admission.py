"""Complete executor authority crosses the public admission/description seam."""

from __future__ import annotations

from dataclasses import replace
from typing import Literal

import pytest
from pydantic import ValidationError

from constructicon.api.control import ControlPlane
from constructicon.api.system import DEFAULT_ROOT_GRANTS, Constructicon
from constructicon.core.address import ScopePath
from constructicon.core.admission import AdmissionAccepted, AdmissionCode, AdmissionRejected
from constructicon.core.control import RunSubmission
from constructicon.core.grants import ModelSelection, Posture
from constructicon.core.identity import digest
from constructicon.core.introspection import DESCRIPTION_SCHEMA_VERSION, SystemDescription
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_control_response_loss import RUN_ACTOR
from tests.conftest import await_attempt_terminal
from tests.executorworld import FakeExecutorProvider, register_component

INPUTS = {"issue": {"title": "complete policy"}}


class _V2Description(SystemDescription):
    """Even an otherwise permissive old reader must refuse the version."""

    schema_version: Literal[2] = 2  # type: ignore[assignment]


def executor_system(
    journal, provider, *, root_grants=DEFAULT_ROOT_GRANTS, injected=True, owner="m8-worker"
):
    return Constructicon(
        journal=journal,
        owner_id=owner,
        lease_ttl_s=30,
        catalog={"complete-fake": provider.descriptor()},
        capabilities={"complete-fake": provider} if injected else {},
        root_grants=root_grants,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"leased": False},
        {"kind": "workspace"},
        {"revision": "not-the-installed-content"},
        {"executor_profile": None},
        {"executor_profile": FakeExecutor({}).profile},
    ],
)
def test_assembly_refuses_incoherent_or_hidden_executor_authority(journal, change) -> None:
    provider = FakeExecutorProvider()
    descriptor = replace(provider.descriptor(), **change)
    with pytest.raises(ValueError, match="incoherent"):
        Constructicon(
            journal=journal,
            catalog={"complete-fake": descriptor},
            capabilities={"complete-fake": provider},
        )
    assert provider.handles == [] and provider.ledger.operations == []


def test_assembly_compares_the_actual_complete_profile_and_provider_contract(journal) -> None:
    provider = FakeExecutorProvider()
    changed = provider.identity.profile.model_copy(update={"structured_output": False})
    with pytest.raises(ValueError, match="profile differs"):
        Constructicon(
            journal=journal,
            catalog={
                "complete-fake": replace(
                    provider.descriptor(),
                    executor_profile=changed,
                )
            },
            capabilities={"complete-fake": provider},
        )
    with pytest.raises(ValueError, match="ExecutorProvider"):
        Constructicon(
            journal=journal,
            catalog={"complete-fake": provider.descriptor()},
            capabilities={"complete-fake": provider.executor},
        )


@pytest.mark.parametrize("injected", [False, True])
async def test_known_unavailable_provider_is_described_and_refused(journal, injected) -> None:
    provider = FakeExecutorProvider(unavailable_reasons=("Linux boundary not proved",))
    system = executor_system(journal, provider, injected=injected)
    graph = await register_component(system, journal)
    assert system.describe().capabilities[0].available is False
    result = system.admit_graph(graph, INPUTS)
    assert isinstance(result, AdmissionRejected)
    assert len(result.faults) == 1
    fault = result.faults[0]
    assert fault.code is AdmissionCode.GRAPH_CONTRACT_INVALID
    assert fault.scope == ScopePath(segments=(graph.name, "worker"))
    assert fault.details == {
        "defect": "executor_unavailable",
        "capability_id": "complete-fake",
        "alias": "executor",
    }
    assert fault.repair and provider.handles == [] and provider.executor.calls == []


@pytest.mark.parametrize(
    "change",
    [
        {"posture": Posture.WRITE},
        {"allowed_tools": ("search",)},
        {"network": "allow"},
        {"env_allowlist": ("UNDECLARED",)},
        {"effort": "unknown"},
        {"model_selection": ModelSelection(kind="explicit")},
    ],
)
async def test_public_admission_uses_the_shared_pure_grant_predicate(journal, change) -> None:
    provider = FakeExecutorProvider()
    grants = DEFAULT_ROOT_GRANTS.model_copy(update=change)
    system = executor_system(journal, provider, root_grants=grants)
    graph = await register_component(system, journal)
    graph = graph.model_copy(update={"name": "root / with : separators"})
    result = system.admit_graph(graph, INPUTS)
    assert isinstance(result, AdmissionRejected)
    expected = provider.executor.validate_grants(grants)
    assert expected
    assert [fault.message for fault in result.faults] == [
        f"executor 'complete-fake': {reason}" for reason in expected
    ]
    assert all(fault.scope == ScopePath(segments=(graph.name, "worker")) for fault in result.faults)
    assert all(fault.details["defect"] == "executor_grants" for fault in result.faults)
    assert provider.handles == [] and provider.ledger.operations == []


async def test_description_publishes_complete_policy_in_schema_three(journal) -> None:
    provider = FakeExecutorProvider()
    system = executor_system(journal, provider)
    await register_component(system, journal)
    description = system.describe()
    assert DESCRIPTION_SCHEMA_VERSION == description.schema_version == 3
    assert description.graph_schema.version == description.admission_schema.version == 1
    capability = description.capabilities[0]
    assert capability.available and capability.revision == provider.identity.revision
    assert capability.executor_profile == provider.identity.profile
    payload = description.model_dump(mode="json")
    assert payload["capabilities"][0]["executor_profile"]["grant_policy"]["schema_version"] == 1
    assert SystemDescription.model_validate_json(description.model_dump_json()) == description
    with pytest.raises(ValidationError):
        _V2Description.model_validate(payload)
    body = {key: value for key, value in payload.items() if key != "description_digest"}
    assert description.description_digest == digest("system-description", 3, body)
    assert description.description_digest != digest("system-description", 2, body)


async def test_cached_availability_change_is_observed_without_reassembly(journal) -> None:
    provider = FakeExecutorProvider()
    system = executor_system(journal, provider)
    graph = await register_component(system, journal)
    assert isinstance(system.admit_graph(graph, INPUTS), AdmissionAccepted)
    provider._unavailable_reasons = ("previously observed prerequisite is no longer valid",)
    assert system.describe().capabilities[0].available is False
    assert isinstance(system.admit_graph(graph, INPUTS), AdmissionRejected)
    assert provider.handles == []


async def test_real_control_host_runs_the_complete_fake_through_its_lease(journal: SqliteJournal):
    provider = FakeExecutorProvider()
    system = executor_system(journal, provider)
    graph = await register_component(system, journal)
    control = ControlPlane(system=system, store=journal)
    await control.startup()
    try:
        submitted = await control.runs_start(
            RUN_ACTOR,
            proposal=graph,
            inputs=INPUTS,
            idempotency_key="complete-fake-run",
        )
        assert isinstance(submitted, RunSubmission)
        terminal = await await_attempt_terminal(journal, submitted.run_id, baseline_event_seq=0)
        assert terminal.kind == "RunSucceeded"
        # Host worker cleanup follows the terminal observation; shutdown joins it.
    finally:
        await control.shutdown()
    assert len(provider.executor.calls) == len(provider.handles) == 1
    handle = provider.handles[0]
    assert handle.entered and handle.closed
    assert provider.ledger.resources == set()
    assert provider.ledger.operations == [("allocate", handle.key), ("close", handle.key)]
    rows = journal.capability_leases(submitted.run_id)
    assert [(row.state, row.disposition) for row in rows] == [("closed", "released")]
