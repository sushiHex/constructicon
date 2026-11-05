"""Schema-9 writer facts cross a closed run-attestation identity era."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import threading
from datetime import timedelta
from pathlib import Path

import pytest

from constructicon.core.address import RunId
from constructicon.core.effect import Attestation, attestation_id_for_run
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.substrate.journal._sqlite_metering import ERA_FAMILY
from constructicon.substrate.journal.sqlite import SCHEMA_VERSION, SqliteJournal
from tests.run_worlds import create_test_run
from tests.substrate.journal.test_attestation_idempotency import RefusingClock
from tests.substrate.journal.test_run_attestation_identity import draft_of

FIXTURE = Path(__file__).parents[1] / "fixtures/attestation_history/schema9-attestations.sql"
WRITER = "15e87ef20ed3233c12a289df34088dc0ac8f8a84"
FAMILY = "attestation_run_v1_pre_v10"


def historical_database(database):
    connection = sqlite3.connect(database)
    try:
        connection.executescript(FIXTURE.read_text(encoding="utf-8"))
    finally:
        connection.close()


def logical_facts(database, *, include_witness=False):
    connection = sqlite3.connect(database)
    try:
        tables = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name",
        )]
        return {table: connection.execute(
            f"SELECT * FROM {table}"
            + (f" WHERE family NOT IN ('{FAMILY}', '{ERA_FAMILY}')"
               if table == "durable_fact_seals" and not include_witness else "")
            + " ORDER BY 1, 2",
        ).fetchall() for table in tables}
    finally:
        connection.close()


def historical_proofs(database):
    with sqlite3.connect(database) as connection:
        return [Attestation.model_validate_json(row[0]) for row in connection.execute(
            "SELECT attestation_json FROM attestations ORDER BY attestation_id",
        )]


def test_actual_schema9_proofs_and_all_dependents_migrate_without_rewriting(tmp_path):
    database = tmp_path / "historical.db"
    historical_database(database)
    before = logical_facts(database)
    proofs = historical_proofs(database)
    assert {proof.action for proof in proofs} == {"merge", "promote", "send"}
    assert sum(proof.created_by_run is None for proof in proofs) == 1
    journal = SqliteJournal(database)
    assert logical_facts(database) == before
    assert [journal.load_attestation(p.attestation_id) for p in proofs] == proofs
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals WHERE family=?", (FAMILY,),
        ).fetchone() == (3,)
    assert SqliteJournal(database).run_records()
    assert logical_facts(database) == before


def test_historical_same_run_retry_and_named_policy_conflict_observe_no_time(tmp_path):
    database = tmp_path / "historical-retry.db"
    historical_database(database)
    clock = RefusingClock()
    journal = SqliteJournal(database, now_fn=clock.now)
    proof = next(p for p in historical_proofs(database)
                 if p.action == "promote" and p.created_by_run is not None)
    lease = journal.claim_run(proof.created_by_run, owner_id="successor", ttl_s=30)
    clock.refuse = True
    before = logical_facts(database, include_witness=True)
    assert journal.mint_attestation(lease, draft_of(proof)) == proof
    with pytest.raises(ContractViolation, match="policy_attestation_id_owned_by_history"):
        journal.mint_policy_attestation(draft_of(proof))
    assert logical_facts(database, include_witness=True) == before
    clock.refuse = False
    other = RunId("independent-after-upgrade")
    create_test_run(journal, other)
    second = journal.claim_run(other, owner_id="second", ttl_s=30)
    minted = journal.mint_attestation(second, draft_of(proof))
    assert minted.created_by_run == other
    assert minted.attestation_id != proof.attestation_id


@pytest.mark.parametrize("seam", ("before_version", "before_commit", "after_commit"))
def test_real_process_migration_death_is_atomic(tmp_path, seam):
    database = tmp_path / "migration-death.db"
    historical_database(database)
    before = logical_facts(database)
    program = """
