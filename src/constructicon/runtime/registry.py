"""ComponentRegistry (M2): logic over an injected durable store.

Registration validates implementation identity and appends an immutable
version; it never moves a pointer. Promotion is a compare-and-swap pointer
move authorized by a journal-minted attestation; rollback is an ordinary
promotion of a retained older version. A CANDIDATE is a query, never a
channel.

Admission consumes an immutable ``RegistrySnapshot``; execution consumes a
``BoundExecution`` produced by ``activate(manifest)`` — the one path used
identically by start, resume, and reproduce, which refuses unavailable or
drifted implementations everywhere (a crash followed by a code update must
never execute an old run's suffix on new code).
"""

from __future__ import annotations

import importlib
import inspect
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from constructicon.core.address import RunId
from constructicon.core.component import ComponentDef, PromotionRecord
from constructicon.core.effect import (
    Attestation,
    CheckResult,
    ComponentProofSubject,
)
from constructicon.core.envelope import utc_now
from constructicon.core.errors import AdmissionError, ConstructiconError
from constructicon.core.executor import ExecutorProfile
from constructicon.core.graph import Graph, Loop, Ref
from constructicon.core.identity import Digest, digest
from constructicon.core.journal import Journal
from constructicon.core.manifest import SELF_BINDING, ExecutionManifest
from constructicon.core.registry import (
    Loadability,
    RegistrySnapshot,
    RegistryStore,
    StoredVersion,
)
from constructicon.runtime.context import NodeImpl


class RegistryError(ConstructiconError):
    pass


@dataclass(frozen=True)
class CapabilityDescriptor:
    """What the catalog exposes about an injectable capability — never the object."""

    capability_id: str
    kind: str
    revision: str
    executor_profile: ExecutorProfile | None = None


@dataclass(frozen=True)
class BoundVersion:
    stored: StoredVersion
    impl: NodeImpl | None
    loadability: Loadability


@dataclass(frozen=True)
class BoundExecution:
    """One manifest, activated: every atomic bound, every digest verified."""

    manifest: ExecutionManifest
    bindings: dict[tuple[str, str], BoundVersion]  # (name, hash) -> bound

    def bound(self, name: str, version: Digest) -> BoundVersion:
        return self.bindings[(name, str(version))]


class InMemoryRegistryStore:
    """The I6 test double — same contract, no durability."""

    def __init__(self) -> None:
        self._versions: dict[str, dict[str, StoredVersion]] = {}
        self._order: dict[str, list[str]] = {}
        self._promotions: list[PromotionRecord] = []

    def snapshot(self) -> RegistrySnapshot:
        stable: dict[str, str] = {}
        history: dict[str, list[tuple[str | None, str]]] = {}
        for record in self._promotions:
            if record.channel == "stable":
                stable[record.component] = str(record.to_version)
                history.setdefault(record.component, []).append(
                    (
                        str(record.from_version) if record.from_version else None,
                        str(record.to_version),
                    )
                )
        return RegistrySnapshot(
            versions={name: dict(entries) for name, entries in self._versions.items()},
            order={name: tuple(hashes) for name, hashes in self._order.items()},
            stable=stable,
            history={name: tuple(pairs) for name, pairs in history.items()},
        )

    def store_version(self, version: StoredVersion) -> None:
        from constructicon.core.errors import JournalDamaged

        name = version.definition.name
        key = str(version.content_hash)
        existing = self._versions.get(name, {}).get(key)
        if existing is not None:
            if existing.definition == version.definition:
                return
            raise JournalDamaged(
                f"component {name!r}@{key} already stored with a different definition"
            )
        self._versions.setdefault(name, {})[key] = version
        self._order.setdefault(name, []).append(key)

    def store_promotion(self, record: PromotionRecord) -> PromotionRecord:
        for prior in self._promotions:
            if prior.attestation_id == record.attestation_id:
                return prior  # one attestation authorizes one move
        current = None
        for prior in self._promotions:
            if prior.component == record.component and prior.channel == "stable":
                current = str(prior.to_version)
        expected = str(record.from_version) if record.from_version else None
        if current != expected:
            raise AdmissionError(
                [
                    f"promotion of {record.component!r} refused: stable moved — "
                    f"expected {expected!r}, found {current!r} (compare-and-swap)"
                ]
            )
        self._promotions.append(record)
        return record


def source_digest_for(impl: NodeImpl) -> Digest | None:
    try:
        return digest("python-source", 1, inspect.getsource(impl))
    except (OSError, TypeError):
        return None


