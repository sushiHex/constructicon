"""New WRITE providers cannot bless a legacy host-executed Git world."""

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.grants import Posture
from constructicon.runtime.registry import CapabilityDescriptor, InMemoryRegistryStore
from constructicon.substrate.gates.runner import GateRunner
from constructicon.substrate.git.authority import GitWorkspaceCapability
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.executorworld import FakeExecutorProvider, launch_identity


@pytest.mark.parametrize("posture", [Posture.READ, Posture.WRITE])
@pytest.mark.parametrize("legacy", ["workspace", "gates"])
@pytest.mark.parametrize("relabel", [False, True])
def test_new_write_provider_refuses_legacy_resources_even_when_relabeled(
    tmp_path, posture, legacy, relabel,
):
    provider = FakeExecutorProvider()
    profile = provider.identity.profile.model_copy(update={"postures": frozenset({posture})})
    provider._identity = launch_identity(profile)
    # These are never invoked: assembly must refuse before any initialization
    # can run candidate code. The real legacy classes, not lookalike labels.
    resource = object.__new__(GitWorkspaceCapability if legacy == "workspace" else GateRunner)
    arguments = dict(
        journal=SqliteJournal(tmp_path / "journal.sqlite"), store=InMemoryRegistryStore(),
        capabilities={"provider": provider, "legacy": resource}, catalog={
            "provider": provider.descriptor("provider"),
            "legacy": CapabilityDescriptor(
                capability_id="legacy", kind=legacy + ".contained" if relabel else legacy,
                revision="legacy", leased=True,
            ),
        },
    )
    if posture is Posture.WRITE:
        with pytest.raises(ValueError, match="require contained workspace and gate bindings"):
            Constructicon(**arguments)
    else:
        Constructicon(**arguments)


@pytest.mark.parametrize("kind", ["workspace", "gates"])
def test_legacy_contract_is_refused_even_without_a_concrete_resource(tmp_path, kind):
    provider = FakeExecutorProvider()
    provider._identity = launch_identity(provider.identity.profile.model_copy(
        update={"postures": frozenset({Posture.WRITE})},
    ))
    with pytest.raises(ValueError, match="require contained workspace and gate bindings"):
        Constructicon(
            journal=SqliteJournal(tmp_path / "journal.sqlite"),
            capabilities={"provider": provider}, catalog={
                "provider": provider.descriptor("provider"),
                "legacy": CapabilityDescriptor(capability_id="legacy", kind=kind, revision="1"),
            },
        )
