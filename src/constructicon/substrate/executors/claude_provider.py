"""One authorized Claude READ invocation over the existing leased task seam.

This adapter never publishes general subscription availability. Assembly may
authorize one exact qualification run; the exclusive attempt survives replay.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import os
import re
import sys
import weakref
from contextlib import AbstractAsyncContextManager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from constructicon.core import claude_read_observation
from constructicon.core import qualification as qualification_law
from constructicon.core.address import GitSha
from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorOutcome,
    ExecutorSuccess,
    TaskSpec,
)
from constructicon.core.grants import EffectiveGrants, Posture
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.native_operator import (
    NativeOperatorExecutorProfileV3,
    NativeOperatorLaunchIdentityV3,
)
from constructicon.core.qualification import QualificationAuthorization
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
from constructicon.substrate.executors import (
    attempt_record,
    claude_initialize,
    claude_native,
    claude_native_events,
    claude_protocol,
    claude_read,
    claude_read_worker,
    claude_startup,
)
from constructicon.substrate.executors.attempt_record import AttemptRecord, Dispatch
from constructicon.substrate.executors.claude_native import (
    ClaudeNativeRecipe,
    ClaudeNativeStoreMount,
)
from constructicon.substrate.executors.claude_protocol import ClaudeAuthMode
from constructicon.substrate.executors.claude_read_worker import (
    READ_WORKER_LIMITS,
    ClaudeReadWorker,
)
from constructicon.substrate.executors.egress import (
    MAX_SOCKET_PATH_BYTES,
    SOCKET_NAME,
    EgressPolicy,
    EgressRelay,
    identity_digests,
)
from constructicon.substrate.executors.linux import LinuxLauncher
from constructicon.substrate.executors.operator_store import (
    BindingCheck,
    BindingStore,
    HeldStoreLock,
)
from constructicon.substrate.git.acquisition import (
    AcquisitionClosure,
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)
from constructicon.substrate.git.contained import ContainedWorkspaceProvider

READ_CATALOG = ("read_file",)
UNAVAILABLE = (
    "Claude READ subscription qualification has not established production availability",
)


class _LocalClose(ContractViolation):
    """The acquisition's own close revoked an operation before its resume."""


def identity_fields(
    launcher: LinuxLauncher, worker_launcher: LinuxLauncher, *,
    workspace_provider: ContainedWorkspaceProvider, workspace_capability_id: str,
    workspace_revision: str, mode: ClaudeAuthMode,
    expected_base: GitSha,
) -> dict[str, Digest]:
    """Actual recipe facts; conformance remains an independent assembly input."""
    fields = _recipe_fields(
        launcher, worker_launcher, workspace_provider=workspace_provider,
        workspace_capability_id=workspace_capability_id, workspace_revision=workspace_revision,
        mode=mode,
        expected_base=expected_base,
    )
    assert launcher.claude is not None
    with (launcher.claude.tree / "claude").open("rb") as executable:
        fields["executable_digest"] = Digest("sha256:" + hashlib.file_digest(
            executable, "sha256",
        ).hexdigest())
    return fields


def _recipe_fields(
    launcher: LinuxLauncher, worker_launcher: LinuxLauncher, *,
    workspace_provider: ContainedWorkspaceProvider, workspace_capability_id: str,
    workspace_revision: str, mode: ClaudeAuthMode,
    expected_base: GitSha,
) -> dict[str, Digest]:
    vendor = launcher.claude
    if vendor is None:
        raise ContractViolation("Claude READ requires its native vendor recipe")
    return {
        "runtime_digest": digest("claude-read-runtimes", 1,
                                 (launcher.expected_runtime, worker_launcher.expected_runtime,
                                  workspace_provider.launcher.expected_runtime)),
        "adapter_revision": ADAPTER_REVISION,
        "decoder_revision": PROTOCOL_REVISION,
        "callback_protocol_revision": PROTOCOL_REVISION,
        "callback_catalog_digest": digest("claude-read-catalog", 1, claude_read.READ_TOOL),
        "isolation_revision": digest("claude-read-isolation", 1,
                                     (launcher.revision, worker_launcher.revision,
                                      workspace_provider.launcher.revision)),
        "configuration_digest": digest("claude-read-configuration", 1, {
            "command": vendor.command, "mode": mode.value,
            "workspace_capability_id": workspace_capability_id,
            "workspace_revision": workspace_revision,
            "workspace_provider_id": workspace_provider.provider_id,
            "workspace_target_ref": workspace_provider.target_ref,
            "workspace_base": expected_base,
            "workspace_posture": workspace_provider.posture,
            "workspace_repository": workspace_provider.authority.repository_id,
        }),
        "limits_digest": digest("claude-read-limits", 1,
                                (asdict(launcher.limits), asdict(worker_launcher.limits),
                                 asdict(workspace_provider.launcher.limits))),
    }


