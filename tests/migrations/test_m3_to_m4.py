"""M4 persistence: frame-aware leases and v1 manifest reproduction survive upgrade."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.identity import canonical_json, digest
from constructicon.core.manifest import manifest_hash_for
from constructicon.core.run import RunStatus
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.conftest import (
    LEASE_TTL_S,
    TRIAGE_SCRIPT,
    FakeClock,
    InjectedCrash,
    build_system,
    pipeline_graph,
)

M3_LEASE_SCHEMA = """
CREATE TABLE capability_leases (
    lease_id          TEXT NOT NULL,
    acquisition_epoch INTEGER NOT NULL,
    run_id            TEXT NOT NULL,
    binding_id        TEXT NOT NULL,
    scope_json        TEXT NOT NULL,
    lifetime          TEXT NOT NULL,
    state             TEXT NOT NULL,
    disposition       TEXT,
    resource_ref      TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (lease_id, acquisition_epoch)
)
"""


def test_v3_lease_rows_become_empty_frame_execution_paths(tmp_path: Path) -> None:
    db = tmp_path / "m3.db"
    SqliteJournal(db)
    scope = ScopePath(segments=("old-run", "writer"))
    resource_ref = '{"candidate_ref":"refs/candidates/old"}'
    with sqlite3.connect(db) as conn:
        conn.execute("DROP TABLE capability_leases")
        conn.execute(M3_LEASE_SCHEMA)
        conn.execute(
            "INSERT INTO capability_leases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "lease-old",
                7,
                "old-run",
                "workspace",
                canonical_json(scope.model_dump(mode="json")),
                "invocation",
                "active",
                None,
                resource_ref,
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        conn.execute("PRAGMA user_version = 3")

    migrated = SqliteJournal(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {
            row[1] for row in conn.execute("PRAGMA table_info(capability_leases)")
        }
        assert "scope_json" in columns and "path_json" not in columns
    rows = migrated.capability_leases(RunId("old-run"))
    assert len(rows) == 1
    row = rows[0]
    assert row.lease_id == "lease-old"
    assert row.acquisition_epoch == 7
    assert row.path == ExecutionPath(scope=scope)
    assert row.resource_ref == resource_ref
    assert row.state == "active"


def _register_pipeline(
    journal: SqliteJournal,
) -> tuple[Constructicon, FakeExecutor, FakeAnnounceEffect]:
    from tests.conftest import (
        ANNOUNCED,
        BRIEF,
        ISSUE,
        SUMMARY,
        announce_impl,
        atomic,
        summarize_impl,
        triage_impl,
    )

    executor = FakeExecutor(dict(TRIAGE_SCRIPT))
    effect = FakeAnnounceEffect()
    system = build_system(journal, executor, effect, owner_id="m4-worker")
    for definition, impl in (
        atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl),
        atomic("test/announce", (BRIEF,), (ANNOUNCED,), announce_impl),
        atomic("test/summarize", (BRIEF,), (SUMMARY,), summarize_impl),
    ):
        version = system.register(definition, impl)
        system.promote_initial(component=definition.name, version=version)
    return system, executor, effect


async def test_v1_stored_manifest_resumes_and_reproduces_after_upgrade(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    journal = SqliteJournal(tmp_path / "legacy-manifest.db", now_fn=clock.now)
    system, executor, effect = _register_pipeline(journal)
    inputs = {"issue": {"title": "retry loop is flaky"}}
    current = system.validate(pipeline_graph(), inputs)
    placeholder = digest("manifest-placeholder", 1, {})
    legacy = current.model_copy(
        update={
            "schema_version": 1,
            "resolved_loops": (),
            "manifest_hash": placeholder,
        }
    )
    legacy = legacy.model_copy(update={"manifest_hash": manifest_hash_for(legacy)})
    legacy_payload = legacy.model_dump(mode="json")
    legacy_payload.pop("resolved_loops")
    legacy_json = canonical_json(legacy_payload)

    run_id = RunId("legacy-v1-run")
    journal.create_run(
        run_id,
        manifest_json=legacy_json,
        manifest_hash=legacy.manifest_hash,
        input_hash=legacy.input_hash,
        inputs=inputs,
    )

    fired = False

    def crash_after_first_completion(name: str) -> None:
        nonlocal fired
        if name == "completion.after_commit" and not fired:
            fired = True
            raise InjectedCrash(name)

    journal.fault_probe = crash_after_first_completion
    with pytest.raises(InjectedCrash):
        await system.resume(run_id)
    journal.fault_probe = lambda name: None
    clock.advance(LEASE_TTL_S + 1)

    resumed = await system.resume(run_id)
    assert resumed.status is RunStatus.SUCCEEDED
    assert len(executor.calls) == 1  # triage checkpoint restored after the crash
    assert len(effect.executions) == 1

    # Reproduction reserializes the v1 model with additive defaults. The
    # existing manifest row omits resolved_loops; semantic comparison accepts
    # the equivalent bytes and refuses any real identity change.
    reproduced = await system.reproduce(
        run_id,
        new_run_id=RunId("legacy-v1-reproduced"),
    )
    assert reproduced.status is RunStatus.SUCCEEDED
    assert reproduced.outputs == resumed.outputs
    assert journal.run_manifest_hash(RunId("legacy-v1-reproduced")) == legacy.manifest_hash

    with sqlite3.connect(tmp_path / "legacy-manifest.db") as conn:
        stored = conn.execute(
            "SELECT manifest_json FROM manifests WHERE manifest_hash = ?",
            (str(legacy.manifest_hash),),
        ).fetchone()[0]
    assert "resolved_loops" not in json.loads(stored)
