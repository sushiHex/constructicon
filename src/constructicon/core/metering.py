"""Bounded, source-scoped facts about one native executor dispatch."""

from __future__ import annotations

from typing import Annotated, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.executor import ExecutorOutcome
from constructicon.core.identity import Digest

MeteringSource = Literal["codex_fresh_thread_total_v1", "claude_main_loop_v1"]
MeteringCoverage = Literal["legacy_unmeasured", "unmeasured", "supported_observations"]
ModelName = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$"),
]
TokenCount = Annotated[int, Field(ge=0, le=2**63 - 1)]
Nonnegative = Annotated[int, Field(ge=0)]
Positive = Annotated[int, Field(gt=0)]


class MeteringWriter(Protocol):
    """Trusted writer for exactly one acquisition; intent replay never permits a send."""

    def intend(self) -> None: ...

    def check_dispatch(self) -> None: ...

    def settle(self, outcome: ExecutorOutcome | None) -> None: ...


class MeteringIntent(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    run_id: RunId
    acquisition_id: str
    lease_id: str
    acquisition_epoch: Positive
    path: ExecutionPath
    binding_id: str
    revision: str
    manifest_hash: Digest
    source: MeteringSource
    origin: Literal["actual"]
    requested_model: ModelName


class MeteringOutcome(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    schema_version: Literal[1] = 1
    coverage: Literal["unavailable", "partial", "observed"]
    served_model: ModelName | None
    input_tokens: TokenCount | None
    output_tokens: TokenCount | None
    dispatch: Literal["possibly_dispatched", "dispatched"]
    result: Literal["success", "partial", "failure"]

    @model_validator(mode="after")
    def _coherent(self) -> MeteringOutcome:
        measured = self.input_tokens is not None or self.output_tokens is not None
        if measured == (self.coverage == "unavailable"):
            raise ValueError("metering coverage contradicts the observed counters")
        complete = (
            self.input_tokens is not None and self.output_tokens is not None
            and self.result == "success" and self.dispatch == "dispatched"
        )
        if complete != (self.coverage == "observed"):
            raise ValueError("fully observed metering requires a successful measured dispatch")
        if (measured or self.result == "success") and self.dispatch != "dispatched":
            raise ValueError("a correlated observation requires a dispatch")
        return self


class MeteringEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    event_seq: Positive
    event_digest: Digest


class MeteringAttempt(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    intent: MeteringIntent
    intent_evidence: MeteringEvidence
    outcome: MeteringOutcome | None
    outcome_evidence: MeteringEvidence | None


class MeteringGroup(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    source: MeteringSource
    intent_only: Nonnegative
    unavailable: Nonnegative
    partial: Nonnegative
    observed: Nonnegative
    known_input_tokens: Nonnegative | None
    known_output_tokens: Nonnegative | None


class MeteringSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    run_id: RunId
    event_seq: Nonnegative
    coverage: MeteringCoverage
    groups: tuple[MeteringGroup, ...]
    attempt_count: Nonnegative
    attempts: tuple[MeteringAttempt, ...]
