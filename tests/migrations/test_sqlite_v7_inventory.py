"""Schema-7 reopen validates positive-proof inventories without healing them."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.component import PromotionRecord
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import digest
from constructicon.core.journal import Checkpoint
from constructicon.core.registry import StoredVersion
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import ISSUE, REVIEW, atomic, review_impl
from tests.migrations.test_sqlite_v6_to_v7 import _downgrade_v7_schema_to_v6
from tests.run_attestations import mint_promotion_attestation
from tests.run_worlds import create_test_run, start_test_run


@pytest.mark.parametrize("damage", ("balanced_orphan", "relocated_manifest"))
def test_schema_7_reopen_refuses_family_inexact_fact_seal_inventory(
    damage: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"v7-inventory-{damage}.db"
    journal = SqliteJournal(database)
    manifest = create_test_run(journal, RunId(f"run-v7-inventory-{damage}"))
    with sqlite3.connect(database) as connection:
        if damage == "balanced_orphan":
            # Preserve the global count while replacing one required family
            # member with an unrelated, known-family orphan.
            connection.execute(
                "DELETE FROM durable_fact_seals WHERE family = 'manifest' AND fact_key = ?",
                (str(manifest.manifest_hash),),
            )
            connection.execute(
                "INSERT INTO durable_fact_seals"
                " (family, fact_key, selector, fact_hash) VALUES (?, ?, ?, ?)",
                (
                    "approval",
                    "approval-orphan",
                    "command-orphan",
                    str(digest("durable-fact-seal", 1, {"orphan": True})),
                ),
            )
        else:
            relocated = str(digest("manifest-relocation", 1, {"seal": True}))
            connection.execute(
                "UPDATE durable_fact_seals SET fact_key = ?, selector = ?"
                " WHERE family = 'manifest' AND fact_key = ?",
                (relocated, relocated, str(manifest.manifest_hash)),
            )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"durable fact seal|manifest"):
        SqliteJournal(database)


@pytest.mark.parametrize("family", ("event", "checkpoint"))
def test_schema_7_never_repairs_a_missing_execution_fact_seal(
    family: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"v7-missing-{family}-seal.db"
    journal = SqliteJournal(database)
    run_id = RunId(f"run-v7-missing-{family}-seal")
    manifest = create_test_run(journal, run_id)
    lease = start_test_run(journal, run_id, owner_id="execution-seal-writer")
    journal.record_completion(
        lease,
        Checkpoint(
            run_id=run_id,
            path=ExecutionPath(scope=ScopePath(segments=("execution-seal",))),
            input_hash=manifest.input_hash,
            resolved_version=None,
            outputs={},
        ),
    )
    with sqlite3.connect(database) as connection:
        erased = connection.execute(
            "SELECT fact_key FROM durable_fact_seals WHERE family = ? LIMIT 1",
            (family,),
        ).fetchone()
        assert erased is not None
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE family = ? AND fact_key = ?",
            (family, erased[0]),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"positive seal|seal inventory"):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM durable_fact_seals WHERE family = ? AND fact_key = ?",
                (family, erased[0]),
            ).fetchone()
            is None
        )


def _registry_version(name: str, offset: int) -> StoredVersion:
    definition, _ = atomic(name, (ISSUE,), (REVIEW,), review_impl)
    if offset:
        definition = definition.model_copy(
            update={
                "outputs": (
                    definition.outputs[0].model_copy(
                        update={"schema_hash": f"migration-{offset}"}
                    ),
                )
            }
        )
    return StoredVersion(
        definition=definition,
        content_hash=definition.content_hash(),
        registered_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=offset),
    )


def _promote(
    journal: SqliteJournal,
    *,
    before: StoredVersion | None,
    target: StoredVersion,
    offset: int,
) -> None:
    attestation = mint_promotion_attestation(
        journal,
        component=target.definition.name,
        version=target.content_hash,
        baseline=before.content_hash if before is not None else None,
        proof=f"v7-registry-inventory-{offset}",
    )
    journal.store_promotion(
        PromotionRecord(
            component=target.definition.name,
            channel="stable",
            from_version=before.content_hash if before is not None else None,
            to_version=target.content_hash,
            attestation_id=attestation.attestation_id,
            actor="static:migration",
            source_run=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC)
            + timedelta(seconds=offset),
        )
    )


def test_schema_7_registry_inventory_proves_the_append_only_high_water(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v7-registry-deleted-registration.db"
    journal = SqliteJournal(database)
    version = _registry_version("migration/deleted-registration", 0)
    journal.store_version(version)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM components")
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE family = 'component_registration'"
        )

    with pytest.raises(
        JournalDamaged,
        match="components append-only sequence history is incomplete",
    ):
        SqliteJournal(database)


def test_schema_6_migration_refuses_a_discontinuous_stable_chain_immediately(
    tmp_path: Path,
) -> None:
    database = tmp_path / "v6-discontinuous-promotions.db"
    journal = SqliteJournal(database)
    first = _registry_version("migration/discontinuous", 0)
    second = _registry_version("migration/discontinuous", 1)
    journal.store_version(first)
    journal.store_version(second)
    _promote(journal, before=None, target=first, offset=1)
    _promote(journal, before=first, target=second, offset=2)
    _downgrade_v7_schema_to_v6(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE promotions SET from_version = NULL WHERE promotion_seq = 2"
        )

    with pytest.raises(
        JournalDamaged,
        match="registry cut contains discontinuous promotion history",
    ):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 6
