"""Exercise the same fixed operator commands documented in the runbook."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from constructicon.core.address import RunId
from constructicon.core.identity import Digest
from constructicon.core.run import RunStatus
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.e2e.m9_evidence import TrialIdentity
from tests.e2e.m9_fixture import TARGET
from tests.e2e.m9_issuer import OPERATOR_ISSUER_PATH
from tests.e2e.m9_operator_trial import run


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


async def test_fixed_operator_rejection_cannot_promote(tmp_path: Path) -> None:
    store = tmp_path / "isolated"
    trial = TrialIdentity("reject")
    parked = await run(store, trial, "prepare")
    journal = SqliteJournal(store / "journal.sqlite")
    before = journal.snapshot().revision
    rejected = await run(store, trial, "reject")
    assert rejected["status"] == "rejected" and rejected["run"] == parked["run"]
    with pytest.raises(ValueError, match="no successful reviewed issuance"):
        await run(store, trial, "promote")
    assert journal.snapshot().revision == before
