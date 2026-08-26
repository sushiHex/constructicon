"""SDK combinators are byte-for-byte canonical Graph construction sugar."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import BaseModel

from constructicon.api.system import Constructicon
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import CONTINUE_TYPE
from constructicon.sdk import flow, harness, loop, port_type, task


class Issue(BaseModel):
    title: str


class Brief(BaseModel):
    title: str


class Summary(BaseModel):
    text: str


@task("sdk/triage", output="brief")
async def triage(
    issue: Annotated[Issue, port_type("sdk/Issue")],
) -> Annotated[Brief, port_type("sdk/Brief")]:
    return Brief(title=issue.title)


@task("sdk/summarize", output="summary")
async def summarize(
    brief: Annotated[Brief, port_type("sdk/Brief")],
) -> Annotated[Summary, port_type("sdk/Summary")]:
    return Summary(text=brief.title)


@task(
    "sdk/refine",
    outputs={
        "brief": Annotated[Brief, port_type("sdk/Brief")],
        "continue": Annotated[bool, port_type(CONTINUE_TYPE)],
    },
)
async def refine(
    brief: Annotated[Brief, port_type("sdk/Brief")],
) -> Mapping[str, Any]:
    return {"brief": brief, "continue": False}


def test_flow_is_exactly_the_hand_authored_graph(system: Constructicon) -> None:
    for bundle in (triage, summarize):
        version = system.register(bundle)
        system.promote_initial(component=bundle.name, version=version)

    authored = flow("sdk/pipeline", triage, summarize)
    direct = Graph(
        name="sdk/pipeline",
        nodes=(
            GraphNode(id="triage", body=Ref(component="sdk/triage")),
            GraphNode(id="summarize", body=Ref(component="sdk/summarize")),
        ),
        connections=(Connection(src="triage", dst="summarize"),),
        inputs=triage.definition.inputs,
        outputs=summarize.definition.outputs,
    )
    assert isinstance(authored.definition.body, Graph)
    assert authored.definition.body.model_dump(mode="json") == direct.model_dump(mode="json")
    inputs = {"issue": {"title": "flaky retry"}}
    sdk_manifest = system.validate(authored.definition.body, inputs)
    direct_manifest = system.validate(direct, inputs)
    assert sdk_manifest.source_graph_hash == direct_manifest.source_graph_hash
    assert sdk_manifest.world_hash == direct_manifest.world_hash
    assert sdk_manifest.manifest_hash == direct_manifest.manifest_hash


def test_loop_and_harness_add_no_execution_language() -> None:
    authored_loop = loop(
        refine,
        feedback={"brief": "brief"},
        continue_from="continue",
        max_iterations=3,
    )
    assert isinstance(authored_loop, Loop)
    assert authored_loop == Loop(
        body=Ref(component="sdk/refine"),
        feedback={"brief": "brief"},
        continue_from="continue",
        max_iterations=3,
    )
    wrapped = harness(
        "sdk/refine-harness",
        authored_loop,
        inputs=refine.definition.inputs,
        outputs=(refine.definition.outputs[0],),
    )
    assert wrapped.definition.role == "harness"
    assert isinstance(wrapped.definition.body, Graph)
    assert isinstance(wrapped.definition.body.nodes[0].body, Loop)
