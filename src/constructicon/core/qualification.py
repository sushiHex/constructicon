"""The bounded qualification authorization (M8 N5 Stage 1).

One owner-placed authorization lets exactly one fixed qualification run admit
and acquire an executor whose published reasons stay unavailable. Dispatching
stages also pin the exclusive attempt record. It is operator configuration
(ADR 0021), not a caller's request: assembly verifies it from a trusted source
and hands it to the provider. This module holds only shape and predicates;
nothing here does I/O.

The bound needs no new durable state. The authorization pins one run, one
node path and one binding, so it pins one logical lease; every acquisition of
that lease is at a durable, fenced run epoch, so ``max_epoch`` bounds the
acquisitions one journal can mint. A journal reset restarts the epochs, which
is accepted for a stage that never dispatches (M8-N5-stage1-qualification.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    PositiveInt,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.grants import EffectiveGrants
from constructicon.core.identity import Digest
from constructicon.core.qualification_write import WriteQualificationPins

QUALIFICATION_OPERATION = "runs_start"


class QualificationAuthorization(BaseModel):
    """Exactly one qualification run, its one acquisition, and its window.

    The no-dispatch stage (Stage 1) never sends a turn. The read stage (Stage 3)
    sends exactly one READ turn: it also pins the grants and the attempt record,
    the one durable artifact that accounts for the attempt and outlives a
    journal reset (M8-N5-stage3-read.md, decision S3-1), and permits one epoch.
    WRITE extends that exception with exact grants and L4-checked assembly
    pins. The epoch bound limits acquisition, not checkpoint-only recovery.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    authorization_id: str
    stage: Literal["qualification-no-dispatch", "qualification-read", "qualification-write"]
    # The run: these fix the command id and so the run id (core/control.py).
    actor_id: str
    idempotency_key: str
    # The invocation: with the run, these fix the logical lease.
    scope: ScopePath
    binding: str
    # What is authorized to run there.
    source_graph_hash: Digest
    capability_id: str
    revision: str
    operator_binding_digest: Digest
    # Where, how often, and until when.
    journal: str
    max_epoch: PositiveInt
    not_after: AwareDatetime
    # Dispatching stages: sealed grants and the exclusive attempt record's path.
    grants: EffectiveGrants | None = None
    attempt_record: str | None = None
    write: WriteQualificationPins | None = None

    @model_validator(mode="before")
    @classmethod
    def _write_key(cls, value: Any) -> Any:
        if (
            isinstance(value, dict)
            and value.get("stage") != "qualification-write"
            and "write" in value
        ):
            raise ValueError("only a WRITE authorization carries WRITE pins")
        return value

    @model_serializer(mode="wrap")
    def _wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        record: dict[str, Any] = handler(self)
        if self.stage != "qualification-write":
            record.pop("write", None)
        return record

    @model_validator(mode="after")
    def _stage_shape(self) -> QualificationAuthorization:
        if self.dispatches:
            if self.grants is None or not self.attempt_record or self.max_epoch != 1:
                raise ValueError(
                    f"a {self.stage.removeprefix('qualification-')} authorization "
                    "pins its grants, its attempt record "
                    "and exactly one epoch",
                )
        elif self.grants is not None or self.attempt_record is not None:
            raise ValueError("a no-dispatch authorization pins no grants or attempt record")
        if self.stage == "qualification-write":
            grants = self.grants
            if self.write is None:
                raise ValueError("a WRITE authorization requires its assembly pins")
            from constructicon.core.permit import fixed_write_grants

            if grants is None or not fixed_write_grants(grants):
                raise ValueError("a WRITE authorization requires the fixed WRITE grant shape")
        return self

    @property
    def purpose(self) -> Literal[
        "qualification-no-dispatch", "qualification-read", "qualification-write",
    ]:
        """The closed purpose, retaining ``stage`` as the wire discriminator."""
        return self.stage

    @property
    def dispatches(self) -> bool:
        return self.stage in ("qualification-read", "qualification-write")

    @property
    def run_id(self) -> RunId:
        from constructicon.core.permit import run_id

        return run_id(self)

    def admits(self, *, source_graph_hash: Digest, capability_id: str, revision: str) -> bool:
        """Admission's question: is this graph authorized for this executor?

        Deliberately timeless: admission must not vary with the clock. Expiry,
        the run and the epoch are acquisition's to refuse.
        """
        from constructicon.core.permit import admits

        return admits(
            self, source_graph_hash=source_graph_hash,
            capability_id=capability_id, revision=revision,
        )

    def acquisition_faults(
        self,
        *,
        run_id: RunId,
        path: ExecutionPath,
        binding: str,
        source_graph_hash: Digest | None,
        capability_id: str,
        revision: str,
        operator_binding_digest: Digest,
        grants: EffectiveGrants,
        epoch: int,
        now: datetime,
    ) -> tuple[str, ...]:
        """Every reason this acquisition is not the authorized one; empty admits."""
        from constructicon.core.permit import fault_sentences, faults

        return fault_sentences(self, faults(
            self, run_id=run_id, path=path, binding=binding,
            source_graph_hash=source_graph_hash, capability_id=capability_id, revision=revision,
            operator_binding_digest=operator_binding_digest, grants=grants,
            epoch=epoch, now=now,
        ))


@runtime_checkable
class QualificationAuthorizing(Protocol):
    """A provider that may admit one authorized qualification graph while unavailable.

    Its published unavailable reasons do not change; admission alone asks this.
    """

    def authorizes_admission(self, *, source_graph_hash: Digest, capability_id: str) -> bool: ...
