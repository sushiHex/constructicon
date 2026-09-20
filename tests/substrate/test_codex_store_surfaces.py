"""The public N3a result carries bounded outcomes, never private binding facts."""

import json

import pytest

from constructicon.core.executor import TaskSpec
from tests.substrate.test_codex_adapter import GRANTS, bare_launcher, clean_native, context
from tests.substrate.test_codex_protocol import assert_published_surfaces_are_bounded
from tests.substrate.test_codex_store import (
    MutatingLauncher,
    available_provider,
)
from tests.substrate.test_codex_store import (
    store_lifecycle as store_lifecycle,
)


@pytest.mark.parametrize("withdrawn", [False, True])
async def test_whole_public_surface_excludes_binding_metadata_on_acceptance_and_refusal(
    tmp_path, store_lifecycle, withdrawn,
):
    world = store_lifecycle[0]

    def terminal_state():
        if withdrawn:
            del world.metadata["active.json"]

    base = bare_launcher(clean_native())
    launcher = MutatingLauncher(
        runtime_root=base.runtime_root, expected_runtime=base.expected_runtime,
        bubblewrap=base.bubblewrap, policy=base.policy,
        expected_policy_sha256=base.expected_policy_sha256,
        native=base.native, result=base.result, mutate=terminal_state,
    )
    provider = available_provider(tmp_path, store_lifecycle, launcher)
    acquired = await provider.acquire(context())
    try:
        await acquired.materialize()
        outcome = await acquired.resource.execute(
            TaskSpec(instruction="bounded fixture"), workspace=None, grants=GRANTS,
        )
        assert outcome.status == ("failure" if withdrawn else "success")
        assert_published_surfaces_are_bounded(outcome)
        # Traverse the complete serialized surface, including new fields and
        # dict keys. Only the sealed opaque binding digest belongs in the inert
        # acquisition reference; no raw locator, key, instance or file handle.
        public = json.dumps({
            "outcome": outcome.model_dump(mode="json"),
            "resource_ref": acquired.resource_ref,
            "identity": provider.identity.model_dump(mode="json"),
        })
        for private in (
            str(world.root), world.key, world.instance,
            world.store.handle_hex, world.lock.handle_hex,
        ):
            assert private not in public
    finally:
        await provider.close(acquired, "discard")
