"""A genuine ExecutorProvider double running recordings through Linux containment.

No fake OS availability, credential, provider route, or model call. Test-side
native records exercise the task seam; they are not a shared backend event IR.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from pathlib import Path

from constructicon.core.errors import ContractViolation
from constructicon.core.executor import (
    ExecutorError,
    ExecutorFailure,
    ExecutorGrantPolicy,
    ExecutorLaunchIdentity,
    ExecutorPartial,
    ExecutorProfile,
    ExecutorSuccess,
    TransportDamage,
)
from constructicon.core.grants import IsolationProfile, Posture
from constructicon.core.identity import Digest, canonical_json, digest, parse_json_value
from constructicon.core.workspace import (
    AcquiredCapability,
    LeaseClosure,
    LeaseReconciliation,
    acquisition_id_for,
    lease_id_for,
)
from constructicon.runtime.registry import CapabilityDescriptor
from constructicon.substrate.git.acquisition import (
    AcquisitionPaths,
    acquisition_guard,
    dispose_acquisition,
)


def decode(result, model):
    output = None
    seen = False
    damage = result.bound_exceeded
    malformed = 0
    for line in result.stdout.split(b"\n"):
        if not line:
            continue
        try:
            record = parse_json_value(line.decode("utf-8"))
            if not isinstance(record, dict) or set(record) != {"type", "output"}:
                raise ValueError("unrecognized recorded semantic event")
            if record["type"] != "result" or seen:
                raise ValueError("contradictory recorded terminal event")
            output = record["output"]
            seen = True
        except (ValueError, UnicodeError) as exc:
            malformed += 1
            damage = damage or str(exc)
    observation = dict(
        output=output, raw_reply=result.stdout.decode("utf-8", errors="replace"),
        elapsed_s=result.elapsed_s, requested_model=model,
    )
    if result.timed_out:
        return ExecutorFailure(**observation, error=ExecutorError(
            kind="timeout", detail="deadline",
        ))
    if result.returncode and not result.bound_exceeded:
        return ExecutorFailure(**observation, error=ExecutorError(
            kind="exit", detail="recorded child failed", exit_code=result.returncode,
        ))
    if damage or not seen:
        return ExecutorPartial(**observation, damage=TransportDamage(
            malformed_records=malformed, first_error=damage or "missing terminal result",
            evidence_excerpt=result.stderr.decode("utf-8", errors="replace")[:256],
        ))
    return ExecutorSuccess(**observation)


class RecordedExecutor:
    def __init__(self, provider, context, paths):
        self.provider = provider
        self.context = context
        self.paths = paths
        self.entered = self.ready = self.closed = False
        self.active = None

    @property
    def profile(self):
        return self.provider.identity.profile

    def validate_grants(self, grants):
        return self.profile.grant_faults(grants)

    async def materialize(self):
        if self.closed or self.entered:
            raise ContractViolation("recorded executor is closed or already entered")
        self.entered = True
        async with acquisition_guard(self.paths):
            self.provider.workspaces.closure.require_open(self.paths)
            self.ready = True

    async def execute(self, task, *, workspace, grants):
        if self.closed or not self.ready:
            raise ContractViolation("recorded executor acquisition is not open")
        if canonical_json(grants) != canonical_json(self.context.binding.effective_grants):
            raise ContractViolation("recorded executor grants differ from the sealed invocation")
        faults = self.validate_grants(grants)
        if faults or task.context or task.response_schema is not None:
            return ExecutorFailure(error=ExecutorError(
                kind="unavailable", detail="unsupported task",
            ))
        data = task.instruction.encode("utf-8")
        if len(data) > self.provider.launcher.limits.input_bytes:
            return ExecutorFailure(error=ExecutorError(kind="unavailable", detail="input bound"))
        view = self.provider.workspaces.owned_view(workspace, self.context)
        async with acquisition_guard(self.paths) as executor_guard:
            if self.closed:
                raise ContractViolation("recorded executor closed while awaiting its guard")
            self.provider.workspaces.closure.require_open(self.paths)
            async with view.use() as workspace_guard:
                if self.closed:
                    raise ContractViolation("recorded executor closed before launch")
                if self.provider.launcher.revision != self.provider.launch_revision:
                    raise ContractViolation("recorded launch identity drifted")
                program = self.provider.program
                actual_program = digest("recorded-program", 1, program)
                if actual_program != self.provider.identity.configuration_digest:
                    raise ContractViolation("recorded program identity drifted")
                self.active = asyncio.create_task(self.provider.launcher.run(
                    ("/usr/bin/python3", "-I", "-c", program),
                    workspace=Path(view.path), posture=grants.posture,
                    guard_fds=(executor_guard, workspace_guard), stdin=data,
                    timeout_s=grants.timeout_s,
                ))
                try:
                    result = await self.active
                except (OSError, ContractViolation) as exc:
                    return ExecutorFailure(error=ExecutorError(kind="unavailable", detail=str(exc)))
                finally:
                    self.active = None
        return decode(result, grants.model_selection.model)


class RecordedExecutorProvider:
    def __init__(self, launcher, workspaces, program):
        self.launcher = launcher
        self.workspaces = workspaces
        self.program = program
        self.launch_revision = launcher.revision
        posture = workspaces.posture
        profile = ExecutorProfile(
            name="recorded-subprocess", structured_output=False, postures=frozenset({posture}),
            isolation=IsolationProfile(
                filesystem="read_only_snapshot" if posture is Posture.READ else "workspace_only",
                process_tree_owned=True, environment_allowlisted=True, network_enforced=True,
            ),
            accepted_efforts=frozenset(),
            grant_policy=ExecutorGrantPolicy(
                tool_sets=((),), network_modes=("none",), network_access="none",
                environment_names=(), workspace_required=True,
            ),
        )
        self._identity = ExecutorLaunchIdentity(
            executable_digest=Digest("sha256:" + hashlib.sha256(
                (launcher.root / "usr/bin/python3.12").read_bytes(),
            ).hexdigest()),
            runtime_digest=launcher.expected_runtime,
            adapter_revision=digest("recorded-adapter", 1, inspect.getsource(RecordedExecutor)),
            decoder_revision=digest("recorded-decoder", 1, inspect.getsource(decode)),
            isolation_revision=self.launch_revision,
            configuration_digest=digest("recorded-program", 1, program),
            limits_digest=digest("recorded-limits", 1, repr(launcher.limits)),
            profile=profile, provider_route=None,
        )
        self._unavailable = ("physical qualification has not run",)
        self.handles = []

    @property
    def identity(self):
        return self._identity

    @property
    def unavailable_reasons(self):
        return self._unavailable

    async def qualify(self):
        await self.launcher.probe()
        self._unavailable = ()

    def descriptor(self, capability_id="recorded-executor"):
        return CapabilityDescriptor(
            capability_id=capability_id, kind="executor", revision=self.identity.revision,
            executor_profile=self.identity.profile, leased=True,
        )

    async def acquire(self, context):
        if self.unavailable_reasons:
            raise ContractViolation("recorded provider is not physically qualified")
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        acquisition = acquisition_id_for(logical, context.run_lease.epoch)
        paths = AcquisitionPaths(self.workspaces.root, acquisition)
        handle = RecordedExecutor(self, context, paths)
        self.handles.append(handle)
        return AcquiredCapability(
            resource=handle, lease_id=logical, acquisition_id=acquisition,
            resource_ref=acquisition, materialize=handle.materialize,
        )

    async def close(self, acquisition, disposition):
        handle = acquisition.resource
        if not isinstance(handle, RecordedExecutor) or handle.provider is not self:
            raise ContractViolation("recorded close requires its own handle")
        handle.closed = True
        if handle.active is not None:
            handle.active.cancel()
        if handle.entered:
            await dispose_acquisition(self.workspaces.closure, handle.paths)
        return LeaseClosure(disposition="released" if disposition == "release" else "discarded")

    async def reconcile(self, context, stale):
        reaped = []
        logical = lease_id_for(context.run_lease.run_id, context.path, context.binding.binding)
        for item in stale:
            row = item.lease
            expected = acquisition_id_for(logical, row.acquisition_epoch)
            if (
                row.lease_id != logical or row.run_id != context.run_lease.run_id
                or row.acquisition_epoch >= context.run_lease.epoch or row.resource_ref != expected
            ):
                raise ContractViolation("recorded executor recovery row contradicts its identity")
            await dispose_acquisition(
                self.workspaces.closure, AcquisitionPaths(self.workspaces.root, expected),
            )
            reaped.append(expected)
        return LeaseReconciliation(reaped=tuple(reaped))
