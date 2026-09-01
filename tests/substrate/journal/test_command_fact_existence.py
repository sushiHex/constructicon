"""One question about a sealed fact, asked one way.

Whether a command carries a plan is asked in two languages: Python asks the
decoded value (``record.plan is not None``) and SQL asks the stored column.
JSON ``null`` is the one value where those disagree — it is a four-byte,
SQL-non-NULL column that decodes to nothing.

`store_command_plan(claim, None)` is a type-legal call on the declared port, and
it landed exactly there: the seal writer saw no plan and wrote no seal, while
the open-path inventory saw a non-NULL column and demanded one. ADR 0016 forbids
healing on open, so the resulting verdict was permanent — one type-legal call
made the store unopenable forever.

The command store has two such ports, and the response column carries the same
`JsonValue` that admits the same bytes, so both are stated here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.conftest import FakeClock

from constructicon.core.control import (
    OPERATE_SCOPE,
    AuthenticatedActor,
    CommandClaim,
    command_request_hash,
)
from constructicon.core.identity import JsonValue
from constructicon.substrate.journal.sqlite import SqliteJournal

ACTOR = AuthenticatedActor(
    actor_id="static:planless",
    auth_method="static",
    scopes=frozenset({OPERATE_SCOPE}),
)
REQUEST: JsonValue = {"why": "a plan that is not a plan"}


def _claimed(journal: SqliteJournal, key: str) -> CommandClaim:
    result = journal.claim_command(
        actor=ACTOR,
        operation="runs_cancel",
        idempotency_key=key,
        request_hash=command_request_hash(REQUEST),
        request=REQUEST,
        owner_id="test:planless",
        ttl_s=30,
    )
    assert result.claim is not None
    return result.claim


def test_a_plan_that_decodes_to_nothing_is_refused(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """The one value the two languages disagree about never reaches the store."""

    database = tmp_path / "null-plan.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    claim = _claimed(journal, "null-plan")

    with pytest.raises(ValueError, match="cannot be planned with no plan"):
        journal.store_command_plan(claim, None)

    # Refused before the write, so the claim is intact and still plannable.
    record = journal.command(claim.command_id)
    assert record is not None
    assert record.plan is None
    journal.store_command_plan(claim, {"kind": "cancel"})
    assert journal.command(claim.command_id) is not None

    # And the store still opens, which is the whole point.
    SqliteJournal(database, now_fn=clock.now)


def test_a_stored_null_plan_reads_as_no_plan_rather_than_as_damage(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """A store that already holds the four bytes opens and says what is true.

    Its command is unplanned — which is exactly what ``null`` decodes to — so
    it can still be planned, finished, and replayed. A store is condemned for
    what it holds, never for which of two readings looked at it first.
    """

    database = tmp_path / "legacy-null-plan.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    claim = _claimed(journal, "legacy-null-plan")

    with sqlite3.connect(database) as raw:
        raw.execute(
            "UPDATE commands SET plan_json = 'null' WHERE command_id = ?",
            (claim.command_id,),
        )
        raw.commit()

    reopened = SqliteJournal(database, now_fn=clock.now)
    record = reopened.command(claim.command_id)
    assert record is not None
    assert record.plan is None

    reopened.store_command_plan(claim, {"kind": "cancel"})
    planned = reopened.command(claim.command_id)
    assert planned is not None
    assert planned.plan == {"kind": "cancel"}
    SqliteJournal(database, now_fn=clock.now)


@pytest.mark.parametrize("finish", ["complete_command", "reject_command"])
def test_a_response_that_decodes_to_nothing_is_refused(
    finish: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    """A terminal command owes every retry the answer it already gave.

    The same bytes in the response column would make the command terminal to
    SQL and answerless to the replay path, which can then only raise.
    """

    database = tmp_path / f"null-response-{finish}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    claim = _claimed(journal, f"null-response-{finish}")
    journal.store_command_plan(claim, {"kind": "cancel"})

    with pytest.raises(ValueError, match="with no response"):
        getattr(journal, finish)(claim, None)

    record = journal.command(claim.command_id)
    assert record is not None
    assert record.state == "prepared"

    finished = getattr(journal, finish)(claim, {"status": "done"})
    assert finished.response == {"status": "done"}
    SqliteJournal(database, now_fn=clock.now)
