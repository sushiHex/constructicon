"""Credential-free diagnostic fixture for the approved M9 experiment."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from constructicon.core.component import CapabilityRequirement, ComponentDef, PythonRef
from constructicon.core.executor import TaskSpec
from constructicon.core.graph import Graph, GraphNode, Ref
from constructicon.core.identity import canonical_json
from constructicon.core.ports import Port
from constructicon.runtime.context import NodeContext
from constructicon.substrate.executors.fake import FakeExecutor
from tests.conftest import atomic

TARGET = "test/m9-diagnostic"
DEPENDENT = "test/m9-diagnostic-report"
PROVIDER = "fake-executor"
REVISION = "1"
CASE = Port(name="case", type_id="test/M9Case", schema_hash="m9-case-v1")
DIAGNOSIS = Port(name="diagnosis", type_id="test/M9Diagnosis", schema_hash="m9-diagnosis-v1")


class Case(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    evidence_id: str
    observation: str


class Diagnosis(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    classification: Literal["network", "storage"]
    evidence_id: str | None


def instruction(prompt: str, case: Case) -> str:
    return f"{prompt}\nCase: {canonical_json(case.model_dump(mode='json'))}"


async def run_task(ctx: NodeContext, inputs: Mapping[str, Any], prompt: str) -> Mapping[str, Any]:
    executor = ctx.capability("executor")
    if not isinstance(executor, FakeExecutor):
        raise ValueError("M9 only admits its scripted executor")
    case = Case.model_validate(inputs["case"])
    outcome = await executor.execute(
        TaskSpec(instruction=instruction(prompt, case)), workspace=None, grants=ctx.grants
    )
    if outcome.status != "success":
        raise ValueError("M9 diagnostic task did not succeed")
    return {"diagnosis": Diagnosis.model_validate(outcome.output).model_dump(mode="json")}


async def baseline(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return await run_task(ctx, inputs, "Classify the observation as network or storage.")


async def candidate(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return await run_task(
        ctx,
        inputs,
        "Classify the observation as network or storage. Cite the supplied evidence ID.",
    )


def scripted_replies() -> dict[str, Any]:
    rows = (
        ("train-1", "DNS lookup timed out", "network", True),
        ("held-1", "Disk quota exceeded", "storage", False),
        ("held-2", "TCP connection refused", "network", True),
    )
    replies: dict[str, Any] = {}
    for evidence_id, observation, classification, baseline_cites in rows:
        case = Case(evidence_id=evidence_id, observation=observation)
        for prompt, cites in (
            ("Classify the observation as network or storage.", baseline_cites),
            (
                "Classify the observation as network or storage. Cite the supplied evidence ID.",
                True,
            ),
        ):
            replies[instruction(prompt, case)] = {
                "classification": classification,
                "evidence_id": evidence_id if cites else None,
            }
    return replies


def diagnostic_definition(impl: Any) -> ComponentDef:
    definition, _ = atomic(TARGET, (CASE,), (DIAGNOSIS,), impl)
    return definition.model_copy(
        update={
            "capability_requirements": (CapabilityRequirement(alias="executor", kind="executor"),),
        }
    )


def report_definition() -> ComponentDef:
    return ComponentDef(
        name=DEPENDENT,
        role="component",
        body=Graph(
            name="m9-report",
            nodes=(
                GraphNode(id="diagnose", body=Ref(component=TARGET, bind={"executor": PROVIDER})),
            ),
            inputs=(CASE,),
            outputs=(DIAGNOSIS,),
        ),
        inputs=(CASE,),
        outputs=(DIAGNOSIS,),
    )


def report_graph() -> Graph:
    return Graph(
        name="m9-pilot",
        nodes=(GraphNode(id="report", body=Ref(component=DEPENDENT)),),
        inputs=(CASE,),
        outputs=(DIAGNOSIS,),
    )


def bind_candidate(choice: str, definition: ComponentDef) -> ComponentDef:
    """Accept exactly one reviewed atom and its immutable executable definition."""
    expected = diagnostic_definition(candidate)
    if (
        choice != "cite-evidence"
        or definition != expected
        or not isinstance(expected.body, PythonRef)
    ):
        raise ValueError("M9 candidate is not the reviewed evidence-citation atom")
    if str(expected.body.source_digest) != (
        "sha256:9d5047fd08fcb9d150998e9336b79fff18a693dfc04a2c2f9ddb1ce37ef882d6"
    ):
        raise ValueError("M9 candidate source digest differs from the reviewed atom")
    return definition
