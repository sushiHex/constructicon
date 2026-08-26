"""Registration never propagates; promotion does — and only with a
journal-minted attestation (I2, I12)."""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Ref
from constructicon.runtime.registry import RegistryError
from tests.conftest import BRIEF, ISSUE, atomic, triage_impl


def test_bare_ref_never_resolves_a_fresh_registration(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    system.register(definition, impl)
    with pytest.raises(RegistryError, match="no stable version"):
        system.registry.resolve(Ref(component="test/triage"))


def test_promotion_moves_the_pointer(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    version = system.register(definition, impl)
    system.promote_initial(component="test/triage", version=version)
    record = system.registry.resolve(Ref(component="test/triage"))
    assert record.content_hash == version


def test_second_registration_stays_a_candidate(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    v1 = system.register(definition, impl)
    system.promote_initial(component="test/triage", version=v1)

    changed = definition.model_copy(update={"role": "component"})
    v2 = system.register(changed, impl)
    assert v2 != v1
    # bare reference still resolves the promoted version, not the newest
    assert system.registry.resolve(Ref(component="test/triage")).content_hash == v1
    # a candidate is a query, never a channel
    assert v2 in system.registry.candidates("test/triage")


def test_caller_authored_attestation_cannot_promote(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    version = system.register(definition, impl)
    with pytest.raises(AdmissionError, match="not journal-minted"):
        system.promote(
            component="test/triage",
            version=version,
            attestation_id="att-i-made-this-up",
            actor="attacker",
        )


def test_mismatched_attestation_subject_is_refused(system: Constructicon) -> None:
    a_def, a_impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    b_def, b_impl = atomic("test/other", (ISSUE,), (BRIEF,), triage_impl)
    a_version = system.register(a_def, a_impl)
    b_version = system.register(b_def, b_impl)
    promotion = system.promote_initial(component="test/other", version=b_version)
    with pytest.raises(AdmissionError, match=r"identity mismatch|subject names"):
        system.promote(
            component="test/triage",
            version=a_version,
            attestation_id=promotion.attestation_id,
            actor="attacker",
        )


def test_rollback_is_a_pointer_move_that_retains_everything(
    system: Constructicon,
) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    v1 = system.register(definition, impl)
    system.promote_initial(component="test/triage", version=v1)
    changed = definition.model_copy(update={"role": "component"})
    v2 = system.register(changed, impl)
    system.promote_initial(component="test/triage", version=v2)
    assert system.registry.stable_version("test/triage") == v2

    system.registry.rollback(component="test/triage", actor="operator", journal=system.journal)
    assert system.registry.stable_version("test/triage") == v1
    assert set(system.registry.versions("test/triage")) == {v1, v2}


def test_rdeps_names_dependents(world: Constructicon) -> None:
    from constructicon.core.component import ComponentDef
    from tests.conftest import pipeline_graph

    composite = ComponentDef(
        name="test/pipeline",
        role="workflow",
        body=pipeline_graph(),
        inputs=(ISSUE,),
        outputs=pipeline_graph().outputs,
    )
    world.register(composite)
    assert "test/pipeline" in world.rdeps("test/triage")
