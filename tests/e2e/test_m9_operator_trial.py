"""Exercise the same fixed operator commands documented in the runbook."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from constructicon.core.address import RunId
from constructicon.core.identity import Digest
from constructicon.core.run import RunState, RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.e2e.m9_evidence import TrialIdentity
from tests.e2e.m9_fixture import TARGET
from tests.e2e.m9_issuer import OPERATOR_ISSUER_PATH, OPERATOR_REJECTION, OperatorRejected
from tests.e2e.m9_operator_evaluator import wait_deadline
from tests.e2e.m9_operator_trial import _verify_rejection, run


def _cli(store: Path, stage: str) -> dict:
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "tests.e2e.m9_operator_trial",
            stage,
            "--trial",
            "operator",
            "--store",
            str(store),
        ],
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=45,
        check=False,
    )
    assert process.returncode == 0, (process.stdout, process.stderr)
    return json.loads(process.stdout)


def _promotion_proofs(store: Path, version: Digest) -> list[str]:
    with closing(sqlite3.connect(store / "journal.sqlite")) as connection:
        return [
            proof_id
            for proof_id, in connection.execute(
                "SELECT attestation_id FROM attestations "
                "WHERE json_extract(attestation_json, '$.action') = 'promote' "
                "AND json_extract(attestation_json, '$.subject.component') = ? "
                "AND json_extract(attestation_json, '$.subject.version') = ?",
                (TARGET, str(version)),
            )
        ]


async def test_fixed_operator_trial_from_park_through_rollback(tmp_path: Path) -> None:
    store = tmp_path / "isolated"
    trial = TrialIdentity("operator")
    parked = _cli(store, "prepare")
    assert parked["status"] == "awaiting-owner"
    journal = SqliteJournal(store / "journal.sqlite")
    run_id = RunId(parked["run"])
    old = Digest(parked["subject"]["baseline_version"])
    new = Digest(parked["subject"]["version"])
    before = journal.snapshot().revision.promotion_seq
    assert journal.snapshot().stable_version(TARGET) == old
    assert journal.checkpoint(run_id, OPERATOR_ISSUER_PATH) is None
    assert _promotion_proofs(store, new) == []
    with pytest.raises(ValueError, match="original trial key"):
        await run(store, TrialIdentity("other"), "prepare")
    with pytest.raises(ValueError, match="no successful reviewed issuance"):
        await run(store, trial, "promote")
    assert await run(store, trial, "prepare") == {
        **parked,
        "request": Digest(parked["request"]),
        "exam": Digest(parked["exam"]),
    }
    approved = _cli(store, "approve")
    assert approved["run"] == run_id and approved["status"] == "approved"
    assert journal.snapshot().revision.promotion_seq == before
    assert journal.snapshot().stable_version(TARGET) == old
    events = journal.events(run_id, limit=100)
    assert [event.kind for event in events].count("RunResumed") == 1
    record = journal.run_record(run_id)
    assert record is not None and record.status == RunStatus.SUCCEEDED
    issued = journal.checkpoint(run_id, OPERATOR_ISSUER_PATH)
    assert issued is not None
    proof_id = issued.outputs["proof"].payload
    proof = journal.load_attestation(proof_id)
    assert proof is not None and proof.created_by_run == run_id and proof.action == "promote"
    assert journal.promotion_for_attestation(proof_id) is None
    assert _promotion_proofs(store, new) == [proof_id]

    promoted = await run(store, trial, "promote")
    assert (promoted["from"], promoted["to"], promoted["proof"]) == (old, new, proof_id)
    assert journal.snapshot().stable_version(TARGET) == new
    assert journal.snapshot().revision.promotion_seq == before + 1
    assert await run(store, trial, "promote") == {**promoted, "replayed": True}
    assert journal.snapshot().revision.promotion_seq == before + 1
    rolled_back = await run(store, trial, "rollback")
    assert (rolled_back["from"], rolled_back["to"]) == (new, old)
    assert journal.snapshot().stable_version(TARGET) == old
    assert journal.snapshot().revision.promotion_seq == before + 2
    assert journal.run_record(run_id) == record
    assert journal.checkpoint(run_id, OPERATOR_ISSUER_PATH) == issued
    assert journal.snapshot().get(TARGET, new) is not None


async def test_fixed_operator_rejection_cannot_promote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = tmp_path / "isolated"
    trial = TrialIdentity("reject")
    parked = await run(store, trial, "prepare")
    new = Digest(parked["subject"]["version"])
    journal = SqliteJournal(store / "journal.sqlite")
    before = journal.snapshot().revision
    rejected = await run(store, trial, "reject")
    assert rejected["status"] == "rejected" and rejected["run"] == parked["run"]
    with pytest.raises(ValueError, match="no successful reviewed issuance"):
        await run(store, trial, "promote")
    assert journal.snapshot().revision == before
    assert _promotion_proofs(store, new) == []

    run_id = RunId(parked["run"])
    failures = [event for event in journal.events(run_id) if event.kind == "NodeFailed"]
    assert len(failures) == 1
    assert failures[0].path == OPERATOR_ISSUER_PATH
    assert failures[0].payload == {
        "error_type": OperatorRejected.__name__,
        "error": OPERATOR_REJECTION,
    }
    events = journal.events
    for changes in (
        {"payload": {"error_type": "ContractViolation", "error": OPERATOR_REJECTION}},
        {"payload": {"error_type": OperatorRejected.__name__, "error": "unrelated failure"}},
        {"path": None},
    ):
        with monkeypatch.context() as patch:

            def altered_events(*args, changes=changes, **kwargs):
                return [
                    event.model_copy(update=changes) if event.kind == "NodeFailed" else event
                    for event in events(*args, **kwargs)
                ]

            patch.setattr(journal, "events", altered_events)
            with pytest.raises(ValueError, match="M9_REJECTION_CAUSE_MISMATCH"):
                _verify_rejection(journal, run_id)


async def test_wait_timeout_names_stage_run_status_and_liveness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    journal = SqliteJournal(tmp_path / "wait.sqlite")
    run_id = RunId("run-lost-owner")
    # Substitute only the durable-state read; the real asyncio deadline expires.
    monkeypatch.setattr(
        journal, "run_state", lambda run: RunState(status=RunStatus.RUNNING, liveness="lost")
    )
    with pytest.raises(TimeoutError) as caught:
        async with wait_deadline(journal, run_id, "source-evidence", timeout_s=0.01):
            await asyncio.sleep(1)
    assert str(caught.value) == (
        "M9_WAIT_TIMEOUT stage=source-evidence run=run-lost-owner status=running "
        "liveness=lost; preserve the store, inspect recorded owner liveness, "
        "and retry the same command only when its run/command lease permits recovery"
    )
    # A timeout from inside the body is not misreported as our wait deadline.
    with pytest.raises(TimeoutError, match="inner timeout"):
        async with wait_deadline(journal, run_id, "source-evidence"):
            raise TimeoutError("inner timeout")
