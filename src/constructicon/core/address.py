"""Static scope vs dynamic invocation (I13 errata).

A ``ScopePath`` says where a component or node instance lives in the sealed
manifest — it exists at admission time, before any execution. An
``ExecutionPath`` says which runtime occurrence ran: the static scope plus the
loop-iteration frames that only exist at runtime.

``invocation_id(run_id, path)`` is THE identity used everywhere — envelopes,
checkpoints, events, effect receipts, channel messages, cancellation, budget
accounting, artifacts, API detail references. One invocation, one address.
"""

from __future__ import annotations

from typing import NewType

from pydantic import BaseModel, ConfigDict, NonNegativeInt

from constructicon.core.identity import Digest, digest

RunId = NewType("RunId", str)
NodeId = NewType("NodeId", str)
GitSha = NewType("GitSha", str)


class ScopePath(BaseModel):
    """Static location of a component or node instance in the manifest."""

    model_config = ConfigDict(frozen=True)

    segments: tuple[str, ...]

    def child(self, segment: str) -> ScopePath:
        return ScopePath(segments=(*self.segments, segment))

    def render(self) -> str:
        return "/".join(self.segments) if self.segments else "<root>"


class IterationFrame(BaseModel):
    model_config = ConfigDict(frozen=True)

    loop: ScopePath
    index: NonNegativeInt


class ExecutionPath(BaseModel):
    """One dynamic invocation address."""

    model_config = ConfigDict(frozen=True)

    scope: ScopePath
    iterations: tuple[IterationFrame, ...] = ()

    def render(self) -> str:
        rendered = self.scope.render()
        for frame in self.iterations:
            rendered += f"[{frame.index}]"
        return rendered


def invocation_id(run_id: RunId, path: ExecutionPath) -> Digest:
    """Derive the universal invocation identity from the identity law."""
    return digest(
        "invocation",
        1,
        {"run_id": run_id, "path": path.model_dump(mode="json")},
    )
