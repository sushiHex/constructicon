"""NodeContext — the only capabilities an atomic implementation ever holds (I3).

A node receives exactly what its admitted bindings grant: injected capability
objects, sealed grants, and the effect boundary. There is no ambient authority
and no global bus.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Protocol

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.effect import EffectReceipt
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import EffectiveGrants
from constructicon.core.identity import JsonValue


class ChannelFacade(Protocol):
    """The only channel surface component code ever holds.

    Where the message goes, under whose authority, on which ports, and under
    which contracts were all sealed at admission. The component supplies a
    payload and nothing else — there is nothing here to select.
    """

    def ask(self, payload: Any) -> Awaitable[JsonValue]:
        """Send this invocation's one request, or return its stored reply.

        Raises ``InvocationParked`` when no reply exists yet: waiting is not
        failing, and the run must not hold anything open while a human thinks.
        """
        ...


class EffectBoundary(Protocol):
    def __call__(
        self,
        kind: str,
        subject: dict[str, Any],
        *,
        attestation_id: str | None = None,
    ) -> Awaitable[EffectReceipt]: ...


class NodeContext:
    def __init__(
        self,
        *,
        run_id: RunId,
        path: ExecutionPath,
        capabilities: Mapping[str, object],
        grants: EffectiveGrants,
        effect: EffectBoundary,
        channels: Mapping[str, ChannelFacade] | None = None,
    ) -> None:
        self.run_id = run_id
        self.path = path
        self.grants = grants
        self._capabilities = dict(capabilities)
        self._effect = effect
        self._channels = dict(channels or {})

    def capability(self, alias: str) -> object:
        try:
            return self._capabilities[alias]
        except KeyError:
            granted = sorted(self._capabilities)
            raise ContractViolation(
                f"node {self.path.render()} holds no capability {alias!r}; "
                f"granted: {granted}"
            ) from None

    def channel(self, alias: str) -> ChannelFacade:
        try:
            return self._channels[alias]
        except KeyError:
            raise ContractViolation(
                f"node {self.path.render()} holds no channel binding {alias!r}; "
                f"granted: {sorted(self._channels)}"
            ) from None

    async def effect(
        self,
        kind: str,
        subject: dict[str, Any],
        *,
        attestation_id: str | None = None,
    ) -> EffectReceipt:
        return await self._effect(kind, subject, attestation_id=attestation_id)


NodeImpl = Callable[[NodeContext, Mapping[str, Any]], Awaitable[Mapping[str, Any]]]
"""An atomic component's in-process implementation.

Receives the context and one value per bound input port; returns one value per
declared output port. The walker validates presence against the declared
contract before any envelope is emitted.
"""
