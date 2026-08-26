"""The walker — dependency-driven execution of a sealed manifest (I13).

The walker accepts ONLY an ``ExecutionManifest``. Once validation has returned,
it never resolves a reference, searches for a port, inherits a grant, chooses a
capability, interprets a selector string, or decides whether an effect is safe:
every such decision lives in the manifest or in a deterministic effect adapter.

Resume re-walks the graph: a completed checkpoint at the same ExecutionPath
(with matching input hash and resolved version) short-circuits; the first miss
resumes live. Effects are at-least-once bounded by idempotency: once an effect
has a committed receipt, no replay, crash, or retry causes a second externally
visible transition.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.component import ComponentDef
from constructicon.core.effect import (
    EffectAdapter,
    EffectReceipt,
    EffectRequest,
    idempotency_key,
    request_hash,
)
from constructicon.core.envelope import Envelope, utc_now
from constructicon.core.errors import ContractViolation
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, digest
from constructicon.core.journal import Checkpoint, Journal, RunStatus
from constructicon.core.manifest import CapabilityBinding, ExecutionManifest
from constructicon.core.ports import (
    GraphInputAddress,
    GraphOutputAddress,
    NodePortAddress,
    Port,
    PortAddress,
)
from constructicon.runtime.context import NodeContext
from constructicon.runtime.registry import ComponentRegistry
from constructicon.runtime.validator import SELF_BINDING


@dataclass(frozen=True)
class RunResult:
    run_id: RunId
    status: RunStatus
    outputs: dict[str, Any]


@dataclass(frozen=True)
class _Instance:
    scope: ScopePath
    component: str
    version: Digest
    definition: ComponentDef


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
        effects: Mapping[str, EffectAdapter],
    ) -> None:
        self._registry = registry
        self._journal = journal
        self._capabilities = dict(capabilities)
        self._effects = dict(effects)

    async def run(
        self,
        manifest: ExecutionManifest,
        *,
        run_id: RunId,
        inputs: dict[str, Any],
    ) -> RunResult:
        journal = self._journal
        if journal.run_status(run_id) is None:
            journal.store_manifest(manifest.model_dump_json(), manifest.manifest_hash)
            journal.create_run(run_id, manifest.manifest_hash, manifest.input_hash)
            journal.append_event(run_id, "RunStarted", payload={"inputs": inputs})
        journal.set_run_status(run_id, RunStatus.RUNNING)

        instances = self._instances(manifest)
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

        root_scope = ScopePath(segments=(manifest.source_graph.name,))
        values: dict[str, Any] = {
            _address_key(GraphInputAddress(scope=root_scope, port=name)): value
            for name, value in inputs.items()
        }

        try:
            for instance in self._ordered(instances, bindings_by_destination):
                await self._execute_or_restore(
                    manifest,
                    instance,
                    run_id=run_id,
                    values=values,
                    bindings_by_destination=bindings_by_destination,
                    grants_by_scope=grants_by_scope,
                    aliases_by_scope=aliases_by_scope,
                )
        except Exception:
            journal.set_run_status(run_id, RunStatus.FAILED)
            journal.append_event(run_id, "RunFailed")
            raise

        outputs: dict[str, Any] = {}
        for port in manifest.source_graph.outputs:
            out_binding = bindings_by_destination.get(
                _address_key(GraphOutputAddress(scope=root_scope, port=port.name))
            )
            if out_binding is None:
                continue
            outputs[port.name] = _collect(values, out_binding.sources, port)
        journal.set_run_status(run_id, RunStatus.SUCCEEDED)
        journal.append_event(run_id, "RunSucceeded", payload={"outputs": list(outputs)})
        return RunResult(run_id=run_id, status=RunStatus.SUCCEEDED, outputs=outputs)

    async def resume(self, run_id: RunId) -> RunResult:
        manifest = self._load_manifest(run_id)
        inputs = self._journal.run_inputs(run_id)
        if inputs is None:
            raise ContractViolation(f"run {run_id!r} has no recorded inputs to resume from")
        return await self.run(manifest, run_id=run_id, inputs=inputs)

    async def reproduce(self, source_run_id: RunId, *, new_run_id: RunId) -> RunResult:
        """A new run under a past run's exact sealed world."""
        manifest = self._load_manifest(source_run_id)
        inputs = self._journal.run_inputs(source_run_id)
        if inputs is None:
            raise ContractViolation(
                f"run {source_run_id!r} has no recorded inputs to reproduce from"
            )
        return await self.run(manifest, run_id=new_run_id, inputs=inputs)

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

    def _instances(self, manifest: ExecutionManifest) -> list[_Instance]:
        instances: list[_Instance] = []
        for resolution in manifest.resolved_components:
            record = self._registry.get_exact(
                resolution.component, resolution.resolved_version
            )
            if isinstance(record.definition.body, Graph):
                continue  # composites flattened at admission; atomics execute
            instances.append(
                _Instance(
                    scope=resolution.scope,
                    component=resolution.component,
                    version=resolution.resolved_version,
                    definition=record.definition,
                )
            )
        return instances

    def _ordered(
        self,
        instances: list[_Instance],
        bindings_by_destination: dict[str, Any],
    ) -> list[_Instance]:
        producer_of: dict[str, _Instance] = {}
        for instance in instances:
            level = ScopePath(segments=instance.scope.segments[:-1])
            node = instance.scope.segments[-1]
            for port in instance.definition.outputs:
                address = NodePortAddress(scope=level, node=node, port=port.name)
                producer_of[_address_key(address)] = instance

        dependencies: dict[tuple[str, ...], set[tuple[str, ...]]] = {
            instance.scope.segments: set() for instance in instances
        }
        for instance in instances:
            level = ScopePath(segments=instance.scope.segments[:-1])
            node = instance.scope.segments[-1]
            for port in instance.definition.inputs:
                binding = bindings_by_destination.get(
                    _address_key(NodePortAddress(scope=level, node=node, port=port.name))
                )
                if binding is None:
                    continue
                for source in binding.sources:
                    producer = producer_of.get(_address_key(source))
                    if producer is not None:
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

    async def _execute_or_restore(
        self,
        manifest: ExecutionManifest,
        instance: _Instance,
        *,
        run_id: RunId,
        values: dict[str, Any],
        bindings_by_destination: dict[str, Any],
        grants_by_scope: dict[tuple[str, ...], CapabilityBinding],
        aliases_by_scope: dict[tuple[str, ...], list[CapabilityBinding]],
    ) -> None:
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
        checkpoint = journal.checkpoint(run_id, path)
        if (
            checkpoint is not None
            and checkpoint.input_hash == input_hash
            and checkpoint.resolved_version == instance.version
        ):
            journal.append_event(run_id, "NodeRestored", path=path)
            outputs = {port: env.payload for port, env in checkpoint.outputs.items()}
        else:
            outputs = await self._invoke(
                manifest,
                instance,
                run_id=run_id,
                path=path,
                node_inputs=node_inputs,
                input_hash=input_hash,
                grants_by_scope=grants_by_scope,
                aliases_by_scope=aliases_by_scope,
            )

        for port in instance.definition.outputs:
            address = NodePortAddress(scope=level, node=node, port=port.name)
            values[_address_key(address)] = outputs[port.name]

    async def _invoke(
        self,
        manifest: ExecutionManifest,
        instance: _Instance,
        *,
        run_id: RunId,
        path: ExecutionPath,
        node_inputs: dict[str, Any],
        input_hash: Digest,
        grants_by_scope: dict[tuple[str, ...], CapabilityBinding],
        aliases_by_scope: dict[tuple[str, ...], list[CapabilityBinding]],
    ) -> dict[str, Any]:
        journal = self._journal
        journal.append_event(run_id, "NodeStarted", path=path)

        record = self._registry.get_exact(instance.component, instance.version)
        if record.impl is None:
            raise ContractViolation(
                f"{instance.scope.render()}: atomic component without implementation"
            )
        self_binding = grants_by_scope.get(instance.scope.segments)
        if self_binding is None:
            raise ContractViolation(
                f"{instance.scope.render()}: manifest carries no sealed grants — "
                "admission should have refused this graph"
            )
        capabilities: dict[str, object] = {}
        for alias_binding in aliases_by_scope.get(instance.scope.segments, ()):  # injected
            capability = self._capabilities.get(alias_binding.capability_id)
            if capability is None:
                raise ContractViolation(
                    f"{instance.scope.render()}: admitted capability "
                    f"{alias_binding.capability_id!r} was not injected at assembly"
                )
            capabilities[alias_binding.binding] = capability

        boundary = self._effect_boundary(manifest, run_id, path)
        context = NodeContext(
            run_id=run_id,
            path=path,
            capabilities=capabilities,
            grants=self_binding.effective_grants,
            effect=boundary,
        )

        outputs_map: Mapping[str, Any] = await record.impl(context, node_inputs)

        declared = {port.name for port in instance.definition.outputs}
        missing = sorted(declared - set(outputs_map))
        if missing:
            raise ContractViolation(
                f"{instance.scope.render()}: implementation omitted declared outputs "
                f"{missing} — the contract is validated before any envelope is emitted"
            )
        envelopes: dict[str, Envelope[Any]] = {
            name: Envelope(
                run_id=run_id,
                path=path,
                port=name,
                created_at=utc_now(),
                payload=outputs_map[name],
            )
            for name in declared
        }
        journal.record_completion(
            Checkpoint(
                run_id=run_id,
                path=path,
                input_hash=input_hash,
                resolved_version=instance.version,
                outputs=envelopes,
            )
        )
        return {name: outputs_map[name] for name in declared}

    def _effect_boundary(
        self, manifest: ExecutionManifest, run_id: RunId, path: ExecutionPath
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
            if existing is not None and existing.status == "committed":
                journal.append_event(
                    run_id, "EffectDeduplicated", path=path, payload={"kind": kind}
                )
                return existing
            adapter = effects.get(kind)
            if adapter is None:
                raise ContractViolation(
                    f"no effect adapter for kind {kind!r}; assembled: {sorted(effects)}"
                )
            request = EffectRequest(
                path=path,
                kind=kind,
                subject=subject,
                idempotency_key=key,
                attestation_id=attestation_id,
            )
            if journal.effect_prepared(key):
                reconciled = await adapter.reconcile(request)
                if reconciled is not None:
                    journal.record_effect_receipt(run_id, request, reconciled)
                    journal.append_event(
                        run_id, "EffectReconciled", path=path, payload={"kind": kind}
                    )
                    return reconciled
                # absent externally: safe to execute (the recovery law)
            journal.record_effect_prepared(run_id, request)
            receipt = await adapter.execute(request)
            journal.record_effect_receipt(run_id, request, receipt)
            journal.append_event(
                run_id,
                "EffectCommitted",
                path=path,
                payload={"kind": kind, "request_hash": str(request_hash(request))},
            )
            return receipt

        return boundary


def _collect(values: dict[str, Any], sources: tuple[PortAddress, ...], port: Port) -> Any:
    resolved = []
    for source in sources:
        key = _address_key(source)
        if key not in values:
            raise ContractViolation(
                f"value for {key} is unavailable — a producer did not complete"
            )
        resolved.append(values[key])
    if port.cardinality == "many":
        return resolved
    return resolved[0]
