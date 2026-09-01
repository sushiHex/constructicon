"""The 6-to-7 climb validates complete owner graphs before it commits."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.effect import EffectReceipt, EffectRequest, idempotency_key, request_hash
from constructicon.core.errors import JournalDamaged
from constructicon.core.manifest import CapabilityLease
from constructicon.core.workspace import lease_id_for
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6
from tests.run_worlds import create_test_run, start_test_run


def _assert_migration_refused(database: Path, pattern: str) -> None:
    with pytest.raises(JournalDamaged, match=pattern):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (6,)


def test_v6_migration_refuses_an_event_erased_behind_its_run_fence(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v6-orphan-run-fence.db"
    journal = SqliteJournal(database)
    run_id = RunId("run-v6-orphan-fence")
    create_test_run(journal, run_id)
    start_test_run(journal, run_id, owner_id="v6-orphan-fence-owner")
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM events WHERE run_id = ?", (str(run_id),))
        connection.commit()

    _assert_migration_refused(database, "event sequence history")


def test_v6_migration_refuses_an_outcome_event_without_its_effect(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v6-orphan-effect-outcome.db"
    journal = SqliteJournal(database)
    run_id = RunId("run-v6-orphan-effect")
    manifest = create_test_run(journal, run_id)
    lease = start_test_run(journal, run_id, owner_id="v6-orphan-effect-owner")
    path = ExecutionPath(scope=ScopePath(segments=("effect",)))
    subject = {"announcement": "ship"}
    request = EffectRequest(
        run_id=run_id,
        manifest_hash=manifest.manifest_hash,
        path=path,
        kind="announce",
        subject=subject,
        idempotency_key=idempotency_key(
            manifest.manifest_hash,
            path,
            "announce",
            subject,
        ),
    )
    journal.record_effect_prepared(lease, request)
    journal.record_effect_outcome(
        lease,
        request,
        EffectReceipt(
            request_hash=request_hash(request),
            status="committed",
            external_reference="announcement/1",
            observed_state=subject,
        ),
        "EffectCommitted",
    )
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM effects WHERE idempotency_key = ?",
            (str(request.idempotency_key),),
        )
        connection.commit()

    _assert_migration_refused(database, r"outcome event.*no exact retained effect")


def test_v6_migration_refuses_an_acquisition_event_without_its_lease(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v6-orphan-lease-acquisition.db"
    journal = SqliteJournal(database)
    run_id = RunId("run-v6-orphan-lease")
    create_test_run(journal, run_id)
    run_lease = start_test_run(journal, run_id, owner_id="v6-orphan-lease-owner")
    path = ExecutionPath(scope=ScopePath(segments=("leased",)))
    lease = CapabilityLease(
        lease_id=lease_id_for(run_id, path, "workspace"),
        acquisition_epoch=run_lease.epoch,
        run_id=run_id,
        binding_id="workspace",
        path=path,
        state="active",
        resource_ref="workspace/1",
    )
    journal.record_capability_lease(run_lease, lease)
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM capability_leases"
            " WHERE lease_id = ? AND acquisition_epoch = ?",
            (lease.lease_id, lease.acquisition_epoch),
        )
        connection.commit()

    _assert_migration_refused(database, r"lease event.*no exact retained lease")
