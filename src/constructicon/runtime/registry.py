"""ComponentRegistry — immutable, versioned definitions (I10, I12).

Registration appends an exact-hash version and never moves any pointer.
Bare references resolve to the ``stable`` channel; promotion is a separate,
attestation-verified pointer move recorded append-only. A CANDIDATE is a query
(any eligible exact version not yet promoted), never a channel.

M1 keeps the store in memory; M2 moves it to the authoritative SQLite store.
Live capability objects never live here — they are injected at assembly (I8).
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from dataclasses import dataclass, field

from constructicon.core.address import RunId
from constructicon.core.component import ComponentDef, PromotionRecord
from constructicon.core.effect import Attestation, ComponentProofSubject
from constructicon.core.envelope import utc_now
from constructicon.core.errors import AdmissionError, ConstructiconError
from constructicon.core.graph import Graph, Loop, Ref
from constructicon.core.identity import Digest, digest
from constructicon.core.journal import Journal
from constructicon.runtime.context import NodeImpl


class RegistryError(ConstructiconError):
    pass


@dataclass(frozen=True)
class VersionRecord:
    definition: ComponentDef
    content_hash: Digest
    impl: NodeImpl | None  # atomic components only


def contract_hash_for(defn_inputs: object, defn_outputs: object) -> Digest:
    return digest("component-contract", 1, {"inputs": defn_inputs, "outputs": defn_outputs})


def source_digest_for(impl: NodeImpl) -> Digest | None:
    try:
        return digest("python-source", 1, inspect.getsource(impl))
    except (OSError, TypeError):
        return None


@dataclass
class ComponentRegistry:
    _versions: dict[str, dict[str, VersionRecord]] = field(default_factory=dict)
    _order: dict[str, list[str]] = field(default_factory=dict)
    _promotions: list[PromotionRecord] = field(default_factory=list)

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
        content = definition.content_hash()
        versions = self._versions.setdefault(definition.name, {})
        key = str(content)
        if key not in versions:
            versions[key] = VersionRecord(definition=definition, content_hash=content, impl=impl)
            self._order.setdefault(definition.name, []).append(key)
        return content

    def stable_version(self, name: str) -> Digest | None:
        for record in reversed(self._promotions):
            if record.component == name and record.channel == "stable":
                return record.to_version
        return None

    def resolve(self, ref: Ref) -> VersionRecord:
        versions = self._versions.get(ref.component)
        if not versions:
            raise RegistryError(f"unknown component {ref.component!r}")
        if ref.version is None or ref.version == "stable":
            stable = self.stable_version(ref.component)
            if stable is None:
                registered = ", ".join(str(v) for v in versions)
                raise RegistryError(
                    f"component {ref.component!r} has no stable version; "
                    f"registered versions: [{registered}] — promote one "
                    "(registration never propagates; promotion does)"
                )
            return versions[str(stable)]
        record = versions.get(ref.version)
        if record is None:
            raise RegistryError(
                f"component {ref.component!r} has no version {ref.version!r}"
            )
        return record

    def get_exact(self, name: str, version: Digest) -> VersionRecord:
        versions = self._versions.get(name)
        if not versions or str(version) not in versions:
            raise RegistryError(f"component {name!r} has no version {version}")
        return versions[str(version)]

    def candidates(self, name: str) -> list[Digest]:
        """Eligible exact versions not currently promoted — a query, not a channel."""
        stable = self.stable_version(name)
        ordered = self._order.get(name, [])
        return [
            Digest(v) for v in ordered if stable is None or v != str(stable)
        ]

    def versions(self, name: str) -> list[Digest]:
        return [Digest(v) for v in self._order.get(name, [])]

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
        """Move the stable pointer — only with a journal-minted attestation (I2)."""
        record = self.get_exact(component, version)
        attestation = journal.load_attestation(attestation_id)
        if attestation is None:
            raise AdmissionError(
                [
                    f"promotion of {component!r} refused: attestation "
                    f"{attestation_id!r} is not journal-minted — a caller-authored "
                    "claim cannot authorize a promotion"
                ]
            )
        faults = _verify_promotion_attestation(attestation, component, record.content_hash)
        if faults:
            raise AdmissionError(faults)
        promotion = PromotionRecord(
            component=component,
            channel="stable",
            from_version=self.stable_version(component),
            to_version=version,
            attestation_id=attestation_id,
            actor=actor,
            source_run=source_run,
            created_at=utc_now(),
        )
        self._promotions.append(promotion)
        return promotion

    def rollback(self, *, component: str, actor: str, journal: Journal) -> PromotionRecord:
        """Move the stable pointer back to its previous version; nothing is deleted."""
        current = self.stable_version(component)
        if current is None:
            raise RegistryError(f"component {component!r} has no stable version to roll back")
        previous: Digest | None = None
        for record in reversed(self._promotions):
            if record.component == component and record.to_version == current:
                previous = record.from_version
                break
        if previous is None:
            raise RegistryError(
                f"component {component!r} has no earlier stable version to roll back to"
            )
        promotion = PromotionRecord(
            component=component,
            channel="stable",
            from_version=current,
            to_version=previous,
            attestation_id="rollback",
            actor=actor,
            source_run=None,
            created_at=utc_now(),
        )
        self._promotions.append(promotion)
        journal_note = journal  # rollback events land in the journal at M2
        _ = journal_note
        return promotion

    def rdeps(self, name: str) -> list[str]:
        """Reverse-dependency closure: what does changing this touch."""
        direct: dict[str, set[str]] = {}
        for owner, versions in self._versions.items():
            for record in versions.values():
                body = record.definition.body
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


def _refs_in(graph: Graph) -> Iterable[str]:
    for node in graph.nodes:
        body = node.body
        if isinstance(body, Ref):
            yield body.component
        elif isinstance(body, Graph):
            yield from _refs_in(body)
        elif isinstance(body, Loop):
            if isinstance(body.body, Ref):
                yield body.body.component
            else:
                yield from _refs_in(body.body)


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
