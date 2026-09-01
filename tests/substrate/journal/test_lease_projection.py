"""Capability leases cross SQLite through one strict relational projection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from tests.conftest import FakeClock
from tests.run_worlds import create_test_run, start_test_run

from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import canonical_json, digest
from constructicon.core.manifest import CapabilityLease
from constructicon.core.run import RunLease
from constructicon.core.workspace import lease_id_for
from constructicon.substrate.journal._sqlite_leases import (
    legacy_lease_base_hash,
    legacy_lease_initial_lifecycle_json,
)
from constructicon.substrate.journal.sqlite import SqliteJournal

RUN_ID = RunId("run-lease-projection")
PATH = ExecutionPath(
    scope=ScopePath(segments=("leased",)),
    iterations=(IterationFrame(loop=ScopePath(segments=("repeat",)), index=1),),
)


def _recorded_lease(
    tmp_path: Path,
    clock: FakeClock,
) -> tuple[SqliteJournal, RunLease, CapabilityLease, Path]:
    database = tmp_path / "lease-projection.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    create_test_run(journal, RUN_ID)
    run_lease = start_test_run(journal, RUN_ID, owner_id="lease-owner")
    capability_lease = CapabilityLease(
        lease_id=lease_id_for(RUN_ID, PATH, "workspace"),
        acquisition_epoch=run_lease.epoch,
        run_id=RUN_ID,
        binding_id="workspace",
        path=PATH,
        state="active",
        resource_ref="workspace/1",
    )
    journal.record_capability_lease(run_lease, capability_lease)
    return journal, run_lease, capability_lease, database


@pytest.mark.parametrize("damage", ("orphan", "current"))
def test_schema_7_reopen_refuses_ineligible_legacy_lease_seals(
    damage: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    _journal, _run_lease, lease, database = _recorded_lease(tmp_path, clock)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        if damage == "current":
            row = connection.execute(
                "SELECT * FROM capability_leases WHERE lease_id = ?",
                (lease.lease_id,),
            ).fetchone()
            assert row is not None
            values = (
                lease.lease_id,
                lease.acquisition_epoch,
                str(lease.run_id),
                str(legacy_lease_base_hash(row)),
                legacy_lease_initial_lifecycle_json(row),
            )
        else:
            values = (
                "lease-orphan-current-schema",
                99,
                "run-orphan-current-schema",
                str(digest("legacy-capability-lease-base", 1, {"orphan": True})),
                canonical_json(
                    {
                        "state": "active",
                        "disposition": None,
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ),
            )
        connection.execute(
            "INSERT INTO legacy_capability_lease_seals"
            " (lease_id, acquisition_epoch, run_id, base_hash, initial_lifecycle_json)"
            " VALUES (?, ?, ?, ?, ?)",
            values,
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="lease seal inventory"):
        SqliteJournal(database, now_fn=clock.now)


def test_schema_7_reopen_refuses_an_acquisition_event_without_its_lease(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    _journal, _run_lease, lease, database = _recorded_lease(tmp_path, clock)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM capability_leases"
            " WHERE lease_id = ? AND acquisition_epoch = ?",
            (lease.lease_id, lease.acquisition_epoch),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"lease event.*no exact retained lease"):
        SqliteJournal(database, now_fn=clock.now)


@pytest.mark.parametrize("column", ("created_at", "updated_at"))
def test_lease_timestamps_use_the_exact_durable_datetime_law(
    column: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, _run_lease, _capability_lease, database = _recorded_lease(
        tmp_path,
        clock,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE capability_leases SET {column} = ?",
            ("2026-01-01 00:00:00+00:00",),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable timestamp"):
        journal.capability_leases(RUN_ID)


@pytest.mark.parametrize("column", ("created_at", "updated_at"))
def test_lease_timestamps_are_bound_to_their_exact_lifecycle_events(
    column: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, _run_lease, _capability_lease, database = _recorded_lease(
        tmp_path,
        clock,
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE capability_leases SET {column} = ?",
            ("2026-02-02T00:00:00+00:00",),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"lifecycle|acquisition event"):
        journal.capability_leases(RUN_ID)


def test_a_lease_epoch_is_never_coerced_from_a_sqlite_real(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, _run_lease, _capability_lease, database = _recorded_lease(
        tmp_path,
        clock,
    )
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE capability_leases SET acquisition_epoch = 1.5")
        connection.commit()

    with pytest.raises(JournalDamaged, match="acquisition epoch"):
        journal.capability_leases(RUN_ID)


def test_lease_relational_text_is_never_normalized_from_a_sqlite_integer(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, _run_lease, _capability_lease, database = _recorded_lease(
        tmp_path,
        clock,
    )
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE capability_leases RENAME TO capability_leases_typed")
        connection.execute(
            "CREATE TABLE capability_leases ("
            " lease_id TEXT NOT NULL, acquisition_epoch INTEGER NOT NULL,"
            " run_id TEXT NOT NULL, binding_id, scope_json TEXT NOT NULL,"
            " lifetime TEXT NOT NULL, state TEXT NOT NULL, disposition TEXT,"
            " resource_ref TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,"
            " PRIMARY KEY (lease_id, acquisition_epoch))"
        )
        connection.execute(
            "INSERT INTO capability_leases SELECT lease_id, acquisition_epoch,"
            " run_id, 7, scope_json, lifetime, state, disposition, resource_ref,"
            " created_at, updated_at FROM capability_leases_typed"
        )
        connection.execute("DROP TABLE capability_leases_typed")
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"binding.*durable text"):
        journal.capability_leases(RUN_ID)


def test_a_lease_scope_must_decode_without_normalizing_its_frame(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, _run_lease, _capability_lease, database = _recorded_lease(
        tmp_path,
        clock,
    )
    with sqlite3.connect(database) as connection:
        raw = json.loads(
            str(connection.execute("SELECT scope_json FROM capability_leases").fetchone()[0])
        )
        raw["iterations"][0]["index"] = True
        connection.execute(
            "UPDATE capability_leases SET scope_json = ?",
            (json.dumps(raw),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.capability_leases(RUN_ID)
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "parsing is not lossless" in str(damaged.value.__cause__)


def test_a_lease_cannot_be_transitioned_through_a_different_run(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, run_lease, capability_lease, database = _recorded_lease(tmp_path, clock)
    fence = journal.max_event_seq(RUN_ID)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE capability_leases SET run_id = 'run-foreign'",
        )
        before = connection.execute("SELECT state, disposition FROM capability_leases").fetchone()
        connection.commit()
    with pytest.raises(JournalDamaged, match="not a valid durable record") as damaged:
        journal.transition_capability_lease(
            run_lease,
            lease_id=capability_lease.lease_id,
            acquisition_epoch=capability_lease.acquisition_epoch,
            expected=frozenset({"active"}),
            target="closed",
            disposition="discarded",
        )
    assert isinstance(damaged.value.__cause__, ValueError)
    assert "not derived from its run" in str(damaged.value.__cause__)

    with sqlite3.connect(database) as connection:
        after = connection.execute("SELECT state, disposition FROM capability_leases").fetchone()
        run_fence = connection.execute(
            "SELECT next_event_seq FROM runs WHERE run_id = ?",
            (str(RUN_ID),),
        ).fetchone()
    assert after == before
    assert run_fence == (fence,)


def test_a_relocated_lease_is_visible_as_damage_from_both_runs(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, _run_lease, _capability_lease, database = _recorded_lease(tmp_path, clock)
    foreign_run = RunId("run-lease-projection-foreign")
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE capability_leases SET run_id = ? WHERE run_id = ?",
            (str(foreign_run), str(RUN_ID)),
        )

    with pytest.raises(JournalDamaged, match="capability lease"):
        journal.capability_leases(RUN_ID)
    with pytest.raises(JournalDamaged, match="capability lease"):
        journal.capability_leases(foreign_run)


def test_an_acquisition_event_cannot_outlive_its_lease_row(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, _run_lease, _capability_lease, database = _recorded_lease(tmp_path, clock)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM capability_leases")
        connection.commit()

    with pytest.raises(JournalDamaged, match="proof without its exact row"):
        journal.capability_leases(RUN_ID)


def test_a_lease_cannot_claim_closure_without_its_transition_event(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, _run_lease, _capability_lease, database = _recorded_lease(tmp_path, clock)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE capability_leases"
            " SET state = 'closed', disposition = 'discarded'"
            " WHERE run_id = ?",
            (str(RUN_ID),),
        )

    with pytest.raises(JournalDamaged, match="lifecycle contradicts its event chain"):
        journal.capability_leases(RUN_ID)


@pytest.mark.parametrize("mismatch", ("run", "epoch"))
def test_recording_a_lease_requires_the_governing_run_fence(
    mismatch: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"lease-writer-{mismatch}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    create_test_run(journal, RUN_ID)
    run_lease = journal.claim_run(RUN_ID, owner_id="lease-owner", ttl_s=30)
    candidate = CapabilityLease(
        lease_id="lease-writer-mismatch",
        acquisition_epoch=(run_lease.epoch + 1 if mismatch == "epoch" else run_lease.epoch),
        run_id=(RunId("run-foreign") if mismatch == "run" else RUN_ID),
        binding_id="workspace",
        path=PATH,
        state="active",
    )

    with pytest.raises(ContractViolation, match="contradicts run lease"):
        journal.record_capability_lease(run_lease, candidate)

    assert journal.capability_leases(RUN_ID) == []
    assert journal.max_event_seq(RUN_ID) == 0
