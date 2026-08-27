"""A fake external system used by the credential-free lifecycle tests."""

from __future__ import annotations

from dataclasses import dataclass, field

from constructicon.core.effect import (
    EffectProfile,
    EffectReceipt,
    EffectRequest,
    request_hash,
)


@dataclass
class FakeAnnounceEffect:
    _ledger: dict[str, EffectReceipt] = field(default_factory=dict)
    executions: int = 0
    reconciliations: int = 0
    simulations: int = 0

    @property
    def profile(self) -> EffectProfile:
        return EffectProfile(
            kind="announce",
            recovery="native_idempotency",
            simulation="supported",
        )

    async def execute(self, request: EffectRequest) -> EffectReceipt:
        existing = self._ledger.get(str(request.idempotency_key))
        if existing is not None:
            return existing
        self.executions += 1
        receipt = EffectReceipt(
            request_hash=request_hash(request),
            status="committed",
            external_reference=f"announcement-{self.executions}",
            observed_state={"subject": request.subject},
        )
        self._ledger[str(request.idempotency_key)] = receipt
        return receipt

    async def reconcile(self, request: EffectRequest) -> EffectReceipt | None:
        self.reconciliations += 1
        return self._ledger.get(str(request.idempotency_key))

    async def simulate(self, request: EffectRequest) -> EffectReceipt:
        """Return a truthful preview without touching the external ledger."""

        self.simulations += 1
        return EffectReceipt(
            request_hash=request_hash(request),
            status="simulated",
            external_reference=None,
            observed_state={"subject": request.subject, "external_transition": False},
        )
