"""Run discovery decodes durable state before applying lifecycle semantics."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from tests.conftest import FakeClock
from tests.run_worlds import create_test_run, sealed_test_manifest, start_test_run

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.control import (
    OPERATE_SCOPE,
    AuthenticatedActor,
    RunCreationPlan,
    RunOrigin,
    StoredRunCreationPlan,
    command_request_hash,
    run_id_for_command,
)
from constructicon.core.effect import (
    AttestationDraft,
    CheckResult,
    ComponentProofSubject,
    EffectRequest,
    idempotency_key,
)
from constructicon.core.errors import ContractViolation, JournalDamaged
from constructicon.core.identity import Digest, digest
from constructicon.core.manifest import manifest_hash_for
from constructicon.core.run import RunStatus
from constructicon.substrate.journal._sqlite_execution_facts import event_fact_key
from constructicon.substrate.journal._sqlite_runs import (
    seal_run_world,
)
from constructicon.substrate.journal.sqlite import SqliteJournal

_MANIFEST = sealed_test_manifest()
MANIFEST_HASH = _MANIFEST.manifest_hash
INPUT_HASH = digest("inputs", 1, {})
MUTATION_PATH = ExecutionPath(scope=ScopePath(segments=("mutation-fence",)))
MUTATION_SUBJECT = {"value": "must-not-be-written"}


def _create(journal: SqliteJournal, run_id: RunId) -> None:
    create_test_run(journal, run_id)


def _create_command_backed_run(
    journal: SqliteJournal,
    *,
    idempotency_key: str,
) -> tuple[RunId, str]:
    actor = AuthenticatedActor(
        actor_id="static:run-creator",
        auth_method="static",
        scopes=frozenset({OPERATE_SCOPE}),
    )
    manifest = sealed_test_manifest()
    request = {
        "proposal": manifest.source_graph.model_dump(mode="json"),
        "inputs": {},
    }
    claimed = journal.claim_command(
        actor=actor,
        operation="runs_start",
        idempotency_key=idempotency_key,
        request_hash=command_request_hash(request),
        request=request,
        owner_id="test:run-creator",
        ttl_s=30,
    )
    assert claimed.claim is not None
    run_id = run_id_for_command(claimed.claim.command_id)
    origin = RunOrigin(
        kind="start",
        actor_id=actor.actor_id,
        command_id=claimed.claim.command_id,
    )
    plan = RunCreationPlan(
        run_id=run_id,
        manifest=manifest,
        inputs={},
        origin=origin,
    )
    journal.store_command_plan(
        claimed.claim,
        StoredRunCreationPlan(plan=plan).model_dump(mode="json"),
    )
    journal.create_run(
        run_id,
        manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash,
        input_hash=manifest.input_hash,
        inputs={},
        origin=origin,
    )
    journal.complete_command(claimed.claim, {"status": "submitted"})
    return run_id, claimed.claim.command_id


def _run_mutation_snapshot(database: Path) -> dict[str, tuple[tuple[object, ...], ...]]:
    with sqlite3.connect(database) as connection:
        return {
            table: tuple(connection.execute(f"SELECT * FROM {table} ORDER BY rowid"))
            for table in ("runs", "events", "effects", "attestations")
        }


@pytest.mark.parametrize("fault", ("run_world", "event_history"))
@pytest.mark.parametrize(
    "mutation",
    (
        "claim",
        "append",
        "transition",
        "heartbeat",
        "release",
        "cancel",
        "effect",
        "attestation",
    ),
)
def test_every_run_mutation_revalidates_world_and_event_history_before_writing(
    mutation: str,
    fault: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    run_id = RunId(f"run-mutation-fence-{mutation}-{fault}")
    database = tmp_path / f"mutation-fence-{mutation}-{fault}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    create_test_run(journal, run_id)
    lease = start_test_run(journal, run_id, owner_id="mutation-fence-owner")
    if mutation == "claim":
        journal.release_run(lease)

    effect = EffectRequest(
        run_id=run_id,
        manifest_hash=_MANIFEST.manifest_hash,
        path=MUTATION_PATH,
        kind="mutation-fence",
        subject=MUTATION_SUBJECT,
        idempotency_key=idempotency_key(
            _MANIFEST.manifest_hash,
            MUTATION_PATH,
            "mutation-fence",
            MUTATION_SUBJECT,
        ),
    )
    draft = AttestationDraft(
        action="promote",
        subject=ComponentProofSubject(
            component="test/mutation-fence",
            version=digest("component", 1, {"mutation-fence": True}),
            baseline_version=None,
        ),
        checks=(
            CheckResult(
                name="mutation-fence",
                status="passed",
                detail="must not be retained",
                elapsed_s=0.0,
            ),
        ),
        check_set_hash=digest("check-set", 1, {"mutation-fence": True}),
        manifest_hash=_MANIFEST.manifest_hash,
    )

    with sqlite3.connect(database) as connection:
        if fault == "run_world":
            connection.execute(
                "UPDATE runs SET inputs_json = ? WHERE run_id = ?",
                ('{"forged":true}', str(run_id)),
            )
        else:
            connection.execute(
                "DELETE FROM events WHERE run_id = ? AND seq = 1",
                (str(run_id),),
            )
    before = _run_mutation_snapshot(database)

    with pytest.raises(JournalDamaged):
        if mutation == "claim":
            journal.claim_run(run_id, owner_id="mutation-fence-successor", ttl_s=30)
        elif mutation == "append":
            journal.append_event(lease, "MustNotBeWritten")
        elif mutation == "transition":
            journal.transition_run(
                lease,
                expected=frozenset({RunStatus.RUNNING}),
                target=RunStatus.FAILED,
                event_kind="MustNotBeWritten",
            )
        elif mutation == "heartbeat":
            journal.heartbeat(lease, ttl_s=60)
        elif mutation == "release":
            journal.release_run(lease)
        elif mutation == "cancel":
            journal.request_cancel(run_id)
        elif mutation == "effect":
            journal.record_effect_prepared(lease, effect)
        else:
            assert mutation == "attestation"
            journal.mint_attestation(lease, draft)

    assert _run_mutation_snapshot(database) == before


def test_cancel_distinguishes_a_truly_unknown_run_from_orphan_evidence(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "cancel-unknown-vs-orphan.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    run_id = RunId("run-cancel-unknown-vs-orphan")

    with pytest.raises(ContractViolation, match="unknown run"):
        journal.request_cancel(run_id)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO events (run_id, seq, kind, created_at) VALUES (?, 1, ?, ?)",
            (str(run_id), "OrphanEvidence", clock.now().isoformat()),
        )
    before = _run_mutation_snapshot(database)

    with pytest.raises(JournalDamaged, match="child facts name no retained run"):
        journal.request_cancel(run_id)

    assert _run_mutation_snapshot(database) == before


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("status", "bogus"),
        ("created_at", "not-a-timestamp"),
        ("created_at", "0"),
        ("created_at", "2026-01-01 00:00:00+00:00"),
        ("lease_expires_at", "not-a-timestamp"),
        ("lease_expires_at", "4102444800"),
        ("cancel_requested", 2),
    ),
)
def test_every_run_state_projection_types_durable_scalar_damage(
    column: str,
    value: object,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    run_id = RunId(f"run-damaged-{column}")
    database = tmp_path / f"run-damaged-{column}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    _create(journal, run_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE runs SET {column} = ? WHERE run_id = ?",
            (value, str(run_id)),
        )
        connection.commit()

    projections = (
        lambda: journal.run_record(run_id),
        lambda: journal.run_state(run_id),
        lambda: journal.recoverable_runs(),
    )
    for project in projections:
        with pytest.raises(JournalDamaged, match="not a valid durable") as damaged:
            project()
        assert isinstance(damaged.value.__cause__, ValueError)


def test_cancel_probe_never_applies_python_truthiness_to_durable_damage(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    run_id = RunId("run-damaged-cancel-probe")
    database = tmp_path / "run-damaged-cancel-probe.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    _create(journal, run_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE runs SET cancel_requested = 2 WHERE run_id = ?",
            (str(run_id),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="durable SQLite boolean") as damaged:
        journal.cancel_requested(run_id)
    assert isinstance(damaged.value.__cause__, ValueError)


@pytest.mark.parametrize(
    ("column", "message"),
    (
        ("owner_epoch", "owner epoch"),
        ("next_event_seq", "event sequence"),
    ),
)
def test_claim_refuses_scalar_coercion_before_advancing_the_owner_epoch(
    column: str,
    message: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    run_id = RunId(f"run-damaged-claim-{column}")
    database = tmp_path / f"damaged-claim-{column}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    _create(journal, run_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE runs SET {column} = 0.5 WHERE run_id = ?",
            (str(run_id),),
        )
        before = connection.execute(
            "SELECT owner_id, owner_epoch, next_event_seq FROM runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        connection.commit()

    with pytest.raises(JournalDamaged, match=message):
        journal.claim_run(run_id, owner_id="new-owner", ttl_s=30)

    with sqlite3.connect(database) as connection:
        after = connection.execute(
            "SELECT owner_id, owner_epoch, next_event_seq FROM runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
    assert after == before


def test_event_allocation_refuses_a_coercible_sequence_without_healing_it(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    run_id = RunId("run-damaged-event-allocation")
    database = tmp_path / "damaged-event-allocation.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    _create(journal, run_id)
    lease = journal.claim_run(run_id, owner_id="event-owner", ttl_s=30)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE runs SET next_event_seq = 0.5 WHERE run_id = ?",
            (str(run_id),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="event sequence"):
        journal.append_event(lease, "MustNotBeWritten")

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT next_event_seq FROM runs WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()
        event_count = connection.execute(
            "SELECT COUNT(*) FROM events WHERE run_id = ?",
            (str(run_id),),
        ).fetchone()[0]
    assert row[0] == 0.5
    assert event_count == 0


def test_a_malformed_run_time_cannot_become_a_cursor_cut(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    run_id = RunId("run-damaged-cursor-cut")
    database = tmp_path / "run-damaged-cursor-cut.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    _create(journal, run_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE runs SET created_at = ? WHERE run_id = ?",
            ("not-a-timestamp", str(run_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="not a valid durable timestamp"):
        journal.latest_run_key()


def test_recovery_filters_typed_state_then_orders_and_limits_results(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "recoverable-order.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    expired = RunId("run-expired")
    pending = RunId("run-pending")
    live = RunId("run-live")
    terminal = RunId("run-terminal")
    _create(journal, live)
    clock.advance(1)
    _create(journal, expired)
    clock.advance(1)
    _create(journal, pending)
    clock.advance(1)
    _create(journal, terminal)
    expired_lease = journal.claim_run(expired, owner_id="expired-owner", ttl_s=1)
    journal.transition_run(
        expired_lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    live_lease = journal.claim_run(live, owner_id="live-owner", ttl_s=30)
    journal.transition_run(
        live_lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    terminal_lease = journal.claim_run(terminal, owner_id="terminal-owner", ttl_s=30)
    journal.transition_run(
        terminal_lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        terminal_lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.SUCCEEDED,
        event_kind="RunSucceeded",
    )
    clock.advance(2)

    expired_state = journal.run_state(expired)
    live_state = journal.run_state(live)
    assert expired_state is not None and expired_state.liveness == "lost"
    assert live_state is not None and live_state.liveness == "live"
    assert journal.recoverable_runs() == [expired, pending]
    assert journal.recoverable_runs(limit=1) == [expired]


def test_run_projection_never_invents_an_identity_from_sql_null(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "null-run-id.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    _create(journal, RunId("run-null-id"))
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE runs SET run_id = NULL")
        connection.commit()

    projections = (journal.run_records, journal.recoverable_runs)
    for project in projections:
        with pytest.raises(JournalDamaged, match=r"run state|run origin history"):
            project()


def test_an_empty_run_origin_is_damage_not_historical_absence(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    run_id = RunId("run-empty-origin")
    database = tmp_path / "empty-origin.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    _create(journal, run_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO run_origins (run_id, origin_json) VALUES (?, '')",
            (str(run_id),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="run origin history"):
        journal.run_record(run_id)


def test_recovery_keeps_sql_work_bounded_with_many_live_runs(
    tmp_path: Path,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "bounded-recovery.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    pending = RunId("run-bounded-pending")
    _create(journal, pending)
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        connection.executemany(
            "INSERT INTO runs (run_id, manifest_hash, input_hash, inputs_json,"
            " status, created_at, owner_id, lease_expires_at, next_event_seq)"
            " VALUES (?, ?, ?, '{}', 'running', ?, 'live-owner', ?, 1)",
            (
                (
                    f"run-live-{index:04d}",
                    str(MANIFEST_HASH),
                    str(INPUT_HASH),
                    "2026-01-01T00:00:00+00:00",
                    "2027-01-01T00:00:00+00:00",
                )
                for index in range(1_000)
            ),
        )
        connection.executemany(
            "INSERT INTO events (run_id, seq, kind, created_at)"
            " VALUES (?, 1, 'RunStarted', ?)",
            (
                (f"run-live-{index:04d}", "2026-01-01T00:00:00+00:00")
                for index in range(1_000)
            ),
        )
        for row in connection.execute(
            "SELECT r.*, o.origin_json FROM runs AS r"
            " LEFT JOIN run_origins AS o ON o.run_id = r.run_id"
            " WHERE r.run_id LIKE 'run-live-%'"
        ).fetchall():
            seal_run_world(connection, row)
        connection.commit()
    statements: list[str] = []
    original_connect = journal._connect

    def traced_connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(journal, "_connect", traced_connect)

    assert journal.recoverable_runs(limit=2) == [pending]
    recovery_selects = [
        statement
        for statement in statements
        if statement.startswith("SELECT r.*, o.origin_json") and " FROM runs AS r " in statement
    ]
    assert len(recovery_selects) == 1
    assert " LIMIT 2" in recovery_selects[0]


def test_a_valid_terminal_status_cannot_hide_a_pending_run_from_recovery(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "pending-status-swap.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    run_id = RunId("run-pending-status-swap")
    _create(journal, run_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE runs SET status = ? WHERE run_id = ?",
            (RunStatus.FAILED.value, str(run_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="durable lifecycle"):
        journal.recoverable_runs()


def test_a_deleted_run_cannot_hide_its_append_only_children(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "orphan-run-events.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    run_id = RunId("run-deleted-with-events")
    _create(journal, run_id)
    lease = journal.claim_run(run_id, owner_id="deleted-run-owner", ttl_s=30)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM runs WHERE run_id = ?", (str(run_id),))

    reads = (
        lambda: journal.run_state(run_id),
        lambda: journal.run_record(run_id),
        lambda: journal.events(run_id),
        lambda: journal.max_event_seq(run_id),
        journal.recoverable_runs,
    )
    for read in reads:
        with pytest.raises(JournalDamaged, match="child facts name no retained run"):
            read()


def test_a_committed_creation_command_cannot_outlive_its_created_run(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "deleted-created-run.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    run_id, _command_id = _create_command_backed_run(
        journal,
        idempotency_key="deleted-created-run",
    )
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM run_origins WHERE run_id = ?", (str(run_id),))
        connection.execute("DELETE FROM runs WHERE run_id = ?", (str(run_id),))
        connection.execute(
            "DELETE FROM durable_fact_seals"
            " WHERE family = 'run_world' AND fact_key = ?",
            (str(run_id),),
        )

    for read in (lambda: journal.run_record(run_id), journal.recoverable_runs):
        with pytest.raises(JournalDamaged, match="child facts name no retained run"):
            read()


@pytest.mark.parametrize(
    "damage",
    ("missing_run", "missing_event", "missing_manifest"),
)
def test_run_inventory_projects_both_sides_of_the_event_fence(
    damage: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / f"run-inventory-{damage}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    run_id = RunId(f"run-inventory-{damage}")
    manifest = create_test_run(journal, run_id)
    start_test_run(journal, run_id, owner_id="run-inventory-owner")
    with sqlite3.connect(database) as connection:
        if damage == "missing_run":
            connection.execute(
                "DELETE FROM durable_fact_seals"
                " WHERE family = 'run_world' AND fact_key = ?",
                (str(run_id),),
            )
            connection.execute("DELETE FROM runs WHERE run_id = ?", (str(run_id),))
        elif damage == "missing_event":
            connection.execute(
                "DELETE FROM durable_fact_seals"
                " WHERE family = 'event' AND fact_key = ?",
                (event_fact_key(run_id, 1),),
            )
            connection.execute(
                "DELETE FROM events WHERE run_id = ? AND seq = 1",
                (str(run_id),),
            )
        else:
            connection.execute(
                "DELETE FROM durable_fact_seals"
                " WHERE family = 'manifest' AND fact_key = ?",
                (str(manifest.manifest_hash),),
            )
            connection.execute(
                "DELETE FROM manifests WHERE manifest_hash = ?",
                (str(manifest.manifest_hash),),
            )
        connection.commit()
    with pytest.raises(JournalDamaged):
        SqliteJournal(database, now_fn=clock.now)


def test_run_inventory_reaches_the_creation_command_from_its_run(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "run-inventory-missing-creation-command.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    _run_id, command_id = _create_command_backed_run(
        journal,
        idempotency_key="run-inventory-missing-creation-command",
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM durable_fact_seals WHERE fact_key = ?"
            " AND family IN ('command_claim', 'command_plan', 'command_terminal')",
            (command_id,),
        )
        connection.execute("DELETE FROM commands WHERE command_id = ?", (command_id,))
        connection.commit()
    with pytest.raises(
        JournalDamaged,
        match=r"creation command|dependent durable fact",
    ):
        SqliteJournal(database, now_fn=clock.now)


def test_an_originless_run_cannot_be_moved_to_another_valid_manifest_world(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "run-world-swap.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    run_id = RunId("run-world-swap")
    original = create_test_run(journal, run_id)
    contender = original.model_copy(
        update={
            "world_hash": digest("test-world", 1, {"other": True}),
            "manifest_hash": Digest("sha256:" + "0" * 64),
        }
    )
    contender = contender.model_copy(
        update={"manifest_hash": manifest_hash_for(contender)}
    )
    journal.create_run(
        RunId("run-world-contender"),
        manifest_json=contender.model_dump_json(),
        manifest_hash=contender.manifest_hash,
        input_hash=contender.input_hash,
        inputs={},
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE runs SET manifest_hash = ? WHERE run_id = ?",
            (str(contender.manifest_hash), str(run_id)),
        )

    reads = (
        lambda: journal.run_manifest_hash(run_id),
        lambda: journal.run_inputs(run_id),
        lambda: journal.run_record(run_id),
        journal.recoverable_runs,
    )
    for read in reads:
        with pytest.raises(JournalDamaged, match=r"positive seal|origin history"):
            read()


def test_a_relocated_manifest_cannot_hide_behind_either_relational_key(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "manifest-relocation.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    run_id = RunId("run-manifest-relocation")
    manifest = create_test_run(journal, run_id)
    relocated = digest("manifest-relocation", 1, {"target": True})
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE manifests SET manifest_hash = ? WHERE manifest_hash = ?",
            (str(relocated), str(manifest.manifest_hash)),
        )

    for identity in (manifest.manifest_hash, relocated):
        with pytest.raises(
            JournalDamaged,
            match=r"(valid durable manifest|positive seal)",
        ):
            journal.load_manifest_json(identity)
    with pytest.raises(
        JournalDamaged,
        match=r"(valid durable manifest|positive seal)",
    ):
        create_test_run(journal, run_id)


def test_a_deleted_manifest_cannot_be_reminted_by_run_creation(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "deleted-manifest.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    run_id = RunId("run-deleted-manifest")
    manifest = create_test_run(journal, run_id)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "DELETE FROM manifests WHERE manifest_hash = ?",
            (str(manifest.manifest_hash),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="positive seal without its row"):
        journal.load_manifest_json(manifest.manifest_hash)
    with pytest.raises(JournalDamaged, match="positive seal without its row"):
        journal.create_run(
            RunId("run-manifest-remint-attempt"),
            manifest_json=manifest.model_dump_json(),
            manifest_hash=manifest.manifest_hash,
            input_hash=manifest.input_hash,
            inputs={},
        )
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM manifests").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM runs WHERE run_id = 'run-manifest-remint-attempt'"
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    ("column", "value"),
    (
        ("lease_expires_at", "2999-01-01"),
        ("lease_expires_at", "2999-02-30T00:00:00+00:00"),
        ("lease_expires_at", "4102444800"),
        ("created_at", "2999-01-01"),
        ("created_at", "2999-02-30T00:00:00+00:00"),
        ("created_at", "0"),
    ),
)
def test_live_run_timestamp_damage_cannot_hide_behind_sqlite_date_coercion(
    column: str,
    value: str,
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    run_id = RunId(f"run-coercible-{column}-{len(value)}")
    database = tmp_path / f"coercible-{column}-{len(value)}.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    _create(journal, run_id)
    journal.claim_run(run_id, owner_id="live-owner", ttl_s=30)
    with sqlite3.connect(database) as connection:
        connection.execute(
            f"UPDATE runs SET status = 'running', {column} = ? WHERE run_id = ?",
            (value, str(run_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="durable timestamp"):
        journal.run_state(run_id)
    with pytest.raises(JournalDamaged, match="durable timestamp"):
        journal.recoverable_runs()


def test_recovery_limit_uses_exact_microsecond_lease_ordering(
    tmp_path: Path,
    clock: FakeClock,
) -> None:
    database = tmp_path / "microsecond-recovery.db"
    journal = SqliteJournal(database, now_fn=clock.now)
    live = RunId("run-live-for-100-microseconds")
    pending = RunId("run-pending-behind-live")
    _create(journal, live)
    lease = journal.claim_run(live, owner_id="brief-owner", ttl_s=0.0001)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    _create(journal, pending)

    live_state = journal.run_state(live)
    assert live_state is not None and live_state.liveness == "live"
    assert journal.recoverable_runs(limit=1) == [pending]
