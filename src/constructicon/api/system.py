"""The system object — injection root and one agent-shaped control surface.

Every later skin (MCP first, CLI, HTTP) wraps this object one-to-one and adds
no new concepts. M5 makes the existing machine discoverable and authorable:
SDK bundles and raw Graph JSON converge on the same strict parser, typed
admission boundary, validator, and sealed manifest.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError

from constructicon.api.introspection import (
    build_component_description,
    build_system_description,
)
from constructicon.core.address import RunId
from constructicon.core.admission import (
    AdmissionAccepted,
    AdmissionCode,
    AdmissionFault,
    AdmissionRejected,
    AdmissionResult,
)
from constructicon.core.component import ComponentDef, PromotionRecord
from constructicon.core.control import ResolutionLock, RunOrigin
from constructicon.core.effect import EffectAdapter
from constructicon.core.errors import AdmissionError, ContractViolation
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, canonical_json, digest, json_value
from constructicon.core.introspection import (
    AdmissionLimits,
    ComponentDescription,
    SystemDescription,
)
from constructicon.core.journal import Journal
from constructicon.core.manifest import ExecutionManifest
from constructicon.core.registry import RegistryStore
from constructicon.core.run import RunState
from constructicon.runtime.authoring import admit_authored_graph
from constructicon.runtime.context import NodeImpl
from constructicon.runtime.registry import (
    CapabilityDescriptor,
    ComponentRegistry,
    InMemoryRegistryStore,
)
from constructicon.runtime.walker import (
    DEFAULT_HEARTBEAT_INTERVAL_S,
    DEFAULT_LEASE_TTL_S,
    RunResult,
    Walker,
)
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.effects.git import MergeVerifiedEffect
from constructicon.substrate.gates.runner import CheckSpec, GateRunner
from constructicon.substrate.git.authority import GitAuthority, GitWorkspaceCapability
from constructicon.substrate.journal.projection import ProjectionResult, project_run
from constructicon.substrate.journal.sqlite import SqliteJournal

DEFAULT_ROOT_GRANTS = EffectiveGrants(
    posture=Posture.READ,
    model_selection=ModelSelection(kind="backend_default"),
    effort=None,
    allowed_tools=(),
    env_allowlist=(),
    network="none",
    timeout_s=600,
)
DEFAULT_ADMISSION_LIMITS = AdmissionLimits()


@dataclass(frozen=True)
class GitWorld:
    """One assembled git authority: splice these into ``Constructicon``."""

    authority: GitAuthority
    workspace: GitWorkspaceCapability
    gates: GateRunner
    capabilities: dict[str, object]
    catalog: dict[str, CapabilityDescriptor]
    effects: dict[str, EffectAdapter]


def git_world(
    *,
    journal: Journal,
    repo_path: Path | str,
    workspaces_root: Path | str,
    target_ref: str = "refs/heads/main",
    checks: tuple[CheckSpec, ...] | None = None,
) -> GitWorld:
    authority = GitAuthority(repo_path, workspaces_root)
    workspace = GitWorkspaceCapability(authority, target_ref=target_ref)
    gates = GateRunner(
        journal=journal,
        authority=authority,
        target_ref=target_ref,
        checks=checks,
    )
    capabilities: dict[str, object] = {
        "git-workspace": workspace,
        "git-gates": gates,
    }
    catalog = {
        "git-workspace": CapabilityDescriptor(
            capability_id="git-workspace",
            kind="workspace",
            revision="1",
            leased=True,
            requires_posture=Posture.WRITE,
        ),
        "git-gates": CapabilityDescriptor(
            capability_id="git-gates",
            kind="gates",
            revision=str(gates.check_set_hash)[:19],
            leased=True,
        ),
    }
    effects: dict[str, EffectAdapter] = {
        "merge_verified": MergeVerifiedEffect(
            journal=journal,
            authority=authority,
        )
    }
    return GitWorld(
        authority=authority,
        workspace=workspace,
        gates=gates,
        capabilities=capabilities,
        catalog=catalog,
        effects=effects,
    )


class Constructicon:
    def __init__(
        self,
        *,
        journal: Journal,
        store: RegistryStore | None = None,
        capabilities: Mapping[str, object] | None = None,
        catalog: Mapping[str, CapabilityDescriptor] | None = None,
        effects: Mapping[str, EffectAdapter] | None = None,
        root_grants: EffectiveGrants = DEFAULT_ROOT_GRANTS,
        admission_limits: AdmissionLimits = DEFAULT_ADMISSION_LIMITS,
        owner_id: str | None = None,
        lease_ttl_s: float = DEFAULT_LEASE_TTL_S,
        heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
    ) -> None:
        self.journal = journal
        if store is None:
            store = journal if isinstance(journal, RegistryStore) else InMemoryRegistryStore()
        self.registry = ComponentRegistry(store=store)
        self.owner_id = owner_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._capabilities = dict(capabilities or {})
        self._catalog = dict(catalog or {})
        self._root_grants = root_grants
        self._admission_limits = admission_limits
        self._walker = Walker(
            registry=self.registry,
            journal=journal,
            capabilities=self._capabilities,
            catalog=self._catalog,
            effects=effects or {},
            owner_id=self.owner_id,
            lease_ttl_s=lease_ttl_s,
            heartbeat_interval_s=heartbeat_interval_s,
        )

    # -- definitions ---------------------------------------------------------

    def register(
        self,
        definition: ComponentDef | DefinitionBundle,
        impl: NodeImpl | None = None,
    ) -> Digest:
        if isinstance(definition, DefinitionBundle):
            if impl is not None:
                raise TypeError(
                    "register(bundle) already carries its implementation; do not "
                    "supply a second impl"
                )
            impl = definition.implementation
            definition = definition.definition
        return self.registry.register(definition, impl)

    def _promote_version(
        self,
        *,
        component: str,
        version: Digest,
        attestation_id: str,
        actor: str,
        source_run: RunId | None = None,
    ) -> PromotionRecord:
        return self.registry.promote(
            component=component,
            version=version,
            attestation_id=attestation_id,
            actor=actor,
            journal=self.journal,
            source_run=source_run,
        )

    def promote(
        self,
        *,
        component: str,
        version: Digest,
        attestation_id: str,
        actor: str,
        source_run: RunId | None = None,
    ) -> PromotionRecord:
        """Compatibility facade; authenticated remote mutations use ControlPlane."""

        return self._promote_version(
            component=component,
            version=version,
            attestation_id=attestation_id,
            actor=actor,
            source_run=source_run,
        )

    def promote_initial(
        self,
        *,
        component: str,
        version: Digest,
        actor: str = "bootstrap",
    ) -> PromotionRecord | None:
        return self.registry.promote_initial(
            component=component,
            version=version,
            journal=self.journal,
            actor=actor,
        )

    def _rollback_version(
        self,
        *,
        component: str,
        actor: str,
        expected_stable: Digest | None = None,
    ) -> PromotionRecord:
        return self.registry.rollback(
            component=component,
            journal=self.journal,
            actor=actor,
            expected_stable=expected_stable,
        )

    def rollback(
        self,
        *,
        component: str,
        actor: str,
        expected_stable: Digest | None = None,
    ) -> PromotionRecord:
        """Compatibility facade; authenticated remote mutations use ControlPlane."""

        return self._rollback_version(
            component=component,
            actor=actor,
            expected_stable=expected_stable,
        )

    # -- admission and runs ---------------------------------------------------

    def validate(
        self,
        graph: Graph,
        inputs: dict[str, Any],
        *,
        resolution_lock: ResolutionLock | None = None,
    ) -> ExecutionManifest:
        return admit_authored_graph(
            graph,
            snapshot=self.registry.snapshot(),
            catalog=self._catalog,
            root_grants=self._root_grants,
            inputs=inputs,
            limits=self._admission_limits,
            resolution_lock=resolution_lock,
        )

    def admit_graph(
        self,
        proposal: Graph | Mapping[str, Any] | str,
        inputs: Mapping[str, Any],
    ) -> AdmissionResult:
        """Parse and admit architect-authored Graph JSON without auto-repair."""

        try:
            normalized_inputs = json_value(dict(inputs))
        except (TypeError, ValueError) as exc:
            return AdmissionRejected(
                faults=(
                    AdmissionFault(
                        code=AdmissionCode.GRAPH_INPUT_INVALID,
                        message=f"graph inputs are not canonical JSON: {exc}",
                        repair=(
                            "submit a JSON object whose keys match declared graph "
                            "inputs and whose values are JSON-compatible"
                        ),
                    ),
                )
            )
        if not isinstance(normalized_inputs, dict):
            return AdmissionRejected(
                faults=(
                    AdmissionFault(
                        code=AdmissionCode.GRAPH_INPUT_INVALID,
                        message="graph inputs must be a JSON object keyed by port name",
                        repair="submit an object whose keys match declared graph inputs",
                    ),
                )
            )

        graph: Graph | None = None
        proposal_digest: Digest | None = None
        try:
            if isinstance(proposal, Graph):
                graph = proposal
                proposal_digest = digest(
                    "graph-proposal",
                    1,
                    graph.model_dump(mode="json"),
                )
            elif isinstance(proposal, str):
                size = len(proposal.encode("utf-8"))
                if size > self._admission_limits.max_proposal_bytes:
                    return self._proposal_too_large(size)
                proposal_digest = digest("graph-proposal", 1, proposal)
                graph = Graph.model_validate_json(proposal)
            else:
                normalized_proposal = json_value(dict(proposal))
                rendered = canonical_json(normalized_proposal)
                size = len(rendered.encode("utf-8"))
                if size > self._admission_limits.max_proposal_bytes:
                    return self._proposal_too_large(size)
                proposal_digest = digest("graph-proposal", 1, normalized_proposal)
                graph = Graph.model_validate(normalized_proposal)
        except ValidationError as exc:
            return AdmissionRejected(
                proposal_digest=proposal_digest,
                graph=None,
                faults=self._validation_faults(exc),
            )
        except (TypeError, ValueError) as exc:
            return AdmissionRejected(
                proposal_digest=proposal_digest,
                graph=None,
                faults=(
                    AdmissionFault(
                        code=AdmissionCode.GRAPH_SCHEMA_INVALID_VALUE,
                        message=f"graph proposal is not canonical JSON: {exc}",
                        repair="submit a JSON object matching the published Graph schema",
                    ),
                )
            )

        assert graph is not None and proposal_digest is not None
        try:
            manifest = self.validate(graph, normalized_inputs)
        except AdmissionError as exc:
            return AdmissionRejected(
                proposal_digest=proposal_digest,
                graph=graph,
                faults=exc.faults,
            )
        return AdmissionAccepted(
            proposal_digest=proposal_digest,
            graph=graph,
            manifest=manifest,
        )

    def _prepare_run(
        self,
        manifest: ExecutionManifest,
        *,
        run_id: RunId,
        inputs: dict[str, Any],
        origin: RunOrigin | None = None,
    ) -> None:
        self._walker.prepare(manifest, run_id=run_id, inputs=inputs, origin=origin)

    def prepare(
        self,
        manifest: ExecutionManifest,
        *,
        run_id: RunId,
        inputs: dict[str, Any],
        origin: RunOrigin | None = None,
    ) -> None:
        """Compatibility facade for local assembly and historical tests."""

        self._prepare_run(manifest, run_id=run_id, inputs=inputs, origin=origin)

    async def _run_prepared(
        self,
        run_id: RunId,
        *,
        cancellation: Literal["cancel", "abandon"] = "cancel",
    ) -> RunResult:
        return await self._walker.run_prepared(run_id, cancellation=cancellation)

    async def run_prepared(
        self,
        run_id: RunId,
        *,
        cancellation: Literal["cancel", "abandon"] = "cancel",
    ) -> RunResult:
        return await self._run_prepared(run_id, cancellation=cancellation)

    async def _start_direct(
        self,
        graph: Graph,
        inputs: dict[str, Any],
        *,
        run_id: RunId | None = None,
    ) -> RunResult:
        manifest = self.validate(graph, inputs)
        return await self._walker.start(
            manifest,
            run_id=run_id or RunId(f"run-{uuid.uuid4().hex}"),
            inputs=inputs,
        )

    async def start(
        self,
        graph: Graph,
        inputs: dict[str, Any],
        *,
        run_id: RunId | None = None,
    ) -> RunResult:
        return await self._start_direct(graph, inputs, run_id=run_id)

    async def _resume_direct(self, run_id: RunId) -> RunResult:
        return await self._walker.resume(run_id)

    async def resume(self, run_id: RunId) -> RunResult:
        return await self._resume_direct(run_id)

    async def _reproduce_direct(
        self,
        source_run_id: RunId,
        *,
        new_run_id: RunId | None = None,
    ) -> RunResult:
        return await self._walker.reproduce(
            source_run_id,
            new_run_id=new_run_id or RunId(f"run-{uuid.uuid4().hex}"),
        )

    async def reproduce(
        self,
        source_run_id: RunId,
        *,
        new_run_id: RunId | None = None,
    ) -> RunResult:
        return await self._reproduce_direct(source_run_id, new_run_id=new_run_id)

    def manifest_for_run(self, run_id: RunId) -> ExecutionManifest:
        return self._walker._load_manifest(run_id)

    def inputs_for_run(self, run_id: RunId) -> dict[str, Any]:
        inputs = self.journal.run_inputs(run_id)
        if inputs is None:
            raise ContractViolation(f"run {run_id!r} has no recorded inputs")
        return inputs

    def materialize_run(self, run_id: RunId) -> dict[str, Any]:
        manifest = self.manifest_for_run(run_id)
        return self._walker._materialize(manifest, run_id, self.inputs_for_run(run_id))

    def _request_cancel(self, run_id: RunId) -> None:
        self.journal.request_cancel(run_id)

    def cancel(self, run_id: RunId) -> None:
        """Compatibility facade; authenticated remote mutations use ControlPlane."""

        self._request_cancel(run_id)

    def run_state(self, run_id: RunId) -> RunState | None:
        return self.journal.run_state(run_id)

    def project_run(self, run_id: RunId, out_dir: Path) -> ProjectionResult:
        if not isinstance(self.journal, SqliteJournal):
            raise ContractViolation(
                "projections regenerate from the SQLite journal; this system "
                f"was assembled with {type(self.journal).__name__}"
            )
        return project_run(self.journal, run_id, out_dir)

    # -- introspection --------------------------------------------------------

    def describe(
        self,
        *,
        component_names: Sequence[str] | None = None,
        limit: int = 100,
    ) -> SystemDescription:
        snapshot = self.registry.snapshot()
        return build_system_description(
            registry=self.registry,
            snapshot=snapshot,
            catalog=self._catalog,
            available_capabilities=frozenset(self._capabilities),
            root_grants=self._root_grants,
            limits=self._admission_limits,
            component_names=component_names,
            limit=limit,
        )

    def describe_component(
        self,
        name: str,
        *,
        version: Digest | None = None,
    ) -> ComponentDescription:
        snapshot = self.registry.snapshot()
        return build_component_description(
            registry=self.registry,
            snapshot=snapshot,
            name=name,
            version=version,
        )

    def rdeps(self, name: str) -> list[str]:
        return self.registry.rdeps(name)

    def _proposal_too_large(self, observed: int) -> AdmissionRejected:
        return AdmissionRejected(
            faults=(
                AdmissionFault(
                    code=AdmissionCode.GRAPH_PROPOSAL_LIMIT_EXCEEDED,
                    message=(
                        f"graph proposal is {observed} bytes; limit is "
                        f"{self._admission_limits.max_proposal_bytes}"
                    ),
                    repair="submit a smaller graph or reference registered composites",
                    details={
                        "observed": observed,
                        "limit": self._admission_limits.max_proposal_bytes,
                    },
                ),
            )
        )

    def _validation_faults(self, exc: ValidationError) -> tuple[AdmissionFault, ...]:
        faults: list[AdmissionFault] = []
        for error in exc.errors(include_input=False, include_url=False):
            error_type = str(error.get("type", "value_error"))
            code = (
                AdmissionCode.GRAPH_SCHEMA_INVALID_JSON
                if error_type == "json_invalid"
                else AdmissionCode.GRAPH_SCHEMA_INVALID_VALUE
            )
            path = tuple(
                item for item in error.get("loc", ()) if isinstance(item, (str, int))
            )
            faults.append(
                AdmissionFault(
                    code=code,
                    message=str(error.get("msg", "Graph schema validation failed")),
                    path=path,
                    repair=(
                        "change the value at this path to match the published Graph schema"
                    ),
                    details={"error_type": error_type},
                )
            )
        ordered = sorted(
            faults,
            key=lambda fault: (
                tuple(str(item) for item in fault.path),
                fault.code.value,
                fault.message,
            ),
        )
        return tuple(ordered[: self._admission_limits.max_faults])
