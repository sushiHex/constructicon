"""Accounting provenance is a positive fact, even for an empty run."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.run_worlds import create_test_run, start_test_run

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import TERMINAL_STATUS_EVENTS, RunStatus
from constructicon.core.workspace import lease_id_for
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal

RUN = RunId("run-capability-provenance")


@pytest.mark.parametrize("target", tuple(TERMINAL_STATUS_EVENTS))
def test_terminal_transition_proves_era_inside_its_staged_event_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: RunStatus,
) -> None:
    from tests.conftest import FakeClock
    from tests.substrate.journal.test_lease_projection import _recorded_lease

    from constructicon.substrate.journal import _sqlite_capability_provenance as provenance

    journal, worker, active, database = _recorded_lease(tmp_path, FakeClock())
    journal.transition_capability_lease(
        worker, lease_id=active.lease_id, acquisition_epoch=active.acquisition_epoch,
        expected=frozenset({"active"}), target="closed", disposition="released",
    )
    original = provenance.require_accounting_era
    observed = []

    def observe(connection, run):
        maximum = connection.execute(
            "SELECT MAX(seq) FROM events WHERE run_id = ?", (worker.run_id,),
        ).fetchone()[0]
        observed.append((run["next_event_seq"], maximum))
        return original(connection, run)

    monkeypatch.setattr(provenance, "require_accounting_era", observe)
    try:
        journal.transition_run(
            worker, expected=frozenset({RunStatus.RUNNING}), target=target,
            event_kind=TERMINAL_STATUS_EVENTS[target],
        )
    except JournalDamaged as damage:
        pytest.fail(f"lawful staged terminal transition was refused: {damage}")
    assert len(observed) == 1
    fence, maximum = observed[0]
    assert fence == maximum + 1
    monkeypatch.undo()
    assert journal.run_state(worker.run_id).status is target
    assert journal.events(worker.run_id)[-1].seq == fence
    assert journal.capability_leases(worker.run_id)[0].state == "closed"
    assert SqliteJournal(database).run_state(worker.run_id).status is target


def test_terminal_transition_refuses_missing_era_without_mutating_its_transaction(
    tmp_path: Path,
) -> None:
    from tests.conftest import FakeClock
    from tests.substrate.journal.test_lease_projection import _recorded_lease

    journal, worker, active, database = _recorded_lease(tmp_path, FakeClock())
    journal.transition_capability_lease(
        worker, lease_id=active.lease_id, acquisition_epoch=active.acquisition_epoch,
        expected=frozenset({"active"}), target="closed", disposition="released",
    )
    with sqlite3.connect(database) as connection:
        before = {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in ("runs", "events", "capability_leases")
        }
        connection.execute("DELETE FROM capability_accounting_eras")
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE family = 'capability_accounting_era'"
        )
    with pytest.raises(JournalDamaged, match="era"):
        journal.transition_run(
            worker, expected=frozenset({RunStatus.RUNNING}), target=RunStatus.CANCELLED,
            event_kind="RunCancelled",
        )
    with sqlite3.connect(database) as connection:
        assert {
            table: connection.execute(f"SELECT * FROM {table}").fetchall()
            for table in before
        } == before


def test_external_accounting_still_requires_complete_committed_event_extent(
    tmp_path: Path,
) -> None:
    from tests.conftest import FakeClock
    from tests.substrate.journal.test_lease_projection import _recorded_lease

    from constructicon.substrate.journal._sqlite_capability_provenance import accounting_run_row

    journal, worker, _active, database = _recorded_lease(tmp_path, FakeClock())
    with sqlite3.connect(database) as connection:
        fence = connection.execute("SELECT next_event_seq FROM runs").fetchone()[0]
        connection.execute("DELETE FROM events WHERE seq = ?", (fence,))
        assert connection.execute("SELECT COUNT(*) FROM events").fetchone()[0] == fence - 1
        assert connection.execute(
            "SELECT COUNT(*) FROM capability_accounting_eras"
        ).fetchone()[0] == 1
    with journal._read() as connection, pytest.raises(JournalDamaged, match=r"event.*fence"):
        accounting_run_row(connection, worker.run_id)
    with pytest.raises(JournalDamaged):
        journal.capability_leases(worker.run_id)
    with pytest.raises(JournalDamaged):
        SqliteJournal(database)


def test_new_runs_co_commit_positive_creation_eras(tmp_path: Path) -> None:
    database = tmp_path / "creation-era.db"
    journal = SqliteJournal(database)
    create_test_run(journal, RUN)
    assert SCHEMA_VERSION == 9
    with sqlite3.connect(database) as connection:
        row = connection.execute("SELECT * FROM capability_accounting_eras").fetchone()
        assert row is not None
        assert row[0] == RUN
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals WHERE family = 'capability_accounting_era'"
        ).fetchone() == (1,)
    assert journal.capability_leases(RUN) == []
    assert SqliteJournal(database).capability_leases(RUN) == []


@pytest.mark.parametrize("disposition", (None, "released"))
def test_current_workers_cannot_mint_lost_facts(
    tmp_path: Path, disposition: str | None,
) -> None:
    database = tmp_path / "worker-lost.db"
    journal = SqliteJournal(database)
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="current-worker")
    path = ExecutionPath(scope=ScopePath(segments=("leased",)))
    acquisition = CapabilityLease(
        lease_id=lease_id_for(RUN, path, "workspace"),
        acquisition_epoch=worker.epoch,
        run_id=RUN,
        binding_id="workspace",
        path=path,
        state="active",
    )
    journal.record_capability_lease(worker, acquisition)
    before = journal.run_head(RUN)
    assert before is not None
    refusal = None
    try:
        journal.transition_capability_lease(
            worker,
            lease_id=acquisition.lease_id,
            acquisition_epoch=acquisition.acquisition_epoch,
            expected=frozenset({"active"}),
            target="lost",
            disposition=disposition,
        )
    except Exception as exc:
        refusal = exc
    assert isinstance(refusal, ContractViolation), refusal
    assert "lost" in str(refusal)
    assert journal.capability_leases(RUN) == [acquisition]
    assert journal.run_head(RUN) == before
    # The refusal does not disable ordinary closure or creation evidence.
    journal.transition_capability_lease(
        worker,
        lease_id=acquisition.lease_id,
        acquisition_epoch=acquisition.acquisition_epoch,
        expected=frozenset({"active"}),
        target="closed",
        disposition="released",
    )
    assert journal.capability_leases(RUN)[0].state == "closed"
    assert SqliteJournal(database).capability_leases(RUN)[0].state == "closed"


@pytest.mark.parametrize("operation", ("point", "close", "acquire"))
def test_current_active_capability_paths_require_positive_era(
    tmp_path: Path,
    operation: str,
) -> None:
    from constructicon.substrate.journal._sqlite_execution import _capability_lease_from_row

    database = tmp_path / "active-missing-era.db"
    journal = SqliteJournal(database)
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="active-worker")
    path = ExecutionPath(scope=ScopePath(segments=("active",)))
    active = CapabilityLease(
        lease_id=lease_id_for(RUN, path, "workspace"),
        acquisition_epoch=worker.epoch,
        run_id=RUN,
        binding_id="workspace",
        path=path,
        state="active",
    )
    journal.record_capability_lease(worker, active)
    assert journal.capability_leases(RUN) == [active]
    with journal._read() as connection:
        row = connection.execute("SELECT * FROM capability_leases").fetchone()
        assert _capability_lease_from_row(row, connection=connection) == active
    with sqlite3.connect(database) as connection:
        before = connection.execute("SELECT * FROM capability_leases").fetchall()
        fence = connection.execute("SELECT owner_epoch, next_event_seq FROM runs").fetchall()
        connection.execute("DELETE FROM capability_accounting_eras")
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE family = 'capability_accounting_era'"
        )
    with pytest.raises(JournalDamaged, match="era"):
        if operation == "point":
            with journal._read() as connection:
                row = connection.execute("SELECT * FROM capability_leases").fetchone()
                _capability_lease_from_row(row, connection=connection)
        elif operation == "close":
            journal.transition_capability_lease(
                worker,
                lease_id=active.lease_id,
                acquisition_epoch=active.acquisition_epoch,
                expected=frozenset({"active"}),
                target="closed",
                disposition="released",
            )
        else:
            other_path = ExecutionPath(scope=ScopePath(segments=("other",)))
            journal.record_capability_lease(
                worker,
                active.model_copy(
                    update={
                        "lease_id": lease_id_for(RUN, other_path, "workspace"),
                        "path": other_path,
                    }
                ),
            )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM capability_leases").fetchall() == before
        assert (
            connection.execute("SELECT owner_epoch, next_event_seq FROM runs").fetchall() == fence
        )


@pytest.mark.parametrize(
    "damage", ("row", "seal", "both", "source", "floor", "inventory", "world", "identity")
)
def test_current_era_damage_is_not_empty_history_or_creation_permission(
    tmp_path: Path,
    damage: str,
) -> None:
    database = tmp_path / f"era-damage-{damage}.db"
    journal = SqliteJournal(database)
    create_test_run(journal, RUN)
    assert journal.capability_leases(RUN) == []
    with sqlite3.connect(database) as connection:
        if damage in {"row", "both"}:
            connection.execute("DELETE FROM capability_accounting_eras")
        if damage in {"seal", "both"}:
            connection.execute(
                "DELETE FROM durable_fact_seals WHERE family = 'capability_accounting_era'"
            )
        if damage == "source":
            connection.execute("UPDATE capability_accounting_eras SET source = 'schema7-migration'")
        if damage == "floor":
            connection.execute("UPDATE capability_accounting_eras SET floor = 1")
        if damage == "inventory":
            connection.execute(
                "UPDATE capability_accounting_eras SET inventory_hash = ?",
                ("sha256:" + "a" * 64,),
            )
        if damage == "world":
            connection.execute(
                "UPDATE capability_accounting_eras SET world_hash = ?",
                ("sha256:" + "b" * 64,),
            )
        if damage == "identity":
            connection.execute("UPDATE capability_accounting_eras SET run_id = 'relocated-run'")
    for operation in (
        lambda: journal.capability_leases(RUN),
        lambda: create_test_run(journal, RUN),
        lambda: SqliteJournal(database),
    ):
        with pytest.raises(JournalDamaged, match=r"accounting|era"):
            operation()
    with sqlite3.connect(database) as connection:
        if damage in {"row", "both"}:
            assert connection.execute(
                "SELECT COUNT(*) FROM capability_accounting_eras"
            ).fetchone() == (0,)


def test_creation_era_and_run_rollback_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from constructicon.substrate.journal import _sqlite_schema

    database = tmp_path / "creation-rollback.db"
    journal = SqliteJournal(database)
    original = _sqlite_schema.seal_run_world
    reached = False

    def interrupted(connection: sqlite3.Connection, row: sqlite3.Row) -> None:
        nonlocal reached
        original(connection, row)
        reached = True
        raise RuntimeError("creation interrupted")

    monkeypatch.setattr(_sqlite_schema, "seal_run_world", interrupted)
    with pytest.raises(RuntimeError, match="creation interrupted"):
        create_test_run(journal, RUN)
    assert reached
    monkeypatch.undo()
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM capability_accounting_eras").fetchone() == (
            0,
        )
    create_test_run(journal, RUN)
    assert SqliteJournal(database).capability_leases(RUN) == []


@pytest.mark.parametrize("erase_row", (False, True))
def test_missing_run_with_retained_accounting_evidence_is_damage(
    tmp_path: Path,
    erase_row: bool,
) -> None:
    database = tmp_path / "orphan-era.db"
    journal = SqliteJournal(database)
    create_test_run(journal, RUN)
    assert journal.capability_leases(RunId("never-created")) == []
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM runs")
        connection.execute("DELETE FROM durable_fact_seals WHERE family = 'run_world'")
        if erase_row:
            connection.execute("DELETE FROM capability_accounting_eras")
    with pytest.raises(JournalDamaged, match="accounting"):
        journal.capability_leases(RUN)


def test_creation_after_commit_retry_keeps_the_exact_era(tmp_path: Path) -> None:
    database = tmp_path / "creation-after-commit.db"
    journal = SqliteJournal(database)
    reached = []

    def crash(name: str) -> None:
        if name == "create.after_commit":
            reached.append(name)
            raise RuntimeError("creation response lost")

    journal.fault_probe = crash
    with pytest.raises(RuntimeError, match="creation response lost"):
        create_test_run(journal, RUN)
    assert reached == ["create.after_commit"]
    recovered = SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        original = connection.execute("SELECT * FROM capability_accounting_eras").fetchall()
    create_test_run(recovered, RUN)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM capability_accounting_eras").fetchall() == original
        assert len(original) == 1


def test_accounting_read_uses_one_snapshot_during_a_committing_acquisition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from constructicon.substrate.journal import _sqlite_capability_provenance as provenance

    database = tmp_path / "accounting-snapshot.db"
    reader = SqliteJournal(database)
    create_test_run(reader, RUN)
    worker = start_test_run(reader, RUN, owner_id="snapshot-worker")
    writer = SqliteJournal(database)
    path = ExecutionPath(scope=ScopePath(segments=("committed-mid-read",)))
    acquisition = CapabilityLease(
        lease_id=lease_id_for(RUN, path, "workspace"),
        acquisition_epoch=worker.epoch,
        run_id=RUN,
        binding_id="workspace",
        path=path,
        state="active",
    )
    original = provenance.accounting_inventory_hash
    committed = False

    def committing(histories, floor):
        nonlocal committed
        if not committed:
            committed = True
            writer.record_capability_lease(worker, acquisition)
        return original(histories, floor)

    monkeypatch.setattr(provenance, "accounting_inventory_hash", committing)
    assert reader.capability_leases(RUN) == []
    assert committed
    assert reader.capability_leases(RUN) == [acquisition]


def test_empty_current_accounting_database_reopens(tmp_path: Path) -> None:
    database = tmp_path / "empty-era-structure.db"
    SqliteJournal(database)
    reopened = SqliteJournal(database)
    assert reopened.capability_leases(RUN) == []
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone() == (0,)
        assert connection.execute("SELECT COUNT(*) FROM capability_accounting_eras").fetchone() == (
            0,
        )
        assert connection.execute("PRAGMA user_version").fetchone() == (9,)


@pytest.mark.parametrize("populated", (False, True))
@pytest.mark.parametrize(
    "damage",
    ("missing-table", "extra-column", "extra-generated-column", "missing-column"),
)
def test_accounting_point_and_open_refuse_missing_or_changed_structure(
    tmp_path: Path,
    damage: str,
    populated: bool,
) -> None:
    database = tmp_path / "era-structure.db"
    journal = SqliteJournal(database)
    if populated:
        create_test_run(journal, RUN)
    with sqlite3.connect(database) as connection:
        if damage == "missing-table":
            connection.execute("DROP TABLE capability_accounting_eras")
        elif damage == "extra-column":
            connection.execute("ALTER TABLE capability_accounting_eras ADD COLUMN extra TEXT")
        elif damage == "extra-generated-column":
            connection.execute(
                "ALTER TABLE capability_accounting_eras"
                " ADD COLUMN extra TEXT GENERATED ALWAYS AS ('extra') VIRTUAL"
            )
        else:
            connection.execute("ALTER TABLE capability_accounting_eras DROP COLUMN inventory_hash")
        before = tuple(connection.iterdump())
    if populated:
        with pytest.raises(JournalDamaged, match="accounting"):
            journal.capability_leases(RUN)
    with pytest.raises(JournalDamaged, match="accounting"):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert tuple(connection.iterdump()) == before


@pytest.mark.parametrize("column", ("run_id", "world_hash", "source", "floor", "inventory_hash"))
def test_empty_accounting_database_refuses_each_changed_column(
    tmp_path: Path, column: str,
) -> None:
    database = tmp_path / f"empty-era-column-{column}.db"
    SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"ALTER TABLE capability_accounting_eras RENAME COLUMN {column} TO changed"
        )
        before = tuple(connection.iterdump())
    with pytest.raises(JournalDamaged, match="accounting"):
        SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        assert tuple(connection.iterdump()) == before
