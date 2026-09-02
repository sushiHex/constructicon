"""Every SQLite projection applies one lossless, typed JSON boundary."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.conftest import ISSUE, REVIEW, atomic, review_impl
from tests.run_attestations import mint_promotion_attestation
from tests.run_worlds import create_test_run, start_test_run

from constructicon.core.address import (
    ExecutionPath,
    IterationFrame,
    RunId,
    ScopePath,
)
from constructicon.core.component import PromotionRecord
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import digest
from constructicon.core.journal import Checkpoint
from constructicon.core.registry import StoredVersion
from constructicon.substrate.journal.sqlite import SqliteJournal


def test_an_event_never_collapses_duplicate_payload_keys(tmp_path: Path) -> None:
    database = tmp_path / "event-json.db"
    journal = SqliteJournal(database)
    run_id = RunId("run-duplicate-event-json")
    create_test_run(journal, run_id)
    start_test_run(journal, run_id, owner_id="duplicate-event-json")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO events (run_id, seq, kind, path_json, payload, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                run_id,
                2,
                "TestEvent",
                None,
                '{"visible":false,"visible":true}',
                datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
            ),
        )
        connection.execute(
            "UPDATE runs SET next_event_seq = 2 WHERE run_id = ?",
            (str(run_id),),
        )

    with pytest.raises(JournalDamaged, match=r"event .* payload is not valid durable JSON"):
        journal.events(run_id)


def test_a_registry_snapshot_never_collapses_duplicate_definition_keys(
    tmp_path: Path,
) -> None:
    database = tmp_path / "registry-json.db"
    journal = SqliteJournal(database)
    definition, _implementation = atomic(
        "durable-json/component",
        (ISSUE,),
        (REVIEW,),
        review_impl,
    )
    journal.store_version(
        StoredVersion(
            definition=definition,
            content_hash=definition.content_hash(),
            registered_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    with sqlite3.connect(database) as connection:
        raw = str(connection.execute("SELECT definition_json FROM components").fetchone()[0])
        connection.execute(
            "UPDATE components SET definition_json = ?",
            ('{"name":"shadow",' + raw[1:],),
        )

    with pytest.raises(
        JournalDamaged,
        match=r"not a valid durable (?:JSON|record)",
    ):
        journal.snapshot()


def test_a_typed_durable_model_never_normalizes_scalar_bytes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "checkpoint-lossless-json.db"
    journal = SqliteJournal(database)
    run_id = RunId("run-lossless-checkpoint")
    path = ExecutionPath(
        scope=ScopePath(segments=("checkpoint",)),
        iterations=(
            IterationFrame(
                loop=ScopePath(segments=("loop",)),
                index=1,
            ),
        ),
    )
    manifest = create_test_run(journal, run_id)
    input_hash = manifest.input_hash
    lease = start_test_run(journal, run_id, owner_id="checkpoint-owner")
    journal.record_completion(
        lease,
        Checkpoint(
            run_id=run_id,
            path=path,
            input_hash=input_hash,
            resolved_version=None,
            outputs={},
        ),
    )
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT checkpoint_json FROM checkpoints WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        assert row is not None
        raw = json.loads(row[0])
        raw["path"]["iterations"][0]["index"] = True
        connection.execute(
            "UPDATE checkpoints SET checkpoint_json = ? WHERE run_id = ?",
            (json.dumps(raw), str(run_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.checkpoint(run_id, path)
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "parsing is not lossless" in str(damaged.value.__cause__)


def _registry_with_promotion(
    database: Path,
) -> tuple[SqliteJournal, StoredVersion, PromotionRecord]:
    journal = SqliteJournal(database)
    definition, _implementation = atomic(
        "durable-json/registry-proof",
        (ISSUE,),
        (REVIEW,),
        review_impl,
    )
    stored = StoredVersion(
        definition=definition,
        content_hash=definition.content_hash(),
        registered_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    journal.store_version(stored)
    authority = mint_promotion_attestation(
        journal,
        component=definition.name,
        version=stored.content_hash,
        baseline=None,
        proof="durable-registry-proof",
    )
    promotion = PromotionRecord(
        component=definition.name,
        channel="stable",
        from_version=None,
        to_version=stored.content_hash,
        attestation_id=authority.attestation_id,
        actor="static:registry-test",
        source_run=None,
        created_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )
    journal.store_promotion(promotion)
    return journal, stored, promotion


def test_a_promotion_prevents_reminting_its_deleted_attestation_without_seals(
    tmp_path: Path,
) -> None:
    database = tmp_path / "promotion-dependent-attestation.db"
    journal, stored, promotion = _registry_with_promotion(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM attestations WHERE attestation_id = ?",
            (promotion.attestation_id,),
        )
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE family IN ('attestation', 'legacy_attestation_m1_m2')"
            " AND fact_key = ?",
            (promotion.attestation_id,),
        )

    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        journal.load_attestation(promotion.attestation_id)
    with pytest.raises(JournalDamaged, match="dependent durable fact"):
        mint_promotion_attestation(
            journal,
            component=stored.definition.name,
            version=stored.content_hash,
            baseline=None,
            proof="durable-registry-proof",
        )

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM attestations").fetchone() == (0,)
        assert connection.execute(
            "SELECT attestation_id FROM promotions WHERE attestation_id = ?",
            (promotion.attestation_id,),
        ).fetchone() == (promotion.attestation_id,)


def test_a_registry_definition_never_normalizes_repeated_set_members(
    tmp_path: Path,
) -> None:
    database = tmp_path / "registry-definition-lossless.db"
    journal, _stored, _promotion = _registry_with_promotion(database)
    with sqlite3.connect(database) as connection:
        raw = json.loads(
            str(connection.execute("SELECT definition_json FROM components").fetchone()[0])
        )
        raw["metadata"]["labels"] = ["duplicate", "duplicate"]
        connection.execute(
            "UPDATE components SET definition_json = ?",
            (json.dumps(raw),),
        )

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.snapshot()
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "not a unique string set" in str(damaged.value.__cause__)


def test_a_registry_definition_must_match_its_relational_name(tmp_path: Path) -> None:
    database = tmp_path / "registry-definition-name.db"
    journal, stored, _promotion = _registry_with_promotion(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE components SET name = ?",
            ("durable-json/redirected",),
        )

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.snapshot()
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "contradicts its relational" in str(damaged.value.__cause__)
    with pytest.raises(JournalDamaged, match="not a valid durable record"):
        journal.store_version(stored)


def test_a_registry_version_identity_must_still_be_an_exact_digest(tmp_path: Path) -> None:
    database = tmp_path / "registry-definition-hash.db"
    journal, _stored, _promotion = _registry_with_promotion(database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE components SET content_hash = 'not-a-digest'")

    with pytest.raises(JournalDamaged, match="not a valid durable digest"):
        journal.snapshot()


def test_a_registry_version_is_selected_and_bound_by_its_definition_hash(
    tmp_path: Path,
) -> None:
    database = tmp_path / "registry-definition-derived-hash.db"
    journal, stored, _promotion = _registry_with_promotion(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE components SET content_hash = ?",
            (str(digest("forged-component-version", 1, {"valid": True})),),
        )

    with pytest.raises(JournalDamaged, match="not a valid durable record") as read_damage:
        journal.snapshot()
    assert read_damage.value.__cause__ is not None
    assert "relational content hash" in str(read_damage.value.__cause__)
    with pytest.raises(JournalDamaged, match="not a valid durable record") as write_damage:
        journal.store_version(stored)
    assert write_damage.value.__cause__ is not None
    assert "relational content hash" in str(write_damage.value.__cause__)


@pytest.mark.parametrize(
    ("table", "column"),
    (("components", "registered_at"), ("promotions", "created_at")),
)
def test_registry_timestamps_use_the_exact_durable_datetime_law(
    tmp_path: Path,
    table: str,
    column: str,
) -> None:
    database = tmp_path / f"registry-time-{table}.db"
    journal, _stored, _promotion = _registry_with_promotion(database)
    with sqlite3.connect(database) as connection:
        # Pydantic accepts the space separator, but it is not what the durable
        # writer emitted and would change a cursor key on round-trip.
        connection.execute(
            f"UPDATE {table} SET {column} = ?",
            ("2026-01-01 00:00:00+00:00",),
        )

    with pytest.raises(JournalDamaged, match="not a valid durable timestamp"):
        journal.snapshot()


@pytest.mark.parametrize("fact", ("registration", "promotion"))
def test_registry_writers_never_reconcile_through_a_damaged_retained_row(
    fact: str,
    tmp_path: Path,
) -> None:
    database = tmp_path / f"registry-writer-{fact}.db"
    journal, stored, promotion = _registry_with_promotion(database)
    with sqlite3.connect(database) as connection:
        if fact == "registration":
            connection.execute("UPDATE components SET registered_at = 'not-a-timestamp'")
        else:
            connection.execute("UPDATE promotions SET created_at = 'not-a-timestamp'")

    with pytest.raises(JournalDamaged, match="not a valid durable timestamp"):
        if fact == "registration":
            journal.store_version(stored)
        else:
            journal.store_promotion(
                promotion.model_copy(
                    update={
                        "attestation_id": mint_promotion_attestation(
                            journal,
                            component=promotion.component,
                            version=promotion.to_version,
                            baseline=stored.content_hash,
                            proof="durable-registry-proof-next",
                        ).attestation_id,
                        "from_version": stored.content_hash,
                    }
                )
            )


def test_a_hidden_nonstable_promotion_is_journal_damage(tmp_path: Path) -> None:
    database = tmp_path / "registry-channel.db"
    journal, _stored, _promotion = _registry_with_promotion(database)
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE promotions SET channel = 'candidate'")

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.snapshot()
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "not 'stable'" in str(damaged.value.__cause__)


@pytest.mark.parametrize(
    ("table", "sequence"),
    (("components", "registration_seq"), ("promotions", "promotion_seq")),
)
def test_registry_sequence_bounds_never_coerce_text_scalars(
    tmp_path: Path,
    table: str,
    sequence: str,
) -> None:
    database = tmp_path / f"registry-sequence-{table}.db"
    journal, _stored, _promotion = _registry_with_promotion(database)
    with sqlite3.connect(database) as connection:
        columns = [str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")]
        connection.execute(f"ALTER TABLE {table} RENAME TO exact_{table}")
        connection.execute(f"CREATE TABLE {table} ({', '.join(columns)})")
        projected = [
            f"CAST({column} AS TEXT)" if column == sequence else column for column in columns
        ]
        connection.execute(
            f"INSERT INTO {table} ({', '.join(columns)}) "
            f"SELECT {', '.join(projected)} FROM exact_{table}"
        )
        connection.execute(f"DROP TABLE exact_{table}")

    with pytest.raises(JournalDamaged, match=f"invalid durable {sequence}"):
        journal.snapshot()
