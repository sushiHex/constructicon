"""Channel routing and its exchange are sealed manifest facts (M7).

Assembly decides where a binding sends (I1); admission compiles the one
request/reply pair it may carry; execution consumes both as part of a single
immutable manifest identity (I13). Two hosts that assemble one manifest with
different routing must disagree on `manifest_hash` rather than silently derive
different messages.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from constructicon.core.channel import ChannelBinding, ChannelContract, ChannelEndpoint
from constructicon.core.manifest import (
    CapabilityBinding,
    ExecutionManifest,
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
CHANNEL = ChannelBinding(
    endpoint=ENDPOINT,
    port="request",
    contract=ChannelContract(type_id="test/AdviceRequest", schema_hash="req-v1"),
    reply_port="advice",
    reply_contract=ChannelContract(type_id="test/AdviceResponse", schema_hash="rep-v1"),
)


def _binding(world: Any, **overrides: Any) -> CapabilityBinding:
    """A real admitted binding, varied only where the test is looking."""

    manifest = world.validate(pipeline_graph(), INPUTS)
    return manifest.capability_bindings[0].model_copy(update=overrides)


def _hash_with(world: Any, channel: ChannelBinding) -> Any:
    manifest = world.validate(pipeline_graph(), INPUTS)
    return manifest_hash_for(
        manifest.model_copy(
            update={
                "schema_version": 3,
                "capability_bindings": (_binding(world, channel=channel),),
            }
        )
    )


def test_a_binding_without_a_channel_keeps_its_pre_m7_bytes(world: Any) -> None:
    """Every historical manifest must hash exactly as it did before M7."""

    legacy = _binding(world)
    assert legacy.channel is None
    assert "channel" not in legacy.model_dump(mode="json")


def test_a_real_manifest_carries_no_channel_key_in_its_identity(world: Any) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    assert manifest.capability_bindings  # the pipeline binds an executor
    assert manifest.schema_version == 2  # still readable by a pre-M7 build
    for binding in manifest_identity_payload(manifest)["capability_bindings"]:
        assert "channel" not in binding
    assert manifest_hash_for(manifest) == manifest.manifest_hash


def test_a_bound_channel_changes_the_manifest_identity(world: Any) -> None:
    """Divergent assembly is caught here, not by a duplicated channel message."""

    manifest = world.validate(pipeline_graph(), INPUTS)
    assert "channel" in _binding(world, channel=CHANNEL).model_dump(mode="json")
    assert _hash_with(world, CHANNEL) != manifest.manifest_hash


@pytest.mark.parametrize(
    "change",
    [
        {"lane": "other-lane"},
        {"recipient_actor_id": "static:someone-else"},
        {"interaction": "approval"},
    ],
)
def test_every_routing_field_moves_the_manifest_identity(
    world: Any,
    change: dict[str, Any],
) -> None:
    elsewhere = CHANNEL.model_copy(update={"endpoint": ENDPOINT.model_copy(update=change)})
    assert _hash_with(world, elsewhere) != _hash_with(world, CHANNEL)


@pytest.mark.parametrize(
    "change",
    [
        {"port": "other-request"},
        {"reply_port": "other-reply"},
        {"contract": ChannelContract(type_id="test/Other", schema_hash="req-v1")},
        {"reply_contract": ChannelContract(type_id="test/AdviceResponse", schema_hash="v2")},
    ],
)
def test_the_compiled_exchange_moves_the_manifest_identity(
    world: Any,
    change: dict[str, Any],
) -> None:
    """The admitted request/reply pair is identity, not a runtime detail."""

    assert _hash_with(world, CHANNEL.model_copy(update=change)) != _hash_with(world, CHANNEL)


def test_a_manifest_binding_a_channel_must_declare_schema_three(world: Any) -> None:
    """The version says what a reader must understand, not who wrote it."""

    manifest = world.validate(pipeline_graph(), INPUTS)
    body = manifest.model_dump(mode="json")
    body["capability_bindings"] = [_binding(world, channel=CHANNEL).model_dump(mode="json")]

    body["schema_version"] = 2
    with pytest.raises(ValidationError, match="must declare schema version 3"):
        ExecutionManifest.model_validate(body)

    body["schema_version"] = 3
    assert ExecutionManifest.model_validate(body).schema_version == 3


def test_a_manifest_binding_no_channel_may_not_claim_schema_three(world: Any) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    body = manifest.model_dump(mode="json")
    body["schema_version"] = 3
    with pytest.raises(ValidationError, match="claims a channel binding"):
        ExecutionManifest.model_validate(body)
