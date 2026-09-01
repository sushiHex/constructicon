"""Small truthful sealed worlds for low-level journal contract tests."""

from __future__ import annotations

from typing import Any

from constructicon.core.address import RunId
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, digest
from constructicon.core.manifest import ExecutionManifest, manifest_hash_for
from constructicon.core.run import RunLease, RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal


def sealed_test_manifest(inputs: dict[str, Any] | None = None) -> ExecutionManifest:
    """Return the smallest real manifest accepted by the production boundary."""

    exact_inputs = inputs or {}
    graph = Graph(
        name="tests/empty",
        nodes=(),
        connections=(),
        inputs=(),
        outputs=(),
    )
    draft = ExecutionManifest(
        source_graph=graph,
        source_graph_hash=digest("graph", 1, graph.model_dump(mode="json")),
        resolved_components=(),
        resolved_connections=(),
        capability_bindings=(),
        input_hash=digest("inputs", 1, exact_inputs),
        world_hash=digest("test-world", 1, {}),
        manifest_hash=Digest("sha256:" + "0" * 64),
    )
    return draft.model_copy(update={"manifest_hash": manifest_hash_for(draft)})


def create_test_run(
    journal: SqliteJournal,
    run_id: RunId,
    *,
    inputs: dict[str, Any] | None = None,
) -> ExecutionManifest:
    exact_inputs = inputs or {}
    manifest = sealed_test_manifest(exact_inputs)
    journal.create_run(
        run_id,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs=exact_inputs,
    )
    return manifest


def start_test_run(
    journal: SqliteJournal,
    run_id: RunId,
    *,
    owner_id: str,
    ttl_s: float = 30,
) -> RunLease:
    """Claim a pending fixture and atomically establish its first attempt."""

    lease = journal.claim_run(run_id, owner_id=owner_id, ttl_s=ttl_s)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    return lease
