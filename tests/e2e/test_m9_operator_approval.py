"""Credential-free approval recovery across three actual worker processes."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any, NoReturn

from constructicon.api.control import ControlPlane
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.component import ComponentLineage
from constructicon.core.control import (
    APPROVE_SCOPE,
    OPERATE_SCOPE,
    READ_SCOPE,
    ApprovalCommandResult,
    AuthenticatedActor,
    ChannelMessagePage,
    ControlRejected,
    RunResultPreviewV2,
    RunSubmission,
    RunSummary,
)
from constructicon.core.effect import ApprovalRecord, ComponentProofSubject
from constructicon.core.envelope import ArtifactRef, utc_now
from constructicon.core.human import ApprovalRequestPayload
from constructicon.core.identity import Digest, json_value
from constructicon.core.run import RunStatus
from constructicon.substrate.channels.mailbox import MailboxChannel
from constructicon.substrate.executors.fake import FakeExecutor
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.e2e.m9_issuer import OPERATOR_CHANNEL, Issuer
from tests.e2e.m9_operator_approval import assemble_operator_approval

_GATE_PATH = ExecutionPath(scope=ScopePath(segments=("m9-operator-issue", "gate")))
_OPERATOR = AuthenticatedActor(
    actor_id="static:trial-operator",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, APPROVE_SCOPE}),
)
_RUNNER = AuthenticatedActor(
    actor_id="static:trial-runner",
    auth_method="static",
    scopes=frozenset({READ_SCOPE, OPERATE_SCOPE}),
)
_SUBJECT = ComponentProofSubject(
    component="trial/prompt",
    version=Digest("sha256:" + "a" * 64),
    baseline_version=Digest("sha256:" + "b" * 64),
)
_APPROVAL_KEY = "m9-trial-decision"
_LOST_RESPONSE = 73


class _EvidenceStub(Issuer):
    """Supply lineage only; keep the real issuance lease and journal authority."""

    def verify(self) -> ComponentLineage:
        return ComponentLineage(
            parent_version=self.subject.baseline_version, created_by_run=self.proposal
        )


def _issuer(journal: SqliteJournal) -> Issuer:
    def unexpected_manifest(_inputs: dict[str, Any]) -> NoReturn:
        raise AssertionError("the approval recovery fixture does not evaluate prompt evidence")

    return _EvidenceStub(
        journal=journal,
        approvals=journal,
        registry=journal,
        owner=_OPERATOR.actor_id,
        subject=_SUBJECT,
        seal=RunId("run-fixture-seal"),
        proposal=RunId("run-fixture-proposal"),
        projection=ArtifactRef(digest=_SUBJECT.version, media_type="application/json", size=0),
        pairs=(),
        executor=FakeExecutor({}),
        fixture=_SUBJECT.version,
        reverse_dependencies=lambda _component: [],
        current_manifest=unexpected_manifest,
    )


async def _wait_for(control: ControlPlane, run_id: RunId, expected: RunStatus) -> None:
    async with asyncio.timeout(15):
        while True:
            state = control.runs_status(_RUNNER, run_id)
            assert isinstance(state, RunSummary), state
            if state.status is expected:
                return
            assert state.status in {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.PARKED}, state
            await asyncio.sleep(0.02)


def _lose_response(probe: str) -> None:
    if probe == "runs_approve.after_domain_mutation":
        os._exit(_LOST_RESPONSE)


async def _worker(
    path: Path, phase: str, run_id: RunId | None = None, request_id: Digest | None = None
) -> dict[str, str | int]:
    # Recover the dead command's claim without sleeping out its normal TTL.
    journal = SqliteJournal(
        path, now_fn=(lambda: utc_now() + timedelta(hours=1)) if phase == "recover" else utc_now
    )
    control, mailbox, graph = assemble_operator_approval(
        journal,
        _issuer(journal),
        seed=phase == "park",
        fault_probe=_lose_response if phase == "approve" else None,
    )
    await control.startup()
    try:
        if phase == "park":
            inputs = {
                "request": ApprovalRequestPayload(
                    subject=json_value(_SUBJECT.model_dump(mode="json"))
                ).model_dump(mode="json")
            }
            submitted = await control.runs_start(
                _RUNNER, proposal=graph, inputs=inputs, idempotency_key="m9-trial-start"
            )
            assert isinstance(submitted, RunSubmission), submitted
            await _wait_for(control, submitted.run_id, RunStatus.PARKED)
            (wait,) = journal.parked_waits()
            (request_id,) = wait.requests
            assert wait.run_id == submitted.run_id
            inbox = control.channels_inbox(_OPERATOR)
            assert isinstance(inbox, ChannelMessagePage), inbox
            (request,) = inbox.items
            assert request.message_id == request_id
            assert request.run_id == wait.run_id and request.interaction == "approval"
            assert mailbox.reply_for(request_id) is None
            return {"pid": os.getpid(), "run": str(wait.run_id), "request": str(request_id)}

        assert run_id is not None and request_id is not None
        if phase == "approve":
            state = control.runs_status(_RUNNER, run_id)
            assert isinstance(state, RunSummary) and state.status is RunStatus.PARKED, state
            assert mailbox.reply_for(request_id) is None
            other = _OPERATOR.model_copy(update={"actor_id": "static:other-approver"})
            wrong_actor = await control.runs_approve(
                other, run_id=run_id, subject=_SUBJECT, decision="approved",
                reason="wrong recipient", idempotency_key="wrong-recipient",
                request_message_id=request_id,
            )
            assert isinstance(wrong_actor, ControlRejected)
            assert mailbox.reply_for(request_id) is None
        else:
            # Prove the fresh host observes the durable reply before replay can wake the run.
            reply = mailbox.reply_for(request_id)
            assert reply is not None
            await _wait_for(control, run_id, RunStatus.SUCCEEDED)

        result = await control.runs_approve(
            _OPERATOR,
            run_id=run_id,
            subject=_SUBJECT,
            decision="approved",
            reason="trial approval",
            idempotency_key=_APPROVAL_KEY,
            request_message_id=request_id,
        )
        assert phase == "recover", "approval returned before the expected process exit"
        assert isinstance(result, ApprovalCommandResult), result
        assert result.reply == reply.message_id
        replayed = await control.runs_approve(
            _OPERATOR,
            run_id=run_id,
            subject=_SUBJECT,
            decision="approved",
            reason="trial approval",
            idempotency_key=_APPROVAL_KEY,
            request_message_id=request_id,
        )
        assert isinstance(replayed, ApprovalCommandResult), replayed
        assert (
            replayed.command.replayed and replayed.command.command_id == result.command.command_id
        )
        assert (replayed.approval_id, replayed.reply) == (result.approval_id, result.reply)
        output = control.runs_result(_RUNNER, run_id)
        assert isinstance(output, RunResultPreviewV2), output
        gate = journal.checkpoint(run_id, _GATE_PATH)
        assert gate is not None
        decision = gate.outputs["decision"].payload
        assert isinstance(decision, dict)
        record = ApprovalRecord.model_validate(decision["approval"])
        proof_id = output.outputs["proof"]
        assert isinstance(proof_id, str)
        proof = journal.load_attestation(proof_id)
        assert proof is not None
        assert proof.created_by_run == run_id and proof.subject == _SUBJECT
        assert proof.manifest_hash == journal.run_manifest_hash(run_id)
        assert record.approval_id == result.approval_id
        assert record.run_id == run_id and record.subject == _SUBJECT
        assert record.actor == _OPERATOR and record.decision == "approved"
        events = [event.kind for event in journal.events(run_id, limit=100)]
        assert events.count("RunParked") == events.count("RunSucceeded") == 1
        return {"pid": os.getpid(), "approval": record.approval_id}
    finally:
        await control.shutdown()


def _process(path: Path, phase: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tests.e2e.test_m9_operator_approval", str(path), phase, *arguments],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_operator_approval_survives_a_lost_response_and_fresh_host(tmp_path: Path) -> None:
    database = tmp_path / "operator-trial.sqlite"
    parked = _process(database, "park")
    assert parked.returncode == 0, (parked.stdout, parked.stderr)
    parked_data = json.loads(parked.stdout)
    run, request = parked_data["run"], parked_data["request"]
    approved = _process(database, "approve", run, request)
    assert approved.returncode == _LOST_RESPONSE, (approved.stdout, approved.stderr)
    journal = SqliteJournal(database)
    record = journal.run_record(RunId(run))
    assert record is not None and record.status is RunStatus.PARKED
    assert (
        MailboxChannel(journal, channel_id=OPERATOR_CHANNEL).reply_for(Digest(request)) is not None
    )
    recovered = _process(database, "recover", run, request)
    assert recovered.returncode == 0, (recovered.stdout, recovered.stderr)
    recovered_data = json.loads(recovered.stdout)
    assert recovered_data["pid"] != parked_data["pid"]


if __name__ == "__main__":
    path, phase, *args = sys.argv[1:]
    identifiers = (RunId(args[0]), Digest(args[1])) if args else (None, None)
    print(json.dumps(asyncio.run(_worker(Path(path), phase, *identifiers))))
