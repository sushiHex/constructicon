"""Every public event read shares one typed, lossless durable projection."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from tests.conftest import FakeClock
from tests.run_worlds import create_test_run, sealed_test_manifest, start_test_run

from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import canonical_json, digest, json_value
from constructicon.substrate.journal.sqlite import SqliteJournal

RUN_ID = RunId("run-event-projection")
_MANIFEST = sealed_test_manifest()
MANIFEST_HASH = _MANIFEST.manifest_hash
INPUT_HASH = digest("inputs", 1, {})
PATH = ExecutionPath(
    scope=ScopePath(segments=("event",)),
    iterations=(IterationFrame(loop=ScopePath(segments=("loop",)), index=1),),
)


def _event(
    tmp_path: Path,
    clock: FakeClock,
) -> tuple[SqliteJournal, Path, int]:
    database = tmp_path / "event-projection.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    create_test_run(journal, RUN_ID)
    lease = start_test_run(journal, RUN_ID, owner_id="event-owner")
    event = journal.append_event(
        lease,
        "ProjectionTest",
        path=PATH,
        payload={"value": 1},
    )
    return journal, database, event.seq


def test_a_pending_run_cannot_acquire_an_event_outside_its_atomic_start(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal = SqliteJournal(tmp_path / "pending-event.db", now_fn=clock.now)
    create_test_run(journal, RUN_ID)
    lease = journal.claim_run(RUN_ID, owner_id="event-owner", ttl_s=30)

    with pytest.raises(ContractViolation, match="event allocation requires status"):
        journal.append_event(lease, "AttemptObserved")

    assert journal.max_event_seq(RUN_ID) == 0
    assert journal.events(RUN_ID) == []


@pytest.mark.parametrize(
    "fault",
    ("created_at", "numeric_created_at", "payload", "path"),
)
def test_exact_and_batch_event_reads_translate_durable_damage(
    fault: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, database, seq = _event(tmp_path, clock)
    with sqlite3.connect(database) as connection:
        if fault in {"created_at", "numeric_created_at"}:
            connection.execute(
                "UPDATE events SET created_at = ? WHERE run_id = ? AND seq = ?",
                (
                    "not-a-timestamp" if fault == "created_at" else "0",
                    str(RUN_ID),
                    seq,
                ),
            )
        elif fault == "payload":
            connection.execute(
                "UPDATE events SET payload = '[]' WHERE run_id = ? AND seq = ?",
                (str(RUN_ID), seq),
            )
        else:
            row = connection.execute(
                "SELECT path_json FROM events WHERE run_id = ? AND seq = ?",
                (str(RUN_ID), seq),
            ).fetchone()
            assert row is not None
            raw_path = json.loads(row[0])
            raw_path["iterations"][0]["index"] = True
            connection.execute(
                "UPDATE events SET path_json = ? WHERE run_id = ? AND seq = ?",
                (canonical_json(json_value(raw_path)), str(RUN_ID), seq),
            )
        connection.commit()

    reads = (
        lambda: journal.event(RUN_ID, seq),
        lambda: journal.events(RUN_ID),
    )
    for read in reads:
        with pytest.raises(JournalDamaged, match=r"event "):
            read()


def test_batch_event_read_refuses_a_non_integer_sequence(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, database, seq = _event(tmp_path, clock)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE events SET seq = 'not-an-integer' WHERE run_id = ? AND seq = ?",
            (str(RUN_ID), seq),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="event sequence history"):
        journal.events(RUN_ID)
    with pytest.raises(JournalDamaged, match="event sequence history"):
        journal.max_event_seq(RUN_ID)


def test_an_event_kind_is_never_normalized_from_a_sqlite_integer(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, database, seq = _event(tmp_path, clock)
    with sqlite3.connect(database) as connection:
        connection.execute("ALTER TABLE events RENAME TO events_typed")
        connection.execute(
            "CREATE TABLE events (run_id TEXT NOT NULL, seq INTEGER NOT NULL,"
            " kind, path_json TEXT, payload TEXT, created_at TEXT NOT NULL,"
            " PRIMARY KEY (run_id, seq))"
        )
        connection.execute(
            "INSERT INTO events SELECT run_id, seq, 7, path_json, payload, created_at"
            " FROM events_typed"
        )
        connection.execute("DROP TABLE events_typed")
        connection.commit()

    with pytest.raises(JournalDamaged, match=r"event .* kind.*durable text"):
        journal.event(RUN_ID, seq)
    with pytest.raises(JournalDamaged, match=r"event .* kind.*durable text"):
        journal.events(RUN_ID)


def test_event_reads_refuse_a_deleted_append_only_fact(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, database, seq = _event(tmp_path, clock)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM events WHERE run_id = ? AND seq = ?",
            (str(RUN_ID), seq),
        )

    reads = (
        lambda: journal.event(RUN_ID, seq),
        lambda: journal.events(RUN_ID),
        lambda: journal.max_event_seq(RUN_ID),
        lambda: journal.run_state(RUN_ID),
    )
    for read in reads:
        with pytest.raises(JournalDamaged, match="event sequence history"):
            read()


def test_event_reads_refuse_a_fact_relocated_between_valid_runs(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, database, seq = _event(tmp_path, clock)
    other = RunId("run-event-projection-other")
    create_test_run(journal, other)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE events SET run_id = ? WHERE run_id = ? AND seq = ?",
            (str(other), str(RUN_ID), seq),
        )

    for run_id in (RUN_ID, other):
        reads = (
            lambda run_id=run_id: journal.events(run_id),
            lambda run_id=run_id: journal.max_event_seq(run_id),
            lambda run_id=run_id: journal.run_record(run_id),
        )
        for read in reads:
            with pytest.raises(JournalDamaged, match="event sequence history"):
                read()


def test_a_valid_event_rewrite_is_refused_by_its_positive_seal(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, database, seq = _event(tmp_path, clock)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE events SET payload = ? WHERE run_id = ? AND seq = ?",
            (canonical_json({"value": 2}), str(RUN_ID), seq),
        )
        connection.commit()

    for read in (journal.run_record, journal.events):
        with pytest.raises(JournalDamaged, match="positive seal"):
            read(RUN_ID)


def test_an_erased_event_and_lowered_fence_leave_an_orphan_seal(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    journal, database, seq = _event(tmp_path, clock)
    assert seq > 1
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM events WHERE run_id = ? AND seq = ?",
            (str(RUN_ID), seq),
        )
        connection.execute(
            "UPDATE runs SET next_event_seq = ? WHERE run_id = ?",
            (seq - 1, str(RUN_ID)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="seal inventory"):
        journal.events(RUN_ID)


def test_a_writer_never_advances_beyond_a_validly_rewritten_event(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "event-writer-seal.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    create_test_run(journal, RUN_ID)
    lease = start_test_run(journal, RUN_ID, owner_id="event-owner")
    first = journal.append_event(lease, "ProjectionTest", payload={"value": 1})
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE events SET payload = ? WHERE run_id = ? AND seq = ?",
            (canonical_json({"value": 2}), str(RUN_ID), first.seq),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.append_event(lease, "MustNotLand")
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ?",
            (str(RUN_ID),),
        ).fetchone() == (first.seq,)
        assert connection.execute(
            "SELECT next_event_seq FROM runs WHERE run_id = ?",
            (str(RUN_ID),),
        ).fetchone() == (first.seq,)
