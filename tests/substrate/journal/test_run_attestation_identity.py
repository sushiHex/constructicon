"""Run-scoped proofs keep exact retries and closed historical authority."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from datetime import timedelta

import pytest
from tests.conftest import BRIEF, ISSUE, atomic, triage_impl
from tests.run_worlds import create_test_run
from tests.substrate.journal.test_attestation_idempotency import RefusingClock, _draft

from constructicon.core.address import RunId
from constructicon.core.effect import AttestationDraft, MergeSubject, attestation_id_for
from constructicon.core.errors import AdmissionError, ContractViolation, JournalDamaged
from constructicon.core.identity import digest
from constructicon.core.registry import PromotionRecord, StoredVersion
from constructicon.substrate.journal.sqlite import SqliteJournal


@pytest.mark.parametrize("action", ("merge", "promote"))
def test_equal_drafts_from_independent_runs_have_distinct_run_bound_proofs(tmp_path, action):
    from constructicon.core.effect import attestation_id_for_run

    clock = RefusingClock()
    database = tmp_path / "independent.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    draft = _draft()
    if action == "merge":
        draft = draft.model_copy(update={"action": "merge", "subject": MergeSubject(
            repository="test/repo", target_ref="refs/heads/main", candidate="1" * 40,
            expected_base="2" * 40, merge_commit="3" * 40, tested_tree="4" * 40,
        )})
    proofs = []
    for name in ("run-a", "run-b"):
        run = RunId(name)
        create_test_run(journal, run)
        lease = journal.claim_run(run, owner_id="worker", ttl_s=30)
        proof = journal.mint_attestation(lease, draft)
        expected = digest("attestation", 2, {
            "draft": draft.model_dump(mode="json"), "created_by_run": str(run),
        })
        assert proof.attestation_id == "att-" + str(expected).removeprefix("sha256:")
        assert proof.attestation_id == attestation_id_for_run(draft, run)
        assert proof.created_by_run == run
        assert proof.attestation_id != attestation_id_for(draft)
        proofs.append(proof)
    assert proofs[0].attestation_id != proofs[1].attestation_id
    reopened = SqliteJournal(database)
    assert [reopened.load_attestation(p.attestation_id) for p in proofs] == proofs


@pytest.mark.parametrize("policy_first", (False, True))
def test_current_policy_and_ordinary_mint_order_is_independent(tmp_path, policy_first):
    journal = SqliteJournal(tmp_path / "ordering.db")
    run = RunId("run-ordering")
    create_test_run(journal, run)
    lease = journal.claim_run(run, owner_id="worker", ttl_s=30)
    draft = _draft()
    if policy_first:
        policy = journal.mint_policy_attestation(draft)
        ordinary = journal.mint_attestation(lease, draft)
    else:
        ordinary = journal.mint_attestation(lease, draft)
        policy = journal.mint_policy_attestation(draft)
    assert policy.created_by_run is None
    assert policy.attestation_id == attestation_id_for(draft)
    assert ordinary.created_by_run == run
    assert ordinary.attestation_id != policy.attestation_id


def test_reclaim_retries_exact_proof_before_time_and_still_checks_manifest(tmp_path):
    clock = RefusingClock()
    journal = SqliteJournal(tmp_path / "reclaim.db", now_fn=clock.now)
    run = RunId("run-reclaim")
    create_test_run(journal, run)
    first = journal.claim_run(run, owner_id="first", ttl_s=30)
    proof = journal.mint_attestation(first, _draft())
    clock.value += timedelta(seconds=31)
    successor = journal.claim_run(run, owner_id="second", ttl_s=30)
    clock.refuse = True
    assert journal.mint_attestation(successor, _draft()) == proof
    with pytest.raises(ContractViolation, match="manifest"):
        journal.mint_attestation(successor, _draft().model_copy(update={
            "manifest_hash": digest("wrong-manifest", 1, {}),
        }))


def test_independent_promotion_proofs_keep_one_move_and_stable_moved_law(tmp_path):
    clock = RefusingClock()
    database = tmp_path / "moves.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    definition, _ = atomic("test/candidate", (ISSUE,), (BRIEF,), triage_impl)
    version = definition.content_hash()
    journal.store_version(StoredVersion(
        definition=definition, content_hash=version, registered_at=clock.now(),
    ))
    draft = _draft().model_copy(update={
        "subject": _draft().subject.model_copy(update={"version": version}),
    })
    moves = []
    for run in (RunId("move-a"), RunId("move-b")):
        create_test_run(journal, run)
        lease = journal.claim_run(run, owner_id="worker", ttl_s=30)
        proof = journal.mint_attestation(lease, draft)
        moves.append(PromotionRecord(
            component=definition.name, channel="stable", from_version=None,
            to_version=version, attestation_id=proof.attestation_id,
            actor="static:operator", source_run=run, created_at=clock.now(),
        ))
    first = journal.store_promotion(moves[0])
    assert journal.store_promotion(moves[0]) == first
    with pytest.raises(AdmissionError, match="stable moved"):
        journal.store_promotion(moves[1])
    with pytest.raises(JournalDamaged, match="contradictory promotion"):
        journal.store_promotion(moves[0].model_copy(update={"from_version": version}))
    assert SqliteJournal(database).promotion_for_attestation(moves[0].attestation_id) == first
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM promotions").fetchone() == (1,)


def draft_of(proof):
    return AttestationDraft.model_validate({
        field: proof.model_dump(mode="json")[field] for field in AttestationDraft.model_fields
    })


def test_exact_v2_id_and_primary_seal_cannot_replace_creator_world_validation(tmp_path):
    from constructicon.core.effect import attestation_id_for_run
    from constructicon.substrate.journal._sqlite_attestations import attestation_fact_hash
    from constructicon.substrate.journal._sqlite_fact_seals import store_durable_fact_seal

    database = tmp_path / "creator-world.db"
    journal = SqliteJournal(database)
    run = RunId("creator-world")
    create_test_run(journal, run)
    lease = journal.claim_run(run, owner_id="worker", ttl_s=30)
    original = journal.mint_attestation(lease, _draft())
    other = create_test_run(journal, RunId("other-world"), inputs={"different": True})
    wrong_draft = _draft().model_copy(update={"manifest_hash": other.manifest_hash})
    identity = attestation_id_for_run(wrong_draft, run)
    wrong = original.model_copy(update={
        "manifest_hash": other.manifest_hash, "attestation_id": identity,
    })
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("INSERT INTO attestations VALUES (?, ?)",
                           (identity, wrong.model_dump_json()))
        row = connection.execute("SELECT * FROM attestations WHERE attestation_id=?",
                                 (identity,)).fetchone()
        store_durable_fact_seal(connection, family="attestation", fact_key=identity,
                                selector=identity,
                                fact_hash=attestation_fact_hash(row, family="attestation"))
    with pytest.raises(JournalDamaged, match="creator run world"):
        journal.load_attestation(identity)
    for read in (
        lambda: journal.run_records(),
        lambda: journal.run_records(limit=1, after=("9999-01-01T00:00:00+00:00", "past-end")),
        lambda: journal.latest_run_key(),
        lambda: journal.recoverable_runs(limit=1),
    ):
        with pytest.raises(JournalDamaged):
            read()


@pytest.mark.parametrize("seam", ("before_commit", "after_commit"))
def test_real_process_attestation_death_retries_exact_evidence(tmp_path, seam):
    database = tmp_path / "attestation-death.db"
    journal = SqliteJournal(database)
    run = RunId("crash-attestation")
    create_test_run(journal, run)
    program = """
