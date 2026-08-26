"""Envelopes and artifact references (I5).

Typed envelopes cross node boundaries. Code crosses as ``GitRef``. Other
durable evidence crosses as content-addressed ``ArtifactRef`` — the digest is
the identity, the locator only a storage hint.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Generic, TypeVar

from pydantic import AwareDatetime, BaseModel, ConfigDict, NonNegativeInt

from constructicon.core.address import ExecutionPath, GitSha, RunId
from constructicon.core.identity import Digest

T = TypeVar("T")


class Envelope(BaseModel, Generic[T]):
    model_config = ConfigDict(frozen=True)

    run_id: RunId
    path: ExecutionPath
    port: str
    created_at: AwareDatetime  # UTC; durations use monotonic clocks
    provenance: tuple[ExecutionPath, ...] = ()
    payload: T


class ArtifactRef(BaseModel):
    """Content-addressed artifact: digest is identity, locator a hint."""

    model_config = ConfigDict(frozen=True)

    digest: Digest
    media_type: str
    size: NonNegativeInt
    locator: str | None = None


class GitRef(BaseModel):
    """The git data plane: code crosses as commits, never as payloads."""

    model_config = ConfigDict(frozen=True)

    repository: str
    commit: GitSha
    paths: tuple[str, ...] = ()
    diff_against: GitSha | None = None


EvidenceRef = ArtifactRef | GitRef


class TextContext(BaseModel):
    """Literal text is typed, never an ambiguous bare string."""

    model_config = ConfigDict(frozen=True)

    text: str


def utc_now() -> datetime:

    return datetime.now(UTC)
