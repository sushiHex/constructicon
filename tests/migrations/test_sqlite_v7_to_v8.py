"""Actual old writers and admitted opaque shapes cross one atomic provenance rung."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.manifest import CapabilityLease
from constructicon.core.workspace import lease_id_for
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.run_worlds import create_test_run

RUN = RunId("run-historical-capabilities")
FIXTURES = Path(__file__).parents[1] / "fixtures" / "capability_history"


def historical_database(database: Path, name: str) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript((FIXTURES / name).read_text(encoding="utf-8"))


def retained_bytes(database: Path) -> dict[str, list[tuple[object, ...]]]:
    with sqlite3.connect(database) as connection:
        return {
            table: connection.execute(
                "SELECT "
                + (
                    "run_id, manifest_hash, input_hash, inputs_json, status, created_at,"
                    " owner_id, owner_epoch, owner_pid, heartbeat_at, lease_expires_at,"
                    " next_event_seq, cancel_requested"
                    if table == "runs"
                    else "*"
                )
                + f" FROM {table} ORDER BY 1, 2"
            ).fetchall()
            for table in ("runs", "manifests", "events", "capability_leases")
        }


def test_actual_schema7_writer_lost_transitions_receive_exact_migration_witnesses(
    tmp_path: Path,
) -> None:
    database = tmp_path / "actual-v7.db"
    historical_database(database, "schema7-lost-transitions.sql")
    before = retained_bytes(database)
    journal = SqliteJournal(database)
    assert SCHEMA_VERSION == 8
    assert retained_bytes(database) == before
    assert journal.capability_leases(RUN)[0].state == "lost"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM capability_accounting_eras").fetchone() == (
            2,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals WHERE family = 'capability_lost_pre_v8'"
        ).fetchone() == (2,)
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals"
            " WHERE family = 'capability_initial_lost_pre_v8'"
        ).fetchone() == (0,)
    assert SqliteJournal(database).capability_leases(RUN) == journal.capability_leases(RUN)


def test_actual_schema6_writer_initial_lifecycle_receives_only_initial_lost_witness(
    tmp_path: Path,
) -> None:
    database = tmp_path / "actual-v6.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    before = retained_bytes(database)
    journal = SqliteJournal(database)
    assert SCHEMA_VERSION == 8
    assert retained_bytes(database) == before
    assert {row.state for row in journal.capability_leases(RUN)} == {"active", "closed", "lost"}
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals WHERE family = 'capability_lost_pre_v8'"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals"
            " WHERE family = 'capability_initial_lost_pre_v8'"
        ).fetchone() == (1,)
    assert len(SqliteJournal(database).capability_leases(RUN)) == 3


@pytest.mark.parametrize("erase_era", (False, True))
@pytest.mark.parametrize("state", ("active", "closed", "lost"))
def test_eventless_legacy_erasure_refuses_even_with_valid_event_extent(
    tmp_path: Path,
    erase_era: bool,
    state: str,
) -> None:
    database = tmp_path / f"eventless-{state}-{erase_era}.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    # Explicit reader-admitted synthetic shape; not attributed to the old writer.
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM events WHERE kind = 'LeaseAcquired'")
        connection.execute("UPDATE runs SET next_event_seq = 1 WHERE run_id = ?", (RUN,))
    journal = SqliteJournal(database)
    rows = journal.capability_leases(RUN)
    assert len(rows) == 3
    selected = next(row for row in rows if row.state == state)
    assert len(SqliteJournal(database).capability_leases(RUN)) == 3
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM capability_leases WHERE lease_id = ?", (selected.lease_id,))
        connection.execute(
            "DELETE FROM legacy_capability_lease_seals WHERE lease_id = ?",
            (selected.lease_id,),
        )
        # Remove the separate initial-lost witness too: retained era/run evidence must suffice.
        if state == "lost":
            connection.execute(
                "DELETE FROM durable_fact_seals WHERE family = 'capability_initial_lost_pre_v8'"
            )
        if erase_era:
            connection.execute("DELETE FROM capability_accounting_eras WHERE run_id = ?", (RUN,))
            connection.execute(
                "DELETE FROM durable_fact_seals WHERE family = 'capability_accounting_era'"
                " AND fact_key = ?",
                (RUN,),
            )
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ?", (RUN,)
        ).fetchone() == (1,)
    with pytest.raises(JournalDamaged, match=r"accounting|inventory|era|lost"):
        journal.capability_leases(RUN)
    with pytest.raises(JournalDamaged, match=r"accounting|inventory|era|lost"):
        SqliteJournal(database)


def test_migration_floor_digest_survives_later_closure_and_new_acquisition(tmp_path: Path) -> None:
    database = tmp_path / "historical-floor.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    journal = SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT floor, inventory_hash FROM capability_accounting_eras WHERE run_id = ?",
            (RUN,),
        ).fetchone()
    original = journal.capability_leases(RUN)
    active = next(row for row in original if row.state == "active")
    worker = journal.claim_run(RUN, owner_id="later-worker", ttl_s=30)
    journal.transition_capability_lease(
        worker,
        lease_id=active.lease_id,
        acquisition_epoch=active.acquisition_epoch,
        expected=frozenset({"active"}),
        target="closed",
        disposition="released",
    )
    path = ExecutionPath(scope=ScopePath(segments=("post-migration",)))
    later = CapabilityLease(
        lease_id=lease_id_for(RUN, path, "workspace"),
        acquisition_epoch=worker.epoch,
        run_id=RUN,
        binding_id="workspace",
        path=path,
        state="active",
    )
    journal.record_capability_lease(worker, later)
    try:
        changed = journal.capability_leases(RUN)
        reopened = SqliteJournal(database).capability_leases(RUN)
    except JournalDamaged as damage:
        pytest.fail(f"legitimate post-floor closure/acquisition was refused: {damage}")
    assert changed != original
    assert len(changed) == 4
    assert next(row for row in changed if row.lease_id == active.lease_id).state == "closed"
    assert later in changed
    assert reopened == changed
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT floor, inventory_hash FROM capability_accounting_eras WHERE run_id = ?",
                (RUN,),
            ).fetchone()
            == before
        )


def test_current_worker_cannot_reactivate_historical_lost(tmp_path: Path) -> None:
    database = tmp_path / "historical-reactivate.db"
    historical_database(database, "schema7-lost-transitions.sql")
    journal = SqliteJournal(database)
    lost = journal.capability_leases(RUN)[0]
    worker = journal.claim_run(RUN, owner_id="current-worker", ttl_s=30)
    before = journal.run_head(RUN)
    with pytest.raises(ContractViolation, match="lost"):
        journal.transition_capability_lease(
            worker,
            lease_id=lost.lease_id,
            acquisition_epoch=lost.acquisition_epoch,
            expected=frozenset({"lost"}),
            target="active",
        )
    assert journal.capability_leases(RUN) == [lost]
    assert journal.run_head(RUN) == before


def test_deleted_historical_lost_witness_is_not_reminted_on_open(tmp_path: Path) -> None:
    database = tmp_path / "deleted-witness.db"
    historical_database(database, "schema7-lost-transitions.sql")
    journal = SqliteJournal(database)
    assert journal.capability_leases(RUN)[0].state == "lost"
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM durable_fact_seals WHERE family = 'capability_lost_pre_v8'")
    with pytest.raises(JournalDamaged, match=r"lost|witness"):
        journal.capability_leases(RUN)
    with pytest.raises(JournalDamaged, match=r"lost|witness"):
        SqliteJournal(database)


def test_new_current_creation_cannot_be_classified_as_migration(tmp_path: Path) -> None:
    database = tmp_path / "new-current.db"
    journal = SqliteJournal(database)
    create_test_run(journal, RUN)
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT source, floor FROM capability_accounting_eras WHERE run_id = ?",
            (RUN,),
        ).fetchone() == ("schema8-creation", 0)
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals WHERE family LIKE 'capability%pre_v8'"
        ).fetchone() == (0,)


@pytest.mark.parametrize("seam", ("before_version", "after_commit"))
def test_real_process_crash_publishes_complete_migration_or_none(tmp_path: Path, seam: str) -> None:
    database = tmp_path / f"migration-crash-{seam}.db"
    historical_database(database, "schema7-lost-transitions.sql")
    before = retained_bytes(database)
    program = """
