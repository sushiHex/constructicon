"""M6 command identity has exactly one live owner under concurrent claims."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from constructicon.core.control import (
    OPERATE_SCOPE,
    AuthenticatedActor,
    command_id_for,
)
from constructicon.core.identity import digest
from constructicon.substrate.journal.sqlite import SqliteJournal


def test_simultaneous_same_key_claims_produce_one_owner(
    journal: SqliteJournal,
) -> None:
    actor = AuthenticatedActor(
        actor_id="static:concurrent-command",
        auth_method="static",
        scopes=frozenset({OPERATE_SCOPE}),
    )
    request = {"proposal": {"name": "one-command"}}
    request_hash = digest("control-request", 1, request)
    barrier = threading.Barrier(2)

    def claim(owner_id: str):
        barrier.wait()
        return journal.claim_command(
            actor=actor,
            operation="runs_start",
            idempotency_key="same-key",
            request_hash=request_hash,
            request=request,
            owner_id=owner_id,
            ttl_s=30,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim, "owner-a")
        second = executor.submit(claim, "owner-b")
        results = (first.result(), second.result())

    assert sorted(result.status for result in results) == ["claimed", "in_progress"]
    winner = next(result for result in results if result.status == "claimed")
    assert winner.claim is not None
    record = journal.command(command_id_for(actor.actor_id, "runs_start", "same-key"))
    assert record is not None
    assert record.state == "prepared"
    assert record.owner_epoch == 1
    assert record.owner_id == winner.claim.owner_id
