"""The corrected durability contract, pinned per crash point (M2 §4).

No *durably checkpointed* invocation re-executes; work that finished only in
memory before its completion transaction committed may execute again — nothing
can preserve output that never reached the journal. No external effect occurs
more than once, ever.

Unit lane: probes inside the concrete store raise ``InjectedCrash`` (a
BaseException, so the walker's node-failure containment cannot launder
simulated death into FAILED); a wrapper could never reach these
intra-transaction seams. The subprocess lane lives in ``test_crash_worker``.
"""

from __future__ import annotations

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.address import RunId
from constructicon.core.run import RunStatus
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import LEASE_TTL_S, FakeClock, InjectedCrash, pipeline_graph

INPUTS = {"issue": {"title": "retry loop is flaky"}}
EXPECTED_SUMMARY = {"text": "summary of fix the flaky retry loop"}

# (probe, executor_calls_after_recovery, expect_restored, expected_effect_event)
#
# The first probe firing is triage's for completion.* and announce's for
# effect.* — so a completion-seam crash decides triage's fate (replay vs
# restore) while an effect-seam crash happens with triage already durable.
# executor calls == 2 -> triage's completion never became durable and its
# in-memory work legitimately replayed; == 1 -> the durable checkpoint was
# restored byte-for-byte and never recomputed. Announce executions are pinned
# to exactly 1 in EVERY row — the effect law has no replay column.
MATRIX: list[tuple[str, int, bool, str]] = [
    # died inside triage's completion txn: rollback, replay
    ("completion.after_checkpoint_insert", 2, False, "EffectCommitted"),
    ("completion.after_event_insert", 2, False, "EffectCommitted"),
    # died after triage's completion committed: restore, never recompute
    ("completion.after_commit", 1, True, "EffectCommitted"),
    # died after announce's effect was prepared, before it executed:
    # reconcile finds nothing externally -> safe to execute, exactly once
    ("effect.after_prepared_commit", 1, True, "EffectCommitted"),
    # died after the effect executed externally, before its receipt txn:
    # reconcile against the external world, never repeat
    ("effect.before_receipt_txn", 1, True, "EffectReconciled"),
    # died inside the receipt txn: same reconcile-first recovery
    ("effect.after_receipt_update", 1, True, "EffectReconciled"),
    # died after the receipt committed: dedup on the committed receipt
    ("effect.after_commit", 1, True, "EffectDeduplicated"),
    # died inside the RunStarted transition: rollback to PENDING, clean claim
    ("transition.after_status_update", 1, False, "EffectCommitted"),
]


@pytest.mark.parametrize(("probe", "executor_calls", "restored", "effect_event"), MATRIX)
async def test_recovery_matrix(
    world: Constructicon,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
    journal: SqliteJournal,
    clock: FakeClock,
    probe: str,
    executor_calls: int,
    restored: bool,
    effect_event: str,
) -> None:
    run_id = RunId(f"run-{probe.replace('.', '-')}")

    def armed(name: str) -> None:
        if name == probe:
            raise InjectedCrash(name)

    journal.fault_probe = armed
    with pytest.raises(InjectedCrash):
        await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    journal.fault_probe = lambda name: None

    clock.advance(LEASE_TTL_S + 1)
    result = await world._resume_direct(run_id)

    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["summary"] == EXPECTED_SUMMARY
    assert result.outputs["announced"] == {"reference": "announce/1"}
    assert len(fake_executor.calls) == executor_calls
    assert len(announce_effect.executions) == 1  # the law, at every crash point
    kinds = [event.kind for event in world._journal.events(run_id, limit=200)]
    assert ("NodeRestored" in kinds) == restored
    assert effect_event in kinds


async def test_crash_after_terminal_commit_returns_the_result_untouched(
    world: Constructicon,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """The caller never saw SUCCEEDED, but the journal did: resume returns the
    materialized result, appends nothing, and regresses nothing."""
    run_id = RunId("run-terminal-crash")
    transitions = 0

    def armed(name: str) -> None:
        nonlocal transitions
        if name == "transition.after_commit":
            transitions += 1
            if transitions == 2:  # 1 = RunStarted, 2 = RunSucceeded
                raise InjectedCrash(name)

    journal.fault_probe = armed
    with pytest.raises(InjectedCrash):
        await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    journal.fault_probe = lambda name: None

    clock.advance(LEASE_TTL_S + 1)
    events_before = len(world._journal.events(run_id, limit=200))
    result = await world._resume_direct(run_id)
    assert result.status is RunStatus.SUCCEEDED
    assert result.outputs["summary"] == EXPECTED_SUMMARY
    assert len(fake_executor.calls) == 1
    assert len(announce_effect.executions) == 1
    assert len(world._journal.events(run_id, limit=200)) == events_before


async def test_reclaim_requires_expiry_and_fences_the_loser(
    world: Constructicon,
    journal: SqliteJournal,
    clock: FakeClock,
    announce_effect: FakeAnnounceEffect,
    tmp_path,
) -> None:
    """Two resumptions of one crashed run: before expiry the second worker is
    refused with the owner's identity; after expiry it wins and the run
    completes exactly once."""
    from constructicon.core.run import OwnershipLost
    from tests.conftest import TRIAGE_SCRIPT, build_system

    run_id = RunId("run-two-claimants")

    def armed(name: str) -> None:
        if name == "completion.after_commit":
            raise InjectedCrash(name)

    journal.fault_probe = armed
    with pytest.raises(InjectedCrash):
        await world._start_direct(pipeline_graph(), INPUTS, run_id=run_id)
    journal.fault_probe = lambda name: None

    second_journal = SqliteJournal(tmp_path / "journal.db", now_fn=clock.now)
    second = build_system(
        second_journal,
        FakeExecutor(dict(TRIAGE_SCRIPT)),
        announce_effect,
        owner_id="worker-two",
    )
    with pytest.raises(OwnershipLost, match="worker-one"):
        await second._resume_direct(run_id)

    clock.advance(LEASE_TTL_S + 1)
    result = await second._resume_direct(run_id)
    assert result.status is RunStatus.SUCCEEDED
    assert len(announce_effect.executions) == 1
