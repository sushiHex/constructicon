"""An exact M1-schema database migrates in place and loses nothing (M2 §6).

The fixture builds the M1 schema verbatim (copied from the merged M1
``sqlite.py``) with a completed and a failed run, opens it with the M2 store
(``PRAGMA user_version`` migration), then proves: durable inputs backfilled
from RunStarted events, sequence counters backfilled from MAX(seq), checkpoint
identities computed, the failed run resumable, the succeeded run
materializable, and both runs projectable — no M1 event or checkpoint lost.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.envelope import Envelope, utc_now
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.journal import Checkpoint
from constructicon.core.manifest import ExecutionManifest
from constructicon.core.run import RunStatus
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.conftest import (
    TRIAGE_SCRIPT,
    FakeClock,
    build_system,
    pipeline_graph,
)

# The M1 schema, verbatim from the merged M1 substrate/journal/sqlite.py.
M1_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id        TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL,
    input_hash    TEXT NOT NULL,
    status        TEXT NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    run_id     TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    path_json  TEXT,
    payload    TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id          TEXT NOT NULL,
    path_key        TEXT NOT NULL,
    checkpoint_json TEXT NOT NULL,
    PRIMARY KEY (run_id, path_key)
);
CREATE TABLE IF NOT EXISTS manifests (
    manifest_hash TEXT PRIMARY KEY,
    manifest_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attestations (
    attestation_id   TEXT PRIMARY KEY,
    attestation_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS effects (
    idempotency_key TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL,
    request_json    TEXT,
    receipt_json    TEXT,
    prepared_at     TEXT NOT NULL,
    receipted_at    TEXT
);
"""

INPUTS = {"issue": {"title": "retry loop is flaky"}}
TRIAGE_OUTPUT = TRIAGE_SCRIPT["triage"]
DONE = RunId("run-m1-done")
FAILED = RunId("run-m1-failed")
TS = "2025-12-01T00:00:00+00:00"


def node_path(node: str) -> ExecutionPath:
    return ExecutionPath(scope=ScopePath(segments=("issue-to-summary", node)))


def checkpoint_json(
    run_id: RunId, node: str, outputs: dict[str, Any], version: Digest
) -> str:
    path = node_path(node)
    node_inputs = (
        {"issue": INPUTS["issue"]} if node == "triage" else {"brief": TRIAGE_OUTPUT}
    )
    return Checkpoint(
        run_id=run_id,
        path=path,
        input_hash=digest("inputs", 1, node_inputs),
        resolved_version=version,
        outputs={
            port: Envelope(
                run_id=run_id, path=path, port=port, created_at=utc_now(), payload=value
            )
            for port, value in outputs.items()
        },
    ).model_dump_json()


def build_m1_database(db: Path, manifest: ExecutionManifest) -> None:
    versions = {
        r.component.removeprefix("test/"): r.resolved_version
        for r in manifest.resolved_components
    }
    conn = sqlite3.connect(db)
    conn.executescript(M1_SCHEMA)
    conn.execute(
        "INSERT INTO manifests VALUES (?, ?)",
        (str(manifest.manifest_hash), manifest.model_dump_json()),
    )

    def add_run(run_id: RunId, status: str) -> None:
        conn.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, ?)",
            (run_id, str(manifest.manifest_hash), str(manifest.input_hash), status, TS),
        )

    def add_event(run_id: RunId, seq: int, kind: str, node: str | None, payload: Any) -> None:
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                seq,
                kind,
                canonical_json(node_path(node).model_dump(mode="json")) if node else None,
                canonical_json(payload) if payload is not None else None,
                TS,
            ),
        )

    def add_checkpoint(run_id: RunId, node: str, outputs: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO checkpoints VALUES (?, ?, ?)",
            (
                run_id,
                canonical_json(node_path(node).model_dump(mode="json")),
                checkpoint_json(run_id, node, outputs, versions[node]),
            ),
        )

    add_run(DONE, "succeeded")
    add_event(DONE, 1, "RunStarted", None, {"inputs": INPUTS})
    for seq, node in ((2, "triage"), (4, "announce"), (6, "summarize")):
        add_event(DONE, seq, "NodeStarted", node, None)
        add_event(DONE, seq + 1, "NodeCompleted", node, None)
    add_event(DONE, 8, "RunSucceeded", None, {"outputs": ["summary", "announced"]})
    add_checkpoint(DONE, "triage", {"brief": TRIAGE_OUTPUT})
    add_checkpoint(DONE, "announce", {"announced": {"reference": "announce/1"}})
    add_checkpoint(
        DONE, "summarize", {"summary": {"text": "summary of fix the flaky retry loop"}}
    )

    add_run(FAILED, "failed")
    add_event(FAILED, 1, "RunStarted", None, {"inputs": INPUTS})
    add_event(FAILED, 2, "NodeStarted", "triage", None)
    add_event(FAILED, 3, "NodeCompleted", "triage", None)
    add_event(FAILED, 4, "RunFailed", None, None)
    add_checkpoint(FAILED, "triage", {"brief": TRIAGE_OUTPUT})

    conn.commit()
    conn.close()


