"""Trusted, finite case projection used by the credential-free M9 pilot."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.envelope import ArtifactRef
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.journal import Journal
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext
from tests.e2e.m9_fixture import Case, Diagnosis

DIAGNOSTIC_PATH = ExecutionPath(scope=ScopePath(segments=("m9-pilot", "report", "diagnose")))
CURATOR = "test/m9-curator"
CURATOR_PATH = ExecutionPath(scope=ScopePath(segments=("m9-seal", "retain")))
PROJECTION = Port(name="projection", type_id="test/M9Projection", schema_hash="m9-projection-v1")
RETAINED = Port(name="retained", type_id="test/M9Projection", schema_hash="m9-projection-v1")
MAX_PROJECTION_BYTES = 8192


class SourceCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    case: Case
    expected: Diagnosis
    source_run: RunId
    manifest_hash: Digest
    input_hash: Digest
    output_checkpoint: Digest
    split: Literal["train", "held"]


class Exam(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    policy: Literal["m9-fixed-v1"] = "m9-fixed-v1"
    fixture: Digest
    cases: tuple[SourceCase, ...]

    def checked(self) -> Exam:
        if (
            len(self.cases) != 3
            or tuple(row.split for row in self.cases) != ("train", "held", "held")
            or len({row.case.evidence_id for row in self.cases}) != 3
            or len({row.input_hash for row in self.cases}) != 3
            or len({row.source_run for row in self.cases}) != 3
            or len({row.expected.classification for row in self.cases[1:]}) != 2
            or any(row.expected.evidence_id != row.case.evidence_id for row in self.cases)
        ):
            raise ValueError("M9 exam requires a non-overlapping three-case split")
        return self

    def canonical(self) -> str:
        return canonical_json(self.checked().model_dump(mode="json"))

    def training_projection(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            {
                "case": row.case.model_dump(mode="json"),
                "expected": row.expected.model_dump(mode="json"),
            }
            for row in self.checked().cases
            if row.split == "train"
        )


def project_case(
    journal: Journal,
    run: RunId,
    expected: Diagnosis,
    split: Literal["train", "held"],
) -> SourceCase:
    record = journal.run_record(run)
    inputs = journal.run_inputs(run)
    checkpoint = journal.checkpoint(run, DIAGNOSTIC_PATH)
    origin = record.origin if record is not None else None
    if (
        record is None
        or record.status != RunStatus.SUCCEEDED
        or origin is None
        or origin.kind != "start"
        or origin.effects != "live"
        or origin.capabilities != "normal"
        or inputs is None
        or checkpoint is None
    ):
        raise ValueError("M9 source is missing completed evidence")
    case = Case.model_validate(inputs["case"])
    if checkpoint.input_hash != digest("inputs", 1, {"case": case.model_dump(mode="json")}):
        raise ValueError("M9 source checkpoint is not bound to the case input")
    if checkpoint.run_id != run or checkpoint.path != DIAGNOSTIC_PATH:
        raise ValueError("M9 source checkpoint belongs to a different invocation")
    return SourceCase(
        case=case,
        expected=expected,
        source_run=run,
        manifest_hash=record.manifest_hash,
        input_hash=record.input_hash,
        output_checkpoint=digest("m9-checkpoint", 1, checkpoint.model_dump(mode="json")),
        split=split,
    )


def projection_ref(raw: str) -> ArtifactRef:
    size = len(raw.encode("utf-8"))
    if size > MAX_PROJECTION_BYTES:
        raise ValueError("M9 projection exceeds the fixture limit")
    return ArtifactRef(
        digest=digest("m9-projection", 1, raw), media_type="application/json", size=size
    )


async def retain_projection(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    del ctx
    raw = inputs["projection"]
    if not isinstance(raw, str) or Exam.model_validate_json(raw).canonical() != raw:
        raise ValueError("M9 curator requires canonical exam bytes")
    projection_ref(raw)
    return {"retained": raw}


def curator_graph() -> Graph:
    return Graph(
        name="m9-seal",
        nodes=(GraphNode(id="retain", body=Ref(component=CURATOR)),),
        inputs=(PROJECTION,),
        outputs=(RETAINED,),
    )


def read_projection(journal: Journal, run: RunId, reference: ArtifactRef) -> Exam:
    record = journal.run_record(run)
    checkpoint = journal.checkpoint(run, CURATOR_PATH)
    if record is None or record.status != RunStatus.SUCCEEDED or checkpoint is None:
        raise ValueError("M9 sealed projection is missing its durable checkpoint")
    envelope = checkpoint.outputs.get("retained")
    if envelope is None or envelope.run_id != run or envelope.path != CURATOR_PATH:
        raise ValueError("M9 projection is not bound to the curator checkpoint")
    raw = envelope.payload
    if not isinstance(raw, str) or projection_ref(raw) != reference:
        raise ValueError("M9 retained projection digest mismatch")
    exam = Exam.model_validate_json(raw).checked()
    if exam.canonical() != raw:
        raise ValueError("M9 retained projection bytes are not canonical")
    return exam


def propose(training: tuple[dict[str, Any], ...], choices: tuple[str, ...]) -> str:
    """An untrusted stand-in sees no run handles, policy or held-out rows."""
    if len(training) != 1 or not choices:
        raise ValueError("M9 proposer received no usable training projection")
    return choices[-1]


PROPOSER = "test/m9-proposer"
PROPOSER_PATH = ExecutionPath(scope=ScopePath(segments=("m9-propose", "suggest")))
TRAIN = Port(name="training", type_id="test/M9Training", schema_hash="m9-training-v1")
CHOICE = Port(name="choice", type_id="test/M9Atom", schema_hash="m9-atom-v1")


async def suggest(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    del ctx
    return {"choice": propose(tuple(json.loads(inputs["training"])), ("baseline", "cite-evidence"))}


def proposer_graph() -> Graph:
    return Graph(
        name="m9-propose",
        nodes=(GraphNode(id="suggest", body=Ref(component=PROPOSER)),),
        inputs=(TRAIN,),
        outputs=(CHOICE,),
    )
