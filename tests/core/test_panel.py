"""The panel aggregation law: total, deterministic, and honest about topology.

Every member is counted exactly once by what it reported. The outcome names
what happened rather than folding every shortfall into "rejected". Members are
placed by their reported path against the aggregator's own path, and a path
the panel's shape cannot account for is refused, not guessed at.
"""

from __future__ import annotations

import random

import pytest
from pydantic import ValidationError

from constructicon.core.address import ExecutionPath, IterationFrame, RunId, ScopePath
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import canonical_json
from constructicon.core.panel import (
    CONTRACT_SCHEMAS,
    PANEL_BALLOT_CONTRACT,
    PanelBallot,
    PanelBallotPayload,
    PanelMemberOutcome,
    PanelMemberResult,
    PanelQuorum,
    PanelResult,
    PanelTally,
    aggregate_panel,
    panel_outcome,
)

RUN = RunId("run-panel-law")
PANEL = ("review", "panel")
AGGREGATOR = ExecutionPath(scope=ScopePath(segments=(*PANEL, "quorum")))
FRAME = IterationFrame(loop=ScopePath(segments=("review",)), index=2)


def _member(
    node: str,
    outcome: PanelMemberOutcome,
    ballot: PanelBallot | None = None,
    *,
    below: tuple[str, ...] = (),
    run_id: RunId = RUN,
    iterations: tuple[IterationFrame, ...] = (),
) -> PanelMemberResult:
    return PanelMemberResult(
        run_id=run_id,
        member=ExecutionPath(
            scope=ScopePath(segments=(*PANEL, node, *below)),
            iterations=iterations,
        ),
        outcome=outcome,
        ballot=ballot,
    )


def _tally(**counts: int) -> PanelTally:
    return PanelTally(**counts)


@pytest.mark.parametrize(
    ("tally", "required", "expected"),
    [
        (_tally(approve=2, reject=1), 2, "approved"),
        (_tally(approve=1, reject=2), 2, "rejected"),
        (_tally(approve=1, abstain=2), 2, "rejected"),
        (_tally(approve=1, reject=1), 2, "rejected"),
        (_tally(approve=1, declined=2), 2, "insufficient_responses"),
        (_tally(timed_out=3), 2, "insufficient_responses"),
        (_tally(approve=3), 4, "impossible_quorum"),
        (_tally(), 1, "impossible_quorum"),
    ],
)
def test_the_outcome_says_what_happened(
    tally: PanelTally,
    required: int,
    expected: str,
) -> None:
    """Rejected means enough members answered to have approved, and did not."""

    assert panel_outcome(tally, PanelQuorum(required_approvals=required)) == expected


def test_every_member_appears_once_by_node_in_one_canonical_order() -> None:
    members = [
        _member("alice", "responded", "approve"),
        _member("bob", "responded", "reject"),
        _member("carol", "declined"),
        _member("dave", "unavailable"),
        _member("erin", "timed_out"),
    ]
    quorum = PanelQuorum(required_approvals=1)
    baseline = aggregate_panel(tuple(members), quorum, aggregator=AGGREGATOR, run_id=RUN)
    assert [summary.node for summary in baseline.members] == [
        "alice",
        "bob",
        "carol",
        "dave",
        "erin",
    ]
    assert baseline.tally == _tally(approve=1, reject=1, declined=1, unavailable=1, timed_out=1)
    assert baseline.tally.members == 5
    assert baseline.outcome == "approved"

    # The walker hands the aggregator sealed source order; the conclusion must
    # not depend on it.
    shuffled = list(members)
    for seed in range(8):
        random.Random(seed).shuffle(shuffled)
        again = aggregate_panel(tuple(shuffled), quorum, aggregator=AGGREGATOR, run_id=RUN)
        assert canonical_json(again.model_dump(mode="json")) == canonical_json(
            baseline.model_dump(mode="json")
        )


def test_a_composite_member_reports_from_beneath_its_node() -> None:
    """A human member is advisor-then-ballot; the ballot's path sits under the node."""

    result = aggregate_panel(
        (_member("human", "responded", "approve", below=("ballot",)),),
        PanelQuorum(required_approvals=1),
        aggregator=AGGREGATOR,
        run_id=RUN,
    )
    assert [summary.node for summary in result.members] == ["human"]


def test_a_member_outside_the_aggregators_siblings_is_refused() -> None:
    """The derivation is defined for the shape `panel()` emits, and says so."""

    elsewhere = PanelMemberResult(
        run_id=RUN,
        member=ExecutionPath(scope=ScopePath(segments=("other", "graph", "node"))),
        outcome="declined",
    )
    with pytest.raises(ContractViolation, match="not a sibling"):
        aggregate_panel(
            (elsewhere,),
            PanelQuorum(required_approvals=1),
            aggregator=AGGREGATOR,
            run_id=RUN,
        )
    # Too shallow to have a node at the member depth.
    shallow = PanelMemberResult(
        run_id=RUN,
        member=ExecutionPath(scope=ScopePath(segments=PANEL)),
        outcome="declined",
    )
    with pytest.raises(ContractViolation, match="not a sibling"):
        aggregate_panel(
            (shallow,),
            PanelQuorum(required_approvals=1),
            aggregator=AGGREGATOR,
            run_id=RUN,
        )


