"""Leased ownership of one fixed, credential-free scripted READ process.

Assembly supplies and seals the fixture command; this module implements no
model, vendor route, scheduler or second durable lease inventory.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
import weakref
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import ExecutionPath
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorLaunchIdentity,
    ExecutorOutcome,
    ExecutorProfile,
    TaskSpec,
)
from constructicon.core.grants import EffectiveGrants, Posture
from constructicon.core.identity import Digest, canonical_json, digest, parse_json_value
from constructicon.core.manifest import CapabilityBinding
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseClosure,
    LeaseContext,
    LeaseReconciliation,
    StaleAcquisition,
    WorkspaceView,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.substrate._lifetime import finish_owned
from constructicon.substrate.executors import pi_protocol, pi_read
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.executors.pi_read import PI_LIMITS, PI_PROFILE, PiReadExecutor
from constructicon.substrate.git.acquisition import (
    AcquisitionClosure,
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)
from constructicon.substrate.git.contained import ContainedWorkspace, ContainedWorkspaceProvider


class _Reference(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True, extra="forbid")

    schema_version: Literal[1] = 1
    acquisition: str
    revision: str
    run_id: str
    owner_epoch: int
    path: ExecutionPath
    manifest_hash: Digest
    binding: CapabilityBinding


class PiReadProvider:
    """A genuine scripted provider's identity, never real Pi availability."""

    def __init__(
        self, launcher: LinuxLauncher, command: tuple[str, ...], *,
        workspace_provider: ContainedWorkspaceProvider, workspace_capability_id: str,
        workspace_revision: str, acquisition_root: Path,
    ) -> None:
        if (launcher.vendor is not None or launcher.limits != PI_LIMITS
                or type(command) is not tuple or not command
                or any(type(argument) is not str or not argument or "\0" in argument
                       for argument in command)
                or len(canonical_json(command).encode()) > PI_LIMITS.input_bytes):
            raise ContractViolation("scripted READ requires fixed networkless launch inputs")
        executable = PurePosixPath(command[0])
        if not executable.is_absolute() or ".." in executable.parts:
            raise ContractViolation("scripted READ executable must be an absolute runtime path")
        if (not acquisition_root.is_absolute()
                or acquisition_root.resolve(strict=False) != acquisition_root
                or workspace_provider.posture is not Posture.READ
                or not workspace_capability_id.strip() or not workspace_revision.strip()):
            raise ContractViolation("scripted READ requires a canonical root and READ workspace")
        launcher.check_artifacts()  # Assembly fact; exchange owns every subsequent physical probe.
        self.launcher = launcher
        self.command = command
        self.workspace_provider = workspace_provider
        self.workspace_capability_id = workspace_capability_id
        self.workspace_revision = workspace_revision
        self.acquisition_root = acquisition_root
        self._workspace_owner = workspace_provider
        self._authority_owner = workspace_provider.authority
        self._launcher_owner = launcher
        self._launcher_root = launcher.root
        self.closure = AcquisitionClosure(workspace_provider.authority)
        self._custody = (acquisition_root, workspace_provider.root,
                         workspace_provider.authority.repository_id,
                         workspace_provider.authority._repo, self.closure,
                         workspace_provider.closure, self.closure.authority,
                         workspace_provider.closure.authority)
        self._handles: weakref.WeakKeyDictionary[PiReadHandle, LeaseContext] = (
            weakref.WeakKeyDictionary()
        )
        self._identity = self._derive_identity()
        self._qualified = False
        self._qualification_entered = False
        self._qualification_poisoned = False
        self._acquired = False

    @property
    def identity(self) -> ExecutorLaunchIdentity:
        return self._identity

    @property
    def profile(self) -> ExecutorProfile:
        return self.identity.profile

    @property
    def unavailable_reasons(self) -> tuple[str, ...]:
        if not self._qualified:
            return ("scripted READ assembly probe has not completed",)
        return ("scripted READ provider acquisition is spent",) if self._acquired else ()

    async def qualify(self, *, check_control: Callable[[], None] | None = None) -> None:
        """One benign existing-launcher proof before publishing fixture availability."""
        if self._qualification_entered:
            self._qualification_poisoned = True
            self._qualified = False
            raise ContractViolation("scripted READ assembly qualification is single-use")
        self._qualification_entered = True
        self._check_sealed()
        if check_control is not None:
            check_control()
        await self.launcher.probe()
        if check_control is not None:
            check_control()
        self._check_sealed()
        if self._qualification_poisoned:
            raise ContractViolation("scripted READ qualification was reentered")
        self._qualified = True

    def _derive_identity(self) -> ExecutorLaunchIdentity:
        runtime = self.launcher.root.resolve(strict=True)
        executable = (runtime / self.command[0].lstrip("/")).resolve(strict=True)
        if (not executable.is_relative_to(runtime) or not executable.is_file()
                or self.launcher.vendor is not None or self.launcher.limits != PI_LIMITS
                or self.workspace_provider is not self._workspace_owner
                or self.workspace_provider.authority is not self._authority_owner):
            raise ContractViolation("scripted READ assembly changed")
        workspace = self.workspace_provider
        configuration: dict[str, Any] = {
            "command": self.command,
            "workspace": {"capability_id": self.workspace_capability_id,
                          "revision": self.workspace_revision,
                          "target_ref": workspace.target_ref, "provider_id": workspace.provider_id,
                          "posture": workspace.posture.value},
        }
        return ExecutorLaunchIdentity(
            executable_digest=digest("pi-read-executable", 1, executable.read_bytes().hex()),
            runtime_digest=self.launcher.expected_runtime,
            adapter_revision=digest("pi-read-owned-adapter", 1, (
                inspect.getsource(sys.modules[__name__]) + inspect.getsource(pi_read)
            )),
            decoder_revision=digest("pi-read-decoder", 1, inspect.getsource(pi_protocol)),
            isolation_revision=self.launcher.revision,
            configuration_digest=digest("pi-read-configuration", 1, configuration),
            limits_digest=digest("pi-read-limits", 1, asdict(self.launcher.limits)),
            profile=PI_PROFILE, provider_route=None,
        )

    def _check_custody(self) -> None:
        local = (self.acquisition_root, self.workspace_provider.root,
                 self.workspace_provider.authority.repository_id,
                 self.workspace_provider.authority._repo, self.closure,
                 self.workspace_provider.closure, self.closure.authority,
                 self.workspace_provider.closure.authority)
        if (self.workspace_provider is not self._workspace_owner
                or self.workspace_provider.authority is not self._authority_owner
                or local != self._custody):
            raise ContractViolation("scripted READ local custody drifted")

    def _check_sealed(self) -> None:
        self._check_custody()
        if (self.launcher is not self._launcher_owner or self.launcher.root != self._launcher_root
                or self._derive_identity() != self.identity):
            raise ContractViolation("scripted READ content or configuration drifted")

    def _check_binding(self, context: LeaseContext) -> None:
        grants = context.binding.effective_grants
        if (not self._qualified or context.binding.revision != self.identity.revision
                or self.profile.grant_faults(grants)
                or grants.model_selection.kind != "explicit"
                or grants.model_selection.model != "fixture/pi-read" or grants.effort != "off"):
            raise ContractViolation("scripted READ acquisition differs from its sealed invocation")

    def _check_context(self, context: LeaseContext) -> None:
        self._check_binding(context)
        if context.check_control is None:
            raise ContractViolation("scripted READ live invocation has no owner control")
        context.check_control()

    def _reference(self, context: LeaseContext, *, epoch: int | None = None) -> str:
        actual_epoch = context.run_lease.epoch if epoch is None else epoch
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        reference = _Reference(
            acquisition=acquisition_id_for(logical, actual_epoch), revision=self.identity.revision,
            run_id=context.run_lease.run_id,
            owner_epoch=actual_epoch, path=context.path, manifest_hash=context.manifest_hash,
            binding=context.binding,
        )
        return canonical_json(reference.model_dump(mode="json"))

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        self._check_context(context)
        if self._acquired:
            raise ContractViolation("scripted READ provider acquisition is spent")
        self._acquired = True
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        acquired = acquisition_id_for(logical, context.run_lease.epoch)
        handle = PiReadHandle(self, context, AcquisitionPaths(self.acquisition_root, acquired))
        self._handles[handle] = context
        return AcquiredCapability(resource=handle, lease_id=logical, acquisition_id=acquired,
                                  resource_ref=handle.reference, materialize=handle.materialize)

    def _own(self, acquired: AcquiredCapability) -> PiReadHandle:
        handle = acquired.resource
        if not isinstance(handle, PiReadHandle):
            raise ContractViolation("scripted READ operation requires its own acquisition")
        logical, paths, reference = self._check_handle(handle)
        if (acquired.lease_id != logical or acquired.acquisition_id != paths.acquisition_id
                or acquired.resource_ref != reference):
            raise ContractViolation("scripted READ acquisition wrapper changed")
        return handle

    def _check_handle(self, handle: PiReadHandle) -> tuple[str, AcquisitionPaths, str]:
        original = self._handles.get(handle)
        if handle.provider is not self or original is None:
            raise ContractViolation("scripted READ operation requires its minted handle")
        logical = lease_id_for(original.run_lease.run_id, original.path, original.binding.binding)
        paths = AcquisitionPaths(self._custody[0], acquisition_id_for(
            logical, original.run_lease.epoch,
        ))
        reference = self._reference(original)
        if (handle.lease_id != logical or handle.paths != paths or handle.reference != reference
                or handle.context is not original):
            raise ContractViolation("scripted READ handle coordinates changed")
        return logical, paths, reference

    async def close(self, acquisition: AcquiredCapability,
                    disposition: Disposition) -> LeaseClosure:
        await self._own(acquisition).close(disposition)
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def relinquish(self, acquisition: AcquiredCapability) -> None:
        await self._own(acquisition).relinquish()

    async def reconcile(self, context: LeaseContext,
                        stale: tuple[StaleAcquisition, ...]) -> LeaseReconciliation:
        # Recovery is journal-owned and intentionally supplies neither a live
        # invocation callback nor source_graph_hash. The manifest binds the graph.
        self._check_binding(context)
        self._check_sealed()
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        pending: list[tuple[AcquisitionPaths, StaleAcquisition]] = []
        seen: set[str] = set()
        for item in stale:
            row = item.lease
            if (row.lease_id != logical or row.run_id != context.run_lease.run_id
                    or row.path != context.path or row.binding_id != context.binding.binding
                    or row.acquisition_epoch >= context.run_lease.epoch or row.state != "active"
                    or row.resource_ref is None or len(row.resource_ref.encode()) > 65536):
                raise ContractViolation("scripted READ recovery row is not this stale invocation")
            try:
                parsed = parse_json_value(row.resource_ref)
                reference = _Reference.model_validate_json(canonical_json(parsed))
            except (ValueError, RecursionError) as error:
                raise ContractViolation("scripted READ recovery reference is invalid") from error
            if (reference.owner_epoch <= 0
                    or self._reference(context, epoch=row.acquisition_epoch) != row.resource_ref
                    or reference.acquisition in seen):
                raise ContractViolation("scripted READ recovery reference contradicts its row")
            seen.add(reference.acquisition)
            pending.append((AcquisitionPaths(self.acquisition_root, reference.acquisition), item))
        # The entire batch is validated before the first permanent fence.
        for paths, item in pending:
            self._check_binding(context)
            self._check_custody()
            await dispose_acquisition(self.closure, paths, disposition=item.disposition)
            self._check_binding(context)
            self._check_custody()
        return LeaseReconciliation(reaped=tuple(item.lease.resource_ref for _, item in pending
                                                if item.lease.resource_ref is not None))


