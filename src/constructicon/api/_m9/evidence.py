"""Trusted, finite case projection used by the credential-free M9 pilot."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from constructicon.api._m9 import fixture as m9_fixture
from constructicon.api._m9.component import atomic
from constructicon.api._m9.fixture import (
    DEPENDENT,
    PROVIDER,
    REVISION,
    TARGET,
    TCP_OBSERVATION,
    Case,
    Diagnosis,
    diagnostic_definition,
    report_definition,
    report_graph,
)
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.component import ComponentDef, PythonRef
from constructicon.core.envelope import ArtifactRef
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.journal import Journal
from constructicon.core.manifest import (
    SELF_BINDING,
    SELF_CAPABILITY,
    ExecutionManifest,
    manifest_hash_for,
    source_graph_hash_for,
)
from constructicon.core.ports import Port
from constructicon.core.run import RunStatus
from constructicon.runtime.context import NodeContext

DIAGNOSTIC_PATH = ExecutionPath(scope=ScopePath(segments=("m9-pilot", "report", "diagnose")))
CURATOR = "test/m9-curator"
CURATOR_PATH = ExecutionPath(scope=ScopePath(segments=("m9-seal", "retain")))
PROJECTION = Port(name="projection", type_id="test/M9Projection", schema_hash="m9-projection-v1")
RETAINED = Port(name="retained", type_id="test/M9Projection", schema_hash="m9-projection-v1")
MAX_PROJECTION_BYTES = 8192
CASE_POLICY: tuple[tuple[Case, Diagnosis, Literal["train", "held"]], ...] = (
    (
        Case(evidence_id="train-1", observation="DNS lookup timed out"),
        Diagnosis(classification="network", evidence_id="train-1"),
        "train",
    ),
    (
        Case(evidence_id="held-1", observation="Disk quota exceeded"),
        Diagnosis(classification="storage", evidence_id="held-1"),
        "held",
    ),
    (
        Case(evidence_id="held-2", observation=TCP_OBSERVATION),
        Diagnosis(classification="network", evidence_id="held-2"),
        "held",
    ),
)


@dataclass(frozen=True)
class TrialIdentity:
    """One fixed experiment namespace; commands remain replayable across processes."""

    trial_id: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", self.trial_id):
            raise ValueError("M9 trial id must use 1 to 48 lowercase letters, digits or hyphens")

    def key(self, stage: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,47}", stage):
            raise ValueError("invalid M9 trial stage")
        return f"m9-v1:{self.trial_id}:{stage}"


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


def curator_definition() -> ComponentDef:
    definition, _ = atomic(CURATOR, (PROJECTION,), (RETAINED,), retain_projection)
    return definition


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


def _retained_manifest(journal: Journal, run: RunId, graph: Graph) -> ExecutionManifest:
    record = journal.run_record(run)
    origin = record.origin if record is not None else None
    if (
        record is None
        or record.run_id != run
        or record.status != RunStatus.SUCCEEDED
        or origin is None
        or origin.kind != "start"
        or origin.effects != "live"
        or origin.capabilities != "normal"
    ):
        raise ValueError("M9 evidence run did not complete in the reviewed start lane")
    raw = journal.load_manifest_json(record.manifest_hash)
    if raw is None:
        raise ValueError("M9 evidence run lacks its retained manifest")
    manifest = ExecutionManifest.model_validate_json(raw)
    if (
        manifest.manifest_hash != record.manifest_hash
        or manifest_hash_for(manifest) != record.manifest_hash
        or manifest.input_hash != record.input_hash
        or manifest.source_graph != graph
        or manifest.source_graph_hash != source_graph_hash_for(graph)
        or manifest.resolved_loops
    ):
        raise ValueError("M9 evidence run differs from the reviewed manifest")
    return manifest


def fixed_exam(
    journal: Journal,
    source_runs: tuple[RunId, ...],
    *,
    fixture: Digest,
    baseline: Digest,
    impact: Digest,
) -> Exam:
    """Derive the finite exam from journal facts and trusted fixture labels."""
    if len(source_runs) != len(CASE_POLICY):
        raise ValueError("M9 requires exactly three allowlisted source runs")
    baseline_definition = diagnostic_definition(m9_fixture.baseline)
    impact_definition = report_definition()
    body = baseline_definition.body
    if (
        not isinstance(body, PythonRef)
        or str(body.source_digest) != (
            "sha256:9890709271e8c48f047d87f2442e076e0c8a4d611692a6ceb8de1acc3da523a4"
        )
        or baseline != baseline_definition.content_hash()
        or impact != impact_definition.content_hash()
    ):
        raise ValueError("M9 source versions differ from the reviewed definitions")
    cases: list[SourceCase] = []
    for run, (case, expected, split) in zip(source_runs, CASE_POLICY, strict=True):
        manifest = _retained_manifest(journal, run, report_graph())
        inputs = {"case": case.model_dump(mode="json")}
        targets = {
            (row.component, row.scope.segments): row for row in manifest.resolved_components
        }
        target = targets.get((TARGET, DIAGNOSTIC_PATH.scope.segments))
        dependent = targets.get((DEPENDENT, DIAGNOSTIC_PATH.scope.segments[:-1]))
        bindings = {
            (row.scope.segments, row.binding, row.capability_id, row.revision)
            for row in manifest.capability_bindings
        }
        if (
            journal.run_inputs(run) != inputs
            or manifest.input_hash != digest("inputs", 1, inputs)
            or len(manifest.resolved_components) != 2
            or target is None
            or target.resolved_version != baseline
            or target.implementation_digest != body.source_digest
            or dependent is None
            or dependent.resolved_version != impact
            or len(manifest.capability_bindings) != 2
            or (DIAGNOSTIC_PATH.scope.segments, "executor", PROVIDER, REVISION) not in bindings
            or not any(
                scope == DIAGNOSTIC_PATH.scope.segments
                and binding == SELF_BINDING
                and capability == SELF_CAPABILITY
                for scope, binding, capability, _ in bindings
            )
        ):
            raise ValueError("M9 source differs from the allowlisted case or resolution")
        checkpoint = journal.checkpoint(run, DIAGNOSTIC_PATH)
        if (
            checkpoint is None
            or checkpoint.resolved_version != baseline
            or set(checkpoint.outputs) != {"diagnosis"}
        ):
            raise ValueError("M9 source lacks its complete baseline checkpoint")
        envelope = checkpoint.outputs["diagnosis"]
        if (
            envelope.run_id != run
            or envelope.path != DIAGNOSTIC_PATH
            or envelope.port != "diagnosis"
        ):
            raise ValueError("M9 source output belongs to another invocation")
        Diagnosis.model_validate(envelope.payload)
        cases.append(project_case(journal, run, expected, split))
    return Exam(fixture=fixture, cases=tuple(cases)).checked()


def read_fixed_projection(
    journal: Journal,
    seal: RunId,
    reference: ArtifactRef,
    *,
    source_runs: tuple[RunId, ...],
    fixture: Digest,
    baseline: Digest,
    impact: Digest,
) -> Exam:
    """Verify the curator and rederive the seal from this trial's allowlist."""
    exam = read_projection(journal, seal, reference)
    manifest = _retained_manifest(journal, seal, curator_graph())
    definition = curator_definition()
    body = definition.body
    version = definition.content_hash()
    raw = exam.canonical()
    inputs = {"projection": raw}
    checkpoint = journal.checkpoint(seal, CURATOR_PATH)
    if (
        not isinstance(body, PythonRef)
        or len(manifest.resolved_components) != 1
        or len(manifest.capability_bindings) != 1
        or checkpoint is None
        or checkpoint.run_id != seal
        or checkpoint.path != CURATOR_PATH
        or checkpoint.resolved_version != version
        or checkpoint.input_hash != manifest.input_hash
        or set(checkpoint.outputs) != {"retained"}
        or checkpoint.outputs["retained"].port != "retained"
        or journal.run_inputs(seal) != inputs
        or manifest.input_hash != digest("inputs", 1, inputs)
    ):
        raise ValueError("M9 seal lacks the reviewed curator checkpoint")
    (resolution,) = manifest.resolved_components
    (binding,) = manifest.capability_bindings
    if (
        resolution.scope != CURATOR_PATH.scope
        or resolution.component != CURATOR
        or resolution.resolved_version != version
        or resolution.implementation_digest != body.source_digest
        or binding.scope != CURATOR_PATH.scope
        or binding.binding != SELF_BINDING
        or binding.capability_id != SELF_CAPABILITY
    ):
        raise ValueError("M9 seal did not use the reviewed curator")
    if exam != fixed_exam(
        journal, source_runs, fixture=fixture, baseline=baseline, impact=impact
    ):
        raise ValueError("M9 sealed bytes differ from the fixed trial exam")
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


def proposer_definition() -> ComponentDef:
    definition, _ = atomic(PROPOSER, (TRAIN,), (CHOICE,), suggest)
    return definition.model_copy(update={"capability_requirements": ()})