class ClaudeOperatorProvider:
    """An unavailable-by-default READ provider with one trusted run exception."""

    def __init__(
        self, *, launcher: LinuxLauncher, worker_launcher: LinuxLauncher,
        profile: NativeOperatorExecutorProfileV3, identity: NativeOperatorLaunchIdentityV3,
        binding_store: BindingStore, closure: AcquisitionClosure,
        workspace_provider: ContainedWorkspaceProvider, workspace_capability_id: str,
        workspace_revision: str, acquisition_root: Path, egress: EgressPolicy,
        mode: ClaudeAuthMode, expected_base: GitSha,
        qualification: QualificationAuthorization | None = None,
    ) -> None:
        if (type(launcher) is not LinuxLauncher or type(worker_launcher) is not LinuxLauncher
                or type(workspace_provider) is not ContainedWorkspaceProvider
                or type(mode) is not ClaudeAuthMode
                or launcher.claude is None or launcher.vendor is not None
                or launcher.claude_recipe is not ClaudeNativeRecipe.STREAM_JSON
                or worker_launcher.vendor is not None or worker_launcher.claude is not None
                or worker_launcher.limits != READ_WORKER_LIMITS
                or workspace_provider.posture is not Posture.READ
                or type(workspace_provider.launcher) is not LinuxLauncher
                or workspace_provider.launcher.vendor is not None
                or workspace_provider.launcher.claude is not None
                or re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", expected_base) is None
                or profile.posture is not Posture.READ
                or profile.grant_policy.tool_sets != (READ_CATALOG,)
                or not profile.grant_policy.workspace_required
                or profile.grant_policy.environment_names
                or profile.isolation.filesystem != "read_only_snapshot"
                or profile.structured_output
                or identity.profile != profile or binding_store.sealed != identity.store
                or closure.authority is not workspace_provider.authority
                or not workspace_capability_id.strip() or not workspace_revision.strip()):
            raise ContractViolation("Claude READ requires its exact native and worker recipe")
        roots = (acquisition_root, workspace_provider.root, binding_store.root)
        if any(not root.is_absolute() or root.resolve(strict=False) != root for root in roots):
            raise ContractViolation("Claude READ requires canonical custody roots")
        if any(a == b or a.is_relative_to(b) or b.is_relative_to(a)
               for index, a in enumerate(roots) for b in roots[index + 1:]):
            raise ContractViolation("Claude READ custody roots must be disjoint")
        if len(os.fsencode(AcquisitionPaths(acquisition_root, "acq-" + "0" * 32).payload
                           / SOCKET_NAME)) > MAX_SOCKET_PATH_BYTES:
            raise ContractViolation("Claude READ acquisition root exceeds the relay path bound")
        self.launcher, self.worker_launcher = launcher, worker_launcher
        self.profile, self._identity = profile, identity
        self.binding_store, self.closure = binding_store, closure
        self.workspace_provider = workspace_provider
        self.workspace_capability_id, self.workspace_revision = (
            workspace_capability_id, workspace_revision,
        )
        self.acquisition_root = acquisition_root
        self.egress, self.mode = egress, mode
        self.expected_base = expected_base
        if qualification is not None:
            try:
                qualification = QualificationAuthorization.model_validate_json(
                    qualification.model_dump_json(),
                )
            except (AttributeError, ValueError) as error:
                raise ContractViolation("Claude READ qualification is invalid") from error
            if (qualification.stage != "qualification-read"
                    or qualification.revision != identity.revision
                    or qualification.operator_binding_digest
                    != identity.store.operator_binding_digest
                    or qualification.grants is None or self._grant_faults(qualification.grants)):
                raise ContractViolation("Claude READ authorization differs from its sealed recipe")
        self.qualification = qualification
        self._handles: weakref.WeakKeyDictionary[
            ClaudeOperatorHandle, tuple[LeaseContext, AttemptRecord]
        ] = (
            weakref.WeakKeyDictionary()
        )
        # Retain authority objects and locators independently of mutable attributes.
        self._custody = self._custody_facts()
        fields = identity_fields(
            launcher, worker_launcher, workspace_provider=workspace_provider,
            workspace_capability_id=workspace_capability_id, workspace_revision=workspace_revision,
            mode=mode,
            expected_base=expected_base,
        )
        if any(getattr(identity, name) != value for name, value in fields.items()):
            raise ContractViolation("Claude READ published identity differs from actual artifacts")
        self._check_sealed()

    @property
    def identity(self) -> NativeOperatorLaunchIdentityV3:
        return self._identity

    @property
    def unavailable_reasons(self) -> tuple[str, ...]:
        return UNAVAILABLE

    def authorizes_admission(self, *, source_graph_hash: Digest, capability_id: str) -> bool:
        authorization = self.qualification
        return authorization is not None and authorization.admits(
            source_graph_hash=source_graph_hash, capability_id=capability_id,
            revision=self.identity.revision,
        )

    def _custody_facts(self) -> tuple[object, ...]:
        workspace = self.workspace_provider
        return (self.launcher, self.launcher.root, self.worker_launcher, self.worker_launcher.root,
                self.binding_store, self.binding_store.root, self.closure, self.closure.authority,
                workspace, workspace.root, workspace.authority, workspace.authority._repo,
                workspace.launcher,
                workspace.closure, workspace.closure.authority, self.acquisition_root,
                self.qualification, self.egress, self.mode, self.expected_base)

    def _check_sealed(self) -> None:
        if self._custody_facts() != self._custody:
            raise ContractViolation("Claude READ custody changed")
        fields = _recipe_fields(
            self.launcher, self.worker_launcher, workspace_provider=self.workspace_provider,
            workspace_capability_id=self.workspace_capability_id,
            workspace_revision=self.workspace_revision, mode=self.mode,
            expected_base=self.expected_base,
        )
        if (self.profile != self.identity.profile
                or self.binding_store.sealed != self.identity.store
                or any(getattr(self.identity, name) != value for name, value in fields.items())
                or any(getattr(self.identity.egress, name) != value
                       for name, value in identity_digests(self.egress).items())):
            raise ContractViolation("Claude READ published identity differs from its actual recipe")

    def _grant_faults(self, grants: EffectiveGrants) -> tuple[str, ...]:
        vendor = self.launcher.claude
        faults = self.profile.grant_faults(grants)
        if (vendor is None or grants.model_selection.model != vendor.model
                or grants.effort != vendor.effort or grants.env_allowlist):
            faults += ("Claude READ requires its fixed model, effort and empty environment",)
        if self.profile.subscription_overage != "operator_authorized":
            faults += ("Claude READ has not proved enforcement of forbidden overages",)
        return faults

    def _check_context(self, context: LeaseContext) -> None:
        authorization = self.qualification
        if authorization is None:
            raise ContractViolation("an unavailable Claude READ provider cannot acquire")
        faults = authorization.acquisition_faults(
            run_id=context.run_lease.run_id, path=context.path, binding=context.binding.binding,
            source_graph_hash=context.source_graph_hash,
            capability_id=context.binding.capability_id,
            revision=context.binding.revision,
            operator_binding_digest=self.identity.store.operator_binding_digest,
            grants=context.binding.effective_grants, epoch=context.run_lease.epoch,
            now=datetime.now(UTC),
        ) + self._grant_faults(context.binding.effective_grants)
        if faults:
            raise ContractViolation("Claude READ qualification acquisition refused")
        if context.check_control is None:
            raise ContractViolation("Claude READ requires invocation control")
        context.check_control()

    def _reference(self, context: LeaseContext, *, epoch: int | None = None) -> str:
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        return canonical_json({
            "schema_version": 1,
            "acquisition": acquisition_id_for(logical, context.run_lease.epoch if epoch is None
                                               else epoch),
            "binding": self.identity.store.operator_binding_digest,
            "revision": self.identity.revision, "run": context.run_lease.run_id,
            "path": context.path, "manifest": context.manifest_hash,
        })

    async def acquire(self, context: LeaseContext) -> AcquiredCapability:
        self._check_sealed()
        self._check_context(context)
        self._check_workspace_base()
        authorization = self.qualification
        assert authorization is not None and authorization.attempt_record is not None
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        acquisition = acquisition_id_for(logical, context.run_lease.epoch)
        attempt = AttemptRecord.reserve(Path(authorization.attempt_record), {
            "authorization_id": authorization.authorization_id,
            "run_id": context.run_lease.run_id, "epoch": context.run_lease.epoch,
            "acquisition_id": acquisition,
        })
        handle = ClaudeOperatorHandle(self, context, AcquisitionPaths(self.acquisition_root,
                                                                      acquisition), attempt)
        self._handles[handle] = context, attempt
        return AcquiredCapability(
            resource=handle, lease_id=logical, acquisition_id=acquisition,
            resource_ref=self._reference(context), materialize=handle.materialize,
        )

    def _check_workspace_base(self) -> None:
        workspace = self.workspace_provider
        if workspace.authority.resolve_ref(workspace.target_ref) != self.expected_base:
            raise ContractViolation("Claude READ fixture target moved from its admitted commit")

    def _own_handle(self, handle: ClaudeOperatorHandle) -> None:
        sealed = self._handles.get(handle)
        if sealed is None:
            raise ContractViolation("Claude READ requires its minted invocation handle")
        context, attempt = sealed
        if (handle.provider is not self or handle.context is not context
                or handle.attempt is not attempt
                or handle.paths != AcquisitionPaths(self.acquisition_root, acquisition_id_for(
                    lease_id_for(context.run_lease.run_id, context.path, context.binding.binding),
                    context.run_lease.epoch,
                ))):
            raise ContractViolation("Claude READ requires its minted invocation handle")

    def _own(self, acquired: AcquiredCapability) -> ClaudeOperatorHandle:
        handle = acquired.resource
        if not isinstance(handle, ClaudeOperatorHandle):
            raise ContractViolation("Claude READ requires its own acquisition")
        self._own_handle(handle)
        context = handle.context
        if (acquired.lease_id != lease_id_for(context.run_lease.run_id, context.path,
                                             context.binding.binding)
                or acquired.acquisition_id != handle.paths.acquisition_id
                or acquired.resource_ref != self._reference(context)):
            raise ContractViolation("Claude READ acquisition wrapper changed")
        return handle

    async def close(self, acquisition: AcquiredCapability,
                    disposition: Disposition) -> LeaseClosure:
        await self._own(acquisition).close(disposition)
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def relinquish(self, acquisition: AcquiredCapability) -> None:
        await self._own(acquisition).relinquish()

    async def reconcile(self, context: LeaseContext,
                        stale: tuple[StaleAcquisition, ...]) -> LeaseReconciliation:
        # Recovery validates sealed durable coordinates, never renews dispatch authorization.
        self._check_sealed()
        if context.binding.revision != self.identity.revision:
            raise ContractViolation("Claude READ recovery has a different revision")
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        pending: list[tuple[AcquisitionPaths, StaleAcquisition]] = []
        seen: set[str] = set()
        for item in stale:
            row = item.lease
            reference = self._reference(context, epoch=row.acquisition_epoch)
            if (row.lease_id != logical or row.run_id != context.run_lease.run_id
                    or row.path != context.path or row.binding_id != context.binding.binding
                    or row.acquisition_epoch >= context.run_lease.epoch
                    or row.state != "active" or row.resource_ref != reference
                    or reference in seen):
                raise ContractViolation("Claude READ recovery row contradicts its invocation")
            seen.add(reference)
            pending.append((AcquisitionPaths(self.acquisition_root, acquisition_id_for(
                logical, row.acquisition_epoch,
            )), item))
        for paths, item in pending:
            await dispose_acquisition(self.closure, paths, disposition=item.disposition)
            self._check_sealed()
        return LeaseReconciliation(reaped=tuple(item.lease.resource_ref for _, item in pending
                                                if item.lease.resource_ref is not None))


