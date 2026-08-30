"""A process death at any channel-send seam converges on one message (M7).

The send crosses the effect law, so the seams are the effect law's: after the
attestation, after the prepared effect, after the message insert, and after the
receipt. Every one of them must leave exactly one message and one receipt.
"""

from __future__ import annotations

import pytest

from constructicon.core.address import RunId
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import FakeClock, InjectedCrash
from tests.e2e.test_channel_round_trip import ADVISOR, INPUTS, _graph, _world

# Every durable boundary the send crosses, in the order it crosses them.
SEAMS = (
    "attestation.after_commit",
    "effect.after_prepared_commit",
    "channel.after_message_insert",
    "effect.after_commit",
)


def _crash_at(journal: SqliteJournal, seam: str) -> None:
    def crash(name: str) -> None:
        if name == seam:
            raise InjectedCrash(name)

    journal.fault_probe = crash


@pytest.mark.parametrize("seam", SEAMS)
async def test_a_death_at_one_send_seam_still_yields_one_message(
    seam: str,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    system, mailbox = _world(journal)
    run_id = RunId(f"run-seam-{seam.replace('.', '-')}")
    manifest = system.validate(_graph(), INPUTS)
    system._prepare_run(manifest, run_id=run_id, inputs=INPUTS)

    _crash_at(journal, seam)
    with pytest.raises(InjectedCrash):
        await system._run_prepared(run_id, cancellation="abandon")

    # A new host, long after the crash: the reconstructed send must not invent
    # a second message or a second observation time.
    journal.fault_probe = lambda name: None
    clock.advance(3600)
    recovered = await system._run_prepared(run_id, cancellation="abandon")
    assert recovered.status is RunStatus.PARKED

    revision = mailbox.latest_revision(ADVISOR)
    assert revision.message_seq == 1  # exactly one request, at every seam
    waits = journal.parked_waits()
    assert [wait.run_id for wait in waits] == [run_id]
    stored = mailbox.message(waits[0].requests[0])
    assert stored is not None
    assert stored.envelope.payload == INPUTS["request"]


@pytest.mark.parametrize("seam", SEAMS)
async def test_a_death_at_one_send_seam_still_completes_after_a_reply(
    seam: str,
    journal: SqliteJournal,
    clock: FakeClock,
) -> None:
    """The whole round trip survives a death at every durable boundary."""

    system, mailbox = _world(journal)
    run_id = RunId(f"run-seam-reply-{seam.replace('.', '-')}")
    manifest = system.validate(_graph(), INPUTS)
    system._prepare_run(manifest, run_id=run_id, inputs=INPUTS)

    _crash_at(journal, seam)
    with pytest.raises(InjectedCrash):
        await system._run_prepared(run_id, cancellation="abandon")

    journal.fault_probe = lambda name: None
    clock.advance(3600)  # the crashed worker's lease is long gone
    assert (await system._run_prepared(run_id, cancellation="abandon")).status is RunStatus.PARKED

    request_id = journal.parked_waits()[0].requests[0]
    mailbox.reply(
        request_id=request_id,
        actor_id=ADVISOR,
        payload={"verdict": "ship it"},
        command_id=f"cmd-{seam}",
    )
    resumed = await system._run_prepared(run_id, cancellation="abandon")
    assert resumed.status is RunStatus.SUCCEEDED
    assert resumed.outputs == {"advice": {"verdict": "ship it"}}
    assert mailbox.latest_revision(ADVISOR).message_seq == 2  # one request, one reply
