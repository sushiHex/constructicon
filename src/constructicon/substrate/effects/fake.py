"""The fake effect boundary — proves live and simulated effect laws.

Real transitions remain in an independently durable ``FakeExternalLedger``.
Simulation is process-local evidence only and never changes that ledger.
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
    """kind="announce" with native idempotency and truthful simulation."""

    def __init__(self, ledger: FakeExternalLedger | None = None) -> None:
        self.ledger = ledger if ledger is not None else FakeExternalLedger()
        self._simulations: list[EffectRequest] = []

    @property
    def profile(self) -> EffectProfile:
        return EffectProfile(
            kind="announce",
            recovery="native_idempotency",
            simulation="supported",
        )

    @property
    def executions(self) -> list[EffectRequest]:
        """One entry per real external transition, in execution order."""
        return [
            EffectRequest.model_validate_json(request_json)
            for request_json in self.ledger.announce_requests()
        ]

    @property
    def simulations(self) -> tuple[EffectRequest, ...]:
        return tuple(self._simulations)

    async def execute(self, request: EffectRequest) -> EffectReceipt:
        key = str(request.idempotency_key)
        existing = self.ledger.announce_receipt(key)
        if existing is not None:
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

    async def simulate(self, request: EffectRequest) -> EffectReceipt:
        self._simulations.append(request)
        return EffectReceipt(
            request_hash=request_hash(request),
            status="simulated",
            external_reference=None,
            observed_state={
                "subject": request.subject,
                "external_transition": False,
            },
        )
