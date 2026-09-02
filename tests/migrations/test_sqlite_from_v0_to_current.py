"""An exact schema-v0 database migrates to current and loses nothing.

The fixture builds the M1 schema verbatim (copied from the merged M1
``sqlite.py``) with a completed and a failed run, opens it with the M2 store
(``PRAGMA user_version`` migration), then proves: durable inputs backfilled
from RunStarted events, sequence counters backfilled from MAX(seq), checkpoint
identities computed, the failed run resumable, the succeeded run
materializable, and both runs projectable — no M1 event or checkpoint lost.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.effect import EffectRequest, request_hash
from constructicon.core.envelope import Envelope, utc_now
from constructicon.core.errors import JournalDamaged
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
from tests.migrations.historical_sqlite import (
    M1_SCHEMA,
    effect_request_before_m3,
    historical_effect_receipt,
    historical_json,
    historical_manifest_v1,
)

INPUTS = {"issue": {"title": "retry loop is flaky"}}
TRIAGE_OUTPUT = TRIAGE_SCRIPT["triage"]
DONE = RunId("run-m1-done")
FAILED = RunId("run-m1-failed")
TS = "2025-12-01T00:00:00+00:00"
M1_BOOTSTRAP_ATTESTATION_ID = "att-m1-bootstrap-random-id"
M1_SECOND_ATTESTATION_ID = "att-m1-second-random-id"


def node_path(node: str) -> ExecutionPath:
    return ExecutionPath(scope=ScopePath(segments=("issue-to-summary", node)))


def m1_effect_facts(
    manifest: ExecutionManifest,
) -> tuple[tuple[Digest, dict[str, Any]], tuple[Digest, dict[str, Any]]]:
    prepared = effect_request_before_m3(
        manifest_hash=manifest.manifest_hash,
        path=node_path("announce"),
        kind="announce",
        # This is the exact request the failed pipeline will retry after the
        # migration.  M1 omitted the run world and mode from its stored bytes.
        subject={"title": TRIAGE_OUTPUT["title"]},
    )
    terminal = effect_request_before_m3(
        manifest_hash=manifest.manifest_hash,
        path=node_path("announce"),
        kind="announce",
        subject={"title": "committed before crash"},
    )
    return prepared, terminal


def checkpoint_json(run_id: RunId, node: str, outputs: dict[str, Any], version: Digest) -> str:
    path = node_path(node)
    node_inputs = {"issue": INPUTS["issue"]} if node == "triage" else {"brief": TRIAGE_OUTPUT}
    return Checkpoint(
        run_id=run_id,
        path=path,
        input_hash=digest("inputs", 1, node_inputs),
        resolved_version=version,
        outputs={
            port: Envelope(run_id=run_id, path=path, port=port, created_at=utc_now(), payload=value)
            for port, value in outputs.items()
        },
    ).model_dump_json()


def build_m1_database(db: Path, manifest: ExecutionManifest) -> None:
    versions = {
        r.component.removeprefix("test/"): r.resolved_version for r in manifest.resolved_components
    }
    conn = sqlite3.connect(db)
    conn.executescript(M1_SCHEMA)
    conn.execute(
        "INSERT INTO manifests VALUES (?, ?)",
        (str(manifest.manifest_hash), historical_manifest_v1(manifest)[1]),
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
    add_checkpoint(DONE, "summarize", {"summary": {"text": "summary of fix the flaky retry loop"}})

    add_run(FAILED, "failed")
    add_event(FAILED, 1, "RunStarted", None, {"inputs": INPUTS})
    add_event(FAILED, 2, "NodeStarted", "triage", None)
    add_event(FAILED, 3, "NodeCompleted", "triage", None)
    add_event(FAILED, 4, "RunFailed", None, None)
    add_checkpoint(FAILED, "triage", {"brief": TRIAGE_OUTPUT})

    prepared, terminal = m1_effect_facts(manifest)
    prepared_key, prepared_request = prepared
    terminal_key, terminal_request = terminal
    conn.execute(
        "INSERT INTO effects VALUES (?, ?, ?, NULL, ?, NULL)",
        (
            str(prepared_key),
            str(FAILED),
            historical_json(prepared_request),
            TS,
        ),
    )
    conn.execute(
        "INSERT INTO effects VALUES (?, ?, ?, ?, ?, ?)",
        (
            str(terminal_key),
            str(DONE),
            historical_json(terminal_request),
            historical_json(historical_effect_receipt(terminal_request)),
            TS,
            TS,
        ),
    )
    for index, attestation_id in enumerate(
        (M1_BOOTSTRAP_ATTESTATION_ID, M1_SECOND_ATTESTATION_ID),
        start=1,
    ):
        bootstrap = {
            "attestation_id": attestation_id,
            "action": "promote",
            "subject": {
                "kind": "component",
                "component": f"m1/bootstrap-{index}",
                "version": str(digest("component", 1, {"m1": index})),
                "baseline_version": None,
            },
            "checks": [
                {
                    "name": "bootstrap-initial",
                    "ok": True,
                    "detail": "M1 bootstrap policy",
                    "elapsed_s": 0.0,
                }
            ],
            "check_set_hash": str(digest("check-set", 1, {"policy": "m1", "index": index})),
            "evidence": [],
            "manifest_hash": str(manifest.manifest_hash),
            "created_by_run": "bootstrap",
            "workspace_id": None,
            # Pydantic's historical model_dump_json rendered UTC as ``Z``;
            # relational timestamps came from isoformat and retained +00:00.
            "created_at": TS.replace("+00:00", "Z"),
        }
        conn.execute(
            "INSERT INTO attestations VALUES (?, ?)",
            (attestation_id, historical_json(bootstrap)),
        )

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
        version = system._register(definition, impl)
        system._promote_initial(component=definition.name, version=version)
    return system, journal, executor


async def test_m1_database_migrates_and_loses_nothing(
    world: Constructicon,
    clock: FakeClock,
    tmp_path: Path,
) -> None:
    manifest, _manifest_json = historical_manifest_v1(world.validate(pipeline_graph(), INPUTS))
    m1_db = tmp_path / "m1.db"
    build_m1_database(m1_db, manifest)

    announce_effect = FakeAnnounceEffect()
    system, journal, executor = migrated_world(m1_db, clock, announce_effect)

    with sqlite3.connect(m1_db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        identities = [row[0] for row in conn.execute("SELECT identity FROM checkpoints")]
        assert identities and all(identities)  # backfilled, never empty
        seqs = dict(conn.execute("SELECT run_id, next_event_seq FROM runs").fetchall())
        assert seqs == {str(DONE): 8, str(FAILED): 4}  # backfilled from MAX(seq)
        stored_manifest = conn.execute(
            "SELECT manifest_json FROM manifests WHERE manifest_hash = ?",
            (str(manifest.manifest_hash),),
        ).fetchone()[0]
        assert json.loads(stored_manifest)["schema_version"] == 1
        assert "resolved_loops" not in json.loads(stored_manifest)
        for family, table in (("event", "events"), ("checkpoint", "checkpoints")):
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM durable_fact_seals WHERE family = ?",
                    (family,),
                ).fetchone()[0]
                == conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )

    prepared, terminal = m1_effect_facts(manifest)
    assert journal.receipt_for(prepared[0]) is None
    receipt = journal.receipt_for(terminal[0])
    assert receipt is not None
    assert receipt.request_hash == digest("effect-request", 1, terminal[1])
    for attestation_id in (M1_BOOTSTRAP_ATTESTATION_ID, M1_SECOND_ATTESTATION_ID):
        bootstrap = journal.load_attestation(attestation_id)
        assert bootstrap is not None
        assert bootstrap.attestation_id == attestation_id
        assert bootstrap.created_by_run == RunId("bootstrap")

    # durable inputs backfilled from each run's RunStarted event — once
    assert journal.run_inputs(DONE) == INPUTS
    assert journal.run_inputs(FAILED) == INPUTS

    # the succeeded M1 run materializes from its checkpoints, untouched
    done = await system._resume_direct(DONE)
    assert done.status is RunStatus.SUCCEEDED
    assert done.outputs["summary"] == {"text": "summary of fix the flaky retry loop"}
    assert len(executor.calls) == 0

    # the failed M1 run resumes: triage restored, the rest executes
    resumed = await system._resume_direct(FAILED)
    assert resumed.status is RunStatus.SUCCEEDED
    assert len(executor.calls) == 0  # triage's M1 checkpoint was restored
    assert len(announce_effect.executions) == 1
    normalized_prepared = EffectRequest(
        run_id=FAILED,
        manifest_hash=manifest.manifest_hash,
        path=node_path("announce"),
        kind="announce",
        subject={"title": TRIAGE_OUTPUT["title"]},
        idempotency_key=prepared[0],
        mode="live",
    )
    migrated_receipt = journal.receipt_for(prepared[0])
    assert migrated_receipt is not None
    assert migrated_receipt.request_hash == request_hash(normalized_prepared)
    assert migrated_receipt.request_hash != digest("effect-request", 1, prepared[1])
    # Completing a migrated preparation is a current outcome.  Its exact old
    # request bytes stay untouched and it never acquires a legacy terminal seal.
    with sqlite3.connect(m1_db) as conn:
        effect_row = conn.execute(
            "SELECT request_json, outcome_run_id, outcome_event_seq"
            " FROM effects WHERE idempotency_key = ?",
            (str(prepared[0]),),
        ).fetchone()
        legacy_seal = conn.execute(
            "SELECT 1 FROM legacy_effect_seals WHERE idempotency_key = ?",
            (str(prepared[0]),),
        ).fetchone()
    assert effect_row is not None
    assert effect_row[0] == historical_json(prepared[1])
    assert effect_row[1] == str(FAILED)
    assert type(effect_row[2]) is int and effect_row[2] > 0
    assert legacy_seal is None
    # The already-terminal M1 fact remains bound to its M1 request shape.
    retained_terminal = journal.receipt_for(terminal[0])
    assert retained_terminal is not None
    assert retained_terminal.request_hash == digest("effect-request", 1, terminal[1])
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
    db = tmp_path / "future.db"
    conn = sqlite3.connect(db)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()
    with pytest.raises(JournalDamaged, match="newer than this build"):
        SqliteJournal(db)


def test_m1_migration_never_heals_a_noninteger_event_sequence(
    world: Constructicon,
    tmp_path: Path,
) -> None:
    manifest, _manifest_json = historical_manifest_v1(world.validate(pipeline_graph(), INPUTS))
    database = tmp_path / "m1-damaged-sequence.db"
    build_m1_database(database, manifest)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE events RENAME TO events_typed")
        connection.execute(
            "CREATE TABLE events (run_id TEXT NOT NULL, seq, kind TEXT NOT NULL,"
            " path_json TEXT, payload TEXT, created_at TEXT NOT NULL,"
            " PRIMARY KEY (run_id, seq))"
        )
        connection.execute(
            "INSERT INTO events SELECT run_id,"
            " CASE WHEN run_id = ? AND seq = 2 THEN 2.5 ELSE seq END,"
            " kind, path_json, payload, created_at FROM events_typed",
            (str(FAILED),),
        )
        connection.execute("DROP TABLE events_typed")
        connection.commit()

    with pytest.raises(JournalDamaged, match="invalid durable event sequence"):
        SqliteJournal(database)
