"""Run the fixed M9 rehearsal locally: python -m tests.e2e.m9_operator_trial."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from constructicon.api.control import ControlPlane
from constructicon.api.system import Constructicon
from constructicon.core.control import (
    ApprovalCommandResult,
    PromotionCommandResult,
    RunSubmission,
    command_id_for,
)
from constructicon.core.effect import ComponentProofSubject
from constructicon.core.human import ApprovalRequestPayload
from constructicon.core.identity import Digest, json_value
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.e2e.m9_evidence import TrialIdentity
from tests.e2e.m9_fixture import TARGET, baseline, candidate, diagnostic_definition
from tests.e2e.m9_issuer import OPERATOR_ISSUER_PATH, load_manifest, operator_issuer_graph
from tests.e2e.m9_operator_approval import assemble_operator_approval
from tests.e2e.m9_operator_evaluator import OPERATOR, OWNER, PROMOTER, Evaluator


def _open(root: Path, trial: TrialIdentity, *, initialize: bool) -> SqliteJournal:
    marker = root / "trial-id"
    identity = f"m9-v1:{trial.trial_id}\n".encode()
    if initialize:
        try:
            root.mkdir()
        except FileExistsError:
            pass
        else:
            with marker.open("xb") as file:
                file.write(identity)
    if not marker.is_file() or marker.read_bytes() != identity:
        raise ValueError("Use a fresh directory or the original trial key and directory")
    database = root / "journal.sqlite"
    if not initialize and not database.is_file():
        raise ValueError("The original trial journal is missing")
    return SqliteJournal(database)


def _issuance(journal: SqliteJournal, trial: TrialIdentity) -> RunSubmission:
    command = journal.command(command_id_for(OPERATOR.actor_id, "runs_start", trial.key("issue")))
    if command is None or command.state != "committed":
        raise ValueError("No committed issuance submission for this trial")
    return RunSubmission.model_validate(command.response)


async def run(root: Path, trial: TrialIdentity, stage: str) -> dict[str, object]:
    journal = _open(root, trial, initialize=stage == "prepare")
    if stage in ("promote", "rollback"):
        return await _move(journal, trial, stage)

    issue_command = journal.command(
        command_id_for(
            OPERATOR.actor_id,
            "runs_start",
            trial.key("issue"),
        )
    )
    if stage != "prepare" and (issue_command is None or issue_command.state != "committed"):
        raise ValueError("Prepare the trial before recording an owner decision")
    initialize = stage == "prepare" and issue_command is None
    evaluator = Evaluator.assemble(journal, initialize=initialize)
    issuer = await evaluator.prepare(trial, retained=issue_command is not None)
    control, _, graph = assemble_operator_approval(journal, issuer, seed=initialize)
    await control.startup()
    try:
        if stage == "prepare":
            request = ApprovalRequestPayload(
                subject=json_value(issuer.subject.model_dump(mode="json"))
            )
            result = await control.runs_start(
                OPERATOR,
                proposal=graph,
                inputs={"request": request.model_dump(mode="json")},
                idempotency_key=trial.key("issue"),
            )
            if not isinstance(result, RunSubmission):
                raise ValueError(f"Issuance refused: {result}")
            run_id = result.run_id
            async with asyncio.timeout(10):
                while True:
                    record = journal.run_record(run_id)
                    if record is None:
                        raise ValueError("Issuance lacks a durable record")
                    if record.status == RunStatus.PARKED:
                        break
                    if record.status not in (RunStatus.PENDING, RunStatus.RUNNING):
                        raise ValueError(f"Issuance no longer waiting: {record.status}")
                    await asyncio.sleep(0.01)
            (wait,) = (wait for wait in journal.parked_waits() if wait.run_id == run_id)
            (message,) = wait.requests
            return {
                "status": "awaiting-owner",
                "run": run_id,
                "request": message,
                "subject": issuer.subject.model_dump(mode="json"),
                "seal": issuer.seal,
                "exam": issuer.projection.digest,
            }

        submission = _issuance(journal, trial)
        run_id = submission.run_id
        key = trial.key("decision")
        prior = journal.command(command_id_for(OWNER.actor_id, "runs_approve", key))
        if prior is None:
            (wait,) = (wait for wait in journal.parked_waits() if wait.run_id == run_id)
            (message,) = wait.requests
        else:
            if not isinstance(prior.request, dict) or not isinstance(
                message_raw := prior.request.get("request_message_id"), str
            ):
                raise ValueError("Stored decision has no bound request")
            message = Digest(message_raw)
        decision = "approved" if stage == "approve" else "rejected"
        result = await control.runs_approve(
            OWNER,
            run_id=run_id,
            subject=issuer.subject,
            decision=decision,
            reason="Local trial owner decision",
            idempotency_key=key,
            request_message_id=message,
        )
        if not isinstance(result, ApprovalCommandResult):
            raise ValueError(f"Owner decision refused: {result}")
        if decision == "approved":
            await evaluator.succeeded(submission, resuming=True)
        else:
            async with asyncio.timeout(10):
                while True:
                    record = journal.run_record(run_id)
                    if record is not None and record.status == RunStatus.FAILED:
                        break
                    if record is None or record.status not in {
                        RunStatus.PARKED,
                        RunStatus.PENDING,
                        RunStatus.RUNNING,
                    }:
                        raise ValueError("Rejected issuance did not terminate as refused")
                    await asyncio.sleep(0.01)
            if journal.checkpoint(run_id, OPERATOR_ISSUER_PATH) is not None:
                raise ValueError("Rejected issuance produced a proof checkpoint")
        return {"status": decision, "run": run_id, "approval": result.approval_id}
    finally:
        await control.shutdown()


async def _move(
    journal: SqliteJournal,
    trial: TrialIdentity,
    stage: str,
) -> dict[str, object]:
    run_id = _issuance(journal, trial).run_id
    record = journal.run_record(run_id)
    checkpoint = journal.checkpoint(run_id, OPERATOR_ISSUER_PATH)
    if (
        record is None
        or record.status != RunStatus.SUCCEEDED
        or checkpoint is None
        or load_manifest(journal, run_id).source_graph != operator_issuer_graph()
    ):
        raise ValueError("Trial has no successful reviewed issuance")
    proof_id = checkpoint.outputs["proof"].payload
    proof = journal.load_attestation(proof_id)
    subject = ComponentProofSubject(
        component=TARGET,
        version=diagnostic_definition(candidate).content_hash(),
        baseline_version=diagnostic_definition(baseline).content_hash(),
    )
    if (
        proof is None
        or not proof.ok
        or proof.action != "promote"
        or proof.subject != subject
        or proof.created_by_run != run_id
        or proof.manifest_hash != record.manifest_hash
    ):
        raise ValueError("Trial proof does not match the successful issuance and exact edge")
    promotion = journal.command(
        command_id_for(
            PROMOTER.actor_id,
            "registry_promote",
            trial.key("promote"),
        )
    )
    if stage == "promote" and (
        promotion is None
        or (promotion.state == "prepared" and journal.promotion_for_attestation(proof_id) is None)
    ):
        await Evaluator.assemble(journal).prepare(trial, retained=True)
    control = ControlPlane(system=Constructicon(journal=journal), store=journal)
    try:
        if stage == "promote":
            result = await control.registry_promote(
                PROMOTER,
                component=TARGET,
                version=subject.version,
                attestation_id=proof_id,
                idempotency_key=trial.key("promote"),
            )
            expected = ("promoted", subject.baseline_version, subject.version)
        else:
            if promotion is None or promotion.state != "committed":
                raise ValueError("Trial has no committed promotion to roll back")
            result = await control.registry_rollback(
                PROMOTER,
                component=TARGET,
                expected_stable=subject.version,
                idempotency_key=trial.key("rollback"),
            )
            expected = ("rolled_back", subject.version, subject.baseline_version)
        if (
            not isinstance(result, PromotionCommandResult)
            or (result.status, result.from_version, result.to_version) != expected
        ):
            raise ValueError(f"Trial {stage} did not return the expected exact edge: {result}")
        return {
            "status": result.status,
            "from": result.from_version,
            "to": result.to_version,
            "proof": proof_id,
            "replayed": result.command.replayed,
        }
    finally:
        await control.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "approve", "reject", "promote", "rollback"))
    parser.add_argument("--trial", required=True)
    parser.add_argument("--store", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = asyncio.run(run(args.store, TrialIdentity(args.trial), args.stage))
    except (ValueError, TimeoutError) as error:
        parser.exit(1, f"Trial stopped: {error}\n")
    print(json.dumps(json_value(result), sort_keys=True))


if __name__ == "__main__":
    main()
