"""Bind the native adapter revision to a fenced writer at the injection root."""

from __future__ import annotations

from dataclasses import dataclass

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
        source: MeteringSource
        if type(self.provider) is CodexOperatorProvider:
            source = "codex_fresh_thread_total_v1"
            model = self.provider.configured_model
        elif type(self.provider) is ClaudeOperatorProvider:
            source = "claude_main_loop_v1"
            vendor = self.provider.launcher.claude
            if vendor is None:
                raise ContractViolation("the assembled Claude operator has no fixed model")
            model = vendor.model
        else:
            raise ContractViolation("executor metering requires an exact supported native adapter")
        meter = self.journal.executor_meter(
            context, revision=self.identity.revision, source=source, configured_model=model,
        )
        acquisition = await self.provider.acquire(context)
        handle = acquisition.resource
        if type(handle) is CodexOperatorHandle or type(handle) is ClaudeOperatorHandle:
            handle.install_meter(meter)
        else:
            await self.provider.relinquish(acquisition)
            raise ContractViolation("executor metering requires an exact supported native handle")
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
