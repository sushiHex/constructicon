"""The channel send boundary: a run-originated message is a proof-carrying effect.

Dispatch here is mechanical. The adapter looks up one exact
``(channel_id, channel_revision)`` pair in an immutable catalog the injection
root gave it — that is physical dispatch against an admitted binding, not name
resolution and not a choice delegated to the walker.
"""

from __future__ import annotations

from collections.abc import Mapping

from constructicon.core.channel import CHANNEL_SEND_EFFECT, Channel, ChannelSendIntent
from constructicon.core.effect import (
    EffectProfile,
    EffectReceipt,
    EffectRequest,
    request_hash,
    validated_channel_send_attestation,
)
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import canonical_json
from constructicon.core.journal import Journal


class ChannelSendEffect:
    """``kind="channel_send"``: reconcilable, and truthfully simulable."""

    def __init__(
        self,
        *,
        journal: Journal,
        catalog: Mapping[tuple[str, str], Channel],
    ) -> None:
        self._journal = journal
        self._catalog = dict(catalog)

    def is_assembled_from(
        self,
        journal: Journal,
        catalog: Mapping[tuple[str, str], Channel],
    ) -> bool:
        """Whether effect, transport, and run facts inhabit one exact world."""

        return self._journal is journal and self._catalog.keys() == catalog.keys() and all(
            self._catalog[key] is channel for key, channel in catalog.items()
        )

    @property
    def profile(self) -> EffectProfile:
        return EffectProfile(
            kind=CHANNEL_SEND_EFFECT,
            recovery="reconcilable",
            simulation="supported",
        )

    async def execute(self, request: EffectRequest) -> EffectReceipt:
        intent = self._intent(request)
        channel = self._channel(intent)
        attestation_id = self._verified_attestation(request, intent)
        message = channel.append_request(intent, attestation_id)
        return _committed(request, message.message_id)

    async def reconcile(self, request: EffectRequest) -> EffectReceipt | None:
        """Load the exact message id and validate it against the intent.

        Found is ``committed``; absent permits execute; contradictory is damage.
        """

        intent = self._intent(request)
        channel = self._channel(intent)
        stored = channel.message(intent.message_id)
        if stored is None:
            return None
        # `append_request` is the one place that compares a stored message with
        # an intent, and it raises on a contradiction. Reusing it keeps one law.
        channel.append_request(intent, self._verified_attestation(request, intent))
        return _committed(request, stored.message_id)

    async def simulate(self, request: EffectRequest) -> EffectReceipt:
        """A counterfactual writes no message and consults no live channel."""

        intent = self._intent(request)
        return EffectReceipt(
            request_hash=request_hash(request),
            status="simulated",
            external_reference=str(intent.message_id),
            observed_state=None,
        )

    @staticmethod
    def _intent(request: EffectRequest) -> ChannelSendIntent:
        if request.kind != CHANNEL_SEND_EFFECT:
            raise ContractViolation(f"channel send adapter received kind {request.kind!r}")
        intent = ChannelSendIntent.model_validate_json(canonical_json(request.subject))
        if canonical_json(request.subject) != canonical_json(intent):
            raise ContractViolation(
                "channel send effect subject is not a lossless ChannelSendIntent"
            )
        return intent

    def _channel(self, intent: ChannelSendIntent) -> Channel:
        endpoint = (intent.channel_id, intent.channel_revision)
        channel = self._catalog.get(endpoint)
        if channel is None:
            raise ContractViolation(
                f"channel {endpoint!r} is not assembled in this process; "
                f"assembled: {sorted(self._catalog)}"
            )
        return channel

    def _verified_attestation(
        self,
        request: EffectRequest,
        intent: ChannelSendIntent,
    ) -> str:
        """A send crosses only under proof this exact message was authorized."""

        if request.attestation_id is None:
            raise ContractViolation("a channel send carries no attestation")
        attestation = self._journal.load_attestation(request.attestation_id)
        if attestation is None:
            raise JournalDamaged(
                f"channel send names attestation {request.attestation_id!r}, "
                "which the journal does not hold"
            )
        try:
            validated_channel_send_attestation(
                attestation,
                intent,
                expected_manifest_hash=request.manifest_hash,
            )
        except ValueError as exc:
            raise ContractViolation(str(exc)) from exc
        return attestation.attestation_id


def _committed(request: EffectRequest, message_id: object) -> EffectReceipt:
    return EffectReceipt(
        request_hash=request_hash(request),
        status="committed",
        external_reference=str(message_id),
        observed_state=None,
    )