import os
import sys
from constructicon.substrate.journal._sqlite_schema import _SqliteSchemaMixin
from constructicon.substrate.journal.sqlite import SqliteJournal
original = _SqliteSchemaMixin._migrate_m7_to_m8
def interrupted(self, connection):
    def probe(name):
        if name == 'capability_migration.' + sys.argv[2]:
            os._exit(91)
    self.fault_probe = probe
    original(self, connection)
_SqliteSchemaMixin._migrate_m7_to_m8 = interrupted
SqliteJournal(sys.argv[1])
raise AssertionError('crash seam was not reached')
"""
    result = subprocess.run(
        [sys.executable, "-c", program, str(database), seam],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 91, result.stderr.decode("utf-8", errors="replace")
    with sqlite3.connect(database) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        era_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE name = 'capability_accounting_eras'"
        ).fetchone()
    assert version == (7 if seam == "before_version" else 8)
    assert bool(era_table) is (seam == "after_commit")
    assert retained_bytes(database) == before
    recovered = SqliteJournal(database)
    assert recovered.capability_leases(RUN)[0].state == "lost"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM capability_accounting_eras").fetchone() == (
            2,
        )


def test_losing_migration_opener_preserves_winner_creation_eras(tmp_path: Path) -> None:
    database = tmp_path / "migration-race.db"
    historical_database(database, "schema7-lost-transitions.sql")
    winner = SqliteJournal(database)
    new_run = RunId("winner-created-current")
    create_test_run(winner, new_run)
    with sqlite3.connect(database) as connection:
        before = connection.execute(
            "SELECT * FROM capability_accounting_eras ORDER BY run_id"
        ).fetchall()
    connection = winner._connect()
    try:
        winner._migrate_m7_to_m8(connection)
    finally:
        connection.close()
    with sqlite3.connect(database) as connection:
        assert (
            connection.execute(
                "SELECT * FROM capability_accounting_eras ORDER BY run_id"
            ).fetchall()
            == before
        )
    assert SqliteJournal(database).capability_leases(new_run) == []


def test_current_paths_cannot_mint_historical_capability_provenance(tmp_path: Path) -> None:
    from constructicon.substrate.journal._sqlite_capability_provenance import (
        mint_migrated_capability_provenance,
    )

    database = tmp_path / "no-current-mint.db"
    journal = SqliteJournal(database)
    with journal._txn() as connection, pytest.raises(JournalDamaged, match="migration-only"):
        mint_migrated_capability_provenance(connection, {})
    create_test_run(journal, RUN)
    assert SqliteJournal(database).capability_leases(RUN) == []


def test_deleted_initial_lost_witness_is_not_inferred_from_the_legacy_seal(tmp_path: Path) -> None:
    database = tmp_path / "initial-lost-witness.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    journal = SqliteJournal(database)
    assert {lease.state for lease in journal.capability_leases(RUN)} == {"active", "closed", "lost"}
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE family = 'capability_initial_lost_pre_v8'"
        )
    with pytest.raises(JournalDamaged, match="capability_initial_lost_pre_v8"):
        journal.capability_leases(RUN)
    with pytest.raises(JournalDamaged, match="capability_initial_lost_pre_v8"):
        SqliteJournal(database)


def test_invalid_old_inventory_is_not_blessed_by_migration(tmp_path: Path) -> None:
    database = tmp_path / "invalid-old.db"
    historical_database(database, "schema7-lost-transitions.sql")
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM durable_fact_seals WHERE family = 'event'")
    with pytest.raises(JournalDamaged, match="seal"):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (7,)
        assert (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'capability_accounting_eras'"
            ).fetchone()
            is None
        )


def test_accounting_cuts_require_positive_era_and_the_recorded_floor(tmp_path: Path) -> None:
    from constructicon.substrate.journal._sqlite_capability_provenance import (
        validate_accounting_run,
    )
    from constructicon.substrate.journal._sqlite_execution import (
        validate_capability_lease_inventory,
    )

    database = tmp_path / "accounting-cuts.db"
    historical_database(database, "schema7-lost-transitions.sql")
    journal = SqliteJournal(database)
    new_run = RunId("current-zero-cut")
    create_test_run(journal, new_run)
    with journal._read() as connection:
        histories = validate_capability_lease_inventory(connection, require_provenance=True)
        era = validate_accounting_run(connection, RUN, histories[RUN])
        assert era.floor == 5
        assert (
            validate_accounting_run(
                connection,
                RUN,
                histories[RUN],
                through_event_seq=5,
            )
            == era
        )
        assert (
            validate_accounting_run(
                connection,
                new_run,
                [],
                through_event_seq=0,
            ).source
            == "schema8-creation"
        )
        for cut in (0, 4, 6):
            with pytest.raises(ContractViolation, match="cut"):
                validate_accounting_run(connection, RUN, histories[RUN], through_event_seq=cut)


def test_current_legacy_event_cannot_downgrade_to_opaque_history(tmp_path: Path) -> None:
    database = tmp_path / "legacy-downgrade.db"
    historical_database(database, "schema6-initial-lifecycle.sql")
    journal = SqliteJournal(database)
    active = next(row for row in journal.capability_leases(RUN) if row.state == "active")
    worker = journal.claim_run(RUN, owner_id="current-worker", ttl_s=30)
    journal.append_event(
        worker,
        "LeaseTransition",
        payload={
            "lease_id": active.lease_id,
            "acquisition_epoch": active.acquisition_epoch,
            "from": "active",
            "to": "closed",
            "disposition": "released",
        },
    )
    with pytest.raises(JournalDamaged, match="opaque historical"):
        journal.capability_leases(RUN)
    with pytest.raises(JournalDamaged, match="opaque historical"):
        SqliteJournal(database)


def test_lost_witness_cannot_lie_above_a_rewritten_migration_floor(tmp_path: Path) -> None:
    from constructicon.substrate.journal._sqlite_capability_provenance import (
        ACCOUNTING_ERA_FAMILY,
        accounting_era_fact_hash,
        accounting_inventory_hash,
        require_accounting_era,
    )
    from constructicon.substrate.journal._sqlite_execution import (
        validate_capability_lease_inventory,
    )
    from tests.durable_seals import reseal_primary_fact

    database = tmp_path / "witness-floor.db"
    historical_database(database, "schema7-lost-transitions.sql")
    journal = SqliteJournal(database)
    with journal._txn() as connection:
        histories = validate_capability_lease_inventory(connection, require_provenance=True)
        run = connection.execute(
            "SELECT r.*, o.origin_json FROM runs r LEFT JOIN run_origins o ON o.run_id=r.run_id"
            " WHERE r.run_id = ?",
            (RUN,),
        ).fetchone()
        era = require_accounting_era(connection, run)
        rewritten = era.model_copy(
            update={
                "floor": 2,
                "inventory_hash": accounting_inventory_hash(histories[RUN], 2),
            }
        )
        connection.execute(
            "UPDATE capability_accounting_eras SET floor = ?, inventory_hash = ? WHERE run_id = ?",
            (rewritten.floor, str(rewritten.inventory_hash), RUN),
        )
        reseal_primary_fact(
            connection,
            family=ACCOUNTING_ERA_FAMILY,
            fact_key=str(RUN),
            fact=accounting_era_fact_hash(rewritten),
        )
    with pytest.raises(JournalDamaged, match="historical floor"):
        journal.capability_leases(RUN)
    with pytest.raises(JournalDamaged, match="historical floor"):
        SqliteJournal(database)


@pytest.mark.parametrize("damage", ("selector", "hash", "key"))
def test_lost_witness_valid_to_valid_rewrite_is_damage(tmp_path: Path, damage: str) -> None:
    from constructicon.core.identity import canonical_json

    database = tmp_path / f"witness-rewrite-{damage}.db"
    historical_database(database, "schema7-lost-transitions.sql")
    journal = SqliteJournal(database)
    assert journal.capability_leases(RUN)[0].state == "lost"
    with sqlite3.connect(database) as connection:
        key = connection.execute(
            "SELECT fact_key FROM durable_fact_seals WHERE family='capability_lost_pre_v8'"
            " ORDER BY fact_key LIMIT 1"
        ).fetchone()[0]
        if damage == "selector":
            value = canonical_json(
                {"run_id": RUN, "event_seq": 3, "lease_id": "foreign-lease", "acquisition_epoch": 1}
            )
        elif damage == "hash":
            value = "sha256:" + "a" * 64
        else:
            value = canonical_json({"run_id": "foreign-run", "seq": 3})
        column = {"selector": "selector", "hash": "fact_hash", "key": "fact_key"}[damage]
        connection.execute(
            f"UPDATE durable_fact_seals SET {column}=?"
            " WHERE family='capability_lost_pre_v8' AND fact_key=?",
            (value, key),
        )
    with pytest.raises(JournalDamaged, match=r"seal|witness|capability_lost_pre_v8"):
        journal.capability_leases(RUN)
    with pytest.raises(JournalDamaged, match=r"seal|witness|capability_lost_pre_v8"):
        SqliteJournal(database)


def test_historical_mint_requires_the_migration_write_transaction(tmp_path: Path) -> None:
    from constructicon.substrate.journal._sqlite_capability_provenance import (
        ERA_DDL,
        mint_migrated_capability_provenance,
    )

    database = tmp_path / "mint-outside-transaction.db"
    historical_database(database, "schema7-lost-transitions.sql")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        for table in ("runs", "events", "capability_leases"):
            connection.execute(f"DELETE FROM {table}")
        connection.execute("DELETE FROM durable_fact_seals WHERE family IN ('run_world', 'event')")
        connection.commit()
        connection.execute(ERA_DDL)
        assert not connection.in_transaction
        with pytest.raises(JournalDamaged, match="migration-only"):
            mint_migrated_capability_provenance(connection, {})
        assert (
            connection.execute("SELECT COUNT(*) FROM capability_accounting_eras").fetchone()[0] == 0
        )
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
    finally:
        connection.close()


def test_schema7_with_published_current_structure_is_not_repaired(tmp_path: Path) -> None:
    from constructicon.substrate.journal._sqlite_capability_provenance import ERA_DDL

    database = tmp_path / "partial-v8-publication.db"
    historical_database(database, "schema7-lost-transitions.sql")
    with sqlite3.connect(database) as connection:
        connection.execute(ERA_DDL)
    with pytest.raises(JournalDamaged, match="already carries current"):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 7
        assert (
            connection.execute("SELECT COUNT(*) FROM capability_accounting_eras").fetchone()[0] == 0
        )
