"""Atomic admission fences for one exact durable run attempt."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from constructicon.core.address import RunId
from constructicon.core.run import RunAttemptSuperseded, RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import LEASE_TTL_S
from tests.run_worlds import create_test_run, sealed_test_manifest, start_test_run

RUN = RunId("run-attempt-fence")
_INPUTS = {"attempt_fence": True}
_MANIFEST = sealed_test_manifest(_INPUTS)
MANIFEST_HASH = _MANIFEST.manifest_hash
INPUT_HASH = _MANIFEST.input_hash


def _create_run(journal: SqliteJournal, run_id: RunId = RUN) -> None:
    create_test_run(journal, run_id, inputs=_INPUTS)


def _claim_projection(db_path: Path, run_id: RunId = RUN) -> tuple[object, ...]:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT status, next_event_seq, owner_id, owner_epoch,"
            " lease_expires_at, heartbeat_at, owner_pid FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    assert row is not None
    return tuple(row)


def test_event_sequence_mismatch_is_atomic_and_matching_fence_claims(
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "journal.db"
    _create_run(journal)
    first = start_test_run(
        journal,
        RUN,
        owner_id="attempt-one",
        ttl_s=LEASE_TTL_S,
    )
    event = journal.append_event(first, "AttemptObserved")
    assert event.seq == 2
    journal.release_run(first)
    before = _claim_projection(db_path)

    with pytest.raises(RunAttemptSuperseded, match="sequence expected 1, observed 2"):
        journal.claim_run(
            RUN,
            owner_id="stale-candidate",
            ttl_s=LEASE_TTL_S,
            expected_event_seq=1,
            expected_statuses=frozenset({RunStatus.RUNNING}),
        )

    assert _claim_projection(db_path) == before
    matching = journal.claim_run(
        RUN,
        owner_id="matching-candidate",
        ttl_s=LEASE_TTL_S,
        expected_event_seq=2,
        expected_statuses=frozenset({RunStatus.RUNNING}),
    )
    assert matching.owner_id == "matching-candidate"
    assert matching.epoch == first.epoch + 1


def test_status_mismatch_with_same_sequence_changes_no_owner_or_epoch(
    journal: SqliteJournal,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "journal.db"
    _create_run(journal)
    before = _claim_projection(db_path)

    with pytest.raises(
        RunAttemptSuperseded,
        match=r"status expected one of \[failed\], observed pending",
    ):
        journal.claim_run(
            RUN,
            owner_id="wrong-status",
            ttl_s=LEASE_TTL_S,
            expected_event_seq=0,
            expected_statuses=frozenset({RunStatus.FAILED}),
        )

    assert _claim_projection(db_path) == before
    matching = journal.claim_run(
        RUN,
        owner_id="right-status",
        ttl_s=LEASE_TTL_S,
        expected_event_seq=0,
        expected_statuses=frozenset({RunStatus.PENDING}),
    )
    assert matching.owner_id == "right-status"
    assert matching.epoch == 1
