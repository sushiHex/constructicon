"""The system object — the injection root (I8) and the one control surface.

Every later skin (MCP server first, CLI, HTTP) wraps this object one-to-one and
adds no new concepts. L4 constructs L1 implementations and injects them into
the L2 runtime; the runtime never imports concrete substrate modules.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from constructicon.core.address import RunId
from constructicon.core.component import ComponentDef, PromotionRecord
from constructicon.core.effect import (
    Attestation,
    CheckResult,
    ComponentProofSubject,
    EffectAdapter,
)
from constructicon.core.envelope import utc_now
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest, digest
from constructicon.core.journal import Journal
from constructicon.core.manifest import ExecutionManifest
from constructicon.runtime.context import NodeImpl
from constructicon.runtime.registry import ComponentRegistry
from constructicon.runtime.validator import CapabilityDescriptor, admit
from constructicon.runtime.walker import RunResult, Walker

DEFAULT_ROOT_GRANTS = EffectiveGrants(
    posture=Posture.READ,
    model_selection=ModelSelection(kind="backend_default"),
    effort=None,
    allowed_tools=(),
    env_allowlist=(),
    network="none",
    timeout_s=600,
)


class Constructicon:
    def __init__(
        self,
        *,
        journal: Journal,
        capabilities: Mapping[str, object] | None = None,
        catalog: Mapping[str, CapabilityDescriptor] | None = None,
        effects: Mapping[str, EffectAdapter] | None = None,
        root_grants: EffectiveGrants = DEFAULT_ROOT_GRANTS,
    ) -> None:
        self.journal = journal
        self.registry = ComponentRegistry()
        self._catalog = dict(catalog or {})
        self._root_grants = root_grants
        self._walker = Walker(
            registry=self.registry,
            journal=journal,
            capabilities=capabilities or {},
            effects=effects or {},
        )

    # -- definitions ---------------------------------------------------------

    def register(self, definition: ComponentDef, impl: NodeImpl | None = None) -> Digest:
        return self.registry.register(definition, impl)

    def promote(
        self, *, component: str, version: Digest, attestation_id: str, actor: str
    ) -> PromotionRecord:
        return self.registry.promote(
            component=component,
            version=version,
            attestation_id=attestation_id,
            actor=actor,
            journal=self.journal,
        )

    def promote_initial(
        self, *, component: str, version: Digest, actor: str = "bootstrap"
    ) -> PromotionRecord:
        """Deterministic bootstrap promotion policy for a freshly registered
        version: verifies the exact version exists, mints the attestation into
        the journal, then moves the pointer through the one promotion path.
        Registration alone never propagates (I12)."""
        record = self.registry.get_exact(component, version)
        checks = (
            CheckResult(
                name="contract-registered",
                ok=True,
                detail=f"{component}@{record.content_hash} carries a validated contract",
                elapsed_s=0.0,
            ),
        )
        attestation = Attestation(
            attestation_id=f"att-{uuid.uuid4().hex}",
            action="promote",
            subject=ComponentProofSubject(
                component=component, version=version, baseline_version=None
            ),
            checks=checks,
            check_set_hash=digest("check-set", 1, {"policy": "bootstrap-initial", "v": 1}),
            evidence=(),
            manifest_hash=digest("manifest", 1, {"bootstrap": True}),
            created_by_run=RunId("bootstrap"),
            workspace_id=None,
            created_at=utc_now(),
        )
        self.journal.mint_attestation(attestation)
        return self.promote(
            component=component,
            version=version,
            attestation_id=attestation.attestation_id,
            actor=actor,
        )

    # -- admission and runs ---------------------------------------------------

    def validate(self, graph: Graph, inputs: dict[str, Any]) -> ExecutionManifest:
        return admit(
            graph,
            registry=self.registry,
            catalog=self._catalog,
            root_grants=self._root_grants,
            inputs=inputs,
        )

    async def start(
        self,
        graph: Graph,
        inputs: dict[str, Any],
        *,
        run_id: RunId | None = None,
    ) -> RunResult:
        manifest = self.validate(graph, inputs)
        return await self._walker.run(
            manifest,
            run_id=run_id or RunId(f"run-{uuid.uuid4().hex}"),
            inputs=inputs,
        )

    async def resume(self, run_id: RunId) -> RunResult:
        return await self._walker.resume(run_id)

    async def reproduce(
        self, source_run_id: RunId, *, new_run_id: RunId | None = None
    ) -> RunResult:
        return await self._walker.reproduce(
            source_run_id, new_run_id=new_run_id or RunId(f"run-{uuid.uuid4().hex}")
        )

    # -- introspection (I9) ---------------------------------------------------

    def describe(self) -> dict[str, Any]:
        components: dict[str, Any] = {}
        for name in sorted(self.registry._versions):  # M1; a public catalog API lands at M5
            stable = self.registry.stable_version(name)
            components[name] = {
                "versions": [str(v) for v in self.registry.versions(name)],
                "stable": str(stable) if stable else None,
                "candidates": [str(v) for v in self.registry.candidates(name)],
            }
        return {
            "components": components,
            "capabilities": {
                capability_id: {"kind": descriptor.kind, "revision": descriptor.revision}
                for capability_id, descriptor in sorted(self._catalog.items())
            },
        }

    def rdeps(self, name: str) -> list[str]:
        return self.registry.rdeps(name)
