"""SDK combinators are byte-for-byte canonical Graph construction sugar."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from constructicon.api.system import Constructicon
from constructicon.core.errors import AdmissionError
from constructicon.core.graph import Connection, Graph, GraphNode, Loop, Ref
from constructicon.core.manifest import CONTINUE_TYPE, ExecutionManifest
from constructicon.core.ports import Port
from constructicon.sdk import flow, harness, loop, panel, port_type, task


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
        version = system._register(bundle)
        system._promote_initial(component=bundle.name, version=version)

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


class Ask(BaseModel):
    question: str


class Vote(BaseModel):
    member: str
    ballot: str


class Quorum(BaseModel):
    required: int


class Tally(BaseModel):
    approvals: int


@task("sdk/panel-yes", output="vote")
async def panel_yes(
    request: Annotated[Ask, port_type("sdk/Ask")],
) -> Annotated[Vote, port_type("sdk/Vote")]:
    return Vote(member="yes", ballot="approve")


@task("sdk/panel-no", output="vote")
async def panel_no(
    request: Annotated[Ask, port_type("sdk/Ask")],
) -> Annotated[Vote, port_type("sdk/Vote")]:
    return Vote(member="no", ballot="reject")


@task("sdk/panel-tally", output="tally")
async def panel_tally(
    votes: list[Annotated[Vote, port_type("sdk/Vote")]],
    quorum: Annotated[Quorum, port_type("sdk/Quorum")],
) -> Annotated[Tally, port_type("sdk/Tally")]:
    return Tally(approvals=sum(1 for vote in votes if vote.ballot == "approve"))


@task("sdk/panel-first", output="tally")
async def panel_first(
    vote: Annotated[Vote, port_type("sdk/Vote")],
) -> Annotated[Tally, port_type("sdk/Tally")]:
    return Tally(approvals=1 if vote.ballot == "approve" else 0)


def _promote_all(system: Constructicon, *bundles: Any) -> None:
    for bundle in bundles:
        version = system._register(bundle)
        system._promote_initial(component=bundle.name, version=version)


def test_panel_is_exactly_the_hand_authored_fan_out_and_fan_in(
    system: Constructicon,
) -> None:
    """The combinator writes no map and chooses nothing; it is the Graph."""

    _promote_all(system, panel_yes, panel_no, panel_tally)
    authored = panel("sdk/review-panel", panel_yes, panel_no, aggregator=panel_tally)
    direct = Graph(
        name="sdk/review-panel",
        nodes=(
            GraphNode(id="panel_yes", body=Ref(component="sdk/panel-yes")),
            GraphNode(id="panel_no", body=Ref(component="sdk/panel-no")),
            GraphNode(id="panel_tally", body=Ref(component="sdk/panel-tally")),
        ),
        connections=(
            Connection(src="panel_yes", dst="panel_tally"),
            Connection(src="panel_no", dst="panel_tally"),
        ),
        # The request every member asks about, then the aggregator's own
        # typed input: quorum is data the caller supplies, never a default.
        inputs=(*panel_yes.definition.inputs, panel_tally.definition.inputs[1]),
        outputs=panel_tally.definition.outputs,
    )
    assert isinstance(authored.definition.body, Graph)
    assert authored.definition.body.model_dump(mode="json") == direct.model_dump(mode="json")
    assert authored.definition.role == "workflow"

    inputs = {"request": {"question": "ship?"}, "quorum": {"required": 1}}
    sdk_manifest = system.validate(authored.definition.body, inputs)
    direct_manifest = system.validate(direct, inputs)
    assert sdk_manifest.source_graph_hash == direct_manifest.source_graph_hash
    assert sdk_manifest.manifest_hash == direct_manifest.manifest_hash

    # The fan-in is exact: the aggregator's `many` port was bound to the two
    # members and nothing else.
    gathered = [
        binding
        for binding in sdk_manifest.resolved_connections
        if binding.destination.kind == "node_port"
        and binding.destination.node == "panel_tally"
        and binding.destination.port == "votes"
    ]
    assert len(gathered) == 1
    sources = gathered[0].sources
    assert sorted(getattr(source, "node", "$input") for source in sources) == [
        "panel_no",
        "panel_yes",
    ]


def test_panel_with_explicit_ids_and_a_repeated_member_is_still_the_direct_graph(
    system: Constructicon,
) -> None:
    """Ids are the author's; a component seated twice is two nodes of one Ref."""

    _promote_all(system, panel_yes, panel_tally)
    sugared = panel(
        "sdk/twice",
        panel_yes,
        panel_yes,
        aggregator=panel_tally,
        ids=("first", "second"),
        aggregator_id="tally",
    )
    direct = Graph(
        name="sdk/twice",
        nodes=(
            GraphNode(id="first", body=Ref(component="sdk/panel-yes")),
            GraphNode(id="second", body=Ref(component="sdk/panel-yes")),
            GraphNode(id="tally", body=Ref(component="sdk/panel-tally")),
        ),
        connections=(
            Connection(src="first", dst="tally"),
            Connection(src="second", dst="tally"),
        ),
        inputs=(*panel_yes.definition.inputs, panel_tally.definition.inputs[1]),
        outputs=panel_tally.definition.outputs,
    )
    assert sugared.definition.body == direct
    assert sugared.definition.body.model_dump(mode="json") == direct.model_dump(mode="json")
    inputs = {"request": {"question": "ship?"}, "quorum": {"required": 1}}
    assert (
        system.validate(sugared.definition.body, inputs).manifest_hash
        == system.validate(direct, inputs).manifest_hash
    )


