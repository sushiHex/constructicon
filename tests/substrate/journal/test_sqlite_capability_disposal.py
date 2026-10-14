"""One ADMIN transaction owns a complete batch and positive replay evidence."""

from __future__ import annotations

import sqlite3

import pytest
from tests.conftest import FakeClock
from tests.migrations.test_sqlite_v7_to_v8 import historical_database, retained_bytes

from constructicon.core import control as contracts
from constructicon.core.address import RunId
from constructicon.core.control import ADMIN_SCOPE, AuthenticatedActor, command_request_hash
from constructicon.core.identity import canonical_json
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal

RUN = RunId("run-disposal-fixture")
ADMIN = AuthenticatedActor(
    actor_id="static:disposal-admin", auth_method="static", scopes=frozenset({ADMIN_SCOPE})
)


def database_world(tmp_path):
    database = tmp_path / "disposal.db"
    historical_database(database, "schema8-disposal-baseline.sql")
    clock = FakeClock()
    journal = SqliteJournal(database, now_fn=clock.now)
    return database, journal, clock


def planned(journal, *, key="dispose", actor=ADMIN, reason="cleanup unavailable", pairs=None):
    request_type = getattr(contracts, "CapabilityDisposalRequest", None)
    planner = getattr(contracts, "plan_capability_disposal", None)
    snapshot = getattr(journal, "capability_disposal_snapshot", None)
    assert request_type is not None and callable(planner) and callable(snapshot)
    if pairs is None:
        pairs = [
            {"lease_id": row.lease_id, "acquisition_epoch": row.acquisition_epoch}
            for row in journal.capability_leases(RUN)
        ]
    request = request_type.model_validate_json(
        canonical_json(
            {
                "run_id": str(RUN),
                "pairs": pairs,
                "reason": reason,
            }
        )
    )
    raw = request.model_dump(mode="json")
    claim = journal.claim_command(
        actor=actor,
        operation="runs_dispose_capabilities",
        idempotency_key=key,
        request_hash=command_request_hash(raw),
        request=raw,
        owner_id="command-worker",
        ttl_s=30,
    ).claim
    assert claim is not None
    command = journal.command(claim.command_id)
    plan = planner(command, snapshot(RUN, request.pairs))
    journal.store_command_plan(claim, {"schema_version": 1, "plan": plan.model_dump(mode="json")})
    return claim, plan


