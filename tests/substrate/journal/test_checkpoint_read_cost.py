"""A checkpoint read proves the invocation it names, not every event in the store.

Every checkpoint lookup ran two queries whose matching predicate was a Python
selector function evaluated per row, with no primary-key prefix to bound them,
so SQLite scanned the whole `events` table — every run, every kind — through a
Python callback before returning at most two rows. That lookup sits on the
walker's per-node path and on every completion write, and the open-time
checkpoint inventory ran it once per checkpoint.

The law is pinned by counting, not timing: one lookup decodes a number of rows
that does not move when unrelated runs and events accumulate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.run_worlds import create_test_run, sealed_test_manifest, start_test_run

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.envelope import Envelope, utc_now
from constructicon.core.journal import Checkpoint
from constructicon.substrate.journal import _sqlite_execution_facts
from constructicon.substrate.journal.sqlite import SqliteJournal

PATH = ExecutionPath(scope=ScopePath(segments=("cost", "node")))
_INPUTS = {"cost": "checkpoint"}
_MANIFEST = sealed_test_manifest(_INPUTS)


def _completed_run(journal: SqliteJournal, run_id: RunId) -> None:
    create_test_run(journal, run_id, inputs=_INPUTS)
    lease = start_test_run(journal, run_id, owner_id="checkpoint-cost")
    journal.record_completion(
        lease,
        Checkpoint(
            run_id=run_id,
            path=PATH,
            input_hash=_MANIFEST.input_hash,
            resolved_version=None,
            outputs={
                "result": Envelope(
                    run_id=run_id,
                    path=PATH,
                    port="result",
                    created_at=utc_now(),
                    payload={"ok": True},
                )
            },
        ),
    )
    for step in range(5):
        journal.append_event(lease, f"Noise{step}", path=PATH, payload={"step": step})


def _decodes_for_one_lookup(
    monkeypatch: pytest.MonkeyPatch,
    journal: SqliteJournal,
    run_id: RunId,
) -> int:
    """How many stored payloads one checkpoint lookup decodes."""

    original = _sqlite_execution_facts._durable_model
    counted = 0

    def counting(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal counted
        counted += 1
        return original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(_sqlite_execution_facts, "_durable_model", counting)
    try:
        assert journal.checkpoint(run_id, PATH) is not None
    finally:
        monkeypatch.undo()
    return counted


def test_one_checkpoint_lookup_costs_the_same_however_large_the_store_is(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    journal = SqliteJournal(tmp_path / "checkpoint-cost.db")
    target = RunId("run-checkpoint-cost-target")
    _completed_run(journal, target)
    early = _decodes_for_one_lookup(monkeypatch, journal, target)

    for index in range(12):
        _completed_run(journal, RunId(f"run-checkpoint-cost-noise-{index}"))
    late = _decodes_for_one_lookup(monkeypatch, journal, target)

    assert early == late, (
        f"one lookup decoded {early} payloads with one run stored and {late} with "
        "thirteen; a checkpoint read is scanning the store's events"
    )
    # The bound is small: the checkpoint it returns and the event that proves it.
    assert late <= 4
