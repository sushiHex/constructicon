"""Fenced run ownership: one live owner, every stale write refused (M2 §1).

The fence is the sequence allocation itself — ``UPDATE runs SET next_event_seq
= next_event_seq + 1 WHERE run_id=? AND owner_id=? AND owner_epoch=?`` — so a
fenced-out worker cannot write an event, a checkpoint, a transition, or a
receipt. Liveness is never lifecycle: a lost run is durably RUNNING with an
expired lease.
"""

from __future__ import annotations

import threading

import pytest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.envelope import Envelope, utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.journal import Checkpoint
from constructicon.core.run import CheckpointConflict, OwnershipLost, RunLease, RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import LEASE_TTL_S, FakeClock
from tests.run_worlds import create_test_run, sealed_test_manifest, start_test_run

RUN = RunId("run-lease")
_MANIFEST = sealed_test_manifest({"a": 1})
MANIFEST_HASH = _MANIFEST.manifest_hash
INPUT_HASH = _MANIFEST.input_hash


def make_run(journal: SqliteJournal, run_id: RunId = RUN) -> None:
    create_test_run(journal, run_id, inputs={"a": 1})


def make_checkpoint(run_id: RunId = RUN, *, payload: str = "value") -> Checkpoint:
    path = ExecutionPath(scope=ScopePath(segments=("g", "node")))
    return Checkpoint(
        run_id=run_id,
        path=path,
        input_hash=INPUT_HASH,
        resolved_version=None,
        outputs={
            "out": Envelope(
                run_id=run_id,
                path=path,
                port="out",
                created_at=utc_now(),
                payload=payload,
            )
        },
    )


def test_claim_refuses_while_a_lease_is_live(journal: SqliteJournal) -> None:
    make_run(journal)
    lease = journal.claim_run(RUN, owner_id="worker-a", ttl_s=LEASE_TTL_S)
    assert lease.epoch == 1
    with pytest.raises(OwnershipLost, match="worker-a"):
        journal.claim_run(RUN, owner_id="worker-b", ttl_s=LEASE_TTL_S)


def test_expired_lease_is_reclaimed_and_the_stale_owner_is_fenced(
    journal: SqliteJournal, clock: FakeClock
) -> None:
    make_run(journal)
    stale = start_test_run(
        journal,
        RUN,
        owner_id="worker-a",
        ttl_s=LEASE_TTL_S,
    )
    clock.advance(LEASE_TTL_S + 1)
    fresh = journal.claim_run(RUN, owner_id="worker-b", ttl_s=LEASE_TTL_S)
    assert fresh.epoch == stale.epoch + 1

    # every owner-side write path is fenced for the stale claimant
    with pytest.raises(OwnershipLost):
        journal.append_event(stale, "NodeStarted")
    with pytest.raises(OwnershipLost):
        journal.heartbeat(stale, ttl_s=LEASE_TTL_S)
    with pytest.raises(OwnershipLost):
        journal.transition_run(
            stale,
            expected=frozenset({RunStatus.RUNNING}),
            target=RunStatus.SUCCEEDED,
            event_kind="RunSucceeded",
        )
    with pytest.raises(OwnershipLost):
        journal.record_completion(stale, make_checkpoint())
    with pytest.raises(OwnershipLost):
        journal.release_run(stale)
    # the winner is untouched by all of that
    event = journal.append_event(fresh, "NodeStarted")
    assert event.seq == 2


