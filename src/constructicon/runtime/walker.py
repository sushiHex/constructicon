"""The walker — leased, fenced execution of a sealed manifest (I1, I13).

The walker accepts ONLY an ``ExecutionManifest``. Once admission has returned,
it never resolves a reference, searches for a port, inherits a grant, chooses a
capability, interprets a selector string, or decides whether an effect is safe:
every such decision lives in the manifest or in a deterministic effect adapter.

Ownership: one fenced ``RunLease`` per run, renewed by a continuous heartbeat
task while nodes and effects are in flight. Every journal write is fenced by
``owner_id + epoch``; a fenced-out worker raises ``OwnershipLost`` and writes
nothing else.

Resume re-walks the graph: a durably checkpointed invocation at the same
``ExecutionPath`` (matching input hash and resolved version) short-circuits;
work that finished only in memory may replay — nothing preserves output that
never reached the journal. Effects are at-least-once bounded by idempotency:
once an effect has a committed receipt, no replay, crash, or retry causes a
second externally visible transition.

Failure is contained: a failed node marks its dependents BLOCKED with a
complete ``DependencyReport``; unrelated branches finish; the run's terminal
status is decided at graph closure.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.component import ComponentDef
from constructicon.core.effect import (
    EffectAdapter,
    EffectReceipt,
    EffectRequest,
    idempotency_key,
)
from constructicon.core.envelope import Envelope, utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import Digest, digest
from constructicon.core.journal import Checkpoint, Journal
from constructicon.core.manifest import (
    SELF_BINDING,
    CapabilityBinding,
    CapabilityLease,
    ExecutionManifest,
)
from constructicon.core.ports import (
    GraphInputAddress,
    GraphOutputAddress,
    NodePortAddress,
    Port,
    PortAddress,
)
from constructicon.core.run import (
    CheckpointConflict,
    DependencyReport,
    InvocationStatus,
    OwnershipLost,
    ProducerStatus,
    RunLease,
    RunStatus,
)
from constructicon.core.workspace import (
    AcquiredCapability,
    Disposition,
    LeaseContext,
    LeasedCapability,
    StaleAcquisition,
)
from constructicon.runtime.context import NodeContext, NodeImpl
from constructicon.runtime.registry import (
    BoundExecution,
    CapabilityDescriptor,
    ComponentRegistry,
)

DEFAULT_LEASE_TTL_S = 30.0
DEFAULT_HEARTBEAT_INTERVAL_S = 10.0


@dataclass(frozen=True)
class RunResult:
    run_id: RunId
    status: RunStatus
    outputs: dict[str, Any]
    failures: dict[str, str] = field(default_factory=dict)  # path -> error
    blocked: tuple[DependencyReport, ...] = ()


@dataclass(frozen=True)
class _Instance:
    scope: ScopePath
    component: str
    version: Digest
    definition: ComponentDef
    impl: NodeImpl


def _address_key(address: PortAddress) -> str:
    if isinstance(address, NodePortAddress):
        return f"node:{'/'.join(address.scope.segments)}:{address.node}:{address.port}"
    if isinstance(address, GraphInputAddress):
        return f"in:{'/'.join(address.scope.segments)}:{address.port}"
    return f"out:{'/'.join(address.scope.segments)}:{address.port}"


class Walker:
    def __init__(
        self,
        *,
        registry: ComponentRegistry,
        journal: Journal,
        capabilities: Mapping[str, object],
        catalog: Mapping[str, CapabilityDescriptor],
        effects: Mapping[str, EffectAdapter],
        owner_id: str,
        lease_ttl_s: float = DEFAULT_LEASE_TTL_S,
        heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
    ) -> None:
        self._registry = registry
        self._journal = journal
        self._capabilities = dict(capabilities)
        self._catalog = dict(catalog)
        self._effects = dict(effects)
        self._owner_id = owner_id
        self._lease_ttl_s = lease_ttl_s
        self._heartbeat_interval_s = heartbeat_interval_s

    # -- entry points ---------------------------------------------------------

    async def start(
        self,
        manifest: ExecutionManifest,
        *,
        run_id: RunId,
        inputs: dict[str, Any],
    ) -> RunResult:
        self._journal.create_run(
            run_id,
            manifest_json=manifest.model_dump_json(),
            manifest_hash=manifest.manifest_hash,
            input_hash=manifest.input_hash,
            inputs=inputs,
        )
        return await self._drive(manifest, run_id=run_id, inputs=inputs)

    async def resume(self, run_id: RunId) -> RunResult:
        """The pinned resume table: PENDING -> claim+start; RUNNING+expired ->
        reclaim; RUNNING+live -> refuse with owner detail; FAILED/PARKED ->
        claim + re-walk from checkpoints; SUCCEEDED -> return the materialized
        result, status untouched; CANCELLED -> report cancelled, never
        silently restart."""
        journal = self._journal
        state = journal.run_state(run_id)
        if state is None:
            raise ContractViolation(f"unknown run {run_id!r}")
        manifest = self._load_manifest(run_id)
        if state.status is RunStatus.SUCCEEDED:
            inputs = journal.run_inputs(run_id)
            if inputs is None:
                raise ContractViolation(
                    f"run {run_id!r} has no recorded inputs to materialize from"
                )
            outputs = self._materialize(manifest, run_id, inputs)
            return RunResult(run_id=run_id, status=RunStatus.SUCCEEDED, outputs=outputs)
        if state.status is RunStatus.CANCELLED:
            return RunResult(run_id=run_id, status=RunStatus.CANCELLED, outputs={})
        inputs = journal.run_inputs(run_id)
        if inputs is None:
            raise ContractViolation(f"run {run_id!r} has no recorded inputs to resume from")
        return await self._drive(manifest, run_id=run_id, inputs=inputs)

    async def reproduce(self, source_run_id: RunId, *, new_run_id: RunId) -> RunResult:
        """A new run under a past run's exact sealed world."""
        manifest = self._load_manifest(source_run_id)
        inputs = self._journal.run_inputs(source_run_id)
        if inputs is None:
            raise ContractViolation(
                f"run {source_run_id!r} has no recorded inputs to reproduce from"
            )
        return await self.start(manifest, run_id=new_run_id, inputs=inputs)

    # -- lifecycle ------------------------------------------------------------

    async def _drive(
        self, manifest: ExecutionManifest, *, run_id: RunId, inputs: dict[str, Any]
    ) -> RunResult:
        # one activation path for start, resume, and reproduce: refuse
        # unavailable or drifted implementations before claiming anything
        bound = self._registry.activate(manifest, catalog=self._catalog)
        journal = self._journal
        lease = journal.claim_run(
            run_id, owner_id=self._owner_id, ttl_s=self._lease_ttl_s
        )
        lost: list[OwnershipLost] = []
        heartbeat = asyncio.create_task(self._heartbeat_loop(lease, lost))
        try:
            result = await self._execute(
                bound, lease=lease, inputs=inputs, lost=lost
            )
        except OwnershipLost:
            await self._stop_heartbeat(heartbeat)
            raise  # fenced out: write nothing else, release included
        except Exception:
            await self._stop_heartbeat(heartbeat)
            self._release_quietly(lease)
            raise
        except BaseException:
            # simulated or genuine process death (InjectedCrash, cancellation):
            # clean up process-local tasks only — durable state must look
            # exactly like a crash, so the lease is left to expire
            await self._stop_heartbeat(heartbeat)
            raise
        await self._stop_heartbeat(heartbeat)
        self._release_quietly(lease)
        return result

    async def _heartbeat_loop(self, lease: RunLease, lost: list[OwnershipLost]) -> None:
        """Continuous renewal while nodes and effects are in flight. Updates
        ownership state only — never events. The fence fields (owner_id,
        epoch) never change, so the original lease stays valid for writes."""
        try:
            while True:
                await asyncio.sleep(self._heartbeat_interval_s)
                self._journal.heartbeat(lease, ttl_s=self._lease_ttl_s)
        except OwnershipLost as exc:
            lost.append(exc)

    @staticmethod
    async def _stop_heartbeat(task: asyncio.Task[None]) -> None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    def _release_quietly(self, lease: RunLease) -> None:
        with contextlib.suppress(OwnershipLost):
            self._journal.release_run(lease)

    # -- execution ------------------------------------------------------------

    async def _execute(
        self,
        bound: BoundExecution,
        *,
        lease: RunLease,
        inputs: dict[str, Any],
        lost: list[OwnershipLost],
    ) -> RunResult:
        journal = self._journal
        manifest = bound.manifest
        run_id = lease.run_id

        state = journal.run_state(run_id)
        if state is None:
            raise ContractViolation(f"unknown run {run_id!r}")
        if state.status is RunStatus.PENDING:
            journal.transition_run(
                lease,
                expected=frozenset({RunStatus.PENDING}),
                target=RunStatus.RUNNING,
                event_kind="RunStarted",
                payload={"inputs": inputs},
            )
        elif state.status in (RunStatus.FAILED, RunStatus.PARKED):
            journal.transition_run(
                lease,
                expected=frozenset({RunStatus.FAILED, RunStatus.PARKED}),
                target=RunStatus.RUNNING,
                event_kind="RunResumed",
            )
        else:  # durably RUNNING — reclaimed from an expired owner
            journal.append_event(lease, "RunReclaimed")

        await self._reconcile_stale_leases(bound, lease)

        instances = self._instances(bound)
        bindings_by_destination = {
            _address_key(binding.destination): binding
            for binding in manifest.resolved_connections
        }
        grants_by_scope = {
            binding.scope.segments: binding
            for binding in manifest.capability_bindings
            if binding.binding == SELF_BINDING
        }
        aliases_by_scope: dict[tuple[str, ...], list[CapabilityBinding]] = {}
        for binding in manifest.capability_bindings:
            if binding.binding != SELF_BINDING:
                aliases_by_scope.setdefault(binding.scope.segments, []).append(binding)
        producer_of = self._producer_index(instances)

        root_scope = ScopePath(segments=(manifest.source_graph.name,))
        values: dict[str, Any] = {
            _address_key(GraphInputAddress(scope=root_scope, port=name)): value
            for name, value in inputs.items()
        }
        status_by_scope: dict[tuple[str, ...], InvocationStatus] = {}
        failures: dict[str, str] = {}
        blocked: list[DependencyReport] = []

        for instance in self._ordered(instances, bindings_by_destination, producer_of):
            if lost:
                raise lost[0]
            if journal.cancel_requested(run_id):
                journal.transition_run(
                    lease,
                    expected=frozenset({RunStatus.RUNNING}),
                    target=RunStatus.CANCELLED,
                    event_kind="RunCancelled",
                )
                return RunResult(
                    run_id=run_id,
                    status=RunStatus.CANCELLED,
                    outputs={},
                    failures=failures,
                    blocked=tuple(blocked),
                )

            report = self._dependency_report(
                instance, bindings_by_destination, producer_of, status_by_scope
            )
            if any(
                producer.status is not InvocationStatus.COMPLETED
                for producer in report.producers
            ):
                status_by_scope[instance.scope.segments] = InvocationStatus.BLOCKED
                blocked.append(report)
                journal.append_event(
                    lease,
                    "NodeBlocked",
                    path=ExecutionPath(scope=instance.scope),
                    payload=report.model_dump(mode="json"),
                )
                continue

            error = await self._execute_or_restore(
                manifest,
                instance,
                lease=lease,
                values=values,
                bindings_by_destination=bindings_by_destination,
                grants_by_scope=grants_by_scope,
                aliases_by_scope=aliases_by_scope,
            )
            if error is None:
                status_by_scope[instance.scope.segments] = InvocationStatus.COMPLETED
            else:
                status_by_scope[instance.scope.segments] = InvocationStatus.FAILED
                failures[instance.scope.render()] = error

        # graph closure: the terminal status is decided here, never mid-branch
        if failures or blocked:
            journal.transition_run(
                lease,
                expected=frozenset({RunStatus.RUNNING}),
                target=RunStatus.FAILED,
                event_kind="RunFailed",
                payload={
                    "failed": sorted(failures),
                    "blocked": [report.destination.render() for report in blocked],
                },
            )
            return RunResult(
                run_id=run_id,
                status=RunStatus.FAILED,
                outputs={},
                failures=failures,
                blocked=tuple(blocked),
            )

        outputs: dict[str, Any] = {}
        for port in manifest.source_graph.outputs:
            out_binding = bindings_by_destination.get(
                _address_key(GraphOutputAddress(scope=root_scope, port=port.name))
            )
            if out_binding is None:
                continue
            outputs[port.name] = _collect(values, out_binding.sources, port)
        journal.transition_run(
            lease,
            expected=frozenset({RunStatus.RUNNING}),
            target=RunStatus.SUCCEEDED,
            event_kind="RunSucceeded",
            payload={"outputs": sorted(outputs)},
        )
        return RunResult(run_id=run_id, status=RunStatus.SUCCEEDED, outputs=outputs)

    # -- capability leases ----------------------------------------------------

    async def _close_acquired(
        self,
        lease: RunLease,
        acquired: list[tuple[LeasedCapability, AcquiredCapability]],
        disposition: Disposition,
    ) -> None:
        """Ordering pinned: physical op first, fenced lease row second."""
        for capability, acquisition in acquired:
            closure = await capability.close(acquisition, disposition)
            self._journal.transition_capability_lease(
                lease,
                lease_id=acquisition.lease_id,
                acquisition_epoch=lease.epoch,
                expected=frozenset({"active"}),
                target="closed",
                disposition=closure.disposition,
            )

    async def _reconcile_stale_leases(
        self, bound: BoundExecution, lease: RunLease
    ) -> None:
        """A prior epoch's open acquisitions: checkpointed invocation ->
        release (reap physical leftovers, durable refs stand); uncheckpointed
        -> discard (the work replays from the pinned base — never adopt a
        dirty workspace as completed computation)."""
        journal = self._journal
        manifest = bound.manifest
        stale_rows = [
            row
            for row in journal.capability_leases(lease.run_id)
            if row.state == "active" and row.acquisition_epoch < lease.epoch
        ]
        if not stale_rows:
            return
        by_scope_and_binding = {
            (binding.scope.segments, binding.binding): binding
            for binding in manifest.capability_bindings
        }
        for row in stale_rows:
            binding = by_scope_and_binding.get((row.scope.segments, row.binding_id))
            path = ExecutionPath(scope=row.scope)
            checkpointed = journal.checkpoint(lease.run_id, path) is not None
            disposition: Disposition = "release" if checkpointed else "discard"
            if binding is not None:
                capability = self._capabilities.get(binding.capability_id)
                if isinstance(capability, LeasedCapability):
                    context = LeaseContext(
                        run_lease=lease,
                        binding=binding,
                        path=path,
                        manifest_hash=manifest.manifest_hash,
                    )
                    await capability.reconcile(
                        context,
                        (StaleAcquisition(lease=row, disposition=disposition),),
                    )
            journal.transition_capability_lease(
                lease,
                lease_id=row.lease_id,
                acquisition_epoch=row.acquisition_epoch,
                expected=frozenset({"active"}),
                target="closed",
                disposition="released" if disposition == "release" else "discarded",
            )

    # -- structure ------------------------------------------------------------

    def _load_manifest(self, run_id: RunId) -> ExecutionManifest:
        manifest_hash = self._journal.run_manifest_hash(run_id)
        if manifest_hash is None:
            raise ContractViolation(f"unknown run {run_id!r}")
        manifest_json = self._journal.load_manifest_json(manifest_hash)
        if manifest_json is None:
            raise ContractViolation(
                f"manifest {manifest_hash} for run {run_id!r} is not in the journal"
            )
        return ExecutionManifest.model_validate_json(manifest_json)

    def _instances(self, bound: BoundExecution) -> list[_Instance]:
        instances: list[_Instance] = []
        for resolution in bound.manifest.resolved_components:
            binding = bound.bound(resolution.component, resolution.resolved_version)
            if binding.loadability.status == "composite":
                continue  # composites flattened at admission; atomics execute
            if binding.impl is None:  # activation refused these already
                raise ContractViolation(
                    f"{resolution.scope.render()}: activation returned no "
                    "implementation for an atomic component"
                )
            instances.append(
                _Instance(
                    scope=resolution.scope,
                    component=resolution.component,
                    version=resolution.resolved_version,
                    definition=binding.stored.definition,
                    impl=binding.impl,
                )
            )
        return instances

    @staticmethod
    def _producer_index(instances: list[_Instance]) -> dict[str, _Instance]:
        producer_of: dict[str, _Instance] = {}
        for instance in instances:
            level = ScopePath(segments=instance.scope.segments[:-1])
            node = instance.scope.segments[-1]
            for port in instance.definition.outputs:
                address = NodePortAddress(scope=level, node=node, port=port.name)
                producer_of[_address_key(address)] = instance
        return producer_of

    def _ordered(
        self,
        instances: list[_Instance],
        bindings_by_destination: dict[str, Any],
        producer_of: dict[str, _Instance],
    ) -> list[_Instance]:
        dependencies: dict[tuple[str, ...], set[tuple[str, ...]]] = {
            instance.scope.segments: set() for instance in instances
        }
        for instance in instances:
            for producer in self._producers(
                instance, bindings_by_destination, producer_of
            ):
                dependencies[instance.scope.segments].add(producer.scope.segments)

        by_scope = {instance.scope.segments: instance for instance in instances}
        ordered: list[_Instance] = []
        placed: set[tuple[str, ...]] = set()

        def place(segments: tuple[str, ...], trail: tuple[tuple[str, ...], ...]) -> None:
            if segments in placed:
                return
            if segments in trail:
                raise ContractViolation("manifest contains a dependency cycle")
            for dependency in sorted(dependencies[segments]):
                place(dependency, (*trail, segments))
            placed.add(segments)
            ordered.append(by_scope[segments])

        for instance in sorted(instances, key=lambda i: i.scope.segments):
            place(instance.scope.segments, ())
        return ordered

    @staticmethod
    def _producers(
        instance: _Instance,
        bindings_by_destination: dict[str, Any],
        producer_of: dict[str, _Instance],
    ) -> list[_Instance]:
        """Every producer recorded in the manifest bindings for this
        destination, in deterministic port order, without duplicates."""
        level = ScopePath(segments=instance.scope.segments[:-1])
        node = instance.scope.segments[-1]
        producers: list[_Instance] = []
        seen: set[tuple[str, ...]] = set()
        for port in instance.definition.inputs:
            binding = bindings_by_destination.get(
                _address_key(NodePortAddress(scope=level, node=node, port=port.name))
            )
            if binding is None:
                continue
            for source in binding.sources:
                producer = producer_of.get(_address_key(source))
                if producer is not None and producer.scope.segments not in seen:
                    seen.add(producer.scope.segments)
                    producers.append(producer)
        return producers

    def _dependency_report(
        self,
        instance: _Instance,
        bindings_by_destination: dict[str, Any],
        producer_of: dict[str, _Instance],
        status_by_scope: dict[tuple[str, ...], InvocationStatus],
    ) -> DependencyReport:
        """The complete recorded producer set — completed producers included,
        never only the failing one."""
        producers = tuple(
            ProducerStatus(
                path=ExecutionPath(scope=producer.scope),
                status=status_by_scope.get(
                    producer.scope.segments, InvocationStatus.QUEUED
                ),
            )
            for producer in self._producers(
                instance, bindings_by_destination, producer_of
            )
        )
        return DependencyReport(
            destination=ExecutionPath(scope=instance.scope), producers=producers
        )

    # -- one node -------------------------------------------------------------

    async def _execute_or_restore(
        self,
        manifest: ExecutionManifest,
        instance: _Instance,
        *,
        lease: RunLease,
        values: dict[str, Any],
        bindings_by_destination: dict[str, Any],
        grants_by_scope: dict[tuple[str, ...], CapabilityBinding],
        aliases_by_scope: dict[tuple[str, ...], list[CapabilityBinding]],
    ) -> str | None:
        """Run or restore one invocation; return an error description on node
        failure, None on completion. Framework errors propagate — they are
        never laundered into a node failure."""
        journal = self._journal
        level = ScopePath(segments=instance.scope.segments[:-1])
        node = instance.scope.segments[-1]
        path = ExecutionPath(scope=instance.scope)

        node_inputs: dict[str, Any] = {}
        for port in instance.definition.inputs:
            binding = bindings_by_destination.get(
                _address_key(NodePortAddress(scope=level, node=node, port=port.name))
            )
            if binding is None:
                if port.cardinality == "optional":
                    node_inputs[port.name] = None
                    continue
                raise ContractViolation(
                    f"{instance.scope.render()}: input {port.name!r} has no binding in "
                    "the manifest — admission should have refused this graph"
                )
            node_inputs[port.name] = _collect(values, binding.sources, port)

        input_hash = digest("inputs", 1, node_inputs)
        checkpoint = journal.checkpoint(lease.run_id, path)
        if (
            checkpoint is not None
            and checkpoint.input_hash == input_hash
            and checkpoint.resolved_version == instance.version
        ):
            journal.append_event(lease, "NodeRestored", path=path)
            outputs = {port: env.payload for port, env in checkpoint.outputs.items()}
        else:
            try:
                outputs = await self._invoke(
                    manifest,
                    instance,
                    lease=lease,
                    path=path,
                    node_inputs=node_inputs,
                    input_hash=input_hash,
                    grants_by_scope=grants_by_scope,
                    aliases_by_scope=aliases_by_scope,
                )
            except (OwnershipLost, CheckpointConflict):
                raise  # fencing and journal damage are never node failures
            except Exception as exc:  # a node failure is execution state (I4)
                journal.append_event(
                    lease,
                    "NodeFailed",
                    path=path,
                    payload={"error": str(exc), "error_type": type(exc).__name__},
                )
                return f"{type(exc).__name__}: {exc}"

        for port in instance.definition.outputs:
            address = NodePortAddress(scope=level, node=node, port=port.name)
            values[_address_key(address)] = outputs[port.name]
        return None

    async def _invoke(
        self,
        manifest: ExecutionManifest,
        instance: _Instance,
        *,
        lease: RunLease,
        path: ExecutionPath,
        node_inputs: dict[str, Any],
        input_hash: Digest,
        grants_by_scope: dict[tuple[str, ...], CapabilityBinding],
        aliases_by_scope: dict[tuple[str, ...], list[CapabilityBinding]],
    ) -> dict[str, Any]:
        journal = self._journal
        journal.append_event(lease, "NodeStarted", path=path)

        self_binding = grants_by_scope.get(instance.scope.segments)
        if self_binding is None:
            raise ContractViolation(
                f"{instance.scope.render()}: manifest carries no sealed grants — "
                "admission should have refused this graph"
            )
        capabilities: dict[str, object] = {}
        acquired: list[tuple[LeasedCapability, AcquiredCapability]] = []
        for alias_binding in aliases_by_scope.get(instance.scope.segments, ()):  # injected
            capability = self._capabilities.get(alias_binding.capability_id)
            if capability is None:
                raise ContractViolation(
                    f"{instance.scope.render()}: admitted capability "
                    f"{alias_binding.capability_id!r} was not injected at assembly"
                )
            descriptor = self._catalog.get(alias_binding.capability_id)
            if descriptor is not None and descriptor.leased:
                if not isinstance(capability, LeasedCapability):
                    raise ContractViolation(
                        f"{instance.scope.render()}: capability "
                        f"{alias_binding.capability_id!r} is declared leased but "
                        "does not implement LeasedCapability"
                    )
                lease_context = LeaseContext(
                    run_lease=lease,
                    binding=alias_binding,
                    path=path,
                    manifest_hash=manifest.manifest_hash,
                )
                acquisition = await capability.acquire(lease_context)
                journal.record_capability_lease(
                    lease,
                    CapabilityLease(
                        lease_id=acquisition.lease_id,
                        acquisition_epoch=lease.epoch,
                        run_id=lease.run_id,
                        binding_id=alias_binding.binding,
                        scope=alias_binding.scope,
                        lifetime=alias_binding.lifetime,
                        state="active",
                        resource_ref=acquisition.resource_ref,
                    ),
                )
                capabilities[alias_binding.binding] = acquisition.resource
                acquired.append((capability, acquisition))
            else:
                capabilities[alias_binding.binding] = capability

        boundary = self._effect_boundary(manifest, lease, path)
        context = NodeContext(
            run_id=lease.run_id,
            path=path,
            capabilities=capabilities,
            grants=self_binding.effective_grants,
            effect=boundary,
        )

        try:
            outputs_map: Mapping[str, Any] = await instance.impl(context, node_inputs)

            declared = {port.name for port in instance.definition.outputs}
            missing = sorted(declared - set(outputs_map))
            if missing:
                raise ContractViolation(
                    f"{instance.scope.render()}: implementation omitted declared "
                    f"outputs {missing} — the contract is validated before any "
                    "envelope is emitted"
                )
            envelopes: dict[str, Envelope[Any]] = {
                name: Envelope(
                    run_id=lease.run_id,
                    path=path,
                    port=name,
                    created_at=utc_now(),
                    payload=outputs_map[name],
                )
                for name in declared
            }
            journal.record_completion(
                lease,
                Checkpoint(
                    run_id=lease.run_id,
                    path=path,
                    input_hash=input_hash,
                    resolved_version=instance.version,
                    outputs=envelopes,
                ),
            )
        except (OwnershipLost, CheckpointConflict):
            raise  # fenced out: write nothing else — the new owner reconciles
        except Exception:
            # node failure: uncheckpointed work replays, so its acquisitions
            # are discarded — never adopted as completed computation
            await self._close_acquired(lease, acquired, "discard")
            raise
        # completion is durable first; a crash before this close leaves the
        # rows active and reconcile reaps them with the checkpoint standing
        await self._close_acquired(lease, acquired, "release")
        return {name: outputs_map[name] for name in declared}

    def _effect_boundary(
        self, manifest: ExecutionManifest, lease: RunLease, path: ExecutionPath
    ) -> Any:
        journal = self._journal
        effects = self._effects

        async def boundary(
            kind: str,
            subject: dict[str, Any],
            *,
            attestation_id: str | None = None,
        ) -> EffectReceipt:
            key = idempotency_key(manifest.manifest_hash, path, kind, subject)
            existing = journal.receipt_for(key)
            if existing is not None and existing.status in ("committed", "rejected"):
                # a journaled rejected receipt is as final as a committed one:
                # the same subject can never later succeed (unknown reconciles)
                journal.append_event(
                    lease, "EffectDeduplicated", path=path, payload={"kind": kind}
                )
                return existing
            adapter = effects.get(kind)
            if adapter is None:
                raise ContractViolation(
                    f"no effect adapter for kind {kind!r}; assembled: {sorted(effects)}"
                )
            request = EffectRequest(
                run_id=lease.run_id,  # sealed by the boundary, never the node
                manifest_hash=manifest.manifest_hash,
                path=path,
                kind=kind,
                subject=subject,
                idempotency_key=key,
                attestation_id=attestation_id,
            )
            if journal.effect_prepared(key):
                # prepared without a receipt: reconcile before re-executing —
                # the recovery law
                reconciled = await adapter.reconcile(request)
                if reconciled is not None:
                    journal.record_effect_outcome(
                        lease, request, reconciled, "EffectReconciled"
                    )
                    return reconciled
                # absent externally: safe to execute
            journal.record_effect_prepared(lease, request)
            receipt = await adapter.execute(request)
            event_kind = {
                "committed": "EffectCommitted",
                "rejected": "EffectRejected",
            }.get(receipt.status, "EffectUnresolved")
            journal.record_effect_outcome(lease, request, receipt, event_kind)
            return receipt

        return boundary

    # -- materialization ------------------------------------------------------

    def _materialize(
        self, manifest: ExecutionManifest, run_id: RunId, inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Rebuild a SUCCEEDED run's outputs purely from durable checkpoints —
        the crash-after-terminal-commit, before-caller-return case."""
        journal = self._journal
        root_scope = ScopePath(segments=(manifest.source_graph.name,))
        values: dict[str, Any] = {
            _address_key(GraphInputAddress(scope=root_scope, port=name)): value
            for name, value in inputs.items()
        }
        for resolution in manifest.resolved_components:
            checkpoint = journal.checkpoint(
                run_id, ExecutionPath(scope=resolution.scope)
            )
            if checkpoint is None:
                continue  # composite scopes checkpoint nothing
            level = ScopePath(segments=resolution.scope.segments[:-1])
            node = resolution.scope.segments[-1]
            for port_name, envelope in checkpoint.outputs.items():
                address = NodePortAddress(scope=level, node=node, port=port_name)
                values[_address_key(address)] = envelope.payload
        bindings_by_destination = {
            _address_key(binding.destination): binding
            for binding in manifest.resolved_connections
        }
        outputs: dict[str, Any] = {}
        for port in manifest.source_graph.outputs:
            out_binding = bindings_by_destination.get(
                _address_key(GraphOutputAddress(scope=root_scope, port=port.name))
            )
            if out_binding is None:
                continue
            outputs[port.name] = _collect(values, out_binding.sources, port)
        return outputs


def _collect(values: dict[str, Any], sources: tuple[PortAddress, ...], port: Port) -> Any:
    resolved = []
    for source in sources:
        key = _address_key(source)
        if key not in values:
            raise ContractViolation(
                f"value for {key} is unavailable — a producer did not complete; "
                "reaching collection without it is kernel damage"
            )
        resolved.append(values[key])
    if port.cardinality == "many":
        return resolved
    return resolved[0]
