"""The panel contracts: what a member reports, and what a panel concludes (M7).

A panel is a Graph pattern, not a primitive: one request fans out to members
and every member's result is gathered by one explicit aggregator through an
ordinary ``many`` port. These are the nominal contracts that pattern speaks,
kept at L0 so the SDK sugar, the standard components, and any adapter a
workflow writes all type the same exchange.

Every outcome here is data a member reported. M7 owns no clock: ``unavailable``
and ``timed_out`` are what a member or a policy component *says*, never what
the kernel infers from elapsed time. A human who does not answer keeps the run
parked; one who will not answer replies ``declined``.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, NonNegativeInt, PositiveInt, model_validator

from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.channel import ChannelContract
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import ActorId, Digest, JsonValue, canonical_json

PanelMemberOutcome = Literal["responded", "declined", "unavailable", "timed_out"]
PanelBallot = Literal["approve", "reject", "abstain"]
PanelOutcome = Literal["approved", "rejected", "insufficient_responses", "impossible_quorum"]

PANEL_MEMBER_RESULT_CONTRACT = ChannelContract(
    type_id="constructicon.std/PanelMemberResult",
    schema_hash="panel-member-result-1",
)
PANEL_QUORUM_CONTRACT = ChannelContract(
    type_id="constructicon.std/PanelQuorum",
    schema_hash="panel-quorum-1",
)
PANEL_RESULT_CONTRACT = ChannelContract(
    type_id="constructicon.std/PanelResult",
    schema_hash="panel-result-1",
)


class _PanelModel(BaseModel):
    """Validated out of stored JSON, so not ``strict``; nothing extra admitted."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PanelBallotPayload(_PanelModel):
    """What a human writes inside an advice reply to cast a vote.

    Strict on purpose: an ``actor_id`` a human writes in here is not a claim
    the panel repeats, it is an unknown field and the ballot is malformed.
    Authorship comes from the outer, executor-stamped reply (ADR 0015).
    """

    schema_version: Literal[1] = 1
    outcome: Literal["responded", "declined"]
    ballot: PanelBallot | None = None
    rationale: JsonValue | None = None

    @model_validator(mode="after")
    def _ballot_iff_responded(self) -> PanelBallotPayload:
        if (self.outcome == "responded") != (self.ballot is not None):
            raise ValueError("a responded ballot names a vote; a declined one names none")
        return self


class PanelMemberResult(_PanelModel):
    """One member's report: who sat where, what they said, and how it arrived.

    ``member`` is the path the member reports for itself. It is the genuine
    invocation path the walker handed that component, but the payload is the
    component's to write and the kernel does not stamp provenance into
    payloads, so it is checked for shape by the aggregator, not attested by the
    kernel. ``actor_id`` and ``message_id`` are copied by the standard ballot
    adapter from the executor-stamped reply and let a vote be followed back to
    its durable channel fact; a fake reports neither. In this payload they are
    telemetry: any component may write them, and a consumer that needs them as
    provenance follows ``message_id`` to the sealed reply rather than trusting
    the copy. ``rationale`` is the member's free text and asserts nothing.
    """

    schema_version: Literal[1] = 1
    run_id: RunId
    member: ExecutionPath
    outcome: PanelMemberOutcome
    ballot: PanelBallot | None = None
    rationale: JsonValue | None = None
    actor_id: ActorId | None = None
    message_id: Digest | None = None

    @model_validator(mode="after")
    def _ballot_iff_responded(self) -> PanelMemberResult:
        if (self.outcome == "responded") != (self.ballot is not None):
            raise ValueError("a responded member names a ballot; any other outcome names none")
        return self


class PanelQuorum(_PanelModel):
    """The one policy input: how many approvals a panel needs.

    Ordinary typed input, never a combinator default. A quorum the member count
    cannot meet is reported as such rather than counted as a rejection.
    """

    schema_version: Literal[1] = 1
    required_approvals: PositiveInt


class PanelTally(_PanelModel):
    """Every member counted exactly once, by what they reported."""

    approve: NonNegativeInt = 0
    reject: NonNegativeInt = 0
    abstain: NonNegativeInt = 0
    declined: NonNegativeInt = 0
    unavailable: NonNegativeInt = 0
    timed_out: NonNegativeInt = 0

    @property
    def responded(self) -> int:
        return self.approve + self.reject + self.abstain

    @property
    def members(self) -> int:
        return self.responded + self.declined + self.unavailable + self.timed_out


class PanelMemberSummary(_PanelModel):
    node: str
    result: PanelMemberResult