def _gathered(manifest: ExecutionManifest) -> list[str]:
    """Every source the tally's `many` port gathers, by node, `$input` for the boundary."""

    bindings = [
        binding
        for binding in manifest.resolved_connections
        if binding.destination.kind == "node_port"
        and binding.destination.node == "panel_tally"
        and binding.destination.port == "votes"
    ]
    assert len(bindings) == 1
    return sorted(getattr(source, "node", "$input") for source in bindings[0].sources)


def test_a_second_compatible_producer_is_gathered_by_many_and_ambiguous_for_one(
    system: Constructicon,
) -> None:
    """`many` gathers exactly what is connected; `one` still refuses to guess."""

    _promote_all(system, panel_yes, panel_no, panel_tally, panel_first)
    inputs = {"request": {"question": "ship?"}, "quorum": {"required": 1}}

    # An unconnected member offers the same contract but is not upstream of the
    # aggregator, so it contributes nothing: the gather is by construction.
    wider = panel("sdk/wider", panel_yes, panel_no, aggregator=panel_tally)
    assert isinstance(wider.definition.body, Graph)
    with_bystander = wider.definition.body.model_copy(
        update={
            "nodes": (
                *wider.definition.body.nodes,
                GraphNode(id="bystander", body=Ref(component="sdk/panel-yes")),
            ),
        }
    )
    assert _gathered(system.validate(with_bystander, inputs)) == ["panel_no", "panel_yes"]

    # The gather is the general connector law, not a panel privilege: a graph
    # input of the members' contract is in every pool, and a compatible helper
    # upstream of a member is in the aggregator's transitive closure. Both
    # widen it. `panel()` never emits either shape; a hand-authored graph that
    # does gets exactly what it connected.
    seed = Port(
        name="seed", type_id="sdk/Vote", schema_hash=panel_yes.definition.outputs[0].schema_hash
    )
    with_input = wider.definition.body.model_copy(
        update={"inputs": (*wider.definition.body.inputs, seed)}
    )
    seeded = {**inputs, "seed": {"approve": True}}
    assert _gathered(system.validate(with_input, seeded)) == ["$input", "panel_no", "panel_yes"]

    with_helper = wider.definition.body.model_copy(
        update={
            "nodes": (
                GraphNode(id="helper", body=Ref(component="sdk/panel-yes")),
                *wider.definition.body.nodes,
            ),
            "connections": (
                Connection(src="helper", dst="panel_yes"),
                *wider.definition.body.connections,
            ),
        }
    )
    assert _gathered(system.validate(with_helper, inputs)) == ["helper", "panel_no", "panel_yes"]

    # An aggregator without a `many` port cannot gather at all, so `panel()`
    # refuses it at authoring — and the hand-authored equivalent is the
    # validator's existing ambiguity fault, unchanged.
    with pytest.raises(TypeError, match="exactly one many-cardinality input"):
        panel("sdk/ambiguous", panel_yes, panel_no, aggregator=panel_first)
    direct = Graph(
        name="sdk/ambiguous",
        nodes=(
            GraphNode(id="panel_yes", body=Ref(component="sdk/panel-yes")),
            GraphNode(id="panel_no", body=Ref(component="sdk/panel-no")),
            GraphNode(id="panel_first", body=Ref(component="sdk/panel-first")),
        ),
        connections=(
            Connection(src="panel_yes", dst="panel_first"),
            Connection(src="panel_no", dst="panel_first"),
        ),
        inputs=panel_yes.definition.inputs,
        outputs=panel_first.definition.outputs,
    )
    with pytest.raises(AdmissionError, match=r"must be unique|ambiguity is an error"):
        system.validate(direct, {"request": {"question": "ship?"}})


