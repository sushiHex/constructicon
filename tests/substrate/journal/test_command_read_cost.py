"""A bounded command read proves the rows it returns, not the whole store.

Every read on the control store ran the full command-claim inventory first, and
that inventory decodes and phase-proves each retained command in turn. So a
lookup for one key, on the recovery pump's hot loop, paid for every command the
store had ever held — and the bill grew with the store rather than with the
answer.

The law is pinned here by counting, not by timing: a bounded read projects a
number of commands that does not move when the store gets bigger. What it keeps
is the erasure defence, because a bounded read's answer can depend on a row's
absence — that check is wholly in SQL and proves nothing by projecting.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from constructicon.core.control import (
    OPERATE_SCOPE,
    AuthenticatedActor,
    command_request_hash,
)
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import JsonValue
from constructicon.substrate.journal import _sqlite_commands
from constructicon.substrate.journal.sqlite import SqliteJournal

ACTOR = AuthenticatedActor(
    actor_id="static:read-cost",
    auth_method="static",
    scopes=frozenset({OPERATE_SCOPE}),
)


def _claim(journal: SqliteJournal, key: str) -> str:
    request: JsonValue = {"key": key}
    result = journal.claim_command(
        actor=ACTOR,
        operation="runs_cancel",
        idempotency_key=key,
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:read-cost",
        ttl_s=3600,
    )
    assert result.claim is not None
    journal.store_command_plan(result.claim, {"kind": "cancel", "key": key})
    return result.claim.command_id


def _projections_for_one_lookup(
    monkeypatch: pytest.MonkeyPatch,
    journal: SqliteJournal,
) -> int:
    """How many commands one bounded lookup decodes."""

    original = _sqlite_commands.command_from_row
    counted = 0

    def counting(row: object):  # type: ignore[no-untyped-def]
        nonlocal counted
        counted += 1
        return original(row)  # type: ignore[arg-type]

    monkeypatch.setattr(_sqlite_commands, "command_from_row", counting)
    try:
        journal.latest_command_key(operation="runs_cancel")
    finally:
        monkeypatch.undo()
    return counted


def test_one_bounded_lookup_costs_the_same_however_many_commands_are_stored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The bound is what matters, not its value: it must not move with N."""

    journal = SqliteJournal(tmp_path / "command-read-cost.db")
    for index in range(4):
        _claim(journal, f"short-{index}")
    early = _projections_for_one_lookup(monkeypatch, journal)

    for index in range(60):
        _claim(journal, f"long-{index}")
    late = _projections_for_one_lookup(monkeypatch, journal)

    assert early == late, (
        f"one lookup decoded {early} commands with a small store and {late} "
        "with a large one; a bounded read is projecting the whole table"
    )
    # And the bound is small: the row this lookup actually returns.
    assert late <= 2


def test_a_bounded_lookup_still_refuses_an_erased_command(
    tmp_path: Path,
) -> None:
    """The cheap half of the inventory is the half that had to stay.

    Erasing the newest command of an operation would otherwise hand the next
    key derivation an older one, and a spent key could be spent again. The seal
    the erased row leaves behind is what says so, and finding it is a join.
    """

    database = tmp_path / "command-read-erasure.db"
    journal = SqliteJournal(database)
    _claim(journal, "kept")
    erased = _claim(journal, "erased")

    with journal._txn() as connection:
        connection.execute("DELETE FROM commands WHERE command_id = ?", (erased,))

    with pytest.raises(JournalDamaged, match="missing or precedes its sealed phase"):
        journal.latest_command_key(operation="runs_cancel")
