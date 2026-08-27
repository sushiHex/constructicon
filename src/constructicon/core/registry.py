"""Registry contracts (M2): durable definitions, immutable snapshots,
host-local implementation binding.

Three concerns, deliberately separated:

- **RegistryStore** — durable component versions and promotion records.
- **RegistrySnapshot** — one immutable, detached view used by one admission;
  ``admit()`` never returns to the mutable store during compilation, so a run
  always resolves one coherent world.
- **Implementation binding** — a process-local callable or a typed
  loadability failure. Host-local, never persisted as registry truth: old
  retained versions remain valid definitions even where this host cannot
  execute them.
"""

from __future__ import annotations

from typing import Literal, Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict

from constructicon.core.component import ComponentDef, PromotionRecord
from constructicon.core.identity import Digest


class StoredVersion(BaseModel):
    model_config = ConfigDict(frozen=True)

    definition: ComponentDef
    content_hash: Digest
    registered_at: AwareDatetime


class RegistrySnapshot(BaseModel):
    """Detached and immutable: the component world one admission sees."""

    model_config = ConfigDict(frozen=True)

    versions: dict[str, dict[str, StoredVersion]]  # name -> hash -> version
    order: dict[str, tuple[str, ...]]  # name -> registration order (hashes)
    stable: dict[str, str]  # name -> stable hash
    # name -> ordered (from_hash|None, to_hash) promotion pairs; the receipts
    # a rollback policy walks to find the retained prior version
    history: dict[str, tuple[tuple[str | None, str], ...]] = {}

    def stable_version(self, name: str) -> Digest | None:
        value = self.stable.get(name)
        return Digest(value) if value else None

    def get(self, name: str, version: Digest) -> StoredVersion | None:
        return self.versions.get(name, {}).get(str(version))

    def names(self) -> list[str]:
        return sorted(self.versions)


class Loadability(BaseModel):
    """Whether THIS host can execute a stored atomic version — diagnostic,
    host-local, and never persisted."""

    model_config = ConfigDict(frozen=True)

    status: Literal[
        "loadable",
        "missing_module",
        "missing_qualname",
        "not_callable",
        "implementation_drift",
        "source_unavailable",
        "composite",
    ]
    expected_digest: Digest | None = None
    observed_digest: Digest | None = None
    detail: str | None = None


@runtime_checkable
class RegistryStore(Protocol):
    """Durable, append-only component storage. Rows are receipts: a
    components row IS the registration receipt, a promotions row IS the
    pointer-move receipt (no synthetic run events)."""

    def snapshot(self) -> RegistrySnapshot: ...

    def store_version(self, version: StoredVersion) -> None:
        """Write-once: absent -> insert; identical -> idempotent;
        contradictory at the same (name, content_hash) -> damage."""
        ...

    def store_promotion(self, record: PromotionRecord) -> PromotionRecord:
        """Compare-and-swap: insert only when the current stable pointer
        equals ``record.from_version``; one attestation authorizes one move
        (a retry with the same attestation returns the existing record)."""
        ...

    def promotion_for_attestation(
        self, attestation_id: str
    ) -> PromotionRecord | None:
        """Read the exact pointer-move receipt authorized by one attestation."""
        ...
