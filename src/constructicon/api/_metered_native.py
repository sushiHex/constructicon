"""Bind the native adapter revision to a fenced writer at the injection root."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeGuard, cast

from constructicon.core.errors import ContractViolation
from constructicon.core.metering import MeteringSource
from constructicon.core.native_operator import NativeOperatorLaunchIdentityV3
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
)
from constructicon.substrate.executors.claude_provider import (
    ClaudeOperatorHandle,
    ClaudeOperatorProvider,
)
from constructicon.substrate.executors.codex import CodexOperatorHandle, CodexOperatorProvider
from constructicon.substrate.journal.sqlite import SqliteJournal


def _codex_model(provider: CodexOperatorProvider) -> str:
    return provider.configured_model


def _claude_model(provider: ClaudeOperatorProvider) -> str:
    vendor = provider.launcher.claude
    if vendor is None:
        raise ContractViolation("the assembled Claude operator has no fixed model")
    return vendor.model


@dataclass(frozen=True)
class _MeteredRoute:
    """One admitted native route: its exact classes, its source and its fixed model."""

    provider: type
    handle: type
    source: MeteringSource
    model: Callable[[Any], str]


_ROUTES: tuple[_MeteredRoute, ...] = (
    _MeteredRoute(
        CodexOperatorProvider, CodexOperatorHandle, "codex_fresh_thread_total_v1", _codex_model),
    _MeteredRoute(
        ClaudeOperatorProvider, ClaudeOperatorHandle, "claude_main_loop_v1", _claude_model),
)
"""The admitted native routes. A third route is one row here; nothing else in
api names a vendor class."""


def _route(resource: object) -> _MeteredRoute | None:
    """The route whose provider class ``resource`` is exactly.

    Class identity, never equality or hashing: a subclass is not admitted, and
    neither is a class whose metaclass answers ``==`` for an admitted one.
    """
    for route in _ROUTES:
        if type(resource) is route.provider:
            return route
    return None


def is_metered_route(
    resource: object,
) -> TypeGuard[CodexOperatorProvider | ClaudeOperatorProvider]:
    """Whether ``resource`` is exactly one of the admitted native providers."""
    return _route(resource) is not None


@dataclass(frozen=True)
class MeteredNativeOperator:
    """Only the exact native routes can write actual metering observations."""

    journal: SqliteJournal
    provider: CodexOperatorProvider | ClaudeOperatorProvider

    @property
    def identity(self) -> NativeOperatorLaunchIdentityV3:
        return self.provider.identity

    @property
    def unavailable_reasons(self) -> tuple[str, ...]:
        return self.provider.unavailable_reasons

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        route = _route(self.provider)
        if route is None:
            raise ContractViolation("executor metering requires an exact supported native adapter")
        model = route.model(self.provider)
        meter = self.journal.executor_meter(
            context, revision=self.identity.revision, source=route.source, configured_model=model,
        )
        acquisition = await self.provider.acquire(context)
        handle = acquisition.resource
        # The route's own handle class: one vendor's provider never meters another's handle.
        if type(handle) is not route.handle:
            await self.provider.relinquish(acquisition)
            raise ContractViolation("executor metering requires an exact supported native handle")
        cast("CodexOperatorHandle | ClaudeOperatorHandle", handle).install_meter(meter)
        return acquisition

    async def close(
        self, acquisition: AcquiredCapability, disposition: Disposition,
    ) -> LeaseClosure:
        return await self.provider.close(acquisition, disposition)

    async def relinquish(self, acquisition: AcquiredCapability) -> None:
        await self.provider.relinquish(acquisition)

    async def reconcile(
        self, context: LeaseContext, stale: tuple[StaleAcquisition, ...],
    ) -> LeaseReconciliation:
        return await self.provider.reconcile(context, stale)
