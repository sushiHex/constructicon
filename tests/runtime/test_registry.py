"""Registration never propagates; promotion does — and only with a
journal-minted attestation moving the pointer through compare-and-swap
(I2, I12)."""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.component import PromotionRecord
from constructicon.core.effect import AttestationDraft, CheckResult, ComponentProofSubject
from constructicon.core.envelope import utc_now
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, digest
from tests.conftest import BRIEF, ISSUE, atomic, triage_impl

INPUTS = {"issue": {"title": "retry loop is flaky"}}


def lone_triage_graph() -> Graph:
    return Graph(
        name="lone",
        nodes=(
            GraphNode(
                id="triage",
                body=Ref(component="test/triage", bind={"executor": "fake-executor"}),
            ),
        ),
        inputs=(ISSUE,),
        outputs=(BRIEF,),
    )


def evaluated_promotion(
    system: Constructicon, component: str, version: Digest, baseline: Digest | None
) -> PromotionRecord:
    """Mint a valid journal attestation and move the pointer — the evaluated
    path a real check panel would drive. Minting is literal: the journal
    computes the id; callers author only drafts."""
    draft = AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component=component, version=version, baseline_version=baseline
        ),
        checks=(CheckResult(name="evaluated", ok=True, detail="test", elapsed_s=0.0),),
        check_set_hash=digest("check-set", 1, {"policy": "test", "v": 1}),
        evidence=(),
        manifest_hash=digest("manifest", 1, {"test": True}),
        workspace_id=None,
    )
    attestation = system._journal.mint_policy_attestation(draft)
    return system._promote_version(
        component=component,
        version=version,
        attestation_id=attestation.attestation_id,
        actor="test",
    )


def test_bare_ref_never_resolves_a_fresh_registration(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    system._register(definition, impl)
    assert system._registry.stable_version("test/triage") is None
    with pytest.raises(AdmissionError, match="no stable version"):
        system.validate(lone_triage_graph(), INPUTS)


def test_promotion_moves_the_pointer(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    version = system._register(definition, impl)
    system._promote_initial(component="test/triage", version=version)
    assert system._registry.stable_version("test/triage") == version


def test_promote_initial_is_idempotent_but_never_replaces(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    v1 = system._register(definition, impl)
    first = system._promote_initial(component="test/triage", version=v1)
    assert first is not None
    # startup re-runs: already stable at this exact version -> None, no new row
    assert system._promote_initial(component="test/triage", version=v1) is None

    changed = definition.model_copy(update={"role": "component"})
    v2 = system._register(changed, impl)
    with pytest.raises(AdmissionError, match="already stable"):
        system._promote_initial(component="test/triage", version=v2)


def test_second_registration_stays_a_candidate(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    v1 = system._register(definition, impl)
    system._promote_initial(component="test/triage", version=v1)

    changed = definition.model_copy(update={"role": "component"})
    v2 = system._register(changed, impl)
    assert v2 != v1
    # the stable channel still names the promoted version, not the newest
    assert system._registry.stable_version("test/triage") == v1
    # a candidate is a query, never a channel
    assert v2 in system._registry.candidates("test/triage")


def test_caller_authored_attestation_cannot_promote(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    version = system._register(definition, impl)
    with pytest.raises(AdmissionError, match="not journal-minted"):
        system._promote_version(
            component="test/triage",
            version=version,
            attestation_id="att-i-made-this-up",
            actor="attacker",
        )


def test_mismatched_attestation_subject_is_refused(system: Constructicon) -> None:
    a_def, a_impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    b_def, b_impl = atomic("test/other", (ISSUE,), (BRIEF,), triage_impl)
    a_version = system._register(a_def, a_impl)
    b_version = system._register(b_def, b_impl)
    promotion = system._promote_initial(component="test/other", version=b_version)
    assert promotion is not None
    with pytest.raises(AdmissionError, match=r"identity mismatch|subject names"):
        system._promote_version(
            component="test/triage",
            version=a_version,
            attestation_id=promotion.attestation_id,
            actor="attacker",
        )


def test_one_attestation_authorizes_one_move(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    v1 = system._register(definition, impl)
    system._promote_initial(component="test/triage", version=v1)
    changed = definition.model_copy(update={"role": "component"})
    v2 = system._register(changed, impl)

    record = evaluated_promotion(system, "test/triage", v2, baseline=v1)
    # a retry with the same attestation returns the existing receipt — the
    # pointer moves exactly once
    retried = system._promote_version(
        component="test/triage",
        version=v2,
        attestation_id=record.attestation_id,
        actor="test",
    )
    assert retried.attestation_id == record.attestation_id
    history = system._registry.snapshot().history["test/triage"]
    assert len(history) == 2  # initial + evaluated, never a third


def test_stale_baseline_promotion_is_refused_by_cas(system: Constructicon) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    v1 = system._register(definition, impl)
    system._promote_initial(component="test/triage", version=v1)
    changed = definition.model_copy(update={"role": "component"})
    v2 = system._register(changed, impl)
    evaluated_promotion(system, "test/triage", v2, baseline=v1)

    # a record carrying yesterday's baseline must not move today's pointer
    stale = PromotionRecord(
        component="test/triage",
        channel="stable",
        from_version=v1,  # stale: stable is v2 now
        to_version=v1,
        attestation_id="att-stale-claimant",
        actor="test",
        source_run=None,
        created_at=utc_now(),
    )
    with pytest.raises(AdmissionError, match="stable moved"):
        system._registry.store.store_promotion(stale)


def test_rollback_is_a_pointer_move_that_retains_everything(
    system: Constructicon,
) -> None:
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    v1 = system._register(definition, impl)
    system._promote_initial(component="test/triage", version=v1)
    changed = definition.model_copy(update={"role": "component"})
    v2 = system._register(changed, impl)
    evaluated_promotion(system, "test/triage", v2, baseline=v1)
    assert system._registry.stable_version("test/triage") == v2

    system._rollback_version(component="test/triage", actor="operator")
    assert system._registry.stable_version("test/triage") == v1
    assert set(system._registry.versions("test/triage")) == {v1, v2}


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
    world._register(composite)
    assert "test/pipeline" in world.rdeps("test/triage")