import os,sys
from constructicon.core.address import RunId
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.substrate.journal.test_attestation_idempotency import _draft
journal = SqliteJournal(sys.argv[1])
lease = journal.claim_run(RunId('crash-attestation'), owner_id='worker', ttl_s=30)
def fault(name):
    if name == 'attestation.' + sys.argv[2]:
        os._exit(92)
journal.fault_probe = fault
journal.mint_attestation(lease, _draft())
raise AssertionError('attestation seam never reached')
"""
    result = subprocess.run([sys.executable, "-c", program, str(database), seam],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    assert result.returncode == 92, result.stderr.decode("utf-8", errors="replace")
    recovered = SqliteJournal(database)
    with sqlite3.connect(database) as connection:
        count = 1 if seam == "after_commit" else 0
        assert connection.execute("SELECT COUNT(*) FROM attestations").fetchone() == (count,)
        assert connection.execute("SELECT COUNT(*) FROM durable_fact_seals"
                                  " WHERE family='attestation'").fetchone() == (count,)
        stored = connection.execute("SELECT attestation_json FROM attestations").fetchone()
    from constructicon.core.run import RunLease

    # Restart with the same still-fenced run epoch, without needing a new claim
    # or observing time for an already committed proof.
    lease = RunLease(run_id=run, owner_id="worker", epoch=1, expires_at=RefusingClock().now())
    if stored is not None:
        recovered._now = lambda: (_ for _ in ()).throw(AssertionError("retry observed time"))
    proof = recovered.mint_attestation(lease, _draft())
    assert recovered.mint_attestation(lease, _draft()) == proof
    if stored is not None:
        from constructicon.core.effect import Attestation

        assert proof == Attestation.model_validate_json(stored[0])
