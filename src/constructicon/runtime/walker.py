"""Leased, fenced execution of a sealed manifest (I1, I13).

The walker accepts only an ``ExecutionManifest``. It never resolves a reference,
searches for a port, inherits a grant, chooses a capability, interprets an
authoring selector, or derives loop structure. M4 adds one generic bounded-loop
unit: the manifest already contains its seeds, feedback, continuation, exports,
and topologically ordered atomic members.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.component import ComponentDef
from constructicon.core.control import RunOrigin
from constructicon.core.effect import (
    EffectAdapter,
    EffectMode,
    EffectReceipt,
    EffectRequest,
    idempotency_key,
)
from constructicon.core.envelope import Envelope, utc_now
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, digest, json_value
from constructicon.core.journal import Checkpoint, Journal
from constructicon.core.manifest import (
    SELF_BINDING,
    CapabilityBinding,
    CapabilityLease,
    ExecutionManifest,
    LoopResolution,
    ResolvedPortBinding,
    parse_manifest_json,
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
    ParkedUnit,
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
    failures: dict[str, str] = field(default_factory=dict)
    blocked: tuple[DependencyReport, ...] = ()
    parked: tuple[ParkedUnit, ...] = ()


@dataclass(frozen=True)
class _Instance:
    scope: ScopePath
    component: str
    version: Digest
    definition: ComponentDef
    impl: NodeImpl | None


@dataclass(frozen=True)
class _Unit:
    scope: ScopePath
    instance: _Instance | None = None
    loop: LoopResolution | None = None


@dataclass(frozen=True)
class _LoopHistory:
    completed_iterations: int
    terminal_iteration: int | None
    exhausted: bool
    final_values: dict[str, Any] | None


class _CancelRequested(Exception):
    pass


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

    def prepare(
        self,
        manifest: ExecutionManifest,
        *,
        run_id: RunId,
        inputs: dict[str, Any],
        origin: RunOrigin | None = None,
    ) -> None:
        """Persist one exact PENDING run without beginning graph execution."""

        normalized = json_value(inputs)
        if not isinstance(normalized, dict):
            raise ContractViolation("run inputs must be a JSON object")
        observed_input_hash = digest("inputs", 1, normalized)
        if observed_input_hash != manifest.input_hash:
            raise ContractViolation(
                f"run inputs hash to {observed_input_hash}, but the sealed manifest "
                f"expects {manifest.input_hash}; re-admit the graph for these inputs"
            )
        self._journal.create_run(
            run_id,
            manifest_json=manifest.model_dump_json(),
            manifest_hash=manifest.manifest_hash,
            input_hash=manifest.input_hash,
            inputs=normalized,
            origin=origin,
        )

    async def start(
        self,
        manifest: ExecutionManifest,
        *,
        run_id: RunId,
        inputs: dict[str, Any],
        origin: RunOrigin | None = None,
    ) -> RunResult:
        self.prepare(manifest, run_id=run_id, inputs=inputs, origin=origin)
        return await self.run_prepared(run_id, cancellation="cancel")

    async def run_prepared(
        self,
        run_id: RunId,
        *,
        cancellation: Literal["cancel", "abandon"] = "cancel",
        expected_event_seq: int | None = None,
        expected_statuses: frozenset[RunStatus] | None = None,
        resume_command_id: str | None = None,
    ) -> RunResult:
        journal = self._journal
        state = journal.run_state(run_id)
        if state is None:
            raise ContractViolation(f"unknown run {run_id!r}")
        manifest = self._load_manifest(run_id)
        inputs = journal.run_inputs(run_id)
        if inputs is None:
            raise ContractViolation(f"run {run_id!r} has no recorded inputs")
        fenced_attempt = expected_event_seq is not None or expected_statuses is not None
        if state.status is RunStatus.SUCCEEDED and not fenced_attempt:
            outputs = self._materialize(manifest, run_id, inputs)
            return RunResult(run_id=run_id, status=RunStatus.SUCCEEDED, outputs=outputs)
        if state.status is RunStatus.CANCELLED and not fenced_attempt:
            return RunResult(run_id=run_id, status=RunStatus.CANCELLED, outputs={})
        origin = journal.run_origin(run_id)
        return await self._drive(
            manifest,
            run_id=run_id,
            inputs=inputs,
            effect_mode=origin.effects if origin else "live",
            capability_mode=origin.capabilities if origin else "normal",
            cancellation=cancellation,
            expected_event_seq=expected_event_seq,
            expected_statuses=expected_statuses,
            resume_command_id=resume_command_id,
        )

    async def resume(self, run_id: RunId) -> RunResult:
        return await self.run_prepared(run_id, cancellation="cancel")

    async def reproduce(
        self,
        source_run_id: RunId,
        *,
        new_run_id: RunId,
        origin: RunOrigin | None = None,
    ) -> RunResult:
        manifest = self._load_manifest(source_run_id)
        inputs = self._journal.run_inputs(source_run_id)
        if inputs is None:
            raise ContractViolation(
                f"run {source_run_id!r} has no recorded inputs to reproduce from"
            )
        return await self.start(
            manifest,
            run_id=new_run_id,
            inputs=inputs,
            origin=origin,
        )

    # -- lifecycle ------------------------------------------------------------

    async def _drive(
        self,
        manifest: ExecutionManifest,
        *,
        run_id: RunId,
        inputs: dict[str, Any],
        effect_mode: EffectMode,
        capability_mode: Literal["normal", "discard"],
        cancellation: Literal["cancel", "abandon"],
        expected_event_seq: int | None,
        expected_statuses: frozenset[RunStatus] | None,
        resume_command_id: str | None,
    ) -> RunResult:
        bound = self._registry.activate(manifest, catalog=self._catalog)
        journal = self._journal
        lease = journal.claim_run(
            run_id,
            owner_id=self._owner_id,
            ttl_s=self._lease_ttl_s,
            expected_event_seq=expected_event_seq,
            expected_statuses=expected_statuses,
        )
        lost: list[OwnershipLost] = []
        heartbeat = asyncio.create_task(self._heartbeat_loop(lease, lost))
        try:
            result = await self._execute(
                bound,
                lease=lease,
                inputs=inputs,
                lost=lost,
                effect_mode=effect_mode,
                capability_mode=capability_mode,
                resume_command_id=resume_command_id,
            )
        except asyncio.CancelledError:
            await self._stop_heartbeat(heartbeat)
            if cancellation == "cancel":
                with contextlib.suppress(OwnershipLost, ContractViolation):
                    journal.transition_run(
                        lease,
                        expected=frozenset({RunStatus.RUNNING}),
                        target=RunStatus.CANCELLED,
                        event_kind="RunCancelled",
                        payload={"source": "asyncio"},
                    )
            self._release_quietly(lease)
            raise
        except OwnershipLost:
            await self._stop_heartbeat(heartbeat)
            raise
        except Exception:
            await self._stop_heartbeat(heartbeat)
            self._release_quietly(lease)
            raise
        except BaseException:
            # Hard death: durable state must look exactly like a crash. The
            # ownership lease expires and the next worker reconciles resources.
            await self._stop_heartbeat(heartbeat)
            raise
        await self._stop_heartbeat(heartbeat)
        self._release_quietly(lease)
        return result

    async def _heartbeat_loop(self, lease: RunLease, lost: list[OwnershipLost]) -> None:
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

    def _check_run_control(
        self,
        lease: RunLease,
        lost: list[OwnershipLost],
    ) -> None:
        if lost:
            raise lost[0]
        if self._journal.cancel_requested(lease.run_id):
            raise _CancelRequested

    # -- graph execution ------------------------------------------------------

    async def _execute(
        self,
        bound: BoundExecution,
        *,
        lease: RunLease,
        inputs: dict[str, Any],
        lost: list[OwnershipLost],
        effect_mode: EffectMode,
        capability_mode: Literal["normal", "discard"],
        resume_command_id: str | None,
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
                payload={
                    "inputs": inputs,
                    **(
                        {"resume_command_id": resume_command_id}
                        if resume_command_id is not None
                        else {}
                    ),
                },
            )
        elif state.status in (RunStatus.FAILED, RunStatus.PARKED):
            journal.transition_run(
                lease,
                expected=frozenset({RunStatus.FAILED, RunStatus.PARKED}),
                target=RunStatus.RUNNING,
                event_kind="RunResumed",
                payload=(
                    {"resume_command_id": resume_command_id}
                    if resume_command_id is not None
                    else None
                ),
            )
        else:
            journal.append_event(
                lease,
                "RunReclaimed",
                payload=(
                    {"resume_command_id": resume_command_id}
                    if resume_command_id is not None
                    else None
                ),
            )

        await self._reconcile_stale_leases(bound, lease, capability_mode=capability_mode)

        instances = self._instances(bound)
        instances_by_scope = {instance.scope.segments: instance for instance in instances}
        bindings = {
            _address_key(binding.destination): binding for binding in manifest.resolved_connections
        }
        grants = {
            binding.scope.segments: binding
            for binding in manifest.capability_bindings
            if binding.binding == SELF_BINDING
        }
        aliases: dict[tuple[str, ...], list[CapabilityBinding]] = {}
        for binding in manifest.capability_bindings:
            if binding.binding != SELF_BINDING:
                aliases.setdefault(binding.scope.segments, []).append(binding)

        units = self._root_units(manifest, instances)
        producer_units = self._unit_producer_index(units)
        ordered_units = self._ordered_units(units, bindings, producer_units)

        root_scope = ScopePath(segments=(manifest.source_graph.name,))
        values: dict[str, Any] = {
            _address_key(GraphInputAddress(scope=root_scope, port=name)): value
            for name, value in inputs.items()
        }
        status_by_unit: dict[tuple[str, ...], InvocationStatus] = {}
        failures: dict[str, str] = {}
        blocked: list[DependencyReport] = []
        parked: list[ParkedUnit] = []

        try:
            for unit in ordered_units:
                # Yield at every scheduler boundary so asyncio cancellation and
                # durable cancellation converge even when all work restores
                # synchronously from checkpoints.
                await asyncio.sleep(0)
                self._check_run_control(lease, lost)
                report = self._unit_dependency_report(
                    unit,
                    bindings,
                    producer_units,
                    status_by_unit,
                )
                if any(
                    producer.status is not InvocationStatus.COMPLETED
                    for producer in report.producers
                ):
                    status_by_unit[unit.scope.segments] = InvocationStatus.BLOCKED
                    blocked.append(report)
                    journal.append_event(
                        lease,
                        "NodeBlocked" if unit.instance is not None else "LoopBlocked",
                        path=ExecutionPath(scope=unit.scope),
                        payload=report.model_dump(mode="json"),
                    )
                    continue

                if unit.instance is not None:
                    error = await self._execute_or_restore(
                        manifest,
                        unit.instance,
                        path=ExecutionPath(scope=unit.scope),
                        lease=lease,
                        values=values,
                        bindings=bindings,
                        grants=grants,
                        aliases=aliases,
                        lost=lost,
                        effect_mode=effect_mode,
                        capability_mode=capability_mode,
                    )
                    if error is None:
                        status_by_unit[unit.scope.segments] = InvocationStatus.COMPLETED
                    else:
                        status_by_unit[unit.scope.segments] = InvocationStatus.FAILED
                        failures[unit.scope.render()] = error
                    continue

                if unit.loop is None:
                    raise ContractViolation("execution unit has neither atomic nor loop body")
                loop_status = await self._execute_loop(
                    manifest,
                    unit.loop,
                    lease=lease,
                    outer_values=values,
                    instances_by_scope=instances_by_scope,
                    bindings=bindings,
                    grants=grants,
                    aliases=aliases,
                    failures=failures,
                    blocked=blocked,
                    parked=parked,
                    lost=lost,
                    effect_mode=effect_mode,
                    capability_mode=capability_mode,
                )
                status_by_unit[unit.scope.segments] = loop_status
        except _CancelRequested:
            journal.transition_run(
                lease,
                expected=frozenset({RunStatus.RUNNING}),
                target=RunStatus.CANCELLED,
                event_kind="RunCancelled",
                payload={"source": "request"},
            )
            return RunResult(
                run_id=run_id,
                status=RunStatus.CANCELLED,
                outputs={},
                failures=failures,
                blocked=tuple(blocked),
                parked=tuple(sorted(parked, key=lambda item: item.path.render())),
            )

        parked_sorted = tuple(sorted(parked, key=lambda item: item.path.render()))
        if failures:
            journal.transition_run(
                lease,
                expected=frozenset({RunStatus.RUNNING}),
                target=RunStatus.FAILED,
                event_kind="RunFailed",
                payload={
                    "failed": sorted(failures),
                    "blocked": [report.destination.render() for report in blocked],
                    "parked": [item.model_dump(mode="json") for item in parked_sorted],
                },
            )
            return RunResult(
                run_id=run_id,
                status=RunStatus.FAILED,
                outputs={},
                failures=failures,
                blocked=tuple(blocked),
                parked=parked_sorted,
            )

        if parked_sorted:
            journal.transition_run(
                lease,
                expected=frozenset({RunStatus.RUNNING}),
                target=RunStatus.PARKED,
                event_kind="RunParked",
                payload={
                    "parked": [item.model_dump(mode="json") for item in parked_sorted],
                    "blocked": [report.destination.render() for report in blocked],
                },
            )
            return RunResult(
                run_id=run_id,
                status=RunStatus.PARKED,
                outputs={},
                failures=failures,
                blocked=tuple(blocked),
                parked=parked_sorted,
            )

        if blocked:
            raise JournalDamaged(
                "graph closure contains blocked units without any failed or parked root"
            )

        outputs = self._graph_outputs(manifest, values, bindings)
        journal.transition_run(
            lease,
            expected=frozenset({RunStatus.RUNNING}),
            target=RunStatus.SUCCEEDED,
            event_kind="RunSucceeded",
            payload={"outputs": sorted(outputs)},
        )
        return RunResult(run_id=run_id, status=RunStatus.SUCCEEDED, outputs=outputs)

    # -- loop execution -------------------------------------------------------

    async def _execute_loop(
        self,
        manifest: ExecutionManifest,
        loop: LoopResolution,
        *,
        lease: RunLease,
        outer_values: dict[str, Any],
        instances_by_scope: dict[tuple[str, ...], _Instance],
        bindings: dict[str, ResolvedPortBinding],
        grants: dict[tuple[str, ...], CapabilityBinding],
        aliases: dict[tuple[str, ...], list[CapabilityBinding]],
        failures: dict[str, str],
        blocked: list[DependencyReport],
        parked: list[ParkedUnit],
        lost: list[OwnershipLost],
        effect_mode: EffectMode,
        capability_mode: Literal["normal", "discard"],
    ) -> InvocationStatus:
        # Validate the entire durable prefix before any new implementation,
        # capability, or effect can run.
        self._inspect_loop_history(
            loop,
            run_id=lease.run_id,
            outer_values=outer_values,
            instances_by_scope=instances_by_scope,
            bindings=bindings,
            require_terminal=False,
        )

        member_producers = self._member_producer_index(loop, instances_by_scope)
        previous_values: dict[str, Any] | None = None
        loop_path = ExecutionPath(scope=loop.scope)
        executed_any = False

        for iteration in range(loop.max_iterations):
            await asyncio.sleep(0)
            self._check_run_control(lease, lost)
            frame = IterationFrame(loop=loop.scope, index=iteration)
            iteration_values = self._seed_loop_iteration(
                loop,
                iteration=iteration,
                outer_values=outer_values,
                previous_values=previous_values,
            )
            status_by_member: dict[tuple[str, ...], InvocationStatus] = {}
            iteration_failed = False
            restored_only = True

            for member_scope in loop.member_order:
                await asyncio.sleep(0)
                self._check_run_control(lease, lost)
                instance = instances_by_scope.get(member_scope.segments)
                if instance is None:
                    raise ContractViolation(
                        f"loop {loop.scope.render()} names missing member {member_scope.render()}"
                    )
                member_path = ExecutionPath(scope=member_scope, iterations=(frame,))
                report = self._member_dependency_report(
                    instance,
                    frame=frame,
                    bindings=bindings,
                    producer_of=member_producers,
                    status_by_member=status_by_member,
                )

                # One failed invocation terminates the iteration. Its downstream
                # members remain BLOCKED; independent later members are SKIPPED.
                # This preserves a contiguous durable checkpoint prefix, so resume
                # can never mistake speculative sibling work for a completed body.
                if iteration_failed:
                    if any(
                        producer.status is not InvocationStatus.COMPLETED
                        for producer in report.producers
                    ):
                        status_by_member[member_scope.segments] = InvocationStatus.BLOCKED
                        blocked.append(report)
                        self._journal.append_event(
                            lease,
                            "NodeBlocked",
                            path=member_path,
                            payload=report.model_dump(mode="json"),
                        )
                    else:
                        status_by_member[member_scope.segments] = InvocationStatus.SKIPPED
                        self._journal.append_event(
                            lease,
                            "NodeSkipped",
                            path=member_path,
                            payload={"reason": "loop_iteration_failed"},
                        )
                    continue

                if any(
                    producer.status is not InvocationStatus.COMPLETED
                    for producer in report.producers
                ):
                    status_by_member[member_scope.segments] = InvocationStatus.BLOCKED
                    blocked.append(report)
                    self._journal.append_event(
                        lease,
                        "NodeBlocked",
                        path=member_path,
                        payload=report.model_dump(mode="json"),
                    )
                    iteration_failed = True
                    continue

                had_checkpoint = self._journal.checkpoint(lease.run_id, member_path) is not None
                error = await self._execute_or_restore(
                    manifest,
                    instance,
                    path=member_path,
                    lease=lease,
                    values=iteration_values,
                    bindings=bindings,
                    grants=grants,
                    aliases=aliases,
                    lost=lost,
                    effect_mode=effect_mode,
                    capability_mode=capability_mode,
                )
                if not had_checkpoint:
                    restored_only = False
                    executed_any = True
                if error is None:
                    status_by_member[member_scope.segments] = InvocationStatus.COMPLETED
                else:
                    status_by_member[member_scope.segments] = InvocationStatus.FAILED
                    failures[member_path.render()] = error
                    iteration_failed = True

            if iteration_failed:
                return InvocationStatus.FAILED

            try:
                decision = self._loop_decision(loop, iteration_values)
            except ContractViolation as exc:
                failures[loop_path.render()] = f"{type(exc).__name__}: {exc}"
                self._journal.append_event(
                    lease,
                    "LoopFailed",
                    path=loop_path,
                    payload={"error": str(exc), "iteration": iteration},
                )
                return InvocationStatus.FAILED
            iteration_path = ExecutionPath(scope=loop.scope, iterations=(frame,))
            self._journal.append_event(
                lease,
                "LoopIterationRestored" if restored_only else "LoopIterationCompleted",
                path=iteration_path,
                payload={"continue": decision},
            )
            if not decision:
                self._publish_loop_exports(loop, iteration_values, outer_values)
                self._journal.append_event(
                    lease,
                    "LoopCompleted" if executed_any else "LoopRestored",
                    path=loop_path,
                    payload={"iterations": iteration + 1},
                )
                return InvocationStatus.COMPLETED
            previous_values = iteration_values

        parked_unit = ParkedUnit(
            path=loop_path,
            reason="policy_exhausted",
            completed_iterations=loop.max_iterations,
        )
        parked.append(parked_unit)
        self._journal.append_event(
            lease,
            "LoopPolicyExhausted" if executed_any else "LoopPolicyReobserved",
            path=loop_path,
            payload=parked_unit.model_dump(mode="json"),
        )
        return InvocationStatus.PARKED

    def _inspect_loop_history(
        self,
        loop: LoopResolution,
        *,
        run_id: RunId,
        outer_values: dict[str, Any],
        instances_by_scope: dict[tuple[str, ...], _Instance],
        bindings: dict[str, ResolvedPortBinding],
        require_terminal: bool,
    ) -> _LoopHistory:
        """Validate and replay a contiguous durable iteration prefix.

        A later member checkpoint after a gap, a later iteration after a false
        decision, or a checkpoint with a contradictory input/version is journal
        damage. This inspector is used by both resume and materialization.
        """

        matrix: list[list[Checkpoint | None]] = []
        for index in range(loop.max_iterations):
            frame = IterationFrame(loop=loop.scope, index=index)
            matrix.append(
                [
                    self._journal.checkpoint(
                        run_id,
                        ExecutionPath(scope=scope, iterations=(frame,)),
                    )
                    for scope in loop.member_order
                ]
            )

        previous_values: dict[str, Any] | None = None
        completed = 0
        for index, checkpoints in enumerate(matrix):
            present = [checkpoint is not None for checkpoint in checkpoints]
            if not any(present):
                if any(any(item is not None for item in later) for later in matrix[index + 1 :]):
                    raise JournalDamaged(
                        f"loop {loop.scope.render()} has iteration {index + 1} "
                        f"checkpoints after an empty iteration {index}"
                    )
                if require_terminal:
                    raise JournalDamaged(
                        f"successful run has incomplete loop {loop.scope.render()} at "
                        f"iteration {index}"
                    )
                return _LoopHistory(completed, None, False, previous_values)

            missing_seen = False
            for exists in present:
                if not exists:
                    missing_seen = True
                elif missing_seen:
                    raise JournalDamaged(
                        f"loop {loop.scope.render()} iteration {index} contains a "
                        "member checkpoint after a missing earlier member"
                    )
            if not all(present):
                if any(any(item is not None for item in later) for later in matrix[index + 1 :]):
                    raise JournalDamaged(
                        f"loop {loop.scope.render()} has later iteration checkpoints "
                        f"after partial iteration {index}"
                    )
                # Validate the durable prefix within this partial iteration.
                values = self._seed_loop_iteration(
                    loop,
                    iteration=index,
                    outer_values=outer_values,
                    previous_values=previous_values,
                )
                for member_scope, checkpoint in zip(
                    loop.member_order,
                    checkpoints,
                    strict=True,
                ):
                    if checkpoint is None:
                        break
                    instance = instances_by_scope[member_scope.segments]
                    self._restore_checked_checkpoint(instance, checkpoint, values, bindings)
                if require_terminal:
                    raise JournalDamaged(
                        f"successful run has partial loop {loop.scope.render()} iteration {index}"
                    )
                return _LoopHistory(completed, None, False, previous_values)

            values = self._seed_loop_iteration(
                loop,
                iteration=index,
                outer_values=outer_values,
                previous_values=previous_values,
            )
            for member_scope, checkpoint in zip(
                loop.member_order,
                checkpoints,
                strict=True,
            ):
                assert checkpoint is not None
                instance = instances_by_scope[member_scope.segments]
                self._restore_checked_checkpoint(instance, checkpoint, values, bindings)
            completed += 1
            decision = self._loop_decision(loop, values)
            if not decision:
                if any(any(item is not None for item in later) for later in matrix[index + 1 :]):
                    raise JournalDamaged(
                        f"loop {loop.scope.render()} has checkpoints after terminal "
                        f"false decision at iteration {index}"
                    )
                return _LoopHistory(completed, index, False, values)
            previous_values = values

        if require_terminal:
            raise JournalDamaged(
                f"successful run materialization found exhausted loop "
                f"{loop.scope.render()} with no false decision"
            )
        return _LoopHistory(completed, None, True, previous_values)

    def _seed_loop_iteration(
        self,
        loop: LoopResolution,
        *,
        iteration: int,
        outer_values: dict[str, Any],
        previous_values: dict[str, Any] | None,
    ) -> dict[str, Any]:
        initial = {
            binding.destination.port: binding
            for binding in loop.initial_bindings
            if isinstance(binding.destination, GraphInputAddress)
        }
        feedback = {
            binding.destination.port: binding
            for binding in loop.feedback_bindings
            if isinstance(binding.destination, GraphInputAddress)
        }
        values: dict[str, Any] = {}
        for port in loop.input_ports:
            use_feedback = iteration > 0 and port.name in feedback
            binding = feedback.get(port.name) if use_feedback else initial.get(port.name)
            if binding is None:
                continue
            source_values = previous_values if use_feedback else outer_values
            if source_values is None:
                raise JournalDamaged(
                    f"loop {loop.scope.render()} iteration {iteration} has feedback "
                    "without a previous completed iteration"
                )
            value = _collect(source_values, binding.sources, port)
            values[_address_key(binding.destination)] = value
        return values

    @staticmethod
    def _loop_decision(loop: LoopResolution, values: dict[str, Any]) -> bool:
        key = _address_key(loop.continue_source)
        if key not in values:
            raise ContractViolation(
                f"loop {loop.scope.render()} continuation source {key} is unavailable"
            )
        decision = values[key]
        if type(decision) is not bool:
            raise ContractViolation(
                f"loop {loop.scope.render()} continuation must be exactly bool, "
                f"received {type(decision).__name__}"
            )
        return decision

    @staticmethod
    def _publish_loop_exports(
        loop: LoopResolution,
        iteration_values: dict[str, Any],
        outer_values: dict[str, Any],
    ) -> None:
        for export in loop.exports:
            outer_values[_address_key(export.destination)] = _collect(
                iteration_values,
                export.sources,
                export.port,
            )

    # -- capability leases ----------------------------------------------------

    async def _close_acquired(
        self,
        lease: RunLease,
        acquired: list[tuple[LeasedCapability, AcquiredCapability]],
        disposition: Disposition,
    ) -> None:
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
        self,
        bound: BoundExecution,
        lease: RunLease,
        *,
        capability_mode: Literal["normal", "discard"],
    ) -> None:
        journal = self._journal
        manifest = bound.manifest
        stale_rows = [
            row
            for row in journal.capability_leases(lease.run_id)
            if row.state == "active" and row.acquisition_epoch < lease.epoch
        ]
        if not stale_rows:
            return
        bindings = {
            (binding.scope.segments, binding.binding): binding
            for binding in manifest.capability_bindings
        }
        for row in stale_rows:
            binding = bindings.get((row.path.scope.segments, row.binding_id))
            checkpointed = journal.checkpoint(lease.run_id, row.path) is not None
            disposition: Disposition = (
                "discard"
                if capability_mode == "discard"
                else "release"
                if checkpointed
                else "discard"
            )
            if binding is not None:
                capability = self._capabilities.get(binding.capability_id)
                if isinstance(capability, LeasedCapability):
                    context = LeaseContext(
                        run_lease=lease,
                        binding=binding,
                        path=row.path,
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

    # -- structure and dependencies ------------------------------------------

    def _load_manifest(self, run_id: RunId) -> ExecutionManifest:
        manifest_hash = self._journal.run_manifest_hash(run_id)
        if manifest_hash is None:
            raise ContractViolation(f"unknown run {run_id!r}")
        manifest_json = self._journal.load_manifest_json(manifest_hash)
        if manifest_json is None:
            raise ContractViolation(
                f"manifest {manifest_hash} for run {run_id!r} is not in the journal"
            )
        try:
            return parse_manifest_json(manifest_json)
        except (ValueError, TypeError) as exc:
            raise JournalDamaged(
                f"manifest {manifest_hash} for run {run_id!r} is damaged: {exc}"
            ) from exc

    def load_manifest(self, run_id: RunId) -> ExecutionManifest:
        """Load and version-validate one current or historical durable manifest."""

        return self._load_manifest(run_id)

    def materialize_run(self, run_id: RunId) -> dict[str, Any]:
        """Materialize one run from durable manifest, inputs, and checkpoints."""

        manifest = self._load_manifest(run_id)
        inputs = self._journal.run_inputs(run_id)
        if inputs is None:
            raise ContractViolation(f"run {run_id!r} has no recorded inputs")
        return self._materialize(manifest, run_id, inputs)

    def _instances(self, bound: BoundExecution) -> list[_Instance]:
        instances: list[_Instance] = []
        for resolution in bound.manifest.resolved_components:
            binding = bound.bound(resolution.component, resolution.resolved_version)
            if binding.loadability.status == "composite":
                continue
            if binding.impl is None:
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

    def _materialization_instances(self, manifest: ExecutionManifest) -> list[_Instance]:
        snapshot = self._registry.snapshot()
        instances: list[_Instance] = []
        for resolution in manifest.resolved_components:
            stored = snapshot.get(resolution.component, resolution.resolved_version)
            if stored is None:
                raise JournalDamaged(
                    f"cannot materialize {resolution.scope.render()}: exact component "
                    f"{resolution.component}@{resolution.resolved_version} is missing"
                )
            if isinstance(stored.definition.body, Graph):
                continue
            instances.append(
                _Instance(
                    scope=resolution.scope,
                    component=resolution.component,
                    version=resolution.resolved_version,
                    definition=stored.definition,
                    impl=None,
                )
            )
        return instances

    @staticmethod
    def _root_units(
        manifest: ExecutionManifest,
        instances: list[_Instance],
    ) -> list[_Unit]:
        member_scopes = {
            scope.segments for loop in manifest.resolved_loops for scope in loop.member_order
        }
        units = [
            _Unit(scope=instance.scope, instance=instance)
            for instance in instances
            if instance.scope.segments not in member_scopes
        ]
        units.extend(_Unit(scope=loop.scope, loop=loop) for loop in manifest.resolved_loops)
        return units

    @staticmethod
    def _atomic_output_address(instance: _Instance, port: Port) -> NodePortAddress:
        level = ScopePath(segments=instance.scope.segments[:-1])
        return NodePortAddress(
            scope=level,
            node=instance.scope.segments[-1],
            port=port.name,
        )

    def _unit_producer_index(self, units: list[_Unit]) -> dict[str, _Unit]:
        result: dict[str, _Unit] = {}
        for unit in units:
            if unit.instance is not None:
                for port in unit.instance.definition.outputs:
                    result[_address_key(self._atomic_output_address(unit.instance, port))] = unit
            elif unit.loop is not None:
                for export in unit.loop.exports:
                    result[_address_key(export.destination)] = unit
        return result

    def _member_producer_index(
        self,
        loop: LoopResolution,
        instances_by_scope: dict[tuple[str, ...], _Instance],
    ) -> dict[str, _Instance]:
        result: dict[str, _Instance] = {}
        for scope in loop.member_order:
            instance = instances_by_scope[scope.segments]
            for port in instance.definition.outputs:
                result[_address_key(self._atomic_output_address(instance, port))] = instance
        return result

    @staticmethod
    def _unit_input_bindings(
        unit: _Unit,
        bindings: dict[str, ResolvedPortBinding],
    ) -> list[ResolvedPortBinding]:
        if unit.loop is not None:
            return list(unit.loop.initial_bindings)
        if unit.instance is None:
            return []
        level = ScopePath(segments=unit.instance.scope.segments[:-1])
        node = unit.instance.scope.segments[-1]
        result: list[ResolvedPortBinding] = []
        for port in unit.instance.definition.inputs:
            binding = bindings.get(
                _address_key(NodePortAddress(scope=level, node=node, port=port.name))
            )
            if binding is not None:
                result.append(binding)
        return result

    def _ordered_units(
        self,
        units: list[_Unit],
        bindings: dict[str, ResolvedPortBinding],
        producer_of: dict[str, _Unit],
    ) -> list[_Unit]:
        dependencies: dict[tuple[str, ...], set[tuple[str, ...]]] = {
            unit.scope.segments: set() for unit in units
        }
        for unit in units:
            for binding in self._unit_input_bindings(unit, bindings):
                for source in binding.sources:
                    producer = producer_of.get(_address_key(source))
                    if producer is not None:
                        dependencies[unit.scope.segments].add(producer.scope.segments)
        by_scope = {unit.scope.segments: unit for unit in units}
        ordered: list[_Unit] = []
        placed: set[tuple[str, ...]] = set()

        def place(scope: tuple[str, ...], trail: tuple[tuple[str, ...], ...]) -> None:
            if scope in placed:
                return
            if scope in trail:
                raise ContractViolation("manifest contains a root dependency cycle")
            for dependency in sorted(dependencies[scope]):
                place(dependency, (*trail, scope))
            placed.add(scope)
            ordered.append(by_scope[scope])

        for unit in sorted(units, key=lambda item: item.scope.segments):
            place(unit.scope.segments, ())
        return ordered

    def _unit_dependency_report(
        self,
        unit: _Unit,
        bindings: dict[str, ResolvedPortBinding],
        producer_of: dict[str, _Unit],
        status_by_unit: dict[tuple[str, ...], InvocationStatus],
    ) -> DependencyReport:
        producers: list[ProducerStatus] = []
        seen: set[tuple[str, ...]] = set()
        for binding in self._unit_input_bindings(unit, bindings):
            for source in binding.sources:
                producer = producer_of.get(_address_key(source))
                if producer is None or producer.scope.segments in seen:
                    continue
                seen.add(producer.scope.segments)
                producers.append(
                    ProducerStatus(
                        path=ExecutionPath(scope=producer.scope),
                        status=status_by_unit.get(
                            producer.scope.segments,
                            InvocationStatus.QUEUED,
                        ),
                    )
                )
        return DependencyReport(
            destination=ExecutionPath(scope=unit.scope),
            producers=tuple(producers),
        )

    def _member_dependency_report(
        self,
        instance: _Instance,
        *,
        frame: IterationFrame,
        bindings: dict[str, ResolvedPortBinding],
        producer_of: dict[str, _Instance],
        status_by_member: dict[tuple[str, ...], InvocationStatus],
    ) -> DependencyReport:
        producers: list[ProducerStatus] = []
        seen: set[tuple[str, ...]] = set()
        level = ScopePath(segments=instance.scope.segments[:-1])
        node = instance.scope.segments[-1]
        for port in instance.definition.inputs:
            binding = bindings.get(
                _address_key(NodePortAddress(scope=level, node=node, port=port.name))
            )
            if binding is None:
                continue
            for source in binding.sources:
                producer = producer_of.get(_address_key(source))
                if producer is None or producer.scope.segments in seen:
                    continue
                seen.add(producer.scope.segments)
                producers.append(
                    ProducerStatus(
                        path=ExecutionPath(
                            scope=producer.scope,
                            iterations=(frame,),
                        ),
                        status=status_by_member.get(
                            producer.scope.segments,
                            InvocationStatus.QUEUED,
                        ),
                    )
                )
        return DependencyReport(
            destination=ExecutionPath(scope=instance.scope, iterations=(frame,)),
            producers=tuple(producers),
        )

    # -- one atomic invocation ------------------------------------------------

    async def _execute_or_restore(
        self,
        manifest: ExecutionManifest,
        instance: _Instance,
        *,
        path: ExecutionPath,
        lease: RunLease,
        values: dict[str, Any],
        bindings: dict[str, ResolvedPortBinding],
        grants: dict[tuple[str, ...], CapabilityBinding],
        aliases: dict[tuple[str, ...], list[CapabilityBinding]],
        lost: list[OwnershipLost],
        effect_mode: EffectMode,
        capability_mode: Literal["normal", "discard"],
    ) -> str | None:
        node_inputs = self._node_inputs(instance, values, bindings)
        input_hash = digest("inputs", 1, node_inputs)
        checkpoint = self._journal.checkpoint(lease.run_id, path)
        if checkpoint is not None:
            if (
                checkpoint.input_hash != input_hash
                or checkpoint.resolved_version != instance.version
            ):
                raise CheckpointConflict(
                    f"run {lease.run_id!r} {path.render()}: durable completion "
                    "contradicts the current input hash or component version; "
                    "refusing before execution"
                )
            self._journal.append_event(lease, "NodeRestored", path=path)
            outputs = {port: envelope.payload for port, envelope in checkpoint.outputs.items()}
        else:
            try:
                outputs = await self._invoke(
                    manifest,
                    instance,
                    path=path,
                    lease=lease,
                    node_inputs=node_inputs,
                    input_hash=input_hash,
                    grants=grants,
                    aliases=aliases,
                    lost=lost,
                    effect_mode=effect_mode,
                    capability_mode=capability_mode,
                )
            except (OwnershipLost, CheckpointConflict, _CancelRequested):
                raise
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._journal.append_event(
                    lease,
                    "NodeFailed",
                    path=path,
                    payload={"error": str(exc), "error_type": type(exc).__name__},
                )
                return f"{type(exc).__name__}: {exc}"
        self._publish_atomic_outputs(instance, outputs, values)
        return None

    def _node_inputs(
        self,
        instance: _Instance,
        values: dict[str, Any],
        bindings: dict[str, ResolvedPortBinding],
    ) -> dict[str, Any]:
        level = ScopePath(segments=instance.scope.segments[:-1])
        node = instance.scope.segments[-1]
        inputs: dict[str, Any] = {}
        for port in instance.definition.inputs:
            binding = bindings.get(
                _address_key(NodePortAddress(scope=level, node=node, port=port.name))
            )
            if binding is None:
                if port.cardinality == "optional":
                    inputs[port.name] = None
                    continue
                raise ContractViolation(
                    f"{instance.scope.render()}: input {port.name!r} has no binding "
                    "in the sealed manifest"
                )
            inputs[port.name] = _collect(values, binding.sources, port)
        return inputs

    async def _invoke(
        self,
        manifest: ExecutionManifest,
        instance: _Instance,
        *,
        path: ExecutionPath,
        lease: RunLease,
        node_inputs: dict[str, Any],
        input_hash: Digest,
        grants: dict[tuple[str, ...], CapabilityBinding],
        aliases: dict[tuple[str, ...], list[CapabilityBinding]],
        lost: list[OwnershipLost],
        effect_mode: EffectMode,
        capability_mode: Literal["normal", "discard"],
    ) -> dict[str, Any]:
        self._journal.append_event(lease, "NodeStarted", path=path)
        self_binding = grants.get(instance.scope.segments)
        if self_binding is None:
            raise ContractViolation(f"{instance.scope.render()}: manifest carries no sealed grants")
        if instance.impl is None:
            raise ContractViolation(
                f"{instance.scope.render()}: no live implementation is activated"
            )

        capabilities: dict[str, object] = {}
        acquired: list[tuple[LeasedCapability, AcquiredCapability]] = []
        for alias_binding in aliases.get(instance.scope.segments, ()):
            self._check_run_control(lease, lost)
            capability = self._capabilities.get(alias_binding.capability_id)
            if capability is None:
                raise ContractViolation(
                    f"{instance.scope.render()}: admitted capability "
                    f"{alias_binding.capability_id!r} was not injected"
                )
            descriptor = self._catalog.get(alias_binding.capability_id)
            if descriptor is not None and descriptor.leased:
                if not isinstance(capability, LeasedCapability):
                    raise ContractViolation(
                        f"{instance.scope.render()}: capability "
                        f"{alias_binding.capability_id!r} is declared leased but "
                        "does not implement LeasedCapability"
                    )
                acquisition = await capability.acquire(
                    LeaseContext(
                        run_lease=lease,
                        binding=alias_binding,
                        path=path,
                        manifest_hash=manifest.manifest_hash,
                    )
                )
                self._journal.record_capability_lease(
                    lease,
                    CapabilityLease(
                        lease_id=acquisition.lease_id,
                        acquisition_epoch=lease.epoch,
                        run_id=lease.run_id,
                        binding_id=alias_binding.binding,
                        path=path,
                        lifetime="invocation",
                        state="active",
                        resource_ref=acquisition.resource_ref,
                    ),
                )
                capabilities[alias_binding.binding] = acquisition.resource
                acquired.append((capability, acquisition))
            else:
                capabilities[alias_binding.binding] = capability

        context = NodeContext(
            run_id=lease.run_id,
            path=path,
            capabilities=capabilities,
            grants=self_binding.effective_grants,
            effect=self._effect_boundary(manifest, lease, path, lost, mode=effect_mode),
        )

        try:
            raw_outputs: Mapping[str, Any] = await instance.impl(context, node_inputs)
            if not isinstance(raw_outputs, Mapping):
                raise ContractViolation(
                    f"{instance.scope.render()}: implementation returned "
                    f"{type(raw_outputs).__name__}, expected a mapping"
                )
            declared = {port.name for port in instance.definition.outputs}
            missing = sorted(declared - set(raw_outputs))
            extra = sorted(set(raw_outputs) - declared)
            if missing or extra:
                raise ContractViolation(
                    f"{instance.scope.render()}: output contract mismatch; "
                    f"missing={missing}, extra={extra}"
                )
            outputs = {name: json_value(raw_outputs[name]) for name in declared}
            envelopes: dict[str, Envelope[Any]] = {
                name: Envelope(
                    run_id=lease.run_id,
                    path=path,
                    port=name,
                    created_at=utc_now(),
                    payload=outputs[name],
                )
                for name in declared
            }
            self._journal.record_completion(
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
            raise
        except (_CancelRequested, asyncio.CancelledError):
            await self._close_acquired(lease, acquired, "discard")
            raise
        except Exception:
            await self._close_acquired(lease, acquired, "discard")
            raise
        await self._close_acquired(
            lease,
            acquired,
            "discard" if capability_mode == "discard" else "release",
        )
        return outputs

    def _restore_checked_checkpoint(
        self,
        instance: _Instance,
        checkpoint: Checkpoint,
        values: dict[str, Any],
        bindings: dict[str, ResolvedPortBinding],
    ) -> None:
        expected_inputs = self._node_inputs(instance, values, bindings)
        expected_hash = digest("inputs", 1, expected_inputs)
        if (
            checkpoint.input_hash != expected_hash
            or checkpoint.resolved_version != instance.version
        ):
            raise CheckpointConflict(
                f"{checkpoint.path.render()}: checkpoint contradicts the reconstructed "
                "loop input hash or component version"
            )
        outputs = {port: envelope.payload for port, envelope in checkpoint.outputs.items()}
        self._publish_atomic_outputs(instance, outputs, values)

    def _publish_atomic_outputs(
        self,
        instance: _Instance,
        outputs: dict[str, Any],
        values: dict[str, Any],
    ) -> None:
        for port in instance.definition.outputs:
            if port.name not in outputs:
                raise JournalDamaged(
                    f"{instance.scope.render()}: durable outputs omit {port.name!r}"
                )
            values[_address_key(self._atomic_output_address(instance, port))] = json_value(
                outputs[port.name]
            )

    # -- effects --------------------------------------------------------------

    def _effect_boundary(
        self,
        manifest: ExecutionManifest,
        lease: RunLease,
        path: ExecutionPath,
        lost: list[OwnershipLost],
        *,
        mode: EffectMode,
    ) -> Any:
        journal = self._journal
        effects = self._effects

        async def boundary(
            kind: str,
            subject: dict[str, Any],
            *,
            attestation_id: str | None = None,
        ) -> EffectReceipt:
            self._check_run_control(lease, lost)
            normalized = json_value(subject)
            if not isinstance(normalized, dict):
                raise ContractViolation("effect subject must be a JSON object")
            key = idempotency_key(manifest.manifest_hash, path, kind, normalized, mode=mode)
            existing = journal.receipt_for(key)
            terminal_statuses = ("simulated",) if mode == "simulated" else ("committed", "rejected")
            if existing is not None and existing.status in terminal_statuses:
                journal.append_event(
                    lease,
                    "EffectDeduplicated",
                    path=path,
                    payload={"kind": kind},
                )
                return existing
            adapter = effects.get(kind)
            if adapter is None:
                raise ContractViolation(
                    f"no effect adapter for kind {kind!r}; assembled: {sorted(effects)}"
                )
            request = EffectRequest(
                run_id=lease.run_id,
                manifest_hash=manifest.manifest_hash,
                path=path,
                kind=kind,
                subject=normalized,
                idempotency_key=key,
                attestation_id=attestation_id,
                mode=mode,
            )
            if mode == "live" and journal.effect_prepared(key):
                reconciled = await adapter.reconcile(request)
                if reconciled is not None:
                    journal.record_effect_outcome(
                        lease,
                        request,
                        reconciled,
                        "EffectReconciled",
                    )
                    return reconciled
            self._check_run_control(lease, lost)
            journal.record_effect_prepared(lease, request)
            if mode == "simulated":
                if adapter.profile.simulation != "supported":
                    raise ContractViolation(
                        f"effect {kind!r} does not support counterfactual simulation"
                    )
                receipt = await adapter.simulate(request)
            else:
                receipt = await adapter.execute(request)
            event_kind = {
                "committed": "EffectCommitted",
                "rejected": "EffectRejected",
                "simulated": "EffectSimulated",
            }.get(receipt.status, "EffectUnresolved")
            journal.record_effect_outcome(lease, request, receipt, event_kind)
            return receipt

        return boundary

    # -- materialization ------------------------------------------------------

    def _materialize(
        self,
        manifest: ExecutionManifest,
        run_id: RunId,
        inputs: dict[str, Any],
    ) -> dict[str, Any]:
        instances = self._materialization_instances(manifest)
        instances_by_scope = {instance.scope.segments: instance for instance in instances}
        bindings = {
            _address_key(binding.destination): binding for binding in manifest.resolved_connections
        }
        units = self._root_units(manifest, instances)
        producers = self._unit_producer_index(units)
        ordered = self._ordered_units(units, bindings, producers)
        root_scope = ScopePath(segments=(manifest.source_graph.name,))
        values: dict[str, Any] = {
            _address_key(GraphInputAddress(scope=root_scope, port=name)): json_value(value)
            for name, value in inputs.items()
        }

        for unit in ordered:
            if unit.instance is not None:
                checkpoint = self._journal.checkpoint(
                    run_id,
                    ExecutionPath(scope=unit.scope),
                )
                if checkpoint is None:
                    raise JournalDamaged(
                        f"successful run lacks checkpoint for {unit.scope.render()}"
                    )
                self._restore_checked_checkpoint(unit.instance, checkpoint, values, bindings)
                continue
            if unit.loop is None:
                raise JournalDamaged("manifest contains an empty execution unit")
            history = self._inspect_loop_history(
                unit.loop,
                run_id=run_id,
                outer_values=values,
                instances_by_scope=instances_by_scope,
                bindings=bindings,
                require_terminal=True,
            )
            if history.terminal_iteration is None or history.final_values is None:
                raise JournalDamaged(
                    f"successful run has no terminal loop state for {unit.scope.render()}"
                )
            self._publish_loop_exports(unit.loop, history.final_values, values)

        return self._graph_outputs(manifest, values, bindings)

    @staticmethod
    def _graph_outputs(
        manifest: ExecutionManifest,
        values: dict[str, Any],
        bindings: dict[str, ResolvedPortBinding],
    ) -> dict[str, Any]:
        root_scope = ScopePath(segments=(manifest.source_graph.name,))
        outputs: dict[str, Any] = {}
        for port in manifest.source_graph.outputs:
            binding = bindings.get(
                _address_key(GraphOutputAddress(scope=root_scope, port=port.name))
            )
            if binding is not None:
                outputs[port.name] = _collect(values, binding.sources, port)
        return outputs


def _collect(
    values: dict[str, Any],
    sources: tuple[PortAddress, ...],
    port: Port,
) -> Any:
    resolved: list[Any] = []
    for source in sources:
        key = _address_key(source)
        if key not in values:
            raise ContractViolation(
                f"value for {key} is unavailable; reaching collection without a "
                "completed producer is kernel damage"
            )
        resolved.append(values[key])
    if port.cardinality == "many":
        return resolved
    if len(resolved) != 1:
        raise ContractViolation(
            f"port {port.name!r} has cardinality {port.cardinality!r} but "
            f"{len(resolved)} sources were sealed"
        )
    return resolved[0]