@dataclass
class ComponentRegistry:
    store: RegistryStore
    _impls: dict[tuple[str, str], NodeImpl] = field(default_factory=dict)

    # -- registration (identity-validated, never propagating) ---------------

    def register(self, definition: ComponentDef, impl: NodeImpl | None = None) -> Digest:
        is_atomic = not isinstance(definition.body, Graph)
        if is_atomic and impl is None:
            raise RegistryError(
                f"atomic component {definition.name!r} requires an implementation"
            )
        if not is_atomic and impl is not None:
            raise RegistryError(
                f"composite component {definition.name!r} must not carry an implementation"
            )
        if is_atomic:
            self._validate_atomic_identity(definition, impl)
        content = definition.content_hash()
        self.store.store_version(
            StoredVersion(
                definition=definition, content_hash=content, registered_at=utc_now()
            )
        )
        if impl is not None:
            self._impls[(definition.name, str(content))] = impl
        return content

    def _validate_atomic_identity(self, definition: ComponentDef, impl: NodeImpl | None) -> None:
        body = definition.body
        assert not isinstance(body, Graph) and impl is not None
        faults: list[str] = []
        if "<locals>" in body.qualname:
            faults.append(
                f"{definition.name!r}: implementation {body.qualname!r} is a local "
                "closure — persistable atomic versions must be importable"
            )
        expected_contract = digest(
            "component-contract",
            1,
            {
                "inputs": [p.model_dump(mode="json") for p in definition.inputs],
                "outputs": [p.model_dump(mode="json") for p in definition.outputs],
            },
        )
        if body.contract_hash != expected_contract:
            faults.append(
                f"{definition.name!r}: PythonRef.contract_hash does not match the "
                "declared ports — recompute it from inputs/outputs"
            )
        observed = source_digest_for(impl)
        if observed is None:
            faults.append(
                f"{definition.name!r}: implementation source is unavailable — a "
                "persistable atomic version requires a concrete source digest"
            )
        elif body.source_digest is None:
            faults.append(
                f"{definition.name!r}: PythonRef.source_digest is required; "
                f"observed {observed}"
            )
        elif body.source_digest != observed:
            faults.append(
                f"{definition.name!r}: implementation drift at registration — "
                f"declared {body.source_digest}, observed {observed}"
            )
        if faults:
            raise AdmissionError(faults)

    # -- snapshots and binding ----------------------------------------------

    def snapshot(self) -> RegistrySnapshot:
        return self.store.snapshot()

    def bind(self, stored: StoredVersion) -> BoundVersion:
        body = stored.definition.body
        if isinstance(body, Graph):
            return BoundVersion(
                stored=stored, impl=None, loadability=Loadability(status="composite")
            )
        key = (stored.definition.name, str(stored.content_hash))
        impl = self._impls.get(key)
        if impl is None:
            impl, loadability = self._load(body.module, body.qualname)
            if impl is None:
                assert loadability is not None
                return BoundVersion(stored=stored, impl=None, loadability=loadability)
        observed = source_digest_for(impl)
        if observed is None:
            return BoundVersion(
                stored=stored,
                impl=None,
                loadability=Loadability(
                    status="source_unavailable",
                    expected_digest=body.source_digest,
                    detail="cannot observe implementation source on this host",
                ),
            )
        if body.source_digest is not None and observed != body.source_digest:
            return BoundVersion(
                stored=stored,
                impl=None,
                loadability=Loadability(
                    status="implementation_drift",
                    expected_digest=body.source_digest,
                    observed_digest=observed,
                    detail="installed code differs from the recorded digest",
                ),
            )
        return BoundVersion(
            stored=stored,
            impl=impl,
            loadability=Loadability(
                status="loadable",
                expected_digest=body.source_digest,
                observed_digest=observed,
            ),
        )

    @staticmethod
    def _load(module: str, qualname: str) -> tuple[NodeImpl | None, Loadability | None]:
        try:
            loaded = importlib.import_module(module)
        except ImportError as exc:
            return None, Loadability(status="missing_module", detail=str(exc))
        target: object = loaded
        for part in qualname.split("."):
            target = getattr(target, part, None)
            if target is None:
                return None, Loadability(
                    status="missing_qualname", detail=f"{module}:{qualname}"
                )
        if not callable(target):
            return None, Loadability(
                status="not_callable", detail=f"{module}:{qualname}"
            )
        return target, None

    def activate(
        self,
        manifest: ExecutionManifest,
        *,
        catalog: Mapping[str, CapabilityDescriptor],
    ) -> BoundExecution:
        """The one activation path for start, resume, and reproduce (I4):
        refuse — never silently substitute — when the world cannot be
        reproduced exactly."""
        snapshot = self.store.snapshot()
        faults: list[str] = []
        bindings: dict[tuple[str, str], BoundVersion] = {}
        for resolution in manifest.resolved_components:
            stored = snapshot.get(resolution.component, resolution.resolved_version)
            if stored is None:
                faults.append(
                    f"{resolution.scope.render()}: component "
                    f"{resolution.component!r}@{resolution.resolved_version} is not "
                    "in the registry — the manifest's world is unavailable"
                )
                continue
            bound = self.bind(stored)
            key = (resolution.component, str(resolution.resolved_version))
            bindings[key] = bound
            if bound.loadability.status == "composite":
                continue
            if bound.loadability.status != "loadable":
                load = bound.loadability
                faults.append(
                    f"{resolution.scope.render()}: {resolution.component!r} is not "
                    f"executable here ({load.status}"
                    + (
                        f": expected {load.expected_digest}, observed {load.observed_digest}"
                        if load.status == "implementation_drift"
                        else f": {load.detail}" if load.detail else ""
                    )
                    + ") — activation refuses rather than substituting"
                )
                continue
            if (
                resolution.implementation_digest is not None
                and bound.loadability.observed_digest != resolution.implementation_digest
            ):
                faults.append(
                    f"{resolution.scope.render()}: installed implementation digest "
                    f"{bound.loadability.observed_digest} differs from the manifest's "
                    f"{resolution.implementation_digest} — refuse, never substitute"
                )
        for binding in manifest.capability_bindings:
            if binding.binding == SELF_BINDING:
                continue
            descriptor = catalog.get(binding.capability_id)
            if descriptor is None:
                faults.append(
                    f"{binding.scope.render()}: capability {binding.capability_id!r} "
                    "is not assembled in this process"
                )
            elif descriptor.revision != binding.revision:
                faults.append(
                    f"{binding.scope.render()}: capability {binding.capability_id!r} "
                    f"revision {descriptor.revision!r} differs from the admitted "
                    f"{binding.revision!r}"
                )
        if faults:
            raise AdmissionError(faults)
        return BoundExecution(manifest=manifest, bindings=bindings)

    # -- promotion (CAS, attestation-verified) ------------------------------

    def promote(
        self,
        *,
        component: str,
        version: Digest,
        attestation_id: str,
        actor: str,
        journal: Journal,
        source_run: RunId | None = None,
    ) -> PromotionRecord:
        snapshot = self.store.snapshot()
        stored = snapshot.get(component, version)
        if stored is None:
            raise RegistryError(f"component {component!r} has no version {version}")
        attestation = journal.load_attestation(attestation_id)
        if attestation is None:
            raise AdmissionError(
                [
                    f"promotion of {component!r} refused: attestation "
                    f"{attestation_id!r} is not journal-minted — a caller-authored "
                    "claim cannot authorize a promotion"
                ]
            )
        faults = _verify_promotion_attestation(attestation, component, version)
        if faults:
            raise AdmissionError(faults)
        record = PromotionRecord(
            component=component,
            channel="stable",
            from_version=snapshot.stable_version(component),
            to_version=version,
            attestation_id=attestation_id,
            actor=actor,
            source_run=source_run,
            created_at=utc_now(),
        )
        return self.store.store_promotion(record)

    def promote_initial(
        self,
        *,
        component: str,
        version: Digest,
        journal: Journal,
        actor: str = "bootstrap",
    ) -> PromotionRecord | None:
        """Deterministic bootstrap policy, idempotent for startup re-runs:
        no pointer -> promote; already stable at this exact version -> None;
        stable elsewhere -> refuse (never silently replace a pointer)."""
        snapshot = self.store.snapshot()
        stable = snapshot.stable_version(component)
        if stable == version:
            return None
        if stable is not None:
            raise AdmissionError(
                [
                    f"promote_initial refused: {component!r} is already stable at "
                    f"{stable}; promoting {version} requires an evaluated promotion, "
                    "not the bootstrap policy"
                ]
            )
        attestation = self._mint_policy_attestation(
            journal,
            component=component,
            version=version,
            baseline=None,
            policy="bootstrap-initial",
            detail="freshly registered version with a validated contract",
        )
        return self.promote(
            component=component,
            version=version,
            attestation_id=attestation.attestation_id,
            actor=actor,
            journal=journal,
        )

    def rollback(
        self, *, component: str, journal: Journal, actor: str
    ) -> PromotionRecord:
        """Rollback is an ordinary promotion of a retained older version —
        minted by a deterministic policy, moved through the same CAS path."""
        snapshot = self.store.snapshot()
        current = snapshot.stable_version(component)
        if current is None:
            raise RegistryError(f"component {component!r} has no stable version to roll back")
        previous: str | None = None
        for from_version, to_version in reversed(snapshot.history.get(component, ())):
            if to_version == str(current):
                previous = from_version
                break
        if previous is None:
            raise RegistryError(
                f"component {component!r} has no earlier stable version to roll back to"
            )
        attestation = self._mint_policy_attestation(
            journal,
            component=component,
            version=Digest(previous),
            baseline=current,
            policy="rollback",
            detail=f"pointer move back from {current} to retained {previous}",
        )
        return self.promote(
            component=component,
            version=Digest(previous),
            attestation_id=attestation.attestation_id,
            actor=actor,
            journal=journal,
        )

    def _mint_policy_attestation(
        self,
        journal: Journal,
        *,
        component: str,
        version: Digest,
        baseline: Digest | None,
        policy: str,
        detail: str,
    ) -> Attestation:
        attestation = Attestation(
            attestation_id=f"att-{uuid.uuid4().hex}",
            action="promote",
            subject=ComponentProofSubject(
                component=component, version=version, baseline_version=baseline
            ),
            checks=(
                CheckResult(name=policy, ok=True, detail=detail, elapsed_s=0.0),
            ),
            check_set_hash=digest("check-set", 1, {"policy": policy, "v": 1}),
            evidence=(),
            manifest_hash=digest("manifest", 1, {"policy": policy}),
            created_by_run=None,  # run-less deterministic policy — never fabricated
            workspace_id=None,
            created_at=utc_now(),
        )
        journal.mint_attestation(attestation)
        return attestation

    # -- queries -------------------------------------------------------------

    def stable_version(self, name: str) -> Digest | None:
        return self.store.snapshot().stable_version(name)

    def versions(self, name: str) -> list[Digest]:
        return [Digest(v) for v in self.store.snapshot().order.get(name, ())]

    def candidates(self, name: str) -> list[Digest]:
        snapshot = self.store.snapshot()
        stable = snapshot.stable.get(name)
        return [
            Digest(v)
            for v in snapshot.order.get(name, ())
            if stable is None or v != stable
        ]

    def rdeps(self, name: str) -> list[str]:
        snapshot = self.store.snapshot()
        direct: dict[str, set[str]] = {}
        for owner, entries in snapshot.versions.items():
            for stored in entries.values():
                body = stored.definition.body
                if isinstance(body, Graph):
                    for dep in _refs_in(body):
                        direct.setdefault(dep, set()).add(owner)
        seen: set[str] = set()
        frontier = [name]
        while frontier:
            current = frontier.pop()
            for dependent in direct.get(current, ()):
                if dependent not in seen:
                    seen.add(dependent)
                    frontier.append(dependent)
        return sorted(seen)


