"""Execution grants (I3, I13).

Authored ``GrantRequest``s may inherit; the sealed manifest carries only fully
concrete ``EffectiveGrants``. ``None`` and ``"inherit"`` are authoring
concepts and must not survive admission; unresolved inheritance at the root is
a validation error.

Executors declare an ``IsolationProfile``. Admission REJECTS a live execution
whose executor cannot mechanically satisfy the requested posture — it never
degrades to "best effort" (I1, literal).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, PositiveInt


class Posture(StrEnum):
    READ = "read"
    WRITE = "write"


class ModelSelection(BaseModel):
    """An explicit choice, or an explicit decision to use the backend default."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["explicit", "backend_default"]
    model: str | None = None


class GrantRequest(BaseModel):
    """Authoring surface — fields left ``None``/"inherit" resolve at admission."""

    model_config = ConfigDict(frozen=True)

    posture: Posture | None = None
    model: str | None = None  # None = backend default (model != authority)
    effort: str | None = None
    allowed_tools: tuple[str, ...] | None = None  # None = inherit parent grant
    env_allowlist: tuple[str, ...] | None = None
    network: Literal["inherit", "none", "allow"] = "inherit"
    timeout_s: PositiveInt | None = None


class EffectiveGrants(BaseModel):
    """Sealed into the manifest: no authority decision left for the executor."""

    model_config = ConfigDict(frozen=True)

    posture: Posture
    model_selection: ModelSelection
    effort: str | None
    allowed_tools: tuple[str, ...]
    env_allowlist: tuple[str, ...]
    network: Literal["none", "allow"]
    timeout_s: PositiveInt


class IsolationProfile(BaseModel):
    """What an executor can mechanically enforce; admission logic, not hope."""

    model_config = ConfigDict(frozen=True)

    filesystem: Literal["none", "workspace_only", "read_only_snapshot"]
    process_tree_owned: bool
    environment_allowlisted: bool
    network_enforced: bool

    def satisfies(self, posture: Posture) -> bool:
        if not (self.process_tree_owned and self.environment_allowlisted):
            return False
        if posture is Posture.READ:
            return self.filesystem in ("none", "read_only_snapshot")
        return self.filesystem == "workspace_only"
