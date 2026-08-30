"""M7: describe() publishes the guarantee a channel transport actually provides."""

from __future__ import annotations

from constructicon.api.system import Constructicon
from constructicon.core.channel import ChannelEndpoint
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.channels.in_process import InProcessChannel
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal

MAILBOX_ID = "channel/review"
IN_PROCESS_ID = "channel/local"


def _system(
    journal: SqliteJournal,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
    *,
    mailbox_batch: int = 100,
    lane: str = "review",
) -> Constructicon:
    mailbox = MailboxChannel(journal, channel_id=MAILBOX_ID, max_batch=mailbox_batch)
    in_process = InProcessChannel(channel_id=IN_PROCESS_ID)
    return Constructicon(
        journal=journal,
        capabilities={
            "fake-executor": fake_executor,
            MAILBOX_ID: mailbox,
            IN_PROCESS_ID: in_process,
        },
        catalog={
            "fake-executor": CapabilityDescriptor(
                capability_id="fake-executor",
                kind="executor",
                revision="1",
                executor_profile=fake_executor.profile,
            ),
            MAILBOX_ID: CapabilityDescriptor(
                capability_id=MAILBOX_ID,
                kind="channel.mailbox",
                revision="1",
                channel_profile=mailbox.profile,
                endpoint=ChannelEndpoint(
                    lane=lane,
                    interaction="advice",
                    recipient_actor_id="static:advisor",
                ),
            ),
            IN_PROCESS_ID: CapabilityDescriptor(
                capability_id=IN_PROCESS_ID,
                kind="channel.in_process",
                revision="1",
                channel_profile=in_process.profile,
            ),
        },
        effects={"announce": announce_effect},
        owner_id="describe-channels",
    )


def test_describe_publishes_each_transports_honest_channel_profile(
    journal: SqliteJournal,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    description = _system(journal, fake_executor, announce_effect).describe(limit=100)
    published = {item.capability_id: item for item in description.capabilities}

    assert published[MAILBOX_ID].kind == "channel.mailbox"
    assert published[MAILBOX_ID].channel_profile is not None
    assert published[MAILBOX_ID].channel_profile.durability == "sqlite_wal"
    assert published[IN_PROCESS_ID].channel_profile is not None
    assert published[IN_PROCESS_ID].channel_profile.durability == "process"
    for capability_id in (MAILBOX_ID, IN_PROCESS_ID):
        profile = published[capability_id].channel_profile
        assert profile is not None
        assert profile.delivery == "at_least_once"  # never claims exactly-once
        assert profile.history == "retained"
        assert published[capability_id].executor_profile is None

    assert published["fake-executor"].channel_profile is None  # no invented profile
    assert published["fake-executor"].executor_profile is not None


def test_the_catalog_digest_covers_a_changed_channel_guarantee(
    journal: SqliteJournal,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    """A published digest that ignored the profile would hide a changed bound."""

    first = _system(journal, fake_executor, announce_effect).describe(limit=100)
    narrowed = _system(
        journal,
        fake_executor,
        announce_effect,
        mailbox_batch=10,
    ).describe(limit=100)
    assert narrowed.catalog_digest != first.catalog_digest
    assert narrowed.description_digest != first.description_digest


def test_describe_publishes_which_participant_each_channel_addresses(
    journal: SqliteJournal,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    """Four near-identical ids are useless if none says whom it reaches."""

    description = _system(journal, fake_executor, announce_effect).describe(limit=100)
    published = {item.capability_id: item for item in description.capabilities}

    endpoint = published[MAILBOX_ID].channel_endpoint
    assert endpoint is not None
    assert endpoint.lane == "review"
    assert endpoint.interaction == "advice"
    assert endpoint.recipient_actor_id == "static:advisor"
    assert published[IN_PROCESS_ID].channel_endpoint is None
    assert published["fake-executor"].channel_endpoint is None


def test_the_catalog_digest_covers_a_rerouted_endpoint(
    journal: SqliteJournal,
    fake_executor: FakeExecutor,
    announce_effect: FakeAnnounceEffect,
) -> None:
    """Rerouting a channel must be visible in the published catalog identity."""

    first = _system(journal, fake_executor, announce_effect).describe(limit=100)
    rerouted = _system(
        journal,
        fake_executor,
        announce_effect,
        lane="escalation",
    ).describe(limit=100)
    assert rerouted.catalog_digest != first.catalog_digest