@task("sdk/panel-other", output="verdict")
async def panel_other(
    request: Annotated[Ask, port_type("sdk/Ask")],
) -> Annotated[Tally, port_type("sdk/Tally")]:
    return Tally(approvals=0)


@task("sdk/panel-echo", output="vote")
async def panel_echo(
    request: Annotated[Vote, port_type("sdk/Vote")],
) -> Annotated[Vote, port_type("sdk/Vote")]:
    return request


@task("sdk/panel-tally-twice", output="tally")
async def panel_tally_twice(
    votes: list[Annotated[Vote, port_type("sdk/Vote")]],
    more: list[Annotated[Vote, port_type("sdk/Vote")]],
) -> Annotated[Tally, port_type("sdk/Tally")]:
    return Tally(approvals=0)


@task("sdk/panel-tally-seeded", output="tally")
async def panel_tally_seeded(
    votes: list[Annotated[Vote, port_type("sdk/Vote")]],
    seed: Annotated[Vote, port_type("sdk/Vote")],
) -> Annotated[Tally, port_type("sdk/Tally")]:
    return Tally(approvals=0)


@task("sdk/panel-tally-tallies", output="tally")
async def panel_tally_tallies(
    votes: list[Annotated[Tally, port_type("sdk/Tally")]],
    quorum: Annotated[Quorum, port_type("sdk/Quorum")],
) -> Annotated[Tally, port_type("sdk/Tally")]:
    return Tally(approvals=0)


@task("sdk/panel-tally-request", output="tally")
async def panel_tally_request(
    votes: list[Annotated[Vote, port_type("sdk/Vote")]],
    request: Annotated[Quorum, port_type("sdk/Quorum")],
) -> Annotated[Tally, port_type("sdk/Tally")]:
    return Tally(approvals=0)


def test_panel_refuses_what_would_be_gathered_wrongly_or_not_at_all() -> None:
    """Exactness is proved at authoring, from contracts a bare name cannot supply."""

    # A member of another contract would be gathered by nobody and be silently
    # absent from the result; it is refused instead.
    with pytest.raises(TypeError, match="share one exact request and result contract"):
        panel("sdk/mixed", panel_yes, panel_other, aggregator=panel_tally)

    # A `many` port of another contract would gather none of the members and
    # admit an empty panel.
    with pytest.raises(TypeError, match="but the members produce"):
        panel("sdk/deaf", panel_yes, aggregator=panel_tally_tallies)

    # A boundary input carrying the members' result contract sits in every
    # node's pool and would be gathered as a member — whether it is a policy
    # input of the aggregator or the members' own request.
    with pytest.raises(TypeError, match="would be gathered as a member"):
        panel("sdk/seeded", panel_yes, aggregator=panel_tally_seeded)
    with pytest.raises(TypeError, match="would be gathered as a member"):
        panel("sdk/echo", panel_echo, aggregator=panel_tally)

    # Shape refusals: no members, a member of the wrong arity, an aggregator
    # with two gathers, and an aggregator id that is also a member id.
    with pytest.raises(ValueError, match="at least one member"):
        panel("sdk/empty", aggregator=panel_tally)
    with pytest.raises(TypeError, match="exactly one input and one output"):
        panel("sdk/arity", panel_tally, aggregator=panel_tally)
    with pytest.raises(TypeError, match="exactly one many-cardinality input"):
        panel("sdk/twice", panel_yes, aggregator=panel_tally_twice)
    with pytest.raises(ValueError, match="collides with a member id"):
        panel("sdk/ids", panel_yes, aggregator=panel_tally, ids=("panel_tally",))

    # The members' request and the aggregator's policy share a boundary name.
    with pytest.raises(TypeError, match="boundary port names collide"):
        panel("sdk/collide", panel_yes, aggregator=panel_tally_request)

    # A bare name carries no contract to prove anything from.
    with pytest.raises(TypeError, match="definition bundles"):
        panel("sdk/bare", "sdk/panel-yes", aggregator=panel_tally)  # type: ignore[arg-type]
