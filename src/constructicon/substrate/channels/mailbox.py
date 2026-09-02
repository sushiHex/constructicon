"""The mailbox channel: the human-wait transport, durable in the one journal.

It owns no second database path and no schema manager. Persistence lives in the
journal's ``_sqlite_channels`` responsibility, so a channel message and the run
that is parked on it survive or fail together.
"""

from __future__ import annotations

from constructicon.core.channel import (
    MAX_INBOX_BATCH,
    ChannelAck,
    ChannelDelivery,
    ChannelMessage,
    ChannelProfile,
    ChannelRevision,
    ChannelSendIntent,
)
from constructicon.core.identity import Digest, JsonValue
from constructicon.core.journal import Journal
from constructicon.substrate.journal.sqlite import SqliteJournal


class MailboxChannel:
    """``kind="channel.mailbox"`` — retained history in the authoritative WAL."""

    def __init__(
        self,
        journal: SqliteJournal,
        *,
        channel_id: str,
        max_batch: int = MAX_INBOX_BATCH,
    ) -> None:
        if max_batch <= 0:
            raise ValueError("channel max_batch must be positive")
        self._journal = journal
        self._channel_id = channel_id
        self._max_batch = max_batch

    @property
    def channel_id(self) -> str:
        return self._channel_id

    @property
    def profile(self) -> ChannelProfile:
        return ChannelProfile(durability="sqlite_wal", max_batch=self._max_batch)

    def is_assembled_from(self, journal: Journal) -> bool:
        """Whether retained messages inhabit the system's exact durable world."""

        return self._journal is journal

    def append_request(
        self,
        intent: ChannelSendIntent,
        attestation_id: str,
    ) -> ChannelMessage:
        return self._journal.channel_append_request(
            channel_id=self._channel_id,
            intent=intent,
            attestation_id=attestation_id,
        )

    def message(self, message_id: Digest) -> ChannelMessage | None:
        return self._journal.channel_message(
            channel_id=self._channel_id,
            message_id=message_id,
        )

    def reply_for(self, request_id: Digest) -> ChannelMessage | None:
        return self._journal.channel_reply_for(
            channel_id=self._channel_id,
            request_id=request_id,
        )

    def reply(
        self,
        *,
        request_id: Digest,
        actor_id: str,
        payload: JsonValue,
        command_id: str,
    ) -> ChannelMessage:
        return self._journal.channel_reply(
            channel_id=self._channel_id,
            request_id=request_id,
            actor_id=actor_id,
            payload=payload,
            command_id=command_id,
        )

    def acknowledge(
        self,
        *,
        message_id: Digest,
        actor_id: str,
        command_id: str,
    ) -> ChannelAck:
        return self._journal.channel_acknowledge(
            channel_id=self._channel_id,
            message_id=message_id,
            actor_id=actor_id,
            command_id=command_id,
        )

    def latest_revision(self, actor_id: str) -> ChannelRevision:
        del actor_id  # the cut is over retained history, not over one actor
        return self._journal.channel_revision(channel_id=self._channel_id)

    def inbox(
        self,
        *,
        actor_id: str,
        revision: ChannelRevision,
        after: tuple[int, str] | None,
        limit: int,
    ) -> tuple[ChannelDelivery, ...]:
        if limit > self._max_batch:
            raise ValueError(f"limit exceeds channel max_batch {self._max_batch}")
        return self._journal.channel_inbox(
            channel_id=self._channel_id,
            actor_id=actor_id,
            revision=revision,
            after=after,
            limit=limit,
        )