def test_schema8_writer_fixture_migrates_without_rewriting_eras_or_history(tmp_path):
    database = tmp_path / "writer8.db"
    historical_database(database, "schema8-disposal-baseline.sql")
    before = retained_bytes(database)
    with sqlite3.connect(database) as connection:
        eras = connection.execute(
            "SELECT * FROM capability_accounting_eras ORDER BY run_id"
        ).fetchall()
    journal = SqliteJournal(database)
    assert SCHEMA_VERSION == 9
    assert retained_bytes(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (9,)
        assert (
            connection.execute(
                "SELECT * FROM capability_accounting_eras ORDER BY run_id"
            ).fetchall()
            == eras
        )
    assert journal.capability_accounting_snapshot(RUN).detail.items[0].state == "active"


def test_admin_disposal_is_one_atomic_batch_with_historical_receipt(tmp_path):
    database, journal, _clock = database_world(tmp_path)
    apply = getattr(journal, "capability_disposal_apply", None)
    resolve = getattr(journal, "capability_disposal_receipt", None)
    assert callable(apply) and callable(resolve), (
        "atomic disposal and canonical receipt are required"
    )
    claim, plan = planned(journal)
    before = journal.run_head(RUN)
    receipt = apply(claim)
    assert receipt is not None
    assert receipt.command_id == claim.command_id
    assert receipt.run_id == RUN
    assert len(receipt.pairs) == 2
    assert all(
        row.state == "lost" and row.disposition is None for row in journal.capability_leases(RUN)
    )
    after = journal.run_head(RUN)
    assert after.record == before.record
    assert after.event_seq == before.event_seq + 3
    assert journal.events(RUN)[-1].kind == "CapabilityDisposalRecorded"
    assert resolve(claim.command_id) == receipt
    assert apply(claim) == receipt
    assert journal.run_head(RUN) == after
    assert SqliteJournal(database).capability_disposal_receipt(claim.command_id) == receipt
    assert len(plan.rows) == 2


def test_worker_claim_supersedes_sealed_disposal_plan_without_partial_batch(tmp_path):
    database, journal, _clock = database_world(tmp_path)
    apply = getattr(journal, "capability_disposal_apply", None)
    assert callable(apply)
    claim, _plan = planned(journal)
    worker = journal.claim_run(RUN, owner_id="competing-worker", ttl_s=30)
    before = retained_bytes(database)
    assert apply(claim).status == "superseded"
    journal.release_run(worker)
    assert apply(claim).status == "superseded"
    assert all(row.state == "active" for row in journal.capability_leases(RUN))
    assert retained_bytes(database)["events"] == before["events"]


def test_overlapping_disposal_plans_have_one_receipt_and_explicit_supersession(tmp_path):
    _database, journal, _clock = database_world(tmp_path)
    first, first_plan = planned(journal, key="overlap-first")
    second, second_plan = planned(journal, key="overlap-second")
    assert first_plan.rows == second_plan.rows
    receipt = journal.capability_disposal_apply(first)
    result = journal.capability_disposal_apply(second)
    assert isinstance(result, contracts.CapabilityDisposalSuperseded)
    assert journal.capability_disposal_receipt(second.command_id) is None
    journal.reject_command(
        second,
        contracts.capability_disposal_superseded_rejection(second_plan).model_dump(mode="json"),
    )
    assert journal.command(second.command_id).state == "rejected"
    assert journal.capability_disposal_receipt(first.command_id) == receipt
    assert sum(event.kind == "CapabilityDisposalRecorded" for event in journal.events(RUN)) == 1


@pytest.mark.parametrize("reader", ("receipt", "command", "reject"))
def test_replaced_audit_slot_cannot_hide_planned_irreversible_lost_facts(tmp_path, reader):
    from tests.durable_seals import reseal_primary_fact

    from constructicon.core.errors import JournalDamaged
    from constructicon.substrate.journal._sqlite_execution_facts import (
        event_fact_hash,
        event_fact_key,
    )

    database, journal, _clock = database_world(tmp_path)
    claim, plan = planned(journal)
    receipt = journal.capability_disposal_apply(claim)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("DELETE FROM durable_fact_seals WHERE family = 'capability_disposal'"
                           " AND fact_key = ?", (claim.command_id,))
        connection.execute("UPDATE events SET kind = 'OperatorObservation', payload = ?"
                           " WHERE run_id = ? AND seq = ?",
                           (canonical_json({"observation": "coherently resealed replacement"}),
                            RUN, receipt.audit_event_seq))
        audit = connection.execute("SELECT * FROM events WHERE run_id = ? AND seq = ?",
                                   (RUN, receipt.audit_event_seq)).fetchone()
        reseal_primary_fact(connection, family="event", fact_key=event_fact_key(RUN, audit["seq"]),
                            fact=event_fact_hash(audit))
        assert connection.execute("SELECT COUNT(*) FROM events WHERE kind = 'LeaseTransition'"
                                  " AND run_id = ?", (RUN,)).fetchone()[0] == len(receipt.pairs)
    before = retained_bytes(database)
    error = None
    try:
        if reader == "receipt":
            journal.capability_disposal_receipt(claim.command_id)
        elif reader == "command":
            journal.command(claim.command_id)
        else:
            journal.reject_command(
                claim,
                contracts.capability_disposal_superseded_rejection(plan).model_dump(mode="json"),
            )
    except Exception as exc:
        error = exc
    assert isinstance(error, JournalDamaged), error
    assert retained_bytes(database) == before


@pytest.mark.parametrize("later_observation", (False, True))
def test_competing_subset_disposal_receipt_permits_superseded_plan_with_other_audit_slot(
    tmp_path, later_observation,
):
    _database, journal, _clock = database_world(tmp_path)
    loser, loser_plan = planned(journal, key="larger-losing-plan")
    winner, _winner_plan = planned(
        journal, key="subset-winning-plan", pairs=[loser_plan.rows[0].pair.model_dump(mode="json")],
    )
    winning_receipt = journal.capability_disposal_apply(winner)
    if later_observation:
        worker = journal.claim_run(RUN, owner_id="observation-worker", ttl_s=30)
        observed = journal.append_event(
            worker, "OperatorObservation", payload={"observation": "later"},
        )
        journal.release_run(worker)
        assert observed.seq == loser_plan.baseline_event_seq + len(loser_plan.rows) + 1
    error = None
    try:
        absent = journal.capability_disposal_receipt(loser.command_id)
        superseded = journal.capability_disposal_apply(loser)
    except Exception as exc:
        error = exc
    assert error is None, error
    assert absent is None
    assert isinstance(superseded, contracts.CapabilityDisposalSuperseded)
    assert journal.capability_disposal_receipt(winner.command_id) == winning_receipt


def test_worker_claim_heartbeat_and_release_do_not_restore_planned_baseline(tmp_path):
    _database, journal, clock = database_world(tmp_path)
    claim, _plan = planned(journal)
    worker = journal.claim_run(RUN, owner_id="heartbeat-worker", ttl_s=30)
    clock.advance(1)
    worker = journal.heartbeat(worker, ttl_s=30)
    assert isinstance(
        journal.capability_disposal_apply(claim), contracts.CapabilityDisposalSuperseded
    )
    journal.release_run(worker)
    assert isinstance(
        journal.capability_disposal_apply(claim), contracts.CapabilityDisposalSuperseded
    )
    assert journal.capability_disposal_receipt(claim.command_id) is None


@pytest.mark.parametrize("committed", (False, True))
def test_command_handoff_preserves_ownership_loss_and_historical_receipt(tmp_path, committed):
    from constructicon.core.run import OwnershipLost

    database, journal, clock = database_world(tmp_path)
    claim, _plan = planned(journal)
    receipt = journal.capability_disposal_apply(claim) if committed else None
    original = journal.command(claim.command_id)
    clock.advance(31)
    successor = journal.claim_command(
        actor=ADMIN,
        operation=original.operation,
        idempotency_key=original.idempotency_key,
        request_hash=original.request_hash,
        request=original.request,
        owner_id="successor-command-worker",
        ttl_s=30,
    ).claim
    assert successor is not None and successor.epoch > claim.epoch
    before = retained_bytes(database)
    error = None
    try:
        journal.capability_disposal_apply(claim)
    except Exception as exc:
        error = exc
    assert isinstance(error, OwnershipLost), error
    assert retained_bytes(database) == before
    recovered = journal.capability_disposal_apply(successor)
    assert (recovered == receipt) if committed else (len(recovered.pairs) == 2)
    assert journal.capability_disposal_apply(successor) == recovered


def test_disposed_pair_cannot_close_but_opaque_historical_loss_can(tmp_path):
    database, journal, _clock = database_world(tmp_path)
    apply = getattr(journal, "capability_disposal_apply", None)
    assert callable(apply)
    claim, _plan = planned(journal)
    assert apply(claim) is not None
    lost = journal.capability_leases(RUN)[0]
    worker = journal.claim_run(RUN, owner_id="worker", ttl_s=30)
    before = retained_bytes(database)
    from constructicon.core.errors import ContractViolation

    with pytest.raises(ContractViolation, match="dispos"):
        journal.transition_capability_lease(
            worker,
            lease_id=lost.lease_id,
            acquisition_epoch=lost.acquisition_epoch,
            expected=frozenset({"lost"}),
            target="closed",
            disposition="released",
        )
    assert retained_bytes(database) == before


def test_selected_foreign_pair_with_erased_row_and_retained_proof_is_damage(tmp_path):
    from constructicon.core.errors import JournalDamaged

    database, journal, _clock = database_world(tmp_path)
    foreign = journal.capability_leases(RunId("run-historical-capabilities"))[0]
    pair = contracts.CapabilityAcquisitionPair(
        lease_id=foreign.lease_id,
        acquisition_epoch=foreign.acquisition_epoch,
    )
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM capability_leases WHERE lease_id = ?", (foreign.lease_id,))
    with pytest.raises(JournalDamaged, match=r"proof|row|acquisition"):
        journal.capability_disposal_snapshot(RUN, (pair,))


@pytest.mark.parametrize("epoch", (1, 2**100))
def test_genuinely_absent_exact_pair_is_a_typed_missing_observation(tmp_path, epoch):
    _database, journal, _clock = database_world(tmp_path)
    pair = contracts.CapabilityAcquisitionPair(lease_id="genuinely-absent", acquisition_epoch=epoch)
    snapshot = journal.capability_disposal_snapshot(RUN, (pair,))
    assert snapshot.run.run_id == RUN
    assert snapshot.rows[0].pair == pair
    assert snapshot.rows[0].state is None
    assert snapshot.rows[0].fact is None


def test_disposed_acquisitions_permit_a_lawful_terminal_transition(tmp_path):
    from constructicon.core.journal import RunStatus

    _database, journal, _clock = database_world(tmp_path)
    claim, _plan = planned(journal)
    journal.capability_disposal_apply(claim)
    worker = journal.claim_run(RUN, owner_id="worker", ttl_s=30)
    failure = None
    try:
        journal.transition_run(
            worker,
            expected=frozenset({RunStatus.RUNNING}),
            target=RunStatus.FAILED,
            event_kind="RunFailed",
            payload={"reason": "physical cleanup remains unverified"},
        )
    except Exception as exc:
        failure = exc
    assert failure is None, failure
    assert journal.run_head(RUN).record.status == RunStatus.FAILED
    assert journal.capability_disposal_receipt(claim.command_id).pairs == tuple(
        row.pair for row in _plan.rows
    )


def test_disposed_batch_accounting_prefetches_whole_journal_only_once(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from tests.run_worlds import create_test_run, start_test_run
    from tests.substrate.journal.test_capability_accounting_snapshot import acquire

    journal = SqliteJournal(tmp_path / "hundred-disposed.db")
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="worker")
    for index in range(100):
        acquire(journal, worker, index)
    journal.release_run(worker)
    claim, _plan = planned(journal)
    journal.capability_disposal_apply(claim)
    queries = []
    original = journal._read

    @contextmanager
    def traced():
        with original() as connection:
            connection.set_trace_callback(queries.append)
            yield connection

    monkeypatch.setattr(journal, "_read", traced)
    snapshot = journal.capability_accounting_snapshot(RUN)
    assert len(snapshot.detail.items) == 100
    assert all(item.loss == "disposed" for item in snapshot.detail.items)
    assert sum(query == "SELECT * FROM capability_leases" for query in queries) == 1
    assert (
        sum(
            query.startswith("SELECT * FROM legacy_capability_lease_seals") and "WHERE" not in query
            for query in queries
        )
        == 1
    )


@pytest.mark.parametrize("seam", ("after_transition_insert", "before_commit", "after_commit"))
def test_disposal_transaction_crash_has_no_partial_batch_and_recovers_receipt(tmp_path, seam):
    from tests.conftest import InjectedCrash

    database, journal, _clock = database_world(tmp_path)
    claim, _plan = planned(journal)
    before = retained_bytes(database)

    def crash(name):
        if name == f"capability_disposal.{seam}":
            raise InjectedCrash(name)

    journal.fault_probe = crash
    with pytest.raises(InjectedCrash):
        journal.capability_disposal_apply(claim)
    recovered = SqliteJournal(database)
    if seam != "after_commit":
        assert retained_bytes(database) == before
        assert recovered.capability_disposal_receipt(claim.command_id) is None
    else:
        assert recovered.capability_disposal_receipt(claim.command_id) is not None
    receipt = recovered.capability_disposal_apply(claim)
    assert all(row.state == "lost" for row in recovered.capability_leases(RUN))
    assert len(receipt.pairs) == 2
    assert recovered.capability_disposal_apply(claim) == receipt


def test_disposal_positive_receipt_refuses_direct_store_rejection(tmp_path):
    from constructicon.core.errors import JournalDamaged

    _database, journal, _clock = database_world(tmp_path)
    claim, plan = planned(journal)
    receipt = journal.capability_disposal_apply(claim)
    with pytest.raises(JournalDamaged, match=r"reject|disposed"):
        journal.reject_command(
            claim,
            contracts.capability_disposal_superseded_rejection(plan).model_dump(mode="json"),
        )
    assert journal.command(claim.command_id).state == "prepared"
    assert journal.capability_disposal_receipt(claim.command_id) == receipt


def test_disposal_refusal_needs_positive_drift_not_just_missing_receipt(tmp_path):
    from constructicon.core.errors import JournalDamaged

    _database, journal, _clock = database_world(tmp_path)
    claim, plan = planned(journal)
    with pytest.raises(JournalDamaged, match=r"supersession|canonical"):
        journal.reject_command(
            claim,
            contracts.capability_disposal_superseded_rejection(plan).model_dump(mode="json"),
        )
    assert journal.command(claim.command_id).state == "prepared"


def test_disposed_distinct_command_accounting_indexes_audits_once(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from tests.run_worlds import create_test_run, start_test_run
    from tests.substrate.journal.test_capability_accounting_snapshot import acquire

    journal = SqliteJournal(tmp_path / "distinct-receipts.db")
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="worker")
    leases = [acquire(journal, worker, index) for index in range(20)]
    journal.release_run(worker)
    for index, lease in enumerate(leases):
        claim, _plan = planned(
            journal,
            key=f"distinct-{index}",
            pairs=[
                {
                    "lease_id": lease.lease_id,
                    "acquisition_epoch": lease.acquisition_epoch,
                }
            ],
        )
        journal.capability_disposal_apply(claim)
    queries = []
    original = journal._read

    @contextmanager
    def traced():
        with original() as connection:
            connection.set_trace_callback(queries.append)
            yield connection

    monkeypatch.setattr(journal, "_read", traced)
    snapshot = journal.capability_accounting_snapshot(RUN)
    assert len(snapshot.detail.items) == 20
    assert all(item.loss == "disposed" for item in snapshot.detail.items)
    assert sum(query == "SELECT * FROM capability_leases" for query in queries) == 1
    assert (
        sum(
            query == "SELECT * FROM events WHERE kind = 'CapabilityDisposalRecorded'"
            for query in queries
        )
        == 1
    )


def test_opaque_historical_lost_pair_can_still_close_lawfully(tmp_path):
    _database, journal, _clock = database_world(tmp_path)
    run_id = RunId("run-historical-capabilities")
    lost = next(row for row in journal.capability_leases(run_id) if row.state == "lost")
    worker = journal.claim_run(run_id, owner_id="historic-worker", ttl_s=30)
    journal.transition_capability_lease(
        worker,
        lease_id=lost.lease_id,
        acquisition_epoch=lost.acquisition_epoch,
        expected=frozenset({"lost"}),
        target="closed",
        disposition="released",
    )
    assert (
        next(
            row for row in journal.capability_leases(run_id) if row.lease_id == lost.lease_id
        ).state
        == "closed"
    )


@pytest.mark.parametrize(
    "damage",
    ("receipt", "receipt_hash", "audit", "transition", "row", "floor", "command", "plan_and_seal"),
)
@pytest.mark.parametrize("reader", ("receipt", "event", "page", "accounting", "command", "open"))
def test_disposal_damage_refuses_every_independent_public_projection(tmp_path, damage, reader):
    from constructicon.core.errors import JournalDamaged

    database, journal, _clock = database_world(tmp_path)
    claim, _plan = planned(journal)
    receipt = journal.capability_disposal_apply(claim)
    with sqlite3.connect(database) as connection:
        if damage == "receipt":
            connection.execute(
                "DELETE FROM durable_fact_seals WHERE family = 'capability_disposal'"
            )
        elif damage == "receipt_hash":
            connection.execute(
                "UPDATE durable_fact_seals SET fact_hash = ? WHERE family = 'capability_disposal'",
                ("sha256:" + "0" * 64,),
            )
        elif damage == "plan_and_seal":
            connection.execute(
                "UPDATE commands SET plan_json = NULL WHERE command_id = ?", (claim.command_id,)
            )
            connection.execute(
                "DELETE FROM durable_fact_seals WHERE family = 'command_plan' AND fact_key = ?",
                (claim.command_id,),
            )
        elif damage == "audit":
            connection.execute(
                "DELETE FROM events WHERE run_id = ? AND seq = ?", (RUN, receipt.audit_event_seq)
            )
        elif damage == "transition":
            connection.execute(
                "DELETE FROM events WHERE run_id = ? AND seq = ?",
                (RUN, receipt.transition_event_seqs[0]),
            )
        elif damage == "row":
            connection.execute(
                "DELETE FROM capability_leases WHERE lease_id = ?", (receipt.pairs[0].lease_id,)
            )
        elif damage == "floor":
            connection.execute(
                "UPDATE capability_accounting_eras SET floor = floor + 1 WHERE run_id = ?", (RUN,)
            )
        else:
            connection.execute(
                "UPDATE commands SET request_json = '{}' WHERE command_id = ?", (claim.command_id,)
            )
    with pytest.raises(JournalDamaged):
        if reader == "receipt":
            journal.capability_disposal_receipt(claim.command_id)
        elif reader == "event":
            journal.event(RUN, receipt.audit_event_seq)
        elif reader == "page":
            journal.events(RUN)
        elif reader == "accounting":
            journal.capability_accounting_snapshot(RUN)
        elif reader == "command":
            journal.command(claim.command_id)
        else:
            SqliteJournal(database)


@pytest.mark.parametrize("binding", ("reason", "row_baseline"))
def test_disposal_relationship_rejects_resealed_primary_fact_contradictions(tmp_path, binding):
    import json

    from tests.durable_seals import reseal_primary_fact

    from constructicon.core.errors import JournalDamaged
    from constructicon.core.identity import digest
    from constructicon.substrate.journal._sqlite_capability_disposal import (
        disposal_relationship_hash,
    )
    from constructicon.substrate.journal._sqlite_commands import command_plan_fact_hash
    from constructicon.substrate.journal._sqlite_execution_facts import event_fact_hash

    database, journal, _clock = database_world(tmp_path)
    claim, _plan = planned(journal)
    receipt = journal.capability_disposal_apply(claim)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        command = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?", (claim.command_id,)
        ).fetchone()
        raw_plan = json.loads(command["plan_json"])
        plan = raw_plan["plan"]
        if binding == "reason":
            plan["reason"] = "another private reason not claimed by this command"
        else:
            fact = plan["rows"][0]["fact"]
            fact["lease"]["resource_ref"] = "fictional-resource-baseline"
            baseline_hash = str(digest("capability-disposal-baseline", 1, fact))
            plan["rows"][0]["baseline_hash"] = baseline_hash
            audit = connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = ?", (RUN, receipt.audit_event_seq)
            ).fetchone()
            payload = json.loads(audit["payload"])
            payload["row_baseline_hashes"][0] = baseline_hash
            connection.execute(
                "UPDATE events SET payload = ? WHERE run_id = ? AND seq = ?",
                (canonical_json(payload), RUN, receipt.audit_event_seq),
            )
            audit = connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = ?", (RUN, receipt.audit_event_seq)
            ).fetchone()
            reseal_primary_fact(
                connection,
                family="event",
                fact=event_fact_hash(audit),
                fact_key=canonical_json(
                    {
                        "run_id": str(RUN),
                        "seq": receipt.audit_event_seq,
                    }
                ),
            )
        connection.execute(
            "UPDATE commands SET plan_json = ? WHERE command_id = ?",
            (canonical_json(raw_plan), claim.command_id),
        )
        command = connection.execute(
            "SELECT * FROM commands WHERE command_id = ?", (claim.command_id,)
        ).fetchone()
        reseal_primary_fact(
            connection,
            family="command_plan",
            fact_key=claim.command_id,
            fact=command_plan_fact_hash(command),
        )
        audit = connection.execute(
            "SELECT * FROM events WHERE run_id = ? AND seq = ?", (RUN, receipt.audit_event_seq)
        ).fetchone()
        transitions = tuple(
            connection.execute(
                "SELECT * FROM events WHERE run_id = ? AND seq = ?", (RUN, seq)
            ).fetchone()
            for seq in receipt.transition_event_seqs
        )
        reseal_primary_fact(
            connection,
            family="capability_disposal",
            fact_key=claim.command_id,
            fact=disposal_relationship_hash(command, audit, transitions),
        )
    error = None
    try:
        journal.capability_disposal_receipt(claim.command_id)
    except Exception as exc:
        error = exc
    assert isinstance(error, JournalDamaged), error
    assert ("ADMIN plan" if binding == "reason" else "baseline differs") in str(error)


