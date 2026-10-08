"""The bounded qualification authorization (M8 N5 Stage 1).

One owner-placed authorization lets exactly one fixed qualification run admit
and acquire an executor whose published reasons stay unavailable, without ever
dispatching. It is operator configuration (ADR 0021), not a caller's request:
an assembly verifies it from a trusted source and hands it to the provider.
This module holds only the shape and its predicates; nothing here does I/O.

The bound needs no new durable state. The authorization pins one run, one
node path and one binding, so it pins one logical lease; every acquisition of
that lease is at a durable, fenced run epoch, so ``max_epoch`` bounds the
acquisitions one journal can mint. A journal reset restarts the epochs, which
is accepted for a stage that never dispatches (M8-N5-stage1-qualification.md).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import AwareDatetime, BaseModel, ConfigDict, PositiveInt, model_validator

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.control import command_id_for, run_id_for_command
from constructicon.core.grants import EffectiveGrants
from constructicon.core.identity import Digest, canonical_json

QUALIFICATION_OPERATION = "runs_start"


class QualificationAuthorization(BaseModel):
    """Exactly one qualification run, its one acquisition, and its window.

    The no-dispatch stage (Stage 1) never sends a turn. The read stage (Stage 3)
    sends exactly one READ turn: it also pins the grants and the attempt record,
    the one durable artifact that accounts for the attempt and outlives a
    journal reset (M8-N5-stage3-read.md, decision S3-1), and permits one epoch.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    authorization_id: str
    stage: Literal["qualification-no-dispatch", "qualification-read"]
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
    # The read stage only: the sealed grants and the attempt record's path.
    grants: EffectiveGrants | None = None
    attempt_record: str | None = None

    @model_validator(mode="after")
    def _stage_shape(self) -> QualificationAuthorization:
        if self.dispatches:
            if self.grants is None or not self.attempt_record or self.max_epoch != 1:
                raise ValueError(
                    "a read authorization pins its grants, its attempt record "
                    "and exactly one epoch",
                )
        elif self.grants is not None or self.attempt_record is not None:
            raise ValueError("a no-dispatch authorization pins no grants or attempt record")
        return self

    @property
    def dispatches(self) -> bool:
        return self.stage == "qualification-read"

    @property
    def run_id(self) -> RunId:
        command = command_id_for(self.actor_id, QUALIFICATION_OPERATION, self.idempotency_key)
        return run_id_for_command(command)

    def admits(self, *, source_graph_hash: Digest, capability_id: str, revision: str) -> bool:
        """Admission's question: is this graph authorized for this executor?

        Deliberately timeless: admission must not vary with the clock. Expiry,
        the run and the epoch are acquisition's to refuse.
        """
        return (
            source_graph_hash == self.source_graph_hash
            and capability_id == self.capability_id
            and revision == self.revision
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
        pinned = self.grants is None or canonical_json(grants) == canonical_json(self.grants)
        checks = (
            (run_id == self.run_id, "a different run"),
            (path == ExecutionPath(scope=self.scope), "a different invocation"),
            (binding == self.binding, "a different binding"),
            (source_graph_hash == self.source_graph_hash, "a different source graph"),
            (capability_id == self.capability_id, "a different capability"),
            (revision == self.revision, "a different adapter revision"),
            (
                operator_binding_digest == self.operator_binding_digest,
                "a different operator binding",
            ),
            (pinned, "other grants"),
            (epoch <= self.max_epoch, "an acquisition beyond the authorized epochs"),
            (now < self.not_after, "an expired authorization"),
        )
        return tuple(f"qualification refuses {fault}" for held, fault in checks if not held)


@runtime_checkable
class QualificationAuthorizing(Protocol):
    """A provider that may admit one authorized qualification graph while unavailable.

    Its published unavailable reasons do not change; admission alone asks this.
    """

    def authorizes_admission(self, *, source_graph_hash: Digest, capability_id: str) -> bool: ...