import os,sys
from constructicon.substrate.journal._sqlite_schema import _SqliteSchemaMixin
from constructicon.substrate.journal.sqlite import SqliteJournal
original = _SqliteSchemaMixin._migrate_m9_to_m10
def interrupted(self, connection):
    def fault(name):
        if name == 'attestation_identity_migration.' + sys.argv[2]:
            os._exit(91)
    self.fault_probe = fault
    original(self, connection)
_SqliteSchemaMixin._migrate_m9_to_m10 = interrupted
SqliteJournal(sys.argv[1])
raise AssertionError('migration crash seam was not reached')
"""
    result = subprocess.run([sys.executable, "-c", program, str(database), seam],
                            stdin=subprocess.DEVNULL, capture_output=True, timeout=30)
    assert result.returncode == 91, result.stderr.decode("utf-8", errors="replace")
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (
            10 if seam == "after_commit" else 9,
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM durable_fact_seals WHERE family=?", (FAMILY,),
        ).fetchone() == (3 if seam == "after_commit" else 0,)
    assert logical_facts(database) == before
    SqliteJournal(database)
    assert logical_facts(database) == before


def test_two_real_constructors_recheck_version_under_migration_lock(tmp_path, monkeypatch):
    from constructicon.substrate.journal import _sqlite_base

    database = tmp_path / "constructor-race.db"
    historical_database(database)
    before = logical_facts(database)
    paused, resume = threading.Event(), threading.Event()
    stale_thread = []
    outcomes = []
    original = _sqlite_base._SqliteBase._connect

    def scheduled(self):
        connection = original(self)
        if threading.get_ident() in stale_thread:
            armed = [True]

            def hold(statement):
                if armed[0] and statement.upper().startswith("BEGIN IMMEDIATE"):
                    armed[0] = False
                    paused.set()
                    assert resume.wait(30)

            connection.set_trace_callback(hold)
        return connection

    monkeypatch.setattr(_sqlite_base._SqliteBase, "_connect", scheduled)

    def stale():
        stale_thread.append(threading.get_ident())
        try:
            outcomes.append(SqliteJournal(database))
        except BaseException as exc:
            outcomes.append(exc)

    worker = threading.Thread(target=stale)
    worker.start()
    try:
        assert paused.wait(30), "stale constructor never reached migration lock"
        winner = SqliteJournal(database)
    finally:
        resume.set()
        worker.join(30)
    assert not worker.is_alive()
    assert len(outcomes) == 1 and isinstance(outcomes[0], SqliteJournal), outcomes
    assert logical_facts(database) == before
    assert winner.run_records() == outcomes[0].run_records()


def test_pre10_context_is_connection_scoped_reentrant_and_resets_on_error(tmp_path):
    from constructicon.substrate.journal._sqlite_attestations import (
        _pre_v10_attestation_reader,
        _pre_v10_reader,
        register_attestation_seal_guard,
        require_attestation_seal,
    )
    from constructicon.substrate.journal._sqlite_runs import (
        RUN_CHILD_ORPHAN_ANOMALY,
        register_run_origin_guard,
    )

    database = tmp_path / "context.db"
    historical_database(database)
    first, second = sqlite3.connect(database), sqlite3.connect(database)
    first.row_factory = second.row_factory = sqlite3.Row
    try:
        with (
            pytest.raises(JournalDamaged, match="transaction"),
            _pre_v10_attestation_reader(first),
        ):
            pytest.fail("unlocked pre10 context was accepted")
        first.execute("BEGIN IMMEDIATE")
        second.execute("BEGIN")
        register_attestation_seal_guard(first)
        register_run_origin_guard(first)
        row = first.execute("SELECT * FROM attestations WHERE json_extract("
                            "attestation_json, '$.action')='send'").fetchone()
        with pytest.raises(RuntimeError, match="injected"), _pre_v10_attestation_reader(first):
            assert _pre_v10_reader(first) and not _pre_v10_reader(second)
            assert first.execute(
                "SELECT constructicon_attestation_pre_v10()",
            ).fetchone()[0] == 1
            assert require_attestation_seal(first, row).provenance == "run-v1-pre-v10"
            with pytest.raises(JournalDamaged):
                require_attestation_seal(second, row)
            with _pre_v10_attestation_reader(first):
                assert _pre_v10_reader(first)
            assert _pre_v10_reader(first)
            with _pre_v10_attestation_reader(second):
                assert _pre_v10_reader(second) and not _pre_v10_reader(first)
            assert _pre_v10_reader(first) and not _pre_v10_reader(second)
            assert first.execute(f"SELECT ({RUN_CHILD_ORPHAN_ANOMALY})").fetchone()[0] == 0
            raise RuntimeError("injected")
        # The SAME registered SQL functions immediately lose compatibility,
        # even while the original connection still owns its transaction.
        assert not _pre_v10_reader(first) and not _pre_v10_reader(second)
        assert first.execute("SELECT constructicon_attestation_pre_v10()").fetchone()[0] == 0
        assert first.execute(f"SELECT ({RUN_CHILD_ORPHAN_ANOMALY})").fetchone()[0] == 1
        with pytest.raises(JournalDamaged):
            require_attestation_seal(first, row)
        first.rollback()
        second.rollback()
        first.execute("PRAGMA user_version=10")
        first.execute("BEGIN IMMEDIATE")
        with (
            pytest.raises(JournalDamaged, match="pre-10 schema"),
            _pre_v10_attestation_reader(first),
        ):
            pytest.fail("schema10 entered pre10 context")
    finally:
        first.close()
        second.close()


@pytest.mark.parametrize("damage", ("future-witness", "missing-primary", "unknown-family", "v2"))
def test_schema9_invalid_inventory_refuses_atomically_without_witnessing(tmp_path, damage):
    from constructicon.substrate.journal._sqlite_attestations import attestation_fact_hash
    from constructicon.substrate.journal._sqlite_fact_seals import store_durable_fact_seal

    database = tmp_path / "bad-source.db"
    historical_database(database)
    proof = next(p for p in historical_proofs(database) if p.action == "send")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        if damage in {"future-witness", "unknown-family"}:
            connection.execute("INSERT INTO durable_fact_seals VALUES (?, ?, ?, ?)",
                               (FAMILY if damage == "future-witness" else "future-family",
                                "unexpected", "unexpected", "sha256:" + "0" * 64))
        elif damage == "missing-primary":
            connection.execute("DELETE FROM durable_fact_seals WHERE family='attestation'"
                               " AND fact_key=?", (proof.attestation_id,))
        else:
            new_id = attestation_id_for_run(draft_of(proof), proof.created_by_run)
            new_proof = proof.model_copy(update={"attestation_id": new_id})
            connection.execute("INSERT INTO attestations VALUES (?, ?)",
                               (new_id, new_proof.model_dump_json()))
            row = connection.execute("SELECT * FROM attestations WHERE attestation_id=?",
                                     (new_id,)).fetchone()
            store_durable_fact_seal(connection, family="attestation", fact_key=new_id,
                                    selector=new_id,
                                    fact_hash=attestation_fact_hash(row, family="attestation"))
    before = logical_facts(database, include_witness=True)
    with pytest.raises(JournalDamaged):
        SqliteJournal(database)
    assert logical_facts(database, include_witness=True) == before
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA user_version").fetchone() == (9,)


@pytest.mark.parametrize("damage", ("missing", "wrong", "orphan", "policy", "primary", "row"))
def test_historical_witness_damage_refuses_current_point_run_and_open(tmp_path, damage):
    database = tmp_path / "witness-damage.db"
    historical_database(database)
    journal = SqliteJournal(database)
    proofs = historical_proofs(database)
    proof = next(p for p in proofs if p.action == "send")
    policy = next(p for p in proofs if p.created_by_run is None)
    with sqlite3.connect(database) as connection:
        if damage == "row":
            connection.execute("DELETE FROM attestations WHERE attestation_id=?",
                               (proof.attestation_id,))
        elif damage in {"missing", "primary"}:
            connection.execute("DELETE FROM durable_fact_seals WHERE family=? AND fact_key=?",
                               (FAMILY if damage == "missing" else "attestation",
                                proof.attestation_id))
        elif damage == "wrong":
            connection.execute("UPDATE durable_fact_seals SET fact_hash=? WHERE family=?",
                               ("sha256:" + "0" * 64, FAMILY))
        else:
            key = policy.attestation_id if damage == "policy" else "att-orphan"
            connection.execute("INSERT INTO durable_fact_seals VALUES (?, ?, ?, ?)",
                               (FAMILY, key, key, "sha256:" + "0" * 64))
    before = logical_facts(database, include_witness=True)
    if damage in {"missing", "wrong", "primary", "row"}:
        with pytest.raises(JournalDamaged):
            journal.load_attestation(proof.attestation_id)
        with pytest.raises(JournalDamaged):
            journal.run_records()
    else:
        with pytest.raises(JournalDamaged):
            journal.load_attestation(policy.attestation_id if damage == "policy" else "att-orphan")
        with pytest.raises(JournalDamaged):
            journal.run_records()
    with pytest.raises(JournalDamaged):
        SqliteJournal(database)
    assert logical_facts(database, include_witness=True) == before


@pytest.mark.parametrize("damage", (
    "missing", "wrong", "creator-swap", "dual-family", "witness-selector", "primary-selector",
    "dual-family-selector", "valid-rewrite",
))
def test_inbox_sql_cannot_hide_unproven_history_behind_another_actor(tmp_path, damage):
    from constructicon.core.channel import ChannelRevision
    from constructicon.substrate.journal._sqlite_attestations import attestation_fact_hash
    from constructicon.substrate.journal._sqlite_fact_seals import (
        sealed_fact_hash,
        store_durable_fact_seal,
    )

    database = tmp_path / "inbox-witness.db"
    historical_database(database)
    journal = SqliteJournal(database)
    proof = next(p for p in historical_proofs(database) if p.action == "send")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM attestations WHERE attestation_id=?",
                                 (proof.attestation_id,)).fetchone()
        if damage in {"witness-selector", "primary-selector"}:
            connection.execute("UPDATE durable_fact_seals SET selector='att-misplaced'"
                               " WHERE family=? AND fact_key=?",
                               (FAMILY if damage == "witness-selector" else "attestation",
                                proof.attestation_id))
        elif damage == "missing":
            connection.execute("DELETE FROM durable_fact_seals WHERE family=? AND fact_key=?",
                               (FAMILY, proof.attestation_id))
        elif damage == "wrong":
            connection.execute("UPDATE durable_fact_seals SET fact_hash=? WHERE family=?"
                               " AND fact_key=?",
                               ("sha256:" + "0" * 64, FAMILY, proof.attestation_id))
        elif damage in {"dual-family", "dual-family-selector"}:
            store_durable_fact_seal(
                connection, family="legacy_attestation_m1_m2", fact_key=proof.attestation_id,
                selector=proof.attestation_id,
                fact_hash=attestation_fact_hash(row, family="legacy_attestation_m1_m2"),
            )
            if damage == "dual-family-selector":
                connection.execute("UPDATE durable_fact_seals SET selector='att-misplaced'"
                                   " WHERE family='legacy_attestation_m1_m2' AND fact_key=?",
                                   (proof.attestation_id,))
        else:
            changed = proof.model_copy(update=(
                {"created_at": proof.created_at + timedelta(seconds=1)}
                if damage == "valid-rewrite" else {"created_by_run": RunId("invented-creator")}
            ))
            connection.execute("UPDATE attestations SET attestation_json=? WHERE attestation_id=?",
                               (changed.model_dump_json(), proof.attestation_id))
            row = connection.execute("SELECT * FROM attestations WHERE attestation_id=?",
                                     (proof.attestation_id,)).fetchone()
            # Even a correctly recomputed primary seal cannot replace the
            # immutable migration witness over exact historical raw bytes.
            connection.execute("UPDATE durable_fact_seals SET fact_hash=?"
                               " WHERE family='attestation'"
                               " AND fact_key=?", (str(sealed_fact_hash(
                                   family="attestation", fact_key=proof.attestation_id,
                                   selector=proof.attestation_id,
                                   fact=attestation_fact_hash(row, family="attestation"),
                               )), proof.attestation_id))
    # The request is for static:legacy-advisor. Only the authority anomaly can
    # select it for this unrelated actor, so a skipped SQL guard yields empty
    # success rather than ever reaching the ordinary point projector.
    with pytest.raises(JournalDamaged):
        journal.channel_inbox(channel_id="channel/legacy", actor_id="static:other",
                              revision=ChannelRevision(message_seq=1, ack_seq=0),
                              after=None, limit=10)
    with pytest.raises(JournalDamaged):
        journal.load_attestation(proof.attestation_id)
    with pytest.raises(JournalDamaged):
        journal.run_records()
    with pytest.raises(JournalDamaged):
        SqliteJournal(database)


def test_new_v1_injection_cannot_obtain_current_authority_even_with_valid_primary(tmp_path):
    from constructicon.core.effect import attestation_id_for
    from constructicon.substrate.journal._sqlite_attestations import attestation_fact_hash
    from constructicon.substrate.journal._sqlite_fact_seals import store_durable_fact_seal

    database = tmp_path / "injected-v1.db"
    historical_database(database)
    journal = SqliteJournal(database)
    original = next(p for p in historical_proofs(database) if p.action == "merge")
    changed_draft = draft_of(original).model_copy(update={"workspace_id": "injected-workspace"})
    identity = attestation_id_for(changed_draft)
    changed = original.model_copy(update={"attestation_id": identity,
                                          "workspace_id": "injected-workspace"})
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("INSERT INTO attestations VALUES (?, ?)",
                           (identity, changed.model_dump_json()))
        row = connection.execute("SELECT * FROM attestations WHERE attestation_id=?",
                                 (identity,)).fetchone()
        store_durable_fact_seal(connection, family="attestation", fact_key=identity,
                                selector=identity,
                                fact_hash=attestation_fact_hash(row, family="attestation"))
    before = logical_facts(database, include_witness=True)
    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.load_attestation(identity)
    with pytest.raises(JournalDamaged):
        journal.run_records()
    with pytest.raises(JournalDamaged):
        SqliteJournal(database)
    assert logical_facts(database, include_witness=True) == before


def test_v2_proof_refuses_an_even_byte_correct_historical_witness(tmp_path):
    from constructicon.substrate.journal._sqlite_attestations import attestation_fact_hash
    from constructicon.substrate.journal._sqlite_fact_seals import store_durable_fact_seal
    from tests.substrate.journal.test_attestation_idempotency import _draft

    database = tmp_path / "v2-extra-witness.db"
    journal = SqliteJournal(database)
    run = RunId("v2-extra-witness")
    create_test_run(journal, run)
    lease = journal.claim_run(run, owner_id="worker", ttl_s=30)
    proof = journal.mint_attestation(lease, _draft())
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM attestations WHERE attestation_id=?",
                                 (proof.attestation_id,)).fetchone()
        store_durable_fact_seal(connection, family=FAMILY, fact_key=proof.attestation_id,
                                selector=proof.attestation_id,
                                fact_hash=attestation_fact_hash(row, family=FAMILY))
    with pytest.raises(JournalDamaged, match="ineligible"):
        journal.load_attestation(proof.attestation_id)
    with pytest.raises(JournalDamaged):
        SqliteJournal(database)


def test_m1_m2_primary_history_cannot_carry_a_run_v1_witness(tmp_path):
    from constructicon.substrate.journal._sqlite_attestations import attestation_fact_hash
    from constructicon.substrate.journal._sqlite_fact_seals import store_durable_fact_seal
    from tests.migrations.test_sqlite_from_v2_to_current import (
        M2_UNUSED_ATTESTATION_ID,
        _build_exact_m2_database,
    )

    database = tmp_path / "m2-ineligible.db"
    _build_exact_m2_database(database)
    journal = SqliteJournal(database)
    assert journal.load_attestation(M2_UNUSED_ATTESTATION_ID) is not None
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        row = connection.execute("SELECT * FROM attestations WHERE attestation_id=?",
                                 (M2_UNUSED_ATTESTATION_ID,)).fetchone()
        store_durable_fact_seal(connection, family=FAMILY, fact_key=M2_UNUSED_ATTESTATION_ID,
                                selector=M2_UNUSED_ATTESTATION_ID,
                                fact_hash=attestation_fact_hash(row, family=FAMILY))
    with pytest.raises(JournalDamaged, match="ineligible"):
        journal.load_attestation(M2_UNUSED_ATTESTATION_ID)
    with pytest.raises(JournalDamaged):
        SqliteJournal(database)


def test_failed_real_migration_cannot_leave_sql_compatibility_on_its_connection(
    tmp_path, monkeypatch,
):
    from constructicon.substrate.journal import _sqlite_schema
    from constructicon.substrate.journal._sqlite_attestations import (
        _pre_v10_reader,
        require_attestation_seal,
    )
    from constructicon.substrate.journal._sqlite_runs import RUN_CHILD_ORPHAN_ANOMALY

    database = tmp_path / "failed-context.db"
    historical_database(database)
    journal = SqliteJournal(tmp_path / "helper.db")
    before = logical_facts(database, include_witness=True)
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row

    def interrupted(conn):
        assert conn is connection and _pre_v10_reader(conn)
        raise RuntimeError("inside migration")

    monkeypatch.setattr(_sqlite_schema, "mint_pre_v10_attestation_witnesses", interrupted)
    try:
        with pytest.raises(RuntimeError, match="inside migration"):
            journal._migrate_m9_to_m10(connection)
        assert not connection.in_transaction and not _pre_v10_reader(connection)
        assert connection.execute("SELECT constructicon_attestation_pre_v10()").fetchone()[0] == 0
        assert connection.execute(f"SELECT ({RUN_CHILD_ORPHAN_ANOMALY})").fetchone()[0] == 1
        connection.execute("BEGIN IMMEDIATE")
        assert connection.execute("SELECT constructicon_attestation_pre_v10()").fetchone()[0] == 0
        row = connection.execute("SELECT * FROM attestations WHERE json_extract("
                                 "attestation_json, '$.action')='send'").fetchone()
        with pytest.raises(JournalDamaged):
            require_attestation_seal(connection, row)
    finally:
        connection.close()
    assert logical_facts(database, include_witness=True) == before


@pytest.mark.parametrize("damage", ("creator-manifest", "parent-world-seal", "manifest-seal"))
def test_off_actor_inbox_proves_creator_manifest_and_positive_world_facts(tmp_path, damage):
    from constructicon.core.channel import ChannelRevision
    from constructicon.substrate.journal._sqlite_attestations import attestation_fact_hash
    from constructicon.substrate.journal._sqlite_channels import channel_message_fact_hash
    from constructicon.substrate.journal._sqlite_fact_seals import store_durable_fact_seal
    from tests.durable_seals import reseal_primary_fact

    database = tmp_path / "inbox-creator-world.db"
    historical_database(database)
    journal = SqliteJournal(database)
    original = next(p for p in historical_proofs(database) if p.action == "send")
    other = create_test_run(journal, RunId("different-world"), inputs={"different": True})

    def inbox(actor):
        return journal.channel_inbox(
            channel_id="channel/legacy", actor_id=actor,
            revision=ChannelRevision(message_seq=1, ack_seq=0), after=None, limit=1,
        )

    assert inbox("static:other") == ()
    assert len(inbox("static:legacy-advisor")) == 1
    identity = original.attestation_id
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        if damage == "manifest-seal":
            connection.execute("DELETE FROM durable_fact_seals WHERE family='manifest'"
                               " AND fact_key=?", (str(original.manifest_hash),))
        else:
            draft = draft_of(original).model_copy(update={"manifest_hash": other.manifest_hash})
            identity = attestation_id_for_run(draft, original.created_by_run)
            proof = original.model_copy(update={"attestation_id": identity,
                                                "manifest_hash": other.manifest_hash})
            connection.execute("INSERT INTO attestations VALUES (?, ?)",
                               (identity, proof.model_dump_json()))
            row = connection.execute("SELECT * FROM attestations WHERE attestation_id=?",
                                     (identity,)).fetchone()
            store_durable_fact_seal(connection, family="attestation", fact_key=identity,
                                    selector=identity,
                                    fact_hash=attestation_fact_hash(row, family="attestation"))
            connection.execute("UPDATE channel_messages SET attestation_id=?", (identity,))
            message = connection.execute("SELECT * FROM channel_messages").fetchone()
            reseal_primary_fact(connection, family="channel_message",
                                fact_key=message["message_id"],
                                fact=channel_message_fact_hash(message))
            if damage == "parent-world-seal":
                # Make raw equality agree too: the retained run-world seal
                # must independently refute this unsealed parent-column swap.
                connection.execute("UPDATE runs SET manifest_hash=? WHERE run_id=?",
                                   (str(other.manifest_hash), str(original.created_by_run)))
    with pytest.raises(JournalDamaged):
        inbox("static:other")
    with pytest.raises(JournalDamaged):
        journal.load_attestation(identity)
    with pytest.raises(JournalDamaged):
        journal.run_records(limit=1)


def _command_backed_request(journal, *, clone=False):
    from constructicon.core.channel import request_message_id
    from constructicon.core.control import (
        OPERATE_SCOPE,
        AuthenticatedActor,
        RunCreationPlan,
        RunOrigin,
        SourceRunLock,
        StoredRunCreationPlan,
        command_request_hash,
        run_id_for_command,
    )
    from constructicon.core.identity import digest
    from tests.channel_requests import mint_send_attestation
    from tests.run_worlds import sealed_test_manifest
    from tests.substrate.channels.test_channel_contract import _intent
    from tests.substrate.journal.test_run_projection import _create_command_backed_run

    run, command = _create_command_backed_run(journal, idempotency_key="proof-creator")
    if clone:
        source = run
        manifest = sealed_test_manifest()
        actor = AuthenticatedActor(actor_id="static:run-creator", auth_method="static",
                                   scopes=frozenset({OPERATE_SCOPE}))
        request = {"source_run_id": str(source), "overrides": {}}
        claimed = journal.claim_command(
            actor=actor, operation="runs_reproduce", idempotency_key="proof-clone",
            request_hash=command_request_hash(request), request=request,
            owner_id="test:clone", ttl_s=30,
        )
        assert claimed.claim is not None
        command = claimed.claim.command_id
        run = run_id_for_command(command)
        origin = RunOrigin(kind="reproduce", actor_id=actor.actor_id, command_id=command,
                           source_run_id=source)
        plan = RunCreationPlan(
            run_id=run, manifest=manifest, inputs={}, origin=origin,
            source_lock=SourceRunLock(
                run_id=source, manifest_hash=manifest.manifest_hash, input_hash=manifest.input_hash,
                source_graph_hash=digest("graph-proposal", 1,
                                         manifest.source_graph.model_dump(mode="json")),
            ),
        )
        journal.store_command_plan(claimed.claim, StoredRunCreationPlan(plan=plan).model_dump(
            mode="json",
        ))
        journal.create_run(run, manifest_json=manifest.model_dump_json(),
                           manifest_hash=manifest.manifest_hash, input_hash=manifest.input_hash,
                           inputs={}, origin=origin)
        journal.complete_command(claimed.claim, {"status": "submitted"})
    intent = _intent()
    intent = intent.model_copy(update={
        "run_id": run,
        "message_id": request_message_id(
            run_id=run, path=intent.path, channel_id=intent.channel_id,
            channel_revision=intent.channel_revision, lane=intent.lane,
            interaction=intent.interaction, port=intent.port,
        ),
    })
    proof = mint_send_attestation(journal, intent)
    journal.channel_append_request(channel_id=intent.channel_id, intent=intent,
                                   attestation_id=proof.attestation_id)
    return run, command, intent, proof


@pytest.mark.parametrize("damage", ("command-plan-seal", "clone-lock"))
def test_creator_command_and_clone_authority_cannot_hide_behind_filters(tmp_path, damage):
    from constructicon.core.channel import ChannelRevision
    from constructicon.core.identity import canonical_json, digest, json_value
    from constructicon.substrate.journal._sqlite_commands import command_plan_fact_hash
    from tests.durable_seals import reseal_primary_fact

    database = tmp_path / "creator-command.db"
    journal = SqliteJournal(database)
    run, command, intent, proof = _command_backed_request(journal, clone=damage == "clone-lock")
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        if damage == "command-plan-seal":
            connection.execute("DELETE FROM durable_fact_seals WHERE family='command_plan'"
                               " AND fact_key=?", (command,))
        else:
            import json

            raw = connection.execute("SELECT plan_json FROM commands WHERE command_id=?",
                                     (command,)).fetchone()[0]
            payload = json.loads(raw)
            payload["plan"]["source_lock"]["manifest_hash"] = str(digest("wrong-lock", 1, {}))
            connection.execute("UPDATE commands SET plan_json=? WHERE command_id=?",
                               (canonical_json(json_value(payload)), command))
            row = connection.execute("SELECT * FROM commands WHERE command_id=?",
                                     (command,)).fetchone()
            reseal_primary_fact(connection, family="command_plan", fact_key=command,
                                fact=command_plan_fact_hash(row))
    with pytest.raises(JournalDamaged):
        journal.load_attestation(proof.attestation_id)
    with pytest.raises(JournalDamaged):
        journal.run_records(after=("9999", "past-end"), limit=1)
    with pytest.raises(JournalDamaged):
        journal.latest_run_key()
    with pytest.raises(JournalDamaged):
        journal.channel_inbox(channel_id=intent.channel_id, actor_id="static:other",
                              revision=ChannelRevision(message_seq=1, ack_seq=0),
                              after=None, limit=1)
    assert str(run)


def test_creator_prefilter_and_inbox_projection_share_one_owned_snapshot(tmp_path, monkeypatch):
    from constructicon.core.channel import ChannelRevision
    from constructicon.substrate.journal import _sqlite_attestations

    database = tmp_path / "creator-snapshot.db"
    journal = SqliteJournal(database)
    _run, command, intent, _proof = _command_backed_request(journal)
    validate = _sqlite_attestations._validate_attestation_creator_worlds
    observed = []

    def scheduled(connection):
        assert connection.in_transaction
        validate(connection)
        if not observed:
            with sqlite3.connect(database) as writer:
                writer.execute("DELETE FROM durable_fact_seals WHERE family='command_plan'"
                               " AND fact_key=?", (command,))
            observed.append(True)

    monkeypatch.setattr(_sqlite_attestations, "_validate_attestation_creator_worlds", scheduled)
    deliveries = journal.channel_inbox(
        channel_id=intent.channel_id, actor_id=intent.recipient_actor_id,
        revision=ChannelRevision(message_seq=1, ack_seq=0), after=None, limit=1,
    )
    assert len(deliveries) == 1 and observed == [True]
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM durable_fact_seals"
                                  " WHERE family='command_plan' AND fact_key=?",
                                  (command,)).fetchone() == (0,)
    with pytest.raises(JournalDamaged):
        journal.channel_inbox(channel_id=intent.channel_id, actor_id="static:other",
                              revision=ChannelRevision(message_seq=1, ack_seq=0),
                              after=None, limit=1)