@pytest.mark.parametrize("retained", ("both", "audit", "relationship"))
@pytest.mark.parametrize("operation", ("command", "reclaim"))
def test_erased_disposal_command_and_phase_seals_are_not_absence(tmp_path, retained, operation):
    from constructicon.core.errors import JournalDamaged

    database, journal, _clock = database_world(tmp_path)
    claim, _plan = planned(journal)
    journal.capability_disposal_apply(claim)
    command = journal.command(claim.command_id)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM commands WHERE command_id = ?", (claim.command_id,))
        connection.execute("DELETE FROM durable_fact_seals WHERE fact_key = ?"
                           " AND family IN ('command_claim', 'command_plan', 'command_terminal')",
                           (claim.command_id,))
        if retained == "audit":
            connection.execute(
                "DELETE FROM durable_fact_seals WHERE family = 'capability_disposal'",
            )
        elif retained == "relationship":
            connection.execute("DELETE FROM events WHERE kind = 'CapabilityDisposalRecorded'")
    before = retained_bytes(database)
    error = None
    try:
        if operation == "command":
            journal.command(claim.command_id)
        else:
            journal.claim_command(
                actor=ADMIN, operation=command.operation, idempotency_key=command.idempotency_key,
                request_hash=command.request_hash, request=command.request,
                owner_id="cannot-remint-deleted-command", ttl_s=30,
            )
    except Exception as exc:
        error = exc
    assert isinstance(error, JournalDamaged), error
    assert retained_bytes(database) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT * FROM commands").fetchall() == []


