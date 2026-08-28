"""A real M3-era manifest remains resumable and reproducible under M4."""

from __future__ import annotations

import json

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.manifest import ExecutionManifest, manifest_hash_for
from constructicon.core.run import RunStatus
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from tests.conftest import pipeline_graph

INPUTS = {"issue": {"title": "retry loop is flaky"}}


def as_m3_manifest(system: Constructicon) -> tuple[ExecutionManifest, str]:
    current = system.validate(pipeline_graph(), INPUTS)
    provisional = current.model_copy(
        update={"schema_version": 1, "resolved_loops": ()}
    )
    manifest = provisional.model_copy(
        update={"manifest_hash": manifest_hash_for(provisional)}
    )
    payload = manifest.model_dump(mode="json")
    payload.pop("resolved_loops")  # the field did not exist in M3
    return manifest, json.dumps(payload, indent=2, sort_keys=False)


async def test_m3_stored_manifest_resumes_and_reproduces_after_upgrade(
    world: Constructicon,
    announce_effect: FakeAnnounceEffect,
) -> None:
    manifest, raw_m3 = as_m3_manifest(world)
    run_id = RunId("run-m3-manifest")
    world._journal.create_run(
        run_id,
        manifest_json=raw_m3,
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs=INPUTS,
    )

    resumed = await world._resume_direct(run_id)
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.outputs["summary"]["text"].startswith("summary of")

    reproduced = await world._reproduce_direct(
        run_id,
        new_run_id=RunId("run-m3-manifest-copy"),
    )
    assert reproduced.status is RunStatus.SUCCEEDED
    assert reproduced.outputs == resumed.outputs
    # Reproduction serializes the v1 model with the additive empty default;
    # create_run accepts it as the same v1 semantics rather than byte damage.
    assert len(announce_effect.executions) == 1
