"""The executor seam — task-shaped, harness-level (decision 2).

All models, subscription or API, fit the same data model schema and are
interchangeable as plugs — substitutable where their declared capability
profile satisfies the node's contract. There is no completion-level provider
layer, ever.

Outcomes share one observation (I4: salvage applies to every status; fields a
backend does not emit stay ``None``, never inferred), extended per-status with
only the status-specific field.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict

from constructicon.core.envelope import ArtifactRef, GitRef, TextContext
from constructicon.core.grants import EffectiveGrants, IsolationProfile, Posture


class TaskSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    instruction: str
    context: tuple[ArtifactRef | GitRef | TextContext, ...] = ()
    response_schema: dict[str, Any] | None = None


class Usage(BaseModel):
    model_config = ConfigDict(frozen=True)

    input_tokens: int | None = None
    output_tokens: int | None = None


class RateLimitInfo(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_using_overage: bool | None = None
    detail: dict[str, Any] | None = None


class TransportDamage(BaseModel):
    model_config = ConfigDict(frozen=True)

    malformed_records: int
    first_error: str | None
    evidence_excerpt: str | None  # bounded head+tail, never the full stream


class ExecutorError(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["spawn", "timeout", "exit", "unavailable"]
    detail: str
    exit_code: int | None = None
    timed_out_after_s: float | None = None
    produced_output: bool | None = None


class ExecutorObservation(BaseModel):
    model_config = ConfigDict(frozen=True)

    raw_reply: str | None = None
    output: Any = None  # extracted structured output, pre-validation
    requested_model: str | None = None
    served_model: str | None = None  # None when the backend does not emit it
    usage: Usage | None = None
    rate_limit: RateLimitInfo | None = None
    elapsed_s: float = 0.0


class ExecutorSuccess(ExecutorObservation):
    status: Literal["success"] = "success"


class ExecutorPartial(ExecutorObservation):
    status: Literal["partial"] = "partial"
    damage: TransportDamage


class ExecutorFailure(ExecutorObservation):
    status: Literal["failure"] = "failure"
    error: ExecutorError


ExecutorOutcome = ExecutorSuccess | ExecutorPartial | ExecutorFailure


class ExecutorProfile(BaseModel):
    """Capability profile: what makes executors honestly substitutable."""

    model_config = ConfigDict(frozen=True)

    name: str
    structured_output: bool
    postures: frozenset[Posture]
    isolation: IsolationProfile
    accepted_efforts: frozenset[str] = frozenset()


class Executor(Protocol):
    @property
    def profile(self) -> ExecutorProfile: ...

    def validate_grants(self, grants: EffectiveGrants) -> tuple[str, ...]:
        """Itemized reasons this executor cannot honor the grants; empty = ok."""
        ...

    async def execute(
        self,
        task: TaskSpec,
        *,
        workspace: object | None,
        grants: EffectiveGrants,
    ) -> ExecutorOutcome: ...