def test_fresh_command_absence_streams_audit_proof_without_materializing_history(
    tmp_path, monkeypatch,
):
    from contextlib import contextmanager

    _database, journal, _clock = database_world(tmp_path)
    pairs = [contracts.CapabilityAcquisitionPair(lease_id=row.lease_id,
             acquisition_epoch=row.acquisition_epoch) for row in journal.capability_leases(RUN)]
    for index, pair in enumerate(pairs):
        claim, _plan = planned(journal, key=f"stream-disposal-{index}",
                               pairs=[pair.model_dump(mode="json")])
        journal.capability_disposal_apply(claim)
    seen = []
    original = journal._txn

    class StreamingOnly:
        def __init__(self, cursor):
            self.cursor = cursor

        def __iter__(self):
            for row in self.cursor:
                seen.append(row["seq"])
                yield row

        def fetchall(self):
            raise AssertionError(
                "fresh command absence must not materialize disposal audit history",
            )

    class ConnectionProbe:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, parameters=()):
            cursor = self.connection.execute(sql, parameters)
            if sql == "SELECT * FROM events WHERE kind = 'CapabilityDisposalRecorded'":
                return StreamingOnly(cursor)
            return cursor

        def __getattr__(self, attribute):
            return getattr(self.connection, attribute)

    @contextmanager
    def traced():
        with original() as connection:
            yield ConnectionProbe(connection)

    monkeypatch.setattr(journal, "_txn", traced)
    request = {"run_id": str(RUN)}
    result = journal.claim_command(
        actor=ADMIN, operation="runs_cancel", idempotency_key="fresh-after-disposals",
        request_hash=command_request_hash(request), request=request,
        owner_id="new-command-worker", ttl_s=30,
    )
    assert result.status == "claimed"
    assert len(seen) == len(pairs) == 2


