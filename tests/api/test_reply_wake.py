"""A stored reply wakes a PARKED run, with no command lookup (M7).

Recovery reads durable domain facts. A death after a reply's domain
transaction but before its command completes still produces the wake, because
nothing here consults command state.
"""

from __future__ import annotations

import asyncio
from datetime import timedelta

from constructicon.core.address import RunId
from constructicon.core.identity import Digest, digest
from constructicon.core.run import RunStatus
from tests.api.test_run_host_recovery import (
    AsyncClock,
    FakeJournal,
    FakeSystem,
    eventually,
    host_for,
    record,
)

WAITING = RunId("run-awaiting-advice")
REQUEST = digest("channel-message", 1, {"request": "advice"})
REPLY = digest("channel-reply", 1, {"request": "advice"})


def _parked_world() -> tuple[AsyncClock, FakeJournal, FakeSystem]:
    clock = AsyncClock()
    journal = FakeJournal(
        [record(str(WAITING), clock, created_offset=0, status=RunStatus.PARKED)]
    )
    journal.parked[WAITING] = (REQUEST,)
    return clock, journal, FakeSystem(journal, clock)


async def test_a_parked_run_is_not_woken_while_its_request_is_unanswered() -> None:
    """PARKED never joins ordinary recovery: only a reply may wake a wait."""

    clock, _journal, system = _parked_world()
    host = host_for(system)
    await host.startup()

    clock.advance(600)  # no lease to expire, no worker to reclaim
    await asyncio.sleep(0)
    assert system.started == []  # a human is still thinking
    await host.shutdown()


async def test_a_stored_reply_wakes_the_run_at_its_parking_fence() -> None:
    _clock, journal, system = _parked_world()
    system.blockers[WAITING] = asyncio.Event()
    host = host_for(system)
    await host.startup()
    assert system.started == []

    journal.replies[REQUEST] = REPLY  # the durable fact the scan observes
    host._wake.set()
    await eventually(lambda: system.started == [WAITING], "the stored reply woke nothing")

    system.blockers[WAITING].set()
    await eventually(
        lambda: journal.records[WAITING].status is RunStatus.SUCCEEDED,
        "the woken attempt never finished",
    )
    await host.shutdown()


async def test_the_attempt_records_the_reply_it_observed_not_a_command() -> None:
    """An M7 wake is reconstructable without any command lookup."""

    _clock, journal, system = _parked_world()
    host = host_for(system)
    await host.startup()
    journal.replies[REQUEST] = REPLY
    host._wake.set()
    await eventually(lambda: system.started == [WAITING], "the reply woke nothing")

    cause = system.causes[WAITING]
    assert cause is not None
    assert cause.kind == "channel_reply"
    assert cause.id == str(REPLY)
    assert cause.payload() == {"reply_message_id": str(REPLY)}  # never the legacy key
    await host.shutdown()


async def test_repeated_scans_of_one_reply_create_one_attempt() -> None:
    """Duplicate discoveries of that exact cause coalesce at the same fence."""

    clock, journal, system = _parked_world()
    system.blockers[WAITING] = asyncio.Event()
    host = host_for(system)
    await host.startup()
    journal.replies[REQUEST] = REPLY

    for _ in range(4):
        host._wake.set()
        await asyncio.sleep(0)
    await eventually(lambda: system.started == [WAITING], "the reply woke nothing")

    clock.advance(1)
    await asyncio.sleep(0)
    assert system.started == [WAITING]  # still exactly one attempt
    system.blockers[WAITING].set()
    await host.shutdown()


async def test_a_wait_whose_reply_is_for_another_request_is_not_woken() -> None:
    _clock, journal, system = _parked_world()
    host = host_for(system)
    await host.startup()

    journal.replies[Digest(digest("channel-message", 1, {"request": "other"}).root)] = REPLY
    host._wake.set()
    await asyncio.sleep(0)
    assert system.started == []  # a reply to someone else wakes nobody
    await host.shutdown()


async def test_a_parked_run_with_no_wait_is_never_woken() -> None:
    """An M4 policy-exhausted park is not waiting for anyone."""

    clock = AsyncClock()
    journal = FakeJournal(
        [record("run-policy-exhausted", clock, created_offset=0, status=RunStatus.PARKED)]
    )
    system = FakeSystem(journal, clock)
    host = host_for(system)
    await host.startup()

    journal.replies[REQUEST] = REPLY
    host._wake.set()
    clock.advance(timedelta(seconds=60).total_seconds())
    await asyncio.sleep(0)
    assert system.started == []
    await host.shutdown()
