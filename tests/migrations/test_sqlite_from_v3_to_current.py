"""Schema-v3 persistence survives upgrade to the current schema."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.effect import (
    Attestation,
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
    attestation_id_for,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import canonical_json, digest
from constructicon.core.manifest import manifest_hash_for
from constructicon.core.run import RunStatus
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal._sqlite_execution import (
    LEGACY_EFFECT_OUTCOME_FACT_FAMILY,
)
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.conftest import (
    BRIEF,
    ISSUE,
    LEASE_TTL_S,
    TRIAGE_SCRIPT,
    FakeClock,
    InjectedCrash,
    atomic,
    build_system,
    pipeline_graph,
    triage_impl,
)
from tests.migrations.historical_sqlite import (
    M3_SCHEMA,
    effect_request_before_m6,
    historical_effect_receipt,
    historical_json,
    historical_manifest_v1,
)
from tests.run_worlds import sealed_test_manifest


def _build_exact_m3_active_lease(
    database: Path,
    *,
    run_id: RunId,
    lease_id: str,
    scope: ScopePath,
    resource_ref: str,
    acquisition_epoch: int = 7,
) -> None:
    """Write the exact M3 run, acquisition event, and lease row together."""

    manifest, manifest_json = historical_manifest_v1(sealed_test_manifest())
    observed_at = "2026-01-01T00:00:00+00:00"
    with sqlite3.connect(database) as connection:
        connection.executescript(M3_SCHEMA)
        connection.execute(
            "INSERT INTO manifests VALUES (?, ?)",
            (str(manifest.manifest_hash), manifest_json),
        )
        connection.execute(
            "INSERT INTO runs"
            " (run_id, manifest_hash, input_hash, inputs_json, status, created_at,"
            " owner_id, owner_epoch, owner_pid, heartbeat_at, lease_expires_at,"
            " next_event_seq, cancel_requested)"
            " VALUES (?, ?, ?, '{}', 'running', ?, ?, ?, 123, ?, ?, 2, 0)",
            (
                str(run_id),
                str(manifest.manifest_hash),
                str(manifest.input_hash),
                observed_at,
                "m3-lease-owner",
                acquisition_epoch,
                observed_at,
                "2026-01-01T00:01:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO events VALUES (?, 1, 'RunStarted', NULL, ?, ?)",
            (str(run_id), canonical_json({"inputs": {}}), observed_at),
        )
        connection.execute(
            "INSERT INTO events VALUES (?, 2, 'LeaseAcquired', NULL, ?, ?)",
            (
                str(run_id),
                canonical_json(
                    {
                        "lease_id": lease_id,
                        "acquisition_epoch": acquisition_epoch,
                        "binding": "workspace",
                        "resource_ref": resource_ref,
                    }
                ),
                observed_at,
            ),
        )
        connection.execute(
            "INSERT INTO capability_leases VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                lease_id,
                acquisition_epoch,
                str(run_id),
                "workspace",
                canonical_json(scope.model_dump(mode="json")),
                "invocation",
                "active",
                None,
                resource_ref,
                observed_at,
                observed_at,
            ),
        )
        connection.execute("PRAGMA user_version = 3")
        connection.commit()


def test_exact_m3_terminal_effect_retains_its_pre_mode_request_hash(
    tmp_path: Path,
) -> None:
    database = tmp_path / "m3-terminal-effect.db"
    run_id = RunId("run-m3-effect")
    manifest, manifest_json = historical_manifest_v1(sealed_test_manifest())
    manifest_hash = manifest.manifest_hash
    path = ExecutionPath(scope=ScopePath(segments=("m3", "effect")))
    key, request = effect_request_before_m6(
        run_id=run_id,
        manifest_hash=manifest_hash,
        path=path,
        kind="announce",
        subject={"title": "written before effect modes"},
    )
    receipt = historical_effect_receipt(request)
    request_json = historical_json(request)
    receipt_json = historical_json(receipt)
    with sqlite3.connect(database) as connection:
        connection.executescript(M3_SCHEMA)
        connection.execute(
            "INSERT INTO manifests VALUES (?, ?)",
            (str(manifest_hash), manifest_json),
        )
        connection.execute(
            "INSERT INTO runs"
            " (run_id, manifest_hash, input_hash, inputs_json, status, created_at,"
            " owner_id, owner_epoch, owner_pid, heartbeat_at, lease_expires_at,"
            " next_event_seq, cancel_requested)"
            " VALUES (?, ?, ?, '{}', 'running', ?, ?, 1, 123, ?, ?, 2, 0)",
            (
                str(run_id),
                str(manifest_hash),
                str(manifest.input_hash),
                "2026-01-03T00:00:00+00:00",
                "m3-effect-owner",
                "2026-01-03T00:00:01+00:00",
                "2026-01-03T00:01:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO events VALUES (?, 1, 'RunStarted', NULL, ?, ?)",
            (
                str(run_id),
                canonical_json({"inputs": {}}),
                "2026-01-03T00:00:01+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO events VALUES (?, 2, 'EffectCommitted', ?, ?, ?)",
            (
                str(run_id),
                canonical_json(path.model_dump(mode="json")),
                canonical_json({"kind": "announce"}),
                "2026-01-03T00:00:03+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO effects VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(key),
                str(run_id),
                request_json,
                receipt_json,
                "2026-01-03T00:00:02+00:00",
                "2026-01-03T00:00:02+00:00",
            ),
        )
        connection.execute("PRAGMA user_version = 3")
        connection.commit()

    migrated = SqliteJournal(database)
    observed = migrated.receipt_for(key)
    assert observed is not None
    assert observed.request_hash == digest("effect-request", 1, request)
    [started, committed] = migrated.events(run_id)
    assert started.kind == "RunStarted"
    assert committed.kind == "EffectCommitted"
    assert committed.path == path
    assert committed.payload == {"kind": "announce"}
    with sqlite3.connect(database) as connection:
        retained = connection.execute(
            "SELECT request_json, receipt_json FROM effects WHERE idempotency_key = ?",
            (str(key),),
        ).fetchone()
        seal = connection.execute(
            "SELECT terminal_fact_hash FROM legacy_effect_seals WHERE idempotency_key = ?",
            (str(key),),
        ).fetchone()
        outcome_provenance = connection.execute(
            "SELECT fact_key FROM durable_fact_seals WHERE family = ?",
            (LEGACY_EFFECT_OUTCOME_FACT_FAMILY,),
        ).fetchone()
    assert retained == (request_json, receipt_json)
    assert seal is not None
    assert outcome_provenance is not None

    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE family = ? AND fact_key = ?",
            (LEGACY_EFFECT_OUTCOME_FACT_FAMILY, outcome_provenance[0]),
        )
        connection.commit()
    with pytest.raises(JournalDamaged, match="current effect outcome event"):
        SqliteJournal(database)


def test_exact_m3_content_derived_promotion_retains_its_historical_edge(
    tmp_path: Path,
) -> None:
    """M3 derived identity did not yet bind the promoted baseline."""

    database = tmp_path / "m3-content-derived-promotion.db"
    definition, _implementation = atomic(
        "migration/m3-promotion",
        (ISSUE,),
        (BRIEF,),
        triage_impl,
    )
    version = definition.content_hash()
    unrelated_baseline = digest("component", 1, {"m3": "unrelated-baseline"})
    draft = AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component=definition.name,
            version=version,
            baseline_version=unrelated_baseline,
        ),
        checks=(
            CheckResult(
                name="m3-policy",
                status="passed",
                detail="M3 checked target but not the full pointer edge",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest("check-set", 1, {"policy": "m3"}),
        manifest_hash=digest("manifest", 1, {"policy": "m3"}),
    )
    attestation = Attestation(
        attestation_id=attestation_id_for(draft),
        **draft.model_dump(mode="python"),
        created_by_run=None,
        created_at="2026-01-03T00:00:00+00:00",
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(M3_SCHEMA)
        connection.execute(
            "INSERT INTO components"
            " (name, content_hash, definition_json, registered_at)"
            " VALUES (?, ?, ?, ?)",
            (
                definition.name,
                str(version),
                definition.model_dump_json(),
                "2026-01-03T00:00:00+00:00",
            ),
        )
        connection.execute(
            "INSERT INTO attestations VALUES (?, ?)",
            (attestation.attestation_id, attestation.model_dump_json()),
        )
        connection.execute(
            "INSERT INTO promotions"
            " (component, channel, from_version, to_version, attestation_id,"
            " actor, source_run, created_at) VALUES (?, 'stable', NULL, ?, ?, ?, NULL, ?)",
            (
                definition.name,
                str(version),
                attestation.attestation_id,
                "m3:operator",
                "2026-01-03T00:00:01+00:00",
            ),
        )
        connection.execute("PRAGMA user_version = 3")
        connection.commit()

    migrated = SqliteJournal(database)
    assert migrated.load_attestation(attestation.attestation_id) == attestation
    promotion = migrated.promotion_for_attestation(attestation.attestation_id)
    assert promotion is not None
    assert promotion.from_version is None
    assert promotion.to_version == version
    assert migrated.snapshot().stable_version(definition.name) == version
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT family FROM durable_fact_seals WHERE selector = ?"
            " AND family LIKE '%promotion%'",
            (attestation.attestation_id,),
        ).fetchone() == ("legacy_promotion_pre_v7",)


def test_m3_migration_never_treats_a_derived_orphan_as_random_id_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "m3-orphan-derived-attestation.db"
    version = digest("component", 1, {"m3": "orphan-proof"})
    draft = AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component="migration/m3-orphan",
            version=version,
            baseline_version=None,
        ),
        checks=(
            CheckResult(
                name="m3-run-check",
                status="passed",
                detail="the run that observed this fact must remain retained",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest("check-set", 1, {"m3": "orphan"}),
        manifest_hash=digest("manifest", 1, {"m3": "orphan"}),
    )
    attestation = Attestation(
        attestation_id=attestation_id_for(draft),
        **draft.model_dump(mode="python"),
        created_by_run=RunId("run-m3-missing-creator"),
        created_at="2026-01-03T00:00:00+00:00",
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(M3_SCHEMA)
        connection.execute(
            "INSERT INTO attestations VALUES (?, ?)",
            (attestation.attestation_id, attestation.model_dump_json()),
        )
        connection.execute("PRAGMA user_version = 3")
        connection.commit()

    with pytest.raises(JournalDamaged, match="creator run world"):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (6,)


def test_v3_lease_rows_become_empty_frame_execution_paths(tmp_path: Path) -> None:
    db = tmp_path / "m3.db"
    scope = ScopePath(segments=("old-run", "writer"))
    resource_ref = '{"candidate_ref":"refs/candidates/old"}'
    _build_exact_m3_active_lease(
        db,
        run_id=RunId("old-run"),
        lease_id="lease-old",
        scope=scope,
        resource_ref=resource_ref,
    )

    migrated = SqliteJournal(db)
    with sqlite3.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        columns = {row[1] for row in conn.execute("PRAGMA table_info(capability_leases)")}
        assert "scope_json" in columns and "path_json" not in columns
    rows = migrated.capability_leases(RunId("old-run"))
    assert len(rows) == 1
    row = rows[0]
    assert row.lease_id == "lease-old"
    assert row.acquisition_epoch == 7
    assert row.path == ExecutionPath(scope=scope)
    assert row.resource_ref == resource_ref
    assert row.state == "active"


def test_schema_7_never_rederives_a_deleted_legacy_lease_seal(
    tmp_path: Path,
) -> None:
    db = tmp_path / "m3-erased-lease-seal.db"
    scope = ScopePath(segments=("old-run", "writer"))
    _build_exact_m3_active_lease(
        db,
        run_id=RunId("old-run"),
        lease_id="lease-old",
        scope=scope,
        resource_ref="workspace/legacy",
    )

    SqliteJournal(db)
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE capability_leases SET resource_ref = 'workspace/forged'")
        conn.execute("DROP TABLE legacy_capability_lease_seals")

    with pytest.raises(
        JournalDamaged,
        match=r"durable tables are missing.*legacy_capability_lease_seals",
    ):
        SqliteJournal(db)

    with sqlite3.connect(db) as conn:
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table'"
                " AND name = 'legacy_capability_lease_seals'"
            ).fetchone()
            is None
        )


def test_schema_7_reopen_refuses_one_missing_legacy_lease_seal(
    tmp_path: Path,
) -> None:
    database = tmp_path / "m3-missing-one-lease-seal.db"
    _build_exact_m3_active_lease(
        database,
        run_id=RunId("old-run"),
        lease_id="lease-old",
        scope=ScopePath(segments=("old-run", "writer")),
        resource_ref="workspace/legacy",
    )
    SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM legacy_capability_lease_seals"
            " WHERE lease_id = 'lease-old' AND acquisition_epoch = 7"
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="lease seal inventory"):
        SqliteJournal(database)


def test_v3_migration_refuses_an_orphan_legacy_lease_seal_atomically(
    tmp_path: Path,
) -> None:
    database = tmp_path / "m3-orphan-lease-seal.db"
    scope = ScopePath(segments=("old-run", "writer"))
    with sqlite3.connect(database) as connection:
        connection.executescript(M3_SCHEMA)
        connection.execute(
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
                "workspace/legacy",
                "2026-01-01T00:00:00+00:00",
                "2026-01-01T00:00:00+00:00",
            ),
        )
        connection.execute(
            "CREATE TABLE legacy_capability_lease_seals ("
            " lease_id TEXT NOT NULL, acquisition_epoch INTEGER NOT NULL,"
            " run_id TEXT NOT NULL, base_hash TEXT NOT NULL,"
            " initial_lifecycle_json TEXT NOT NULL,"
            " PRIMARY KEY (lease_id, acquisition_epoch))"
        )
        connection.execute(
            "INSERT INTO legacy_capability_lease_seals VALUES (?, ?, ?, ?, ?)",
            (
                "lease-orphan",
                1,
                "orphan-run",
                str(digest("legacy-lease-base", 1, {"orphan": True})),
                canonical_json(
                    {
                        "state": "active",
                        "disposition": None,
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
            ),
        )
        connection.execute("PRAGMA user_version = 3")
        connection.commit()

    with pytest.raises(JournalDamaged, match="lease seal inventory"):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        # M3->M6 are independently committed ladder rungs; the failing v7 rung
        # rolls back its inferred primary seal and never publishes version 7.
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
        assert connection.execute(
            "SELECT COUNT(*) FROM legacy_capability_lease_seals"
        ).fetchone() == (1,)


def test_a_v3_lease_transitions_from_its_sealed_initial_lifecycle(
    tmp_path: Path,
) -> None:
    db = tmp_path / "m3-transition.db"
    run_id = RunId("old-transition-run")
    scope = ScopePath(segments=("old-transition",))
    _build_exact_m3_active_lease(
        db,
        run_id=run_id,
        lease_id="lease-preserved-v3-identity",
        scope=scope,
        resource_ref="workspace/legacy",
    )

    migrated = SqliteJournal(db)
    run_lease = migrated.claim_run(
        run_id,
        owner_id="post-migration-owner",
        ttl_s=60,
    )
    migrated.transition_capability_lease(
        run_lease,
        lease_id="lease-preserved-v3-identity",
        acquisition_epoch=7,
        expected=frozenset({"active"}),
        target="closed",
        disposition="discarded",
    )

    [stored] = migrated.capability_leases(run_id)
    assert stored.state == "closed"
    assert stored.disposition == "discarded"
    transition = migrated.events(run_id)[-1]
    assert transition.kind == "LeaseTransition"
    assert transition.payload is not None
    assert transition.payload["legacy_base_hash"].startswith("sha256:")

    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE capability_leases SET updated_at = ? WHERE lease_id = ?",
            ("2026-02-02T00:00:00+00:00", stored.lease_id),
        )
        conn.commit()
    with pytest.raises(JournalDamaged, match="sealed history"):
        migrated.capability_leases(run_id)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "UPDATE capability_leases SET updated_at = ? WHERE lease_id = ?",
            (transition.created_at.isoformat(), stored.lease_id),
        )
        conn.commit()

    with sqlite3.connect(db) as conn:
        payload = json.loads(
            conn.execute("SELECT payload FROM events WHERE kind = 'LeaseTransition'").fetchone()[0]
        )
        payload["legacy_base_hash"] = str(digest("legacy-lease-base", 1, {"forged": 1}))
        conn.execute(
            "UPDATE events SET payload = ? WHERE kind = 'LeaseTransition'",
            (json.dumps(payload),),
        )
        conn.commit()

    with pytest.raises(JournalDamaged, match="positive seal"):
        migrated.capability_leases(run_id)


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
        version = system._register(definition, impl)
        system._promote_initial(component=definition.name, version=version)
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
        await system._resume_direct(run_id)
    journal.fault_probe = lambda name: None
    clock.advance(LEASE_TTL_S + 1)

    resumed = await system._resume_direct(run_id)
    assert resumed.status is RunStatus.SUCCEEDED
    assert len(executor.calls) == 1  # triage checkpoint restored after the crash
    assert len(effect.executions) == 1

    # Reproduction reserializes the v1 model with additive defaults. The
    # existing manifest row omits resolved_loops; semantic comparison accepts
    # the equivalent bytes and refuses any real identity change.
    reproduced = await system._reproduce_direct(
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