def test_losing_hundred_pair_receipt_point_owns_one_fresh_structural_proof(tmp_path, monkeypatch):
    from contextlib import contextmanager

    from tests.run_worlds import create_test_run, start_test_run
    from tests.substrate.journal.test_capability_accounting_snapshot import acquire

    journal = SqliteJournal(tmp_path / "hundred-pair-race.db")
    create_test_run(journal, RUN)
    worker = start_test_run(journal, RUN, owner_id="worker")
    for index in range(100):
        acquire(journal, worker, index)
    journal.release_run(worker)
    winner, _plan = planned(journal, key="hundred-pair-winner")
    loser, _plan = planned(journal, key="hundred-pair-loser")
    journal.capability_disposal_apply(winner)
    queries = []
    original = journal._read

    @contextmanager
    def traced():
        with original() as connection:
            connection.set_trace_callback(queries.append)
            yield connection

    monkeypatch.setattr(journal, "_read", traced)
    for _ in range(2):
        queries.clear()
        assert journal.capability_disposal_receipt(loser.command_id) is None
        # Every public point call starts an independent owned read proof. Each
        # loss reuses the already-proven winning receipt inside that call only.
        assert sum(query == "SELECT * FROM capability_leases" for query in queries) == 1
        assert sum(
            query == "SELECT * FROM events WHERE kind = 'CapabilityDisposalRecorded'"
            for query in queries
        ) == 1
