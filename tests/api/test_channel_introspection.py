"""M7: describe() publishes the guarantee a channel transport actually provides."""

from __future__ import annotations

from typing import Any, cast

import pytest

from constructicon.api.system import Constructicon
from constructicon.core.channel import (
    CHANNEL_SEND_EFFECT,
    IN_PROCESS_CHANNEL_KIND,
    MAILBOX_CHANNEL_KIND,
    Channel,
    ChannelDurability,
    ChannelEndpoint,
    ChannelProfile,
)
from constructicon.core.journal import Journal
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.channels.in_process import InProcessChannel
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.effects.channel import ChannelSendEffect
from constructicon.substrate.effects.fake import FakeAnnounceEffect
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal

MAILBOX_ID = "channel/review"
IN_PROCESS_ID = "channel/local"


class _MailboxProxy:
    """A structural durable transport, deliberately not a MailboxChannel subclass."""

    def __init__(self, mailbox: MailboxChannel) -> None:
        self._mailbox = mailbox

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mailbox, name)

    def is_assembled_from(self, journal: Journal) -> bool:
        return self._mailbox.is_assembled_from(journal)


class _UnprovenMailboxProxy:
    def __init__(self, mailbox: MailboxChannel) -> None:
        self._mailbox = mailbox

    def __getattr__(self, name: str) -> Any:
        if name == "is_assembled_from":
            raise AttributeError(name)
        return getattr(self._mailbox, name)


class _ValueEqualSqliteJournal(SqliteJournal):
    """A different durable world that deliberately compares equal."""

    def __eq__(self, other: object) -> bool:
        return isinstance(other, SqliteJournal)


def _assemble_mailbox(journal: SqliteJournal, capability: object) -> Constructicon:
    profile = cast(Channel, capability).profile
    return Constructicon(
        journal=journal,
        capabilities={MAILBOX_ID: capability},
        catalog={
            MAILBOX_ID: CapabilityDescriptor(
                capability_id=MAILBOX_ID,
                kind=MAILBOX_CHANNEL_KIND,
                revision="1",
                channel_profile=profile,
            )
        },
    )


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


def test_a_descriptor_cannot_put_channel_routing_on_a_non_channel_kind() -> None:
    endpoint = ChannelEndpoint(
        lane="review",
        interaction="advice",
        recipient_actor_id="static:advisor",
    )
    with pytest.raises(ValueError, match="only a channel"):
        CapabilityDescriptor(
            capability_id="not-a-channel",
            kind="executor",
            revision="1",
            endpoint=endpoint,
        )


def test_a_channel_kind_cannot_omit_its_published_transport_contract() -> None:
    with pytest.raises(ValueError, match="ChannelProfile"):
        CapabilityDescriptor(
            capability_id="channel/incomplete",
            kind="channel.mailbox",
            revision="1",
        )


def test_a_channel_transport_cannot_pretend_to_be_an_invocation_lease() -> None:
    with pytest.raises(ValueError, match="cannot be leased"):
        CapabilityDescriptor(
            capability_id="channel/leased",
            kind="channel.mailbox",
            revision="1",
            channel_profile=ChannelProfile(durability="sqlite_wal", max_batch=10),
            leased=True,
        )


def test_an_absent_optional_capability_may_be_lazy_but_cannot_be_renamed(
    journal: SqliteJournal,
) -> None:
    descriptor = CapabilityDescriptor(
        capability_id="executor/lazy",
        kind="executor",
        revision="1",
    )
    Constructicon(
        journal=journal,
        catalog={descriptor.capability_id: descriptor},
    )

    with pytest.raises(ValueError, match="differs from its descriptor identity"):
        Constructicon(
            journal=journal,
            catalog={"executor/alias": descriptor},
        )


def test_a_durable_mailbox_cannot_inhabit_another_journal(tmp_path) -> None:
    journal = SqliteJournal(tmp_path / "system.db")
    mailbox = MailboxChannel(
        SqliteJournal(tmp_path / "foreign.db"),
        channel_id=MAILBOX_ID,
    )

    with pytest.raises(ValueError, match="must use the exact Constructicon journal"):
        Constructicon(
            journal=journal,
            capabilities={MAILBOX_ID: mailbox},
            catalog={
                MAILBOX_ID: CapabilityDescriptor(
                    capability_id=MAILBOX_ID,
                    kind="channel.mailbox",
                    revision="1",
                    channel_profile=mailbox.profile,
                )
            },
        )


def test_every_structural_sqlite_channel_must_prove_its_exact_journal(tmp_path) -> None:
    journal = _ValueEqualSqliteJournal(tmp_path / "system.db")
    foreign_journal = _ValueEqualSqliteJournal(tmp_path / "foreign.db")
    assert foreign_journal == journal and foreign_journal is not journal
    local = _MailboxProxy(MailboxChannel(journal, channel_id=MAILBOX_ID))
    foreign = _MailboxProxy(
        MailboxChannel(foreign_journal, channel_id=MAILBOX_ID)
    )
    unproven = _UnprovenMailboxProxy(
        MailboxChannel(journal, channel_id=MAILBOX_ID)
    )

    _assemble_mailbox(journal, local)
    for channel in (foreign, unproven):
        with pytest.raises(ValueError, match="must use the exact Constructicon journal"):
            _assemble_mailbox(journal, channel)


@pytest.mark.parametrize(
    ("kind", "durability"),
    (
        (MAILBOX_CHANNEL_KIND, "process"),
        (IN_PROCESS_CHANNEL_KIND, "sqlite_wal"),
    ),
)
def test_reserved_channel_kinds_cannot_claim_the_other_builtin_durability(
    kind: str,
    durability: ChannelDurability,
) -> None:
    with pytest.raises(ValueError, match="reserved channel kind"):
        CapabilityDescriptor(
            capability_id="channel/mislabeled",
            kind=kind,
            revision="1",
            channel_profile=ChannelProfile(durability=durability, max_batch=10),
        )


def test_custom_channel_kinds_remain_extensible() -> None:
    descriptor = CapabilityDescriptor(
        capability_id="channel/custom",
        kind="channel.custom",
        revision="1",
        channel_profile=ChannelProfile(durability="process", max_batch=10),
    )
    assert descriptor.kind == "channel.custom"


def test_an_explicit_channel_send_effect_cannot_inhabit_another_journal(
    tmp_path,
) -> None:
    journal = _ValueEqualSqliteJournal(tmp_path / "system.db")
    foreign = _ValueEqualSqliteJournal(tmp_path / "foreign.db")
    assert foreign == journal and foreign is not journal
    mailbox = MailboxChannel(journal, channel_id=MAILBOX_ID)
    catalog = {
        MAILBOX_ID: CapabilityDescriptor(
            capability_id=MAILBOX_ID,
            kind="channel.mailbox",
            revision="1",
            channel_profile=mailbox.profile,
        )
    }

    with pytest.raises(ValueError, match="exact Constructicon journal"):
        Constructicon(
            journal=journal,
            capabilities={MAILBOX_ID: mailbox},
            catalog=catalog,
            effects={
                CHANNEL_SEND_EFFECT: ChannelSendEffect(
                    journal=foreign,
                    catalog={(MAILBOX_ID, "1"): mailbox},
                )
            },
        )
