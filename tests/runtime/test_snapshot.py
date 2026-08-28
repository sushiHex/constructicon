"""One admission sees one coherent world: a detached, immutable snapshot that
concurrent registry mutation can never tear (M2 §3)."""

from __future__ import annotations

from constructicon.api.system import Constructicon
from constructicon.core.ports import NodePortAddress
from constructicon.runtime.validator import admit
from tests.conftest import pipeline_graph

INPUTS = {"issue": {"title": "retry loop is flaky"}}


def test_admission_resolves_one_pre_mutation_world(world: Constructicon) -> None:
    from constructicon.api.system import DEFAULT_ROOT_GRANTS
    from tests.conftest import BRIEF, ISSUE, atomic, triage_impl

    snapshot = world._registry.snapshot()
    v1 = snapshot.stable_version("test/triage")
    assert v1 is not None

    first = admit(
        pipeline_graph(),
        snapshot=snapshot,
        catalog=world._catalog,
        root_grants=DEFAULT_ROOT_GRANTS,
        inputs=INPUTS,
    )

    # the world moves mid-compilation: a new triage version becomes stable
    definition, impl = atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl)
    changed = definition.model_copy(update={"role": "component"})
    v2 = world._register(changed, impl)
    from tests.runtime.test_registry import evaluated_promotion

    evaluated_promotion(world, "test/triage", v2, baseline=v1)
    assert world._registry.stable_version("test/triage") == v2

    # the held snapshot still resolves the OLD coherent world
    second = admit(
        pipeline_graph(),
        snapshot=snapshot,
        catalog=world._catalog,
        root_grants=DEFAULT_ROOT_GRANTS,
        inputs=INPUTS,
    )
    resolved = {r.component: r.resolved_version for r in second.resolved_components}
    assert resolved["test/triage"] == v1
    assert second.world_hash == first.world_hash

    # only a fresh snapshot sees the promotion
    third = world.validate(pipeline_graph(), INPUTS)
    fresh = {r.component: r.resolved_version for r in third.resolved_components}
    assert fresh["test/triage"] == v2
    assert third.world_hash != first.world_hash


def test_snapshot_is_detached_from_later_store_reads(world: Constructicon) -> None:
    snapshot = world._registry.snapshot()
    names_before = snapshot.names()
    from tests.conftest import BRIEF, ISSUE, atomic, summarize_impl

    definition, impl = atomic("test/late", (ISSUE,), (BRIEF,), summarize_impl)
    world._register(definition, impl)
    assert snapshot.names() == names_before
    assert "test/late" in world._registry.snapshot().names()


def test_manifest_records_implementation_digests(world: Constructicon) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    for resolution in manifest.resolved_components:
        # every atomic in this world is a PythonRef with a concrete digest
        assert resolution.implementation_digest is not None
    destinations = {
        (binding.destination.node, binding.destination.port)
        for binding in manifest.resolved_connections
        if isinstance(binding.destination, NodePortAddress)
    }
    assert ("announce", "brief") in destinations