def _refs_in(graph: Graph) -> list[str]:
    found: list[str] = []
    for node in graph.nodes:
        body = node.body
        if isinstance(body, Ref):
            found.append(body.component)
        elif isinstance(body, Graph):
            found.extend(_refs_in(body))
        elif isinstance(body, Loop):
            if isinstance(body.body, Ref):
                found.append(body.body.component)
            else:
                found.extend(_refs_in(body.body))
    return found


def _verify_promotion_attestation(
    attestation: Attestation, component: str, version: Digest
) -> list[str]:
    faults: list[str] = []
    if attestation.action != "promote":
        faults.append(
            f"attestation {attestation.attestation_id!r} authorizes "
            f"{attestation.action!r}, not a promotion"
        )
    subject = attestation.subject
    if not isinstance(subject, ComponentProofSubject):
        faults.append("promotion attestation must carry a component subject")
        return faults
    if subject.component != component:
        faults.append(
            f"attestation subject names {subject.component!r}, promotion targets {component!r}"
        )
    if subject.version != version:
        faults.append(
            f"attestation binds version {subject.version}, promotion targets {version} — "
            "identity mismatch is refused, never repaired silently"
        )
    if not attestation.ok:
        failing = [check.name for check in attestation.checks if not check.ok] or ["<none>"]
        faults.append(f"attestation checks failing: {failing}")
    return faults
