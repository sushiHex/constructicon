"""The panel lane: fakes first, then one human across a restart, then approval.

A panel is `panel()` over ordinary members and the standard quorum aggregator.
Nothing here is a primitive: the request fans out through the graph boundary,
every member's report is gathered through one `many` port, and the human
member is the standard advisor followed by the standard ballot — the same
exchange PR C sealed, with the same authorship stamped.

A restart here is a real one: each round trip's answer is recorded by a child
interpreter that imports the components afresh over the same database file,
and nothing crosses the boundary but that file. Resumption after a reply is
the control plane's own: the mutation launches the woken attempt on its run
host, and the attempt records the reply that caused it.
"""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.address import ExecutionPath, RunId
from constructicon.core.control import ApprovalCommandResult, ChannelReplyResult
from constructicon.core.errors import ContractViolation
from constructicon.core.graph import Graph, Ref
from constructicon.core.human import ApprovalRequestPayload
from constructicon.core.identity import Digest, json_value
from constructicon.core.panel import PanelBallot, PanelMemberOutcome, PanelMemberResult, PanelResult
from constructicon.core.ports import Port
from constructicon.core.run import AttemptCause, RunStatus
from constructicon.runtime.context import NodeContext
from constructicon.sdk import flow, panel
from constructicon.sdk.std import (
    ADVICE_REQUEST,
    ADVISOR_COMPONENT,
    APPROVAL_CHANNEL,
    APPROVAL_COMPONENT,
    APPROVAL_DECISION,
    APPROVAL_REQUEST,
    PANEL_BALLOT_COMPONENT,
    PANEL_QUORUM_COMPONENT,
    PANEL_RESULT,
    PANEL_VOTE,
    definitions,
    human_panel_member,
)
from constructicon.sdk.types import DefinitionBundle
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.conftest import atomic
from tests.e2e.test_standard_human_components import (
    ADVICE_CHANNEL_ID,
    ADVISOR,
    ADVISOR_ID,
    APPROVER,
    GATE_CHANNEL_ID,
    SUBJECT,
    _world,
)

REQUEST = {"question": "does this ship? answer with a ballot: outcome, ballot, rationale"}


def _report(
    ctx: NodeContext,
    inputs: Mapping[str, Any],
    outcome: PanelMemberOutcome,
    ballot: PanelBallot | None = None,
) -> Mapping[str, Any]:
    """A member that reports one outcome as data, with no transport provenance."""

    vote = PanelMemberResult(
        run_id=ctx.run_id,
        member=ctx.path,
        outcome=outcome,
        ballot=ballot,
        rationale={"asked": inputs["request"]},
    )
    return {"vote": vote.model_dump(mode="json")}