def migrated_world(
    db: Path, clock: FakeClock, announce_effect: FakeAnnounceEffect
) -> tuple[Constructicon, SqliteJournal, FakeExecutor]:
    journal = SqliteJournal(db, now_fn=clock.now)  # the migration runs here
    executor = FakeExecutor(dict(TRIAGE_SCRIPT))
    system = build_system(journal, executor, announce_effect, owner_id="m2-worker")
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

    for definition, impl in (
        atomic("test/triage", (ISSUE,), (BRIEF,), triage_impl),
        atomic("test/announce", (BRIEF,), (ANNOUNCED,), announce_impl),
        atomic("test/summarize", (BRIEF,), (SUMMARY,), summarize_impl),
    ):
        version = system.register(definition, impl)
        system.promote_initial(component=definition.name, version=version)
    return system, journal, executor


async def test_m1_database_migrates_and_loses_nothing(
    world: Constructicon,
    clock: FakeClock,
    tmp_path: Path,
) -> None:
    manifest = world.validate(pipeline_graph(), INPUTS)
    m1_db = tmp_path / "m1.db"
    build_m1_database(m1_db, manifest)

    announce_effect = FakeAnnounceEffect()
    system, journal, executor = migrated_world(m1_db, clock, announce_effect)

    with sqlite3.connect(m1_db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        identities = [
            row[0] for row in conn.execute("SELECT identity FROM checkpoints")
        ]
        assert identities and all(identities)  # backfilled, never empty
        seqs = dict(
            conn.execute("SELECT run_id, next_event_seq FROM runs").fetchall()
        )
        assert seqs == {str(DONE): 8, str(FAILED): 4}  # backfilled from MAX(seq)

    # durable inputs backfilled from each run's RunStarted event — once
    assert journal.run_inputs(DONE) == INPUTS
    assert journal.run_inputs(FAILED) == INPUTS

    # the succeeded M1 run materializes from its checkpoints, untouched
    done = await system.resume(DONE)
    assert done.status is RunStatus.SUCCEEDED
    assert done.outputs["summary"] == {"text": "summary of fix the flaky retry loop"}
    assert len(executor.calls) == 0

    # the failed M1 run resumes: triage restored, the rest executes
    resumed = await system.resume(FAILED)
    assert resumed.status is RunStatus.SUCCEEDED
    assert len(executor.calls) == 0  # triage's M1 checkpoint was restored
    assert len(announce_effect.executions) == 1
    kinds = [event.kind for event in journal.events(FAILED, limit=200)]
    assert "NodeRestored" in kinds and "RunResumed" in kinds

    # no M1 event was lost or renumbered
    done_kinds = [event.kind for event in journal.events(DONE, limit=200)]
    assert done_kinds[:2] == ["RunStarted", "NodeStarted"]
    assert done_kinds[7] == "RunSucceeded"

    # both runs project canonically from the migrated store
    first = system.project_run(DONE, tmp_path / "done")
    again = system.project_run(DONE, tmp_path / "done-again")
    assert first.events_digest == again.events_digest
    system.project_run(FAILED, tmp_path / "failed")


def test_opening_a_newer_schema_is_refused(tmp_path: Path) -> None:
    import pytest

    from constructicon.core.errors import JournalDamaged

    db = tmp_path / "future.db"
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(JournalDamaged, match="newer than this build"):
        SqliteJournal(db)
