"""Checkpoint selectors and payloads name one exact invocation fact."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.run_worlds import create_test_run, sealed_test_manifest, start_test_run

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.envelope import Envelope, utc_now
from constructicon.core.errors import JournalDamaged
from constructicon.core.journal import Checkpoint
from constructicon.substrate.journal._sqlite_base import _checkpoint_identity
from constructicon.substrate.journal.sqlite import SqliteJournal

RUN_A = RunId("run-checkpoint-selector-a")
RUN_B = RunId("run-checkpoint-selector-b")
PATH = ExecutionPath(scope=ScopePath(segments=("checkpoint", "selector")))
_INPUTS = {"checkpoint": "selector"}
_MANIFEST = sealed_test_manifest(_INPUTS)
INPUT_HASH = _MANIFEST.input_hash
MANIFEST_HASH = _MANIFEST.manifest_hash


def _create_run(journal: SqliteJournal, run_id: RunId) -> None:
    create_test_run(journal, run_id, inputs=_INPUTS)


def _checkpoint() -> Checkpoint:
    return Checkpoint(
        run_id=RUN_A,
        path=PATH,
        input_hash=INPUT_HASH,
        resolved_version=None,
        outputs={
            "result": Envelope(
                run_id=RUN_A,
                path=PATH,
                port="result",
                created_at=utc_now(),
                payload={"ok": True},
            )
        },
    )


def test_a_relocated_checkpoint_is_visible_as_damage_from_both_runs(
    tmp_path: Path,
) -> None:
    database = tmp_path / "checkpoint-selector.db"
    journal = SqliteJournal(database)
    _create_run(journal, RUN_A)
    _create_run(journal, RUN_B)
    lease = start_test_run(journal, RUN_A, owner_id="checkpoint-writer")
    checkpoint = _checkpoint()
    journal.record_completion(lease, checkpoint)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE checkpoints SET run_id = ? WHERE run_id = ?",
            (str(RUN_B), str(RUN_A)),
        )

    with pytest.raises(JournalDamaged, match="checkpoint"):
        journal.checkpoint(RUN_A, PATH)
    with pytest.raises(JournalDamaged, match="checkpoint"):
        journal.checkpoint(RUN_B, PATH)
    with pytest.raises(JournalDamaged, match="checkpoint"):
        journal.record_completion(lease, checkpoint)

    with sqlite3.connect(database) as connection:
        count = connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()
    assert count == (1,)


def test_a_completion_event_cannot_outlive_its_checkpoint_row(
    tmp_path: Path,
) -> None:
    database = tmp_path / "checkpoint-deleted.db"
    journal = SqliteJournal(database)
    _create_run(journal, RUN_A)
    lease = start_test_run(journal, RUN_A, owner_id="checkpoint-writer")
    checkpoint = _checkpoint()
    journal.record_completion(lease, checkpoint)

    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM checkpoints WHERE run_id = ?", (str(RUN_A),))
        connection.commit()

    with pytest.raises(JournalDamaged, match="row and completion event disagree"):
        journal.checkpoint(RUN_A, PATH)
    with pytest.raises(JournalDamaged, match="row and completion event disagree"):
        journal.record_completion(lease, checkpoint)


def test_a_valid_checkpoint_rewrite_is_refused_by_its_positive_seal(
    tmp_path: Path,
) -> None:
    database = tmp_path / "checkpoint-content-seal.db"
    journal = SqliteJournal(database)
    _create_run(journal, RUN_A)
    lease = start_test_run(journal, RUN_A, owner_id="checkpoint-writer")
    checkpoint = _checkpoint()
    journal.record_completion(lease, checkpoint)
    changed = checkpoint.model_copy(
        update={
            "outputs": {
                "result": checkpoint.outputs["result"].model_copy(update={"payload": {"ok": False}})
            }
        }
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE checkpoints SET identity = ?, checkpoint_json = ? WHERE run_id = ?",
            (
                str(_checkpoint_identity(changed)),
                changed.model_dump_json(),
                str(RUN_A),
            ),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.checkpoint(RUN_A, PATH)
    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.record_completion(lease, checkpoint)


def test_erasing_both_completion_rows_still_leaves_positive_checkpoint_proof(
    tmp_path: Path,
) -> None:
    database = tmp_path / "checkpoint-erased-pair.db"
    journal = SqliteJournal(database)
    _create_run(journal, RUN_A)
    lease = start_test_run(journal, RUN_A, owner_id="checkpoint-writer")
    checkpoint = _checkpoint()
    journal.record_completion(lease, checkpoint)
    with sqlite3.connect(database) as connection:
        completion_seq = connection.execute(
            "SELECT seq FROM events WHERE run_id = ? AND kind = 'NodeCompleted'",
            (str(RUN_A),),
        ).fetchone()
        assert completion_seq is not None
        connection.execute(
            "DELETE FROM checkpoints WHERE run_id = ?",
            (str(RUN_A),),
        )
        connection.execute(
            "DELETE FROM events WHERE run_id = ? AND seq = ?",
            (str(RUN_A), completion_seq[0]),
        )
        connection.execute(
            "UPDATE runs SET next_event_seq = next_event_seq - 1 WHERE run_id = ?",
            (str(RUN_A),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="missing behind its positive seal"):
        journal.checkpoint(RUN_A, PATH)