# Atomic implementations must be cold-importable, so each fake is a named function.
async def panel_yes(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return _report(ctx, inputs, "responded", "approve")


async def panel_no(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return _report(ctx, inputs, "responded", "reject")


async def panel_shrug(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return _report(ctx, inputs, "responded", "abstain")


async def panel_declined(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return _report(ctx, inputs, "declined")


async def panel_away(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return _report(ctx, inputs, "unavailable")


async def panel_late(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    return _report(ctx, inputs, "timed_out")


async def panel_to_approval(ctx: NodeContext, inputs: Mapping[str, Any]) -> Mapping[str, Any]:
    """The panel concluded; ask the approver about the fixed subject — if it approved.

    Anything else fails the run here, so an approval request exists only
    because the panel's result said so.
    """

    result = PanelResult.model_validate(inputs["result"])
    if result.outcome != "approved":
        raise ContractViolation(f"the panel concluded {result.outcome!r}; nothing to approve")
    payload = ApprovalRequestPayload(subject=json_value(SUBJECT.model_dump(mode="json")))
    return {"request": payload.model_dump(mode="json")}


def _bundle(
    name: str, inputs: tuple[Port, ...], outputs: tuple[Port, ...], impl: Any
) -> DefinitionBundle:
    definition, implementation = atomic(name, inputs, outputs, impl)
    return DefinitionBundle(definition=definition, implementation=implementation)


def _member(name: str, impl: Any) -> DefinitionBundle:
    return _bundle(name, (ADVICE_REQUEST,), (PANEL_VOTE,), impl)


def _std(name: str) -> DefinitionBundle:
    return next(bundle for bundle in definitions() if bundle.name == name)


def _promote(system: Constructicon, *bundles: DefinitionBundle) -> None:
    for bundle in bundles:
        version = system._register(bundle.definition, bundle.implementation)
        system._promote_initial(component=bundle.name, version=version)


def _quorum_result(journal: SqliteJournal, run_id: RunId) -> PanelResult:
    """The aggregator's own checkpoint, wherever the panel sat in the run."""

    with sqlite3.connect(journal._db_path) as connection:
        keys = [
            row[0]
            for row in connection.execute(
                "SELECT path_key FROM checkpoints WHERE run_id = ?", (str(run_id),)
            )
        ]
    paths = [ExecutionPath.model_validate(json.loads(key)) for key in keys]
    quorum = [path for path in paths if path.scope.segments[-1] == "panel_quorum"]
    assert len(quorum) == 1, keys
    checkpoint = journal.checkpoint(run_id, quorum[0])
    assert checkpoint is not None
    result = PanelResult.model_validate(checkpoint.outputs["result"].payload)
    assert result.aggregator == quorum[0]
    return result


ATTEMPT_KINDS = frozenset({"RunStarted", "RunResumed", "RunReclaimed"})


def _attempts(journal: SqliteJournal, run_id: RunId) -> list[tuple[str, AttemptCause | None]]:
    """Every attempt the run made, in order, with the durable fact that caused it."""

    attempts: list[tuple[str, AttemptCause | None]] = []
    after = 0
    while True:
        page = journal.events(run_id, after_seq=after, limit=500)
        if not page:
            return attempts
        for event in page:
            if event.kind in ATTEMPT_KINDS:
                attempts.append((event.kind, AttemptCause.from_payload(event.payload)))
        after = page[-1].seq


async def _settles(journal: SqliteJournal, run_id: RunId, *, status: RunStatus) -> None:
    """Wait for the host's own attempt to leave the run in ``status``."""

    deadline = time.monotonic() + 10.0
    while True:
        record = journal.run_record(run_id)
        if record is not None and record.status is status:
            return
        assert time.monotonic() < deadline, f"the run never reached {status.value}"
        await asyncio.sleep(0.01)


async def _parks_anew(journal: SqliteJournal, run_id: RunId, *, after: Digest) -> Digest:
    """Wait for the host's own attempt to park the run at a request other than ``after``."""

    deadline = time.monotonic() + 10.0
    while True:
        requests = [
            request
            for wait in journal.parked_waits()
            if wait.run_id == run_id
            for request in wait.requests
            if request != after
        ]
        if requests:
            assert len(requests) == 1, requests
            return requests[0]
        assert time.monotonic() < deadline, "the run never parked again"
        await asyncio.sleep(0.01)


def _counts(database: Path) -> tuple[int, int, int, int]:
    with sqlite3.connect(database) as connection:
        requests, replies = connection.execute(
            "SELECT SUM(kind = 'request'), SUM(kind = 'reply') FROM channel_messages"
        ).fetchone()
        acks = connection.execute("SELECT COUNT(*) FROM channel_acks").fetchone()[0]
        approvals = connection.execute("SELECT COUNT(*) FROM approvals").fetchone()[0]
    return requests, replies, acks, approvals


FAKES = (
    _member("test/panel-yes", panel_yes),
    _member("test/panel-no", panel_no),
    _member("test/panel-shrug", panel_shrug),
    _member("test/panel-declined", panel_declined),
    _member("test/panel-away", panel_away),
    _member("test/panel-late", panel_late),
)
TO_APPROVAL = _bundle(
    "test/panel-to-approval", (PANEL_RESULT,), (APPROVAL_REQUEST,), panel_to_approval
)
ALICE = human_panel_member("test/human-alice", ADVICE_CHANNEL_ID)
REVIEW = panel("test/review-panel", FAKES[0], ALICE, aggregator=_std(PANEL_QUORUM_COMPONENT))
LANE = flow(
    "test/panel-lane",
    REVIEW,
    TO_APPROVAL,
    Ref(component=APPROVAL_COMPONENT, bind={APPROVAL_CHANNEL: GATE_CHANNEL_ID}),
    ids=("panel", "to_approval", "approval"),
    outputs=(APPROVAL_DECISION,),
)
LANE_INPUTS = {"request": REQUEST, "quorum": {"required_approvals": 2}}


def _assemble(store: SqliteJournal) -> Constructicon:
    """What every process imports: the same definitions, promoted the same way."""

    system, _advice, _gate = _world(store)
    _promote(system, FAKES[0], ALICE, REVIEW, TO_APPROVAL, LANE)
    return system


async def _ask(system: Constructicon, journal: SqliteJournal, run_id: RunId) -> Digest:
    """Start the lane and park it at the human's ballot request."""

    manifest = system.validate(LANE.definition.body, LANE_INPUTS)
    system._prepare_run(manifest, run_id=run_id, inputs=LANE_INPUTS)
    assert (await system._run_prepared(run_id, cancellation="abandon")).status is RunStatus.PARKED
    (wait,) = journal.parked_waits()
    (request,) = wait.requests
    return request


async def test_every_declared_member_reaches_the_aggregate(journal: SqliteJournal) -> None:
    """All four outcomes are data, and none is dropped on the way to the result."""

    system, _advice, _gate = _world(journal)
    _promote(system, *FAKES)
    review = panel("test/fake-panel", *FAKES, aggregator=_std(PANEL_QUORUM_COMPONENT))
    _promote(system, review)

    for required, expected in ((1, "approved"), (2, "rejected"), (7, "impossible_quorum")):
        run_id = RunId(f"run-panel-fakes-{required}")
        inputs = {"request": REQUEST, "quorum": {"required_approvals": required}}
        manifest = system.validate(review.definition.body, inputs)
        system._prepare_run(manifest, run_id=run_id, inputs=inputs)
        outcome = await system._run_prepared(run_id, cancellation="abandon")
        assert outcome.status is RunStatus.SUCCEEDED
        result = PanelResult.model_validate(system.materialize_run(run_id)["result"])
        assert result.outcome == expected
        assert [summary.node for summary in result.members] == [
            "panel_away",
            "panel_declined",
            "panel_late",
            "panel_no",
            "panel_shrug",
            "panel_yes",
        ]
        assert result.tally.model_dump() == {
            "approve": 1,
            "reject": 1,
            "abstain": 1,
            "declined": 1,
            "unavailable": 1,
            "timed_out": 1,
        }
        # A fake reports no transport provenance, and says so.
        assert all(summary.result.actor_id is None for summary in result.members)


HUMAN_RUN = RunId("run-panel-human")
REPO_ROOT = Path(__file__).parents[2]


async def _stage_reply(database: Path) -> None:
    """A fresh process: import the components, record Alice's ballot, let the host wake the run."""

    journal = SqliteJournal(database)
    control = ControlPlane(system=_assemble(journal), store=journal)
    (wait,) = journal.parked_waits()
    (ballot_request,) = wait.requests
    replied = await control.channels_reply(
        ADVISOR,
        message_id=ballot_request,
        payload={"outcome": "responded", "ballot": "approve", "rationale": "looks right"},
        idempotency_key="alice-ballot",
    )
    assert isinstance(replied, ChannelReplyResult)
    await _parks_anew(journal, HUMAN_RUN, after=ballot_request)
    await control.shutdown()


async def _stage_approve(database: Path) -> None:
    """A fresh process: import the components, record the approval, let the host finish the run."""

    journal = SqliteJournal(database)
    control = ControlPlane(system=_assemble(journal), store=journal)
    (wait,) = journal.parked_waits()
    (approval_request,) = wait.requests
    decided = await control.runs_approve(
        APPROVER,
        run_id=HUMAN_RUN,
        subject=SUBJECT,
        decision="approved",
        reason="the panel approved",
        idempotency_key="panel-approval",
        request_message_id=approval_request,
    )
    assert isinstance(decided, ApprovalCommandResult)
    assert decided.reply is not None
    await _settles(journal, HUMAN_RUN, status=RunStatus.SUCCEEDED)
    await control.shutdown()


_STAGES = {"reply": _stage_reply, "approve": _stage_approve}


def _child(stage: str, database: str) -> None:
    """Entry point of a child process: one stage of the lane, nothing carried over."""

    asyncio.run(_STAGES[stage](Path(database)))


def _in_a_fresh_process(stage: str, database: Path) -> None:
    """Run one stage in a new interpreter over the same database file."""

    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            f"from tests.e2e.test_panel import _child; _child({stage!r}, {str(database)!r})",
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr[-4000:]


async def test_a_human_member_votes_across_a_real_process_restart_and_the_panel_reaches_approval(
    tmp_path: Path,
) -> None:
    """Two round trips, each across a real process restart, credential-free.

    The process that asks does nothing more once the run is parked. A child
    process imports the components, records the ballot, and its own
    control-plane host wakes the run to conclude the panel; a third records the
    approval the same way. No application state crosses a boundary except
    through the database file. One request, reply, acknowledgement, and wake
    per round trip, one approval.
    """

    database = tmp_path / "panel.db"
    first = SqliteJournal(database)
    ballot_request = await _ask(_assemble(first), first, HUMAN_RUN)
    del first

    _in_a_fresh_process("reply", database)

    second = SqliteJournal(database)
    concluded = _quorum_result(second, HUMAN_RUN)
    assert concluded.outcome == "approved"
    assert [summary.node for summary in concluded.members] == ["human_alice", "panel_yes"]
    human = concluded.members[0].result
    assert human.actor_id == ADVISOR_ID
    assert human.ballot == "approve"
    assert human.message_id is not None
    assert concluded.members[1].result.actor_id is None
    (wait,) = second.parked_waits()
    (approval_request,) = wait.requests
    assert approval_request != ballot_request
    del second

    _in_a_fresh_process("approve", database)

    third = SqliteJournal(database)
    world = _assemble(third)
    record = world.materialize_run(HUMAN_RUN)["decision"]["approval"]
    assert record["run_id"] == str(HUMAN_RUN)
    approval_ids = [
        row[0] for row in sqlite3.connect(database).execute("SELECT approval_id FROM approvals")
    ]
    assert approval_ids == [record["approval_id"]]

    # Three attempts and no more: the start in the first process, and one
    # resumption per reply, each caused by exactly the durable reply to that
    # round trip's request — and the vote's copied message id is that reply.
    replies = third.answered_requests([ballot_request, approval_request])
    assert set(replies) == {ballot_request, approval_request}
    assert human.message_id == replies[ballot_request]
    assert _attempts(third, HUMAN_RUN) == [
        ("RunStarted", None),
        ("RunResumed", AttemptCause(kind="channel_reply", id=str(replies[ballot_request]))),
        ("RunResumed", AttemptCause(kind="channel_reply", id=str(replies[approval_request]))),
    ]
    assert _counts(database) == (2, 2, 2, 1)


async def test_a_panel_that_does_not_approve_never_reaches_the_approver(tmp_path: Path) -> None:
    """The approval request exists only because the panel's result said so."""

    database = tmp_path / "panel-rejects.db"
    run_id = RunId("run-panel-human-rejects")
    journal = SqliteJournal(database)
    world = _assemble(journal)
    ballot_request = await _ask(world, journal, run_id)

    control = ControlPlane(system=world, store=journal)
    replied = await control.channels_reply(
        ADVISOR,
        message_id=ballot_request,
        payload={"outcome": "responded", "ballot": "reject"},
        idempotency_key="alice-rejects",
    )
    assert isinstance(replied, ChannelReplyResult)
    await _settles(journal, run_id, status=RunStatus.FAILED)
    await control.shutdown()

    concluded = _quorum_result(journal, run_id)
    assert concluded.outcome == "rejected"
    assert concluded.tally.model_dump() == {
        "approve": 1,
        "reject": 1,
        "abstain": 0,
        "declined": 0,
        "unavailable": 0,
        "timed_out": 0,
    }
    assert _attempts(journal, run_id) == [
        ("RunStarted", None),
        ("RunResumed", AttemptCause(kind="channel_reply", id=str(replied.message_id))),
    ]
    assert journal.parked_waits() == []
    assert _counts(database) == (1, 1, 1, 0)


def test_the_human_member_is_the_advisor_then_the_ballot() -> None:
    """Composition, not a new exchange: the same sealed pair PR C stamps."""

    body = ALICE.definition.body
    assert isinstance(body, Graph)
    assert [node.id for node in body.nodes] == ["advisor", "ballot"]
    advisor, ballot = (node.body for node in body.nodes)
    assert isinstance(advisor, Ref) and isinstance(ballot, Ref)
    assert advisor.component == ADVISOR_COMPONENT
    assert advisor.bind == {"advisor": ADVICE_CHANNEL_ID}
    assert ballot.component == PANEL_BALLOT_COMPONENT
    assert ballot.bind == {}
    assert ALICE.definition.capability_requirements is None  # bound inside, as composites are
    assert ALICE.implementation is None