def test_two_concurrent_claimants_produce_one_winner(
    journal: SqliteJournal,
) -> None:
    make_run(journal)
    leases: list[RunLease] = []
    losses: list[OwnershipLost] = []
    barrier = threading.Barrier(2)

    def claim(owner: str) -> None:
        barrier.wait()
        try:
            leases.append(journal.claim_run(RUN, owner_id=owner, ttl_s=LEASE_TTL_S))
        except OwnershipLost as exc:
            losses.append(exc)

    threads = [threading.Thread(target=claim, args=(o,)) for o in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(leases) == 1 and len(losses) == 1


def test_heartbeat_extends_the_lease(journal: SqliteJournal, clock: FakeClock) -> None:
    make_run(journal)
    lease = journal.claim_run(RUN, owner_id="worker-a", ttl_s=LEASE_TTL_S)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    clock.advance(LEASE_TTL_S - 5)
    renewed = journal.heartbeat(lease, ttl_s=LEASE_TTL_S)
    assert renewed.expires_at > lease.expires_at
    clock.advance(10)  # past the original expiry, inside the renewed one
    state = journal.run_state(RUN)
    assert state is not None and state.liveness == "live"
    with pytest.raises(OwnershipLost):
        journal.claim_run(RUN, owner_id="worker-b", ttl_s=LEASE_TTL_S)


def test_liveness_is_a_read_time_view_never_a_persisted_status(
    journal: SqliteJournal, clock: FakeClock
) -> None:
    make_run(journal)
    state = journal.run_state(RUN)
    assert state is not None
    assert state.status is RunStatus.PENDING and state.liveness == "not_applicable"

    lease = journal.claim_run(RUN, owner_id="worker-a", ttl_s=LEASE_TTL_S)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    state = journal.run_state(RUN)
    assert state is not None and state.liveness == "live"

    clock.advance(LEASE_TTL_S + 1)
    state = journal.run_state(RUN)
    assert state is not None
    assert state.status is RunStatus.RUNNING  # durably RUNNING — never LOST
    assert state.liveness == "lost"


def test_terminal_runs_cannot_be_claimed(journal: SqliteJournal) -> None:
    make_run(journal)
    lease = journal.claim_run(RUN, owner_id="worker-a", ttl_s=LEASE_TTL_S)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.SUCCEEDED,
        event_kind="RunSucceeded",
    )
    journal.release_run(lease)
    with pytest.raises(ContractViolation, match="terminally"):
        journal.claim_run(RUN, owner_id="worker-b", ttl_s=LEASE_TTL_S)


def test_transition_refuses_unexpected_states(journal: SqliteJournal) -> None:
    make_run(journal)
    lease = journal.claim_run(RUN, owner_id="worker-a", ttl_s=LEASE_TTL_S)
    with pytest.raises(ContractViolation, match="event allocation requires status"):
        journal.transition_run(
            lease,
            expected=frozenset({RunStatus.RUNNING}),
            target=RunStatus.SUCCEEDED,
            event_kind="RunSucceeded",
        )


def test_create_run_is_write_once(journal: SqliteJournal) -> None:
    make_run(journal)
    make_run(journal)  # identical repetition is idempotent
    different = sealed_test_manifest({"a": 2})
    with pytest.raises(CheckpointConflict, match="different manifest/inputs"):
        journal.create_run(
            RUN,
            manifest_json=different.model_dump_json(),
            manifest_hash=different.manifest_hash,
            input_hash=different.input_hash,
            inputs={"a": 2},
        )


def test_checkpoints_are_write_once(journal: SqliteJournal) -> None:
    make_run(journal)
    lease = start_test_run(
        journal,
        RUN,
        owner_id="worker-a",
        ttl_s=LEASE_TTL_S,
    )
    journal.record_completion(lease, make_checkpoint())
    # identical repetition (timestamps differ, semantics identical) -> idempotent
    journal.record_completion(lease, make_checkpoint())
    with pytest.raises(CheckpointConflict, match="different completion"):
        journal.record_completion(lease, make_checkpoint(payload="contradiction"))


def test_event_sequences_are_fenced_and_gapless_per_writer(
    journal: SqliteJournal,
) -> None:
    make_run(journal)
    lease = start_test_run(
        journal,
        RUN,
        owner_id="worker-a",
        ttl_s=LEASE_TTL_S,
    )
    seqs = [journal.append_event(lease, f"E{i}").seq for i in range(3)]
    assert seqs == [2, 3, 4]