class PiReadHandle:
    """One retained acquisition guard and one single-use, deadline-bound task."""

    def __init__(self, provider: PiReadProvider, context: LeaseContext,
                 paths: AcquisitionPaths) -> None:
        self.provider = provider
        self.context = context
        self.paths = paths
        self.reference = provider._reference(context)
        self.lease_id = lease_id_for(context.run_lease.run_id, context.path,
                                     context.binding.binding)
        self.entered = self.ready = self.closed = self.executed = self.poisoned = False
        self._deadline: float | None = None
        self._guard_owner: AbstractAsyncContextManager[int] | None = None
        self._guard_fd: int | None = None
        self._materialization: asyncio.Task[None] | None = None
        self.active: asyncio.Task[ExecutorOutcome] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._close_disposition: Disposition | None = None
        self._observed_failures: set[int] = set()

    @property
    def profile(self) -> ExecutorProfile:
        return self.provider.profile

    @property
    def deadline(self) -> float | None:
        return self._deadline

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        faults = self.profile.grant_faults(grants)
        if (grants.model_selection.kind != "explicit"
                or grants.model_selection.model != "fixture/pi-read" or grants.effort != "off"):
            faults += ("scripted READ requires its explicit fixture model and effort",)
        return faults

    def _check(self) -> None:
        self.provider._check_handle(self)
        if self.closed or self.poisoned or self.provider._reference(self.context) != self.reference:
            raise ContractViolation("scripted READ acquisition lost local invocation ownership")
        self.provider._check_context(self.context)
        self.provider._check_sealed()
        if self.closed or self.poisoned:
            raise ContractViolation("scripted READ acquisition closed during its control check")

    async def materialize(self) -> None:
        if self.closed or self.entered:
            raise ContractViolation("scripted READ materialization is closed or already entered")
        self.entered = True
        self._deadline = (asyncio.get_running_loop().time()
                          + self.context.binding.effective_grants.timeout_s)
        self._materialization = asyncio.create_task(self._materialize_owned())
        try:
            async with asyncio.timeout_at(self.deadline):
                await self._materialization
        except BaseException:
            self._observe_failure(self._materialization)
            raise

    def _observe_failure(self, task: asyncio.Task[Any]) -> None:
        if task.done() and not task.cancelled():
            error = task.exception()
            if error is not None:
                self._observed_failures.add(id(error))

    async def _materialize_owned(self) -> None:
        self._check()
        owner = acquisition_guard(self.paths)
        guard = await owner.__aenter__()
        try:
            self._check()
            await finish_owned(asyncio.create_task(asyncio.to_thread(
                self.provider.closure.require_open, self.paths,
            )))
            self._check()
            self.provider.closure.require_open(self.paths)
            self._guard_owner, self._guard_fd = owner, guard
            self.ready = True
        except BaseException as primary:
            try:
                await finish_owned(asyncio.create_task(owner.__aexit__(None, None, None)))
            except BaseException as secondary:
                raise BaseExceptionGroup(
                    "READ startup and release failed", [primary, secondary],
                ) from None
            raise

    def _workspace(self, view: WorkspaceView | None) -> ContainedWorkspace:
        workspace = self.provider.workspace_provider.owned_view(view, self.context)
        actual, expected = workspace.context, self.context
        if actual.check_control is None:
            raise ContractViolation("scripted READ workspace has no invocation control")
        actual.check_control()
        self.provider.workspace_provider.owned_view(view, self.context)
        if (actual.run_lease.owner_id != expected.run_lease.owner_id
                or actual.binding.capability_id != self.provider.workspace_capability_id
                or actual.binding.revision != self.provider.workspace_revision
                or canonical_json(actual.binding.effective_grants)
                != canonical_json(expected.binding.effective_grants)):
            raise ContractViolation("scripted READ workspace owner or binding differs")
        return workspace

    async def execute(self, task: TaskSpec, *, workspace: WorkspaceView | None,
                      grants: EffectiveGrants) -> ExecutorOutcome:
        if self.executed:
            self.poisoned = True
            raise ContractViolation("scripted READ acquisition executes once")
        if not self.ready or self.closed:
            raise ContractViolation("scripted READ acquisition is not materialized and open")
        self.executed = True
        self._check()
        if (canonical_json(grants) != canonical_json(self.context.binding.effective_grants)
                or self.validate_grants(grants)):
            raise ContractViolation("scripted READ call differs from its sealed grants")
        view = self._workspace(workspace)
        assert self.deadline is not None
        self.active = asyncio.create_task(self._execute_owned(task, view, grants))
        try:
            async with asyncio.timeout_at(self.deadline):
                return await self.active
        except BaseException:
            self._observe_failure(self.active)
            raise

    async def _execute_owned(self, task: TaskSpec, view: ContainedWorkspace,
                             grants: EffectiveGrants) -> ExecutorOutcome:
        async with view.use() as workspace_guard:
            self._check()
            self._workspace(view)
            self.provider.closure.require_open(self.paths)
            self.provider.workspace_provider.closure.require_open(view.paths)
            assert self._guard_fd is not None and self.deadline is not None
            executor = PiReadExecutor(self.provider.launcher, self.provider.command,
                                      guard_fds=(self._guard_fd, workspace_guard),
                                      check_control=self._check, _deadline=self.deadline)
            result = await executor.execute(task, workspace=view, grants=grants)
            self._check()
            self._workspace(view)
            return result

    async def _join_and_release(self) -> list[BaseException]:
        errors: list[BaseException] = []
        for task in (self._materialization, self.active):
            if task is None:
                continue
            was_pending = not task.done()
            if was_pending:
                task.cancel()
            try:
                await finish_owned(task)
            except asyncio.CancelledError:
                if not was_pending:
                    # Earlier invocation cancellation is already its caller's fact.
                    pass
            except BaseException as error:
                if id(error) not in self._observed_failures:
                    errors.append(error)
        owner, self._guard_owner = self._guard_owner, None
        self._guard_fd = None
        if owner is not None:
            try:
                await owner.__aexit__(None, None, None)
            except BaseException as error:
                errors.append(error)
        return errors

    async def _cleanup_owned(self, disposition: Disposition | None) -> None:
        errors: list[BaseException] = []
        if disposition is not None and self.entered:
            try:
                self.provider._check_custody()
                await finish_owned(asyncio.create_task(asyncio.to_thread(
                    self.provider.closure.commit, self.paths,
                )))
            except BaseException as error:
                errors.append(error)
        errors.extend(await self._join_and_release())
        if disposition is not None and self.entered and not errors:
            try:
                self.provider._check_custody()
                await dispose_acquisition(self.provider.closure, self.paths,
                                           disposition=disposition)
            except BaseException as error:
                errors.append(error)
        if len(errors) == 1:
            raise errors[0]
        if errors:
            raise BaseExceptionGroup("scripted READ cleanup failed", errors)

    async def close(self, disposition: Disposition) -> None:
        if self._cleanup is None:
            self.closed = True
            self._close_disposition = disposition
            self._cleanup = asyncio.create_task(self._cleanup_owned(disposition))
        elif self._close_disposition != disposition:
            raise ContractViolation("scripted READ close disposition changed")
        await finish_owned(self._cleanup)

    async def relinquish(self) -> None:
        if self._cleanup is None:
            self.closed = True
            self._cleanup = asyncio.create_task(self._cleanup_owned(None))
        await finish_owned(self._cleanup)