class ClaudeOperatorHandle:
    """One task whose retained custody outlives native, worker and relay work."""

    def __init__(self, provider: ClaudeOperatorProvider, context: LeaseContext,
                 paths: AcquisitionPaths, attempt: AttemptRecord) -> None:
        self.provider, self.context, self.paths, self.attempt = provider, context, paths, attempt
        self.entered = self.ready = self.closed = self.executed = False
        self._deadline: float | None = None
        self._guard_owner: AbstractAsyncContextManager[int] | None = None
        self._guard_fd: int | None = None
        self._held: HeldStoreLock | None = None
        self._credential_fd: int | None = None
        self.initial_check: BindingCheck | None = None
        self.terminal_check: BindingCheck | None = None
        self.active: asyncio.Task[ExecutorOutcome] | None = None
        self._materialization: asyncio.Task[None] | None = None
        self._cleanup: asyncio.Task[None] | None = None
        self._release: asyncio.Task[None] | None = None
        self._disposition: Disposition | None = None
        self._intent = self._settled = False
        self._callback_started = self._callback_completed = 0
        self._observed_errors: set[int] = set()
        self.relay_closed = False
        self.relay_denied: dict[str, int] = {}
        self.relay_destinations: dict[str, int] = {}

    @property
    def profile(self) -> NativeOperatorExecutorProfileV3:
        return self.provider.profile

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        return self.provider._grant_faults(grants)

    def _check_control(self) -> None:
        self.provider._own_handle(self)
        if self.closed:
            raise _LocalClose("Claude READ acquisition closed")
        self.provider._check_context(self.context)
        if self.closed:
            raise _LocalClose("Claude READ acquisition closed during control check")
        if self._deadline is not None and asyncio.get_running_loop().time() >= self._deadline:
            raise ContractViolation("Claude READ acquisition deadline expired")

    def _binding(self) -> BindingCheck:
        if self._held is None:
            raise ContractViolation("Claude READ acquisition has no retained store lock")
        checked = self.provider.binding_store.check_held(self._held)
        if (type(checked) is not BindingCheck
                or checked.binding_digest != self.provider.identity.store.operator_binding_digest
                or (self.initial_check is not None and checked != self.initial_check)):
            raise ContractViolation("Claude READ binding check is not an affirmative sealed fact")
        return checked

    def _check(self) -> None:
        self._check_control()
        self.provider._check_sealed()
        self.provider.closure.require_open(self.paths)
        self._check_control()
        self._binding()
        self._check_control()

    async def _open(self) -> None:
        self._check_control()
        await finish_owned(asyncio.create_task(asyncio.to_thread(
            self.provider.closure.require_open, self.paths,
        )))
        self._check_control()
        # Fence publication can race the thread's return. The transfer itself has no await.
        self.provider.closure.require_open(self.paths)

    async def materialize(self) -> None:
        if self.closed or self.entered:
            raise ContractViolation("Claude READ materialization is single use")
        self.entered = True
        self._deadline = (asyncio.get_running_loop().time()
                          + self.context.binding.effective_grants.timeout_s)
        self._materialization = asyncio.create_task(self._materialize_owned())
        try:
            async with asyncio.timeout_at(self._deadline):
                await self._materialization
        except BaseException as primary:
            self._observe(self._materialization)
            failure: BaseException | None = None
            if self._held is not None:
                try:
                    self.terminal_check = self._binding()
                except BaseException as error:
                    failure = error
            self._settle(None)
            if failure is not None:
                raise BaseExceptionGroup("Claude READ materialization and binding failed",
                                         [primary, failure]) from None
            raise

    def _observe(self, task: asyncio.Task[Any]) -> None:
        if task.done() and not task.cancelled():
            error = task.exception()
            if error is not None:
                self._observed_errors.add(id(error))

    async def _materialize_owned(self) -> None:
        self._check_control()
        self._guard_owner = acquisition_guard(self.paths)
        self._guard_fd = await self._guard_owner.__aenter__()
        await self._open()
        self._held = await self.provider.binding_store.acquire_lock(
            self.provider.binding_store.open_candidate(), self._check_control, self._open,
        )
        self._check_control()
        self.initial_check = self._binding()
        self._check()
        self._credential_fd = self.provider.binding_store.open_credential(self._held)
        for launcher in (self.provider.launcher, self.provider.worker_launcher):
            await launcher.probe(deadline=self._deadline)
            self._check()
        self.ready = True

    def _before_user(self) -> None:
        self._check()
        self.provider._check_workspace_base()
        if self._intent:
            raise ContractViolation("Claude READ user dispatch is single use")
        error = self.attempt.intend()
        if error is not None:
            raise ContractViolation("Claude READ could not retain dispatch intent")
        # Durability may block past expiry; it never supplies a renewed authorization.
        self._check()
        self._intent = True

    def _settle(self, outcome: ExecutorOutcome | None) -> None:
        if self._settled:
            return
        self._settled = True
        dispatch: Dispatch = (
            "not dispatched" if not self._intent else
            "completed" if isinstance(outcome, ExecutorSuccess) else "possibly dispatched"
        )
        try:
            self.attempt.complete(dispatch, {
                "status": None if outcome is None else outcome.status,
                "callback_started": self._callback_started,
                "callback_completed": self._callback_completed,
                "initial_binding_checked": self.initial_check is not None,
                "terminal_binding_checked": self.terminal_check is not None,
                "relay_closed": self.relay_closed,
                "relay_denied": dict(self.relay_denied),
                "relay_destinations": dict(self.relay_destinations),
            })
        except OSError as error:
            if isinstance(outcome, ExecutorSuccess):
                raise ContractViolation("Claude READ could not retain its outcome") from error

    def _before_spawn(self) -> BindingCheck:
        self._check()
        return self._binding()

    async def execute(self, task: TaskSpec, *, workspace: WorkspaceView | None,
                      grants: EffectiveGrants) -> ExecutorOutcome:
        if self.closed or not self.ready or self.executed:
            raise ContractViolation("Claude READ executes one materialized task only")
        self.executed = True
        outcome: ExecutorOutcome | None = None
        try:
            self._check()
            if (canonical_json(grants) != canonical_json(self.context.binding.effective_grants)
                    or self.validate_grants(grants) or task.context
                    or task.response_schema is not None):
                raise ContractViolation("Claude READ task differs from its sealed grants")
            owned = self.provider.workspace_provider.owned_view(workspace, self.context)
            binding = owned.context.binding
            if (owned.base != self.provider.expected_base
                    or binding.capability_id != self.provider.workspace_capability_id
                    or binding.revision != self.provider.workspace_revision
                    or owned.context.run_lease.owner_id != self.context.run_lease.owner_id):
                raise ContractViolation("Claude READ workspace differs from its admitted binding")
            worker = ClaudeReadWorker(provider=self.provider.workspace_provider,
                                      context=self.context, workspace=owned,
                                      launcher=self.provider.worker_launcher)
            self.active = asyncio.create_task(self._run(task, worker))
            result = await self.active
            self._check()
            outcome = result
            return outcome
        except BaseException as primary:
            if self.active is not None:
                self._observe(self.active)
            else:
                try:
                    self.terminal_check = self._binding()
                except BaseException as error:
                    raise BaseExceptionGroup("Claude READ task and binding failed",
                                             [primary, error]) from None
            raise
        finally:
            self._settle(outcome)

    async def _run(self, task: TaskSpec, worker: ClaudeReadWorker) -> ExecutorOutcome:
        self._check()
        assert self._deadline is not None and self._held is not None
        assert self._guard_fd is not None and self._credential_fd is not None
        vendor = self.provider.launcher.claude
        assert vendor is not None
        relay = EgressRelay(self.provider.egress, self.paths.payload,
                            self._deadline, self._check)

        async def read(path: str, remaining: float) -> str:
            self._check()
            if self._callback_started:
                raise ContractViolation("Claude READ permits one callback")
            self._callback_started += 1
            text = await worker(path, remaining)
            self._check()
            self._callback_completed += 1
            return text

        outcome: ExecutorOutcome | None = None
        failure: BaseException | None = None
        try:
            async with relay as egress:
                self._check()
                mount = ClaudeNativeStoreMount(
                    self._held.lock_fd, self._credential_fd, self._before_spawn, egress,
                )
                outcome = await claude_read.run_read_transaction(
                    self.provider.launcher, vendor.command, task,
                    mode=self.provider.mode, model=vendor.model,
                    effort=vendor.effort, worker=read,
                    guard_fds=(self._guard_fd, self._held.lock_fd),
                    timeout_s=self._deadline - asyncio.get_running_loop().time(),
                    native_store=mount, before_user=self._before_user, check_control=self._check,
                )
                self._check()
        except BaseException as error:
            failure = error
        self.relay_closed = relay.closed
        self.relay_denied = relay.denied
        self.relay_destinations = dict(relay.destinations)
        try:
            # A failed exchange still owes a terminal custody observation; its
            # primary cancellation/fatal failure survives a failed observation.
            self.terminal_check = self._binding()
        except BaseException as error:
            if failure is not None:
                raise BaseExceptionGroup("Claude READ exchange and binding failed",
                                         [failure, error]) from None
            raise
        if failure is not None:
            raise failure
        self._check()
        assert outcome is not None
        if (not self.relay_closed or self.relay_denied
                or self._callback_started != 1 or self._callback_completed != 1):
            detail = (claude_read.known_refusal_detail(outcome.error.detail)
                      if isinstance(outcome, ExecutorFailure) and outcome.error.kind == "exit"
                      else None)
            return ExecutorFailure(
                requested_model=outcome.requested_model, served_model=outcome.served_model,
                usage=outcome.usage, rate_limit=outcome.rate_limit, elapsed_s=outcome.elapsed_s,
                error=ExecutorError(kind="exit", detail=detail or "Claude READ refused"),
            )
        return outcome

    async def close(self, disposition: Disposition) -> None:
        if self._disposition is not None and self._disposition != disposition:
            raise ContractViolation("Claude READ repeated close changed disposition")
        self._disposition = disposition
        self.closed = True
        if self._cleanup is None:
            self._cleanup = asyncio.create_task(self._close_owned())
        await finish_owned(self._cleanup)

    async def _close_owned(self) -> None:
        errors: list[BaseException] = []
        released = False
        if self.entered:
            try:
                await finish_owned(asyncio.create_task(asyncio.to_thread(
                    self.provider.closure.commit, self.paths,
                )))
            except BaseException as error:
                errors.append(error)
        try:
            await self.relinquish()
            released = True
        except BaseException as error:
            errors.append(error)
        if self.entered and released:
            try:
                await dispose_acquisition(self.provider.closure, self.paths,
                                          disposition=self._disposition or "discard")
            except BaseException as error:
                errors.append(error)
        if errors:
            raise BaseExceptionGroup("Claude READ close failed", errors)

    async def relinquish(self) -> None:
        self.closed = True
        if self._release is None:
            self._release = asyncio.create_task(self._release_owned())
        await finish_owned(self._release)

    async def _release_owned(self) -> None:
        errors: list[BaseException] = []
        pending = [task for task in (self._materialization, self.active) if task is not None]
        cancelled: set[asyncio.Task[Any]] = set()
        for task in pending:
            if not task.done():
                cancelled.add(task)
                task.cancel()
        if pending:
            results = await asyncio.gather(*pending, return_exceptions=True)
            for task, result in zip(pending, results, strict=True):
                if isinstance(result, BaseExceptionGroup) and task in cancelled:
                    _, result = result.split(asyncio.CancelledError)
                if (isinstance(result, BaseException)
                        and not isinstance(result, asyncio.CancelledError)
                        and not (isinstance(result, _LocalClose) and self.closed)
                        and id(result) not in self._observed_errors):
                    errors.append(result)
        self.ready = False
        if self._held is not None:
            try:
                self.terminal_check = self._binding()
            except BaseException as error:
                errors.append(error)
        try:
            self._settle(None)
        except BaseException as error:
            errors.append(error)
        if self._credential_fd is not None:
            fd, self._credential_fd = self._credential_fd, None
            try:
                os.close(fd)
            except BaseException as error:
                errors.append(error)
        if self._held is not None:
            held, self._held = self._held, None
            try:
                self.provider.binding_store.close_held(held)
            except BaseException as error:
                errors.append(error)
        if self._guard_owner is not None and self._guard_fd is not None:
            owner, self._guard_owner = self._guard_owner, None
            self._guard_fd = None
            try:
                await owner.__aexit__(None, None, None)
            except BaseException as error:
                errors.append(error)
        if errors:
            raise BaseExceptionGroup("Claude READ custody release failed", errors)


def _protocol_revision() -> Digest:
    """Bind the complete decoder and closed observation vocabulary."""
    return digest("claude-read-protocol", 3, {
        module.__name__: inspect.getsource(module)
        for module in (claude_protocol, claude_startup, claude_read,
                       claude_initialize, claude_native_events, claude_read_observation)
    })


PROTOCOL_REVISION = _protocol_revision()
ADAPTER_REVISION = digest("claude-read-owned-adapter", 3, {
    module.__name__: inspect.getsource(module)
    for module in (sys.modules[__name__], claude_read_worker, claude_native,
                   attempt_record, qualification_law)
})