class PanelResult(_PanelModel):
    """What the panel concluded, and every member it concluded it from.

    The outcome is total and says what happened. ``rejected`` means enough
    members answered to have approved and they did not; a shortfall of answers
    is ``insufficient_responses``, and a policy no member count could meet is
    ``impossible_quorum``. Nothing is dropped: a member who declined, was
    unavailable, or timed out is in ``members`` with that outcome.

    Self-verifying. The result names the aggregator and run it was concluded
    for, and validation re-derives the members' placement, the tally, and the
    outcome from the members themselves: a stored or foreign result whose
    conclusion contradicts its members is refused (I4). Any aggregator sharing
    this contract is held to the same law as the standard one.
    """

    schema_version: Literal[1] = 1
    run_id: RunId
    aggregator: ExecutionPath
    quorum: PanelQuorum
    outcome: PanelOutcome
    tally: PanelTally
    members: tuple[PanelMemberSummary, ...]

    @model_validator(mode="after")
    def _concluded_from_its_members(self) -> PanelResult:
        try:
            placed = _place(
                tuple(summary.result for summary in self.members),
                aggregator=self.aggregator,
                run_id=self.run_id,
            )
        except ContractViolation as exc:
            raise ValueError(str(exc)) from exc
        tally = _tally(placed)
        if (self.members, self.tally, self.outcome) != (
            placed,
            tally,
            panel_outcome(tally, self.quorum),
        ):
            raise ValueError("panel result contradicts the members it names")
        return self


def panel_outcome(tally: PanelTally, quorum: PanelQuorum) -> PanelOutcome:
    """The deterministic policy, stated once."""

    if quorum.required_approvals > tally.members:
        return "impossible_quorum"
    if tally.approve >= quorum.required_approvals:
        return "approved"
    if tally.responded < quorum.required_approvals:
        return "insufficient_responses"
    return "rejected"


def _member_key(result: PanelMemberResult) -> str:
    # The complete structural path, canonically encoded. `render()` is not
    # injective — ("x/y",) and ("x", "y") render alike — so it is not an order.
    return canonical_json(result.member.model_dump(mode="json"))


def _place(
    votes: tuple[PanelMemberResult, ...],
    *,
    aggregator: ExecutionPath,
    run_id: RunId,
) -> tuple[PanelMemberSummary, ...]:
    """Seat every member by its reported path, in one canonical order.

    Members are the aggregator's siblings by ``panel()`` construction, so each
    result's path must begin with the aggregator's parent scope, have a segment
    at that depth — that segment is the member's node — and sit in the same
    loop iteration. Any other topology is refused rather than guessed at, and
    so is a node claimed twice — whether by one path repeated or by two paths
    beneath it: a member that reports a sibling's identity collides with the
    sibling instead of replacing it. The walker delivers one payload per sealed
    source, so the count is the kernel's; what a member can misreport is only
    its own name, and a misreported name that is nobody else's is a lie about
    itself, not a second vote.
    """

    scope = aggregator.scope.segments
    if not scope:
        raise ContractViolation("a panel aggregator has a scope; the root is not one")
    parent = scope[:-1]
    depth = len(parent)
    summaries: list[PanelMemberSummary] = []
    seen: set[str] = set()
    for result in sorted(votes, key=_member_key):
        if result.run_id != run_id:
            raise ContractViolation(
                f"panel member {result.member.render()} reports run {result.run_id!r}, "
                f"not {run_id!r}"
            )
        segments = result.member.scope.segments
        if (
            segments[:depth] != parent
            or len(segments) <= depth
            or result.member.iterations != aggregator.iterations
        ):
            raise ContractViolation(
                f"panel member {result.member.render()} is not a sibling of the "
                f"aggregator at {aggregator.render()}"
            )
        node = segments[depth]
        if node in seen:
            raise ContractViolation(f"panel member {node!r} reported more than one result")
        seen.add(node)
        summaries.append(PanelMemberSummary(node=node, result=result))
    return tuple(summaries)


def _tally(members: tuple[PanelMemberSummary, ...]) -> PanelTally:
    counts = {
        "approve": 0,
        "reject": 0,
        "abstain": 0,
        "declined": 0,
        "unavailable": 0,
        "timed_out": 0,
    }
    for summary in members:
        result = summary.result
        # A responded member names its ballot and nothing else names one, so
        # the bucket is the ballot when there is one and the outcome otherwise.
        counts[result.ballot or result.outcome] += 1
    return PanelTally(**counts)


def aggregate_panel(
    votes: tuple[PanelMemberResult, ...],
    quorum: PanelQuorum,
    *,
    aggregator: ExecutionPath,
    run_id: RunId,
) -> PanelResult:
    """Conclude a panel from its members' reports; ``aggregator`` is the caller's own path."""

    members = _place(votes, aggregator=aggregator, run_id=run_id)
    tally = _tally(members)
    return PanelResult(
        run_id=run_id,
        aggregator=aggregator,
        quorum=quorum,
        outcome=panel_outcome(tally, quorum),
        tally=tally,
        members=members,
    )


__all__ = [
    "PANEL_MEMBER_RESULT_CONTRACT",
    "PANEL_QUORUM_CONTRACT",
    "PANEL_RESULT_CONTRACT",
    "PanelBallot",
    "PanelBallotPayload",
    "PanelMemberOutcome",
    "PanelMemberResult",
    "PanelMemberSummary",
    "PanelOutcome",
    "PanelQuorum",
    "PanelResult",
    "PanelTally",
    "aggregate_panel",
    "panel_outcome",
]
