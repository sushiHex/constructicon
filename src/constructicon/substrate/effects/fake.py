"""The fake effect boundary — proves the effect law without touching the world.

Every REAL external transition is recorded in a ``FakeExternalLedger`` — an
independently durable second store, so replay/resume/reproduce/crash tests can
assert against an "outside" the journal cannot retroactively edit. The
acceptance tests assert that no idempotency key ever grows the ledger twice:
once an effect has a committed receipt, no retry causes a second externally
visible transition.
"""

from __future__ import annotations

from constructicon.core.effect import (
    EffectProfile,
    EffectReceipt,
    EffectRequest,
    request_hash,
)
from constructicon.substrate.external.fake import FakeExternalLedger


class FakeAnnounceEffect:
    """kind="announce" with native idempotency, like a well-behaved external API."""

    def __init__(self, ledger: FakeExternalLedger | None = None) -> None:
        self.ledger = ledger if ledger is not None else FakeExternalLedger()

    @property
    def profile(self) -> EffectProfile:
        return EffectProfile(kind="announce", recovery="native_idempotency")

    @property
    def executions(self) -> list[EffectRequest]:
        """One entry per REAL external transition, in execution order."""
        return [
            EffectRequest.model_validate_json(request_json)
            for request_json in self.ledger.announce_requests()
        ]

    async def execute(self, request: EffectRequest) -> EffectReceipt:
        key = str(request.idempotency_key)
        existing = self.ledger.announce_receipt(key)
        if existing is not None:  # native idempotency: same key, same outcome
            return EffectReceipt.model_validate_json(existing)
        receipt = EffectReceipt(
            request_hash=request_hash(request),
            status="committed",
            external_reference=f"announce/{self.ledger.announce_count() + 1}",
            observed_state={"subject": request.subject},
        )
        self.ledger.record_announce(
            key, request.model_dump_json(), receipt.model_dump_json()
        )
        return receipt

    async def reconcile(self, request: EffectRequest) -> EffectReceipt | None:
        existing = self.ledger.announce_receipt(str(request.idempotency_key))
        return EffectReceipt.model_validate_json(existing) if existing else None