def test_a_member_claiming_a_siblings_identity_collides_with_it() -> None:
    """Identity is member-reported, so a second claim is a contradiction, not a swap."""

    honest = _member("bob", "responded", "reject")
    forged = _member("bob", "responded", "approve")
    with pytest.raises(ContractViolation, match="more than one result"):
        aggregate_panel(
            (honest, forged),
            PanelQuorum(required_approvals=1),
            aggregator=AGGREGATOR,
            run_id=RUN,
        )
    # Two distinct paths under one node are the same node twice.
    with pytest.raises(ContractViolation, match="more than one result"):
        aggregate_panel(
            (honest, _member("bob", "declined", below=("ballot",))),
            PanelQuorum(required_approvals=1),
            aggregator=AGGREGATOR,
            run_id=RUN,
        )


def test_a_member_cannot_claim_the_aggregators_own_seat() -> None:
    """The aggregator is not a member; a report from its seat is a lie about the shape."""

    for below in ((), ("deeper",)):
        with pytest.raises(ContractViolation, match="aggregator's own seat"):
            aggregate_panel(
                (_member("quorum", "responded", "approve", below=below),),
                PanelQuorum(required_approvals=1),
                aggregator=AGGREGATOR,
                run_id=RUN,
            )


def test_every_named_panel_contract_publishes_its_shape() -> None:
    """A participant can discover the ballot without reading source (I9)."""

    ballot = CONTRACT_SCHEMAS[PANEL_BALLOT_CONTRACT]
    assert set(ballot["properties"]) == {"schema_version", "outcome", "ballot", "rationale"}
    assert ballot["additionalProperties"] is False
    assert {contract.schema_hash for contract in CONTRACT_SCHEMAS} == {
        "panel-ballot-1",
        "panel-member-result-1",
        "panel-quorum-1",
        "panel-result-1",
    }


def test_a_member_sits_in_the_aggregators_own_iteration() -> None:
    """Inside a loop, siblings share the frame; a member reporting another is not one."""

    in_loop = ExecutionPath(scope=AGGREGATOR.scope, iterations=(FRAME,))
    result = aggregate_panel(
        (_member("alice", "responded", "approve", iterations=(FRAME,)),),
        PanelQuorum(required_approvals=1),
        aggregator=in_loop,
        run_id=RUN,
    )
    assert result.outcome == "approved"
    with pytest.raises(ContractViolation, match="not a sibling"):
        aggregate_panel(
            (_member("alice", "responded", "approve"),),
            PanelQuorum(required_approvals=1),
            aggregator=in_loop,
            run_id=RUN,
        )
    with pytest.raises(ContractViolation, match="not a sibling"):
        aggregate_panel(
            (_member("alice", "responded", "approve", iterations=(FRAME,)),),
            PanelQuorum(required_approvals=1),
            aggregator=AGGREGATOR,
            run_id=RUN,
        )


def test_a_member_from_another_run_is_refused() -> None:
    with pytest.raises(ContractViolation, match="reports run"):
        aggregate_panel(
            (_member("alice", "declined", run_id=RunId("run-other")),),
            PanelQuorum(required_approvals=1),
            aggregator=AGGREGATOR,
            run_id=RUN,
        )


def test_order_is_the_structural_path_not_its_rendering() -> None:
    """('x/y',) and ('x', 'y') render alike; they are different places."""

    joined = PanelMemberResult(
        run_id=RUN,
        member=ExecutionPath(scope=ScopePath(segments=(*PANEL, "x/y"))),
        outcome="declined",
    )
    split = PanelMemberResult(
        run_id=RUN,
        member=ExecutionPath(scope=ScopePath(segments=(*PANEL, "x", "y"))),
        outcome="declined",
    )
    assert joined.member.render() == split.member.render()
    result = aggregate_panel(
        (joined, split),
        PanelQuorum(required_approvals=1),
        aggregator=AGGREGATOR,
        run_id=RUN,
    )
    assert [summary.node for summary in result.members] == ["x", "x/y"]


def test_a_result_that_contradicts_its_members_is_refused() -> None:
    """A stored or foreign result is re-derived from its members on the way in (I4)."""

    concluded = aggregate_panel(
        (_member("alice", "responded", "approve"), _member("bob", "declined")),
        PanelQuorum(required_approvals=1),
        aggregator=AGGREGATOR,
        run_id=RUN,
    )
    stored = concluded.model_dump(mode="json")
    assert PanelResult.model_validate(stored) == concluded
    alice, bob = stored["members"]
    elsewhere = ExecutionPath(scope=ScopePath(segments=("other", "graph", "quorum")))
    contradictions = (
        {"outcome": "rejected"},
        {"tally": {**stored["tally"], "approve": 2}},
        {"tally": {**stored["tally"], "declined": 0}},
        {"members": [bob, alice]},
        {"members": [alice, alice]},
        {"members": [{**alice, "node": "mallory"}, bob]},
        {"members": [alice]},
        {"quorum": {"required_approvals": 3}},
        {"aggregator": elsewhere.model_dump(mode="json")},
        {"run_id": "run-other"},
    )
    for contradiction in contradictions:
        with pytest.raises(ValidationError):
            PanelResult.model_validate({**stored, **contradiction})


def test_a_ballot_is_named_exactly_when_a_member_responded() -> None:
    with pytest.raises(ValidationError):
        _member("alice", "responded")
    with pytest.raises(ValidationError):
        _member("alice", "declined", "approve")
    with pytest.raises(ValidationError):
        PanelBallotPayload(outcome="responded")
    with pytest.raises(ValidationError):
        PanelBallotPayload(outcome="declined", ballot="approve")


def test_a_ballot_payload_admits_no_claim_about_its_author() -> None:
    """An actor written inside the answer is an unknown field, not a claim."""

    with pytest.raises(ValidationError):
        PanelBallotPayload.model_validate(
            {"outcome": "responded", "ballot": "approve", "actor_id": "static:forged"}
        )
