"""The system object — the injection root (I8) and the one control surface.

Every later skin (MCP server first, CLI, HTTP) wraps this object one-to-one and
adds no new concepts. L4 constructs L1 implementations and injects them into
the L2 runtime; the runtime never imports concrete substrate modules.

Two ``Constructicon`` instances over the same database files are two workers of
one system: the second can resume, reproduce, and project the first's runs, and
the fenced lease decides which of two concurrent claimants wins.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from constructicon.core.address import RunId
from constructicon.core.component import ComponentDef, PromotionRecord
from constructicon.core.effect import EffectAdapter
from constructicon.core.errors import ContractViolation
from constructicon.core.grants import EffectiveGrants, ModelSelection, Posture
from constructicon.core.graph import Graph
from constructicon.core.identity import Digest
from constructicon.core.journal import Journal
from constructicon.core.manifest import ExecutionManifest
from constructicon.core.registry import RegistryStore
from constructicon.core.run import RunState
from constructicon.runtime.context import NodeImpl
from constructicon.runtime.registry import (
    CapabilityDescriptor,
    ComponentRegistry,
    InMemoryRegistryStore,
)
from constructicon.runtime.validator import admit
from constructicon.runtime.walker import (
    DEFAULT_HEARTBEAT_INTERVAL_S,
    DEFAULT_LEASE_TTL_S,
    RunResult,
    Walker,
)
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
        owner_id: str | None = None,
        lease_ttl_s: float = DEFAULT_LEASE_TTL_S,
        heartbeat_interval_s: float = DEFAULT_HEARTBEAT_INTERVAL_S,
    ) -> None:
        self.journal = journal
        if store is None:
            # the SQLite journal implements RegistryStore over the same file;
            # sharing the file does not merge the concepts (I8)
            store = journal if isinstance(journal, RegistryStore) else InMemoryRegistryStore()
        self.registry = ComponentRegistry(store=store)
        self.owner_id = owner_id or f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self._catalog = dict(catalog or {})
        self._root_grants = root_grants
        self._walker = Walker(
            registry=self.registry,
            journal=journal,
            capabilities=capabilities or {},
            catalog=self._catalog,
            effects=effects or {},
            owner_id=self.owner_id,
            lease_ttl_s=lease_ttl_s,
            heartbeat_interval_s=heartbeat_interval_s,
        )

    # -- definitions ---------------------------------------------------------

    def register(self, definition: ComponentDef, impl: NodeImpl | None = None) -> Digest:
        return self.registry.register(definition, impl)

    def promote(
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

    def promote_initial(
        self, *, component: str, version: Digest, actor: str = "bootstrap"
    ) -> PromotionRecord | None:
        """Idempotent deterministic bootstrap policy: no stable pointer ->
        promote; already stable at this exact version -> None; stable
        elsewhere -> refuse. Registration alone never propagates (I12)."""
        return self.registry.promote_initial(
            component=component, version=version, journal=self.journal, actor=actor
        )

    def rollback(self, *, component: str, actor: str) -> PromotionRecord:
        """An ordinary promotion of the retained prior stable version."""
        return self.registry.rollback(
            component=component, journal=self.journal, actor=actor
        )

    # -- admission and runs ---------------------------------------------------

    def validate(self, graph: Graph, inputs: dict[str, Any]) -> ExecutionManifest:
        return admit(
            graph,
            snapshot=self.registry.snapshot(),
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
        return await self._walker.start(
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

    def cancel(self, run_id: RunId) -> None:
        """Durably request cooperative cancellation; the owning walker honors
        it at the next node boundary and never silently restarts the run."""
        self.journal.request_cancel(run_id)

    def run_state(self, run_id: RunId) -> RunState | None:
        return self.journal.run_state(run_id)

    def project_run(self, run_id: RunId, out_dir: Path) -> ProjectionResult:
        if not isinstance(self.journal, SqliteJournal):
            raise ContractViolation(
                "projections regenerate from the SQLite journal; this system "
                f"was assembled with {type(self.journal).__name__}"
            )
        return project_run(self.journal, run_id, out_dir)

    # -- introspection (I9) ---------------------------------------------------

    def describe(self) -> dict[str, Any]:
        snapshot = self.registry.snapshot()
        components: dict[str, Any] = {}
        for name in snapshot.names():
            stable = snapshot.stable.get(name)
            order = snapshot.order.get(name, ())
            components[name] = {
                "versions": list(order),
                "stable": stable,
                "candidates": [v for v in order if v != stable],
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
