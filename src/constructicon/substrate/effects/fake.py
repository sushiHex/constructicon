"""The fake effect boundary — proves the effect law without touching the world.

``executions`` records every real external transition the adapter performed.
The M1 acceptance test asserts that replay, resume, and reproduce never grow
it for the same idempotency key: once an effect has a committed receipt, no
retry causes a second externally visible transition.
"""

from __future__ import annotations

from constructicon.core.effect import (
    EffectProfile,
    EffectReceipt,
    EffectRequest,
    request_hash,
)


class FakeAnnounceEffect:
    """kind="announce" with native idempotency, like a well-behaved external API."""

    def __init__(self) -> None:
        self.executions: list[EffectRequest] = []
        self._by_key: dict[str, EffectReceipt] = {}

    @property
    def profile(self) -> EffectProfile:
        return EffectProfile(kind="announce", recovery="native_idempotency")

    async def execute(self, request: EffectRequest) -> EffectReceipt:
        key = str(request.idempotency_key)
        existing = self._by_key.get(key)
        if existing is not None:  # native idempotency: same key, same outcome
            return existing
        self.executions.append(request)
        receipt = EffectReceipt(
            request_hash=request_hash(request),
            status="committed",
            external_reference=f"announce/{len(self.executions)}",
            observed_state={"subject": request.subject},
        )
        self._by_key[key] = receipt
        return receipt

    async def reconcile(self, request: EffectRequest) -> EffectReceipt | None:
        return self._by_key.get(str(request.idempotency_key))
