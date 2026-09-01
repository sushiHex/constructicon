"""Run-authenticated requests for direct durable-channel tests."""

from __future__ import annotations

from datetime import UTC, datetime

from constructicon.core.channel import ChannelMessage, ChannelSendIntent
from constructicon.core.effect import (
    Attestation,
    AttestationDraft,
    CheckResult,
    channel_send_subject,
)
from constructicon.core.identity import digest
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.run_attestations import ensure_test_run, mint_run_attestation


def mint_send_attestation(
    journal: SqliteJournal,
    intent: ChannelSendIntent,
) -> Attestation:
    """Mint the exact successful send authority production's walker would carry."""

    manifest_hash = journal.run_manifest_hash(intent.run_id)
    if manifest_hash is None:
        manifest_hash = ensure_test_run(journal, intent.run_id)
    return mint_run_attestation(
        journal,
        intent.run_id,
        AttestationDraft(
            action="send",
            subject=channel_send_subject(intent),
            checks=(
                CheckResult(
                    name="test-channel-send",
                    status="passed",
                    detail="direct substrate fixture",
                    elapsed_s=0.0,
                ),
            ),
            check_set_hash=digest("check-set", 1, {"test": "channel-send"}),
            manifest_hash=manifest_hash,
        ),
    )


class AttestedMailboxChannel(MailboxChannel):
    """Mailbox test double that replaces opaque fixture ids with real proof."""

    def append_request(
        self,
        intent: ChannelSendIntent,
        attestation_id: str,
    ) -> ChannelMessage:
        attestation = self._journal.load_attestation(attestation_id)
        if attestation is None:
            # Proof setup is not a transport observation. Keep direct contract
            # tests' injected transport clock reserved for append/reply/ack,
            # just as the command fixture keeps its preparation clock separate.
            proof_journal = SqliteJournal(
                self._journal._db_path,
                now_fn=lambda: datetime(2000, 1, 1, tzinfo=UTC),
            )
            attestation = mint_send_attestation(proof_journal, intent)
        return super().append_request(intent, attestation.attestation_id)
