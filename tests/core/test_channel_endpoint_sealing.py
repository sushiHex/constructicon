"""Channel routing is a sealed manifest fact, not a live-object detail (M7).

Assembly decides where a binding sends (I1); execution consumes that decision
as part of one immutable manifest identity (I13). Two hosts that assemble the
same manifest with different routing must therefore disagree on `manifest_hash`
rather than silently derive different messages.
"""

from __future__ import annotations

from typing import Any

from constructicon.core.channel import ChannelEndpoint
from constructicon.core.manifest import (
    CapabilityBinding,
    manifest_hash_for,
    manifest_identity_payload,
)
from tests.conftest import pipeline_graph

INPUTS = {"issue": {"title": "seal the endpoint"}}
ENDPOINT = ChannelEndpoint(
    lane="review",
    interaction="advice",
    recipient_actor_id="static:advisor",
)


def _binding(world: Any, **overrides: Any) -> CapabilityBinding:
    """A real admitted binding, varied only where the test is looking."""

    manifest = world.validate(pipeline_graph(), INPUTS)
    return manifest.capability_bindings[0].model_copy(update=overrides)


def test_a_binding_without_an_endpoint_keeps_its_pre_m7_bytes(world: Any) -> None:
    """Every historical manifest must hash exactly as it did before M7."""

    legacy = _binding(world)
    assert legacy.endpoint is None
    assert "endpoint" not in legacy.model_dump(mode="json")


def test_a_real_manifest_carries_no_endpoint_key_in_its_identity(world: Any) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    assert manifest.capability_bindings  # the pipeline binds an executor
    payload = manifest_identity_payload(manifest)
    for binding in payload["capability_bindings"]:
        assert "endpoint" not in binding
    assert manifest_hash_for(manifest) == manifest.manifest_hash


def test_routing_participates_in_manifest_identity(world: Any) -> None:
    """Divergent assembly is caught here, not by a duplicated channel message."""

    manifest = world.validate(pipeline_graph(), INPUTS)
    bound = manifest.model_copy(
        update={"capability_bindings": (_binding(world, endpoint=ENDPOINT),)}
    )
    elsewhere = manifest.model_copy(
        update={
            "capability_bindings": (
                _binding(
                    world,
                    endpoint=ENDPOINT.model_copy(update={"lane": "other-lane"}),
                ),
            )
        }
    )
    assert "endpoint" in bound.capability_bindings[0].model_dump(mode="json")
    assert manifest_hash_for(bound) != manifest_hash_for(elsewhere)
    assert manifest_hash_for(bound) != manifest.manifest_hash


def test_recipient_and_interaction_are_identity_too(world: Any) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)

    def _with(endpoint: ChannelEndpoint) -> Any:
        return manifest_hash_for(
            manifest.model_copy(
                update={"capability_bindings": (_binding(world, endpoint=endpoint),)}
            )
        )

    base = _with(ENDPOINT)
    assert _with(ENDPOINT.model_copy(update={"recipient_actor_id": "static:other"})) != base
    assert _with(ENDPOINT.model_copy(update={"interaction": "approval"})) != base
