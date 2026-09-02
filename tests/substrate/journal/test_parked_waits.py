"""Wake recovery reads durable domain facts, never command state."""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest
from tests.conftest import FakeClock, pipeline_graph
from tests.run_worlds import sealed_test_manifest

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.errors import JournalDamaged
from constructicon.core.identity import Digest, canonical_json, digest
from constructicon.core.run import ParkedUnit, RunStatus
from constructicon.substrate.journal._sqlite_execution_facts import seal_event
from constructicon.substrate.journal._sqlite_runs import seal_manifest, seal_run_world
from constructicon.substrate.journal.sqlite import SqliteJournal

PATH = ExecutionPath(scope=ScopePath(segments=("review",)))


def _request(name: str) -> Digest:
    return digest("channel-message", 1, {"request": name})


def _park(
    world: Any,
    journal: SqliteJournal,
    suffix: str,
    *,
    units: tuple[ParkedUnit, ...],
    event_kind: str = "RunParked",
    release: bool = True,
) -> RunId:
    inputs = {"issue": {"title": suffix}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId(f"run-parked-{suffix}")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    lease = journal.claim_run(run_id, owner_id=f"owner-{suffix}", ttl_s=300)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.PARKED,
        event_kind=event_kind,
        payload={
            "parked": [unit.model_dump(mode="json") for unit in units],
            "blocked": [],
        },
    )
    if release:
        journal.release_run(lease)
    return run_id


def test_parked_waits_projects_each_waiting_request_at_its_parking_fence(
    world: Any,
    journal: SqliteJournal,
) -> None:
    advice, approval = _request("advice"), _request("approval")
    run_id = _park(
        world,
        journal,
        "two-waits",
        units=(
            ParkedUnit(path=PATH, reason="awaiting_advisor", waiting_on=advice),
            ParkedUnit(
                path=ExecutionPath(scope=ScopePath(segments=("approve",))),
                reason="awaiting_approval",
                waiting_on=approval,
            ),
        ),
    )

    waits = journal.parked_waits()
    assert [wait.run_id for wait in waits] == [run_id]
    assert set(waits[0].requests) == {advice, approval}
    assert waits[0].event_seq == journal.max_event_seq(run_id)  # the exact fence


def test_a_policy_exhausted_park_projects_no_request_to_wake_on(
    world: Any,
    journal: SqliteJournal,
) -> None:
    """M4 parking is not waiting for anyone; only a reply may wake a wait."""

    _park(
        world,
        journal,
        "exhausted",
        units=(ParkedUnit(path=PATH, reason="policy_exhausted", completed_iterations=3),),
    )
    waits = journal.parked_waits()
    assert len(waits) == 1
    assert waits[0].requests == ()


def test_only_parked_runs_are_projected(world: Any, journal: SqliteJournal) -> None:
    _park(
        world,
        journal,
        "waiting",
        units=(ParkedUnit(path=PATH, reason="awaiting_advisor", waiting_on=_request("a")),),
    )
    inputs = {"issue": {"title": "running"}}
    manifest = world.validate(pipeline_graph(), inputs)
    live = RunId("run-still-running")
    world._prepare_run(manifest, run_id=live, inputs=inputs)
    lease = journal.claim_run(live, owner_id="owner-live", ttl_s=300)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    assert [wait.run_id for wait in journal.parked_waits()] == [RunId("run-parked-waiting")]


def test_another_hosts_valid_completion_during_projection_is_not_damage_or_a_wait(
    world: Any,
    journal: SqliteJournal,
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Status and its parking fence are one snapshot; current progress wins.

    The former two-read projection selected a PARKED row, then asked for its
    latest terminal event on another connection. A second host completing the
    run in between made that later read return RunSucceeded and falsely turned
    ordinary progress into JournalDamaged, stopping recovery for every run.
    """

    scanning = journal
    successor = SqliteJournal(journal._db_path, now_fn=clock.now)
    run_id = _park(
        world,
        scanning,
        "advanced-while-projecting",
        units=(
            ParkedUnit(
                path=PATH,
                reason="awaiting_advisor",
                waiting_on=_request("advanced"),
            ),
        ),
    )

    original = scanning._run_record_from_row
    advanced = False
    parked_fence = scanning.max_event_seq(run_id)

    def decode_after_advancing(row: Any) -> Any:
        nonlocal advanced
        record = original(row)
        if not advanced:
            advanced = True
            lease = successor.claim_run(
                run_id,
                owner_id="successor",
                ttl_s=300,
                expected_event_seq=parked_fence,
                expected_statuses=frozenset({RunStatus.PARKED}),
            )
            successor.transition_run(
                lease,
                expected=frozenset({RunStatus.PARKED}),
                target=RunStatus.RUNNING,
                event_kind="RunResumed",
            )
            successor.transition_run(
                lease,
                expected=frozenset({RunStatus.RUNNING}),
                target=RunStatus.SUCCEEDED,
                event_kind="RunSucceeded",
            )
            successor.release_run(lease)
        return record

    monkeypatch.setattr(scanning, "_run_record_from_row", decode_after_advancing)

    assert scanning.parked_waits() == []
    completed = successor.run_record(run_id)
    assert completed is not None and completed.status is RunStatus.SUCCEEDED


def test_current_fence_lookup_chunks_past_sqlite_bind_ceiling(
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-snapshot fence remains bounded even for a caller's large page."""

    count = 901
    manifest = sealed_test_manifest()
    manifest_hash = manifest.manifest_hash
    input_hash = digest("inputs", 1, {})
    created_at = journal._now_iso()
    payload = canonical_json(
        {
            "parked": [
                ParkedUnit(
                    path=PATH,
                    reason="awaiting_advisor",
                    waiting_on=_request("bind-ceiling"),
                ).model_dump(mode="json")
            ],
            "blocked": [],
        }
    )
    runs = [
        (
            f"run-parked-bind-{index:04d}",
            str(manifest_hash),
            str(input_hash),
            "{}",
            RunStatus.PARKED.value,
            created_at,
        )
        for index in range(count)
    ]
    events = [
        (run_id, 1, "RunParked", payload, created_at)
        for run_id, _manifest, _input, _inputs, _status, _created in runs
    ]
    with journal._txn() as connection:
        connection.execute(
            "INSERT INTO manifests (manifest_hash, manifest_json) VALUES (?, ?)",
            (str(manifest_hash), manifest.model_dump_json()),
        )
        connection.executemany(
            "INSERT INTO runs (run_id, manifest_hash, input_hash, inputs_json,"
            " status, created_at, next_event_seq) VALUES (?, ?, ?, ?, ?, ?, 1)",
            runs,
        )
        connection.executemany(
            "INSERT INTO events (run_id, seq, kind, payload, created_at) VALUES (?, ?, ?, ?, ?)",
            events,
        )
        stored_manifest = connection.execute(
            "SELECT manifest_hash, manifest_json FROM manifests WHERE manifest_hash = ?",
            (str(manifest_hash),),
        ).fetchone()
        assert stored_manifest is not None
        seal_manifest(connection, stored_manifest)
        for row in connection.execute(
            "SELECT r.*, NULL AS origin_json FROM runs AS r"
        ).fetchall():
            seal_run_world(connection, row)
        for row in connection.execute("SELECT * FROM events").fetchall():
            seal_event(connection, row)

    original_connect = journal._connect

    def limited_connect() -> sqlite3.Connection:
        connection = original_connect()
        connection.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 900)
        return connection

    monkeypatch.setattr(journal, "_connect", limited_connect)

    assert len(journal.parked_waits(limit=count)) == count

    victim = RunId(f"run-parked-bind-{count - 1:04d}")  # lives in the second chunk
    original_decode = journal._run_record_from_row
    removed = False

    def decode_after_removing_later_chunk(row: Any) -> Any:
        nonlocal removed
        record = original_decode(row)
        if not removed:
            removed = True
            with sqlite3.connect(journal._db_path) as connection:
                connection.execute("DELETE FROM runs WHERE run_id = ?", (str(victim),))
                connection.commit()
        return record

    monkeypatch.setattr(journal, "_run_record_from_row", decode_after_removing_later_chunk)
    with pytest.raises(JournalDamaged, match="disappeared during projection"):
        journal.parked_waits(limit=count)


def test_a_parked_run_whose_latest_event_is_not_a_park_is_damage(
    world: Any,
    journal: SqliteJournal,
) -> None:
    """Fail closed: a wake that guessed a fence could revive the wrong attempt."""

    _park(
        world,
        journal,
        "mislabelled",
        units=(ParkedUnit(path=PATH, reason="awaiting_advisor", waiting_on=_request("a")),),
        event_kind="RunFailed",
        release=False,
    )
    with pytest.raises(JournalDamaged, match="no latest RunParked event"):
        journal.parked_waits()


def test_a_valid_status_swap_cannot_hide_a_parked_run_from_recovery(
    world: Any,
    journal: SqliteJournal,
) -> None:
    run_id = _park(
        world,
        journal,
        "status-swapped",
        units=(
            ParkedUnit(
                path=PATH,
                reason="awaiting_advisor",
                waiting_on=_request("status-swapped"),
            ),
        ),
    )
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE runs SET status = ? WHERE run_id = ?",
            (RunStatus.FAILED.value, str(run_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="durable lifecycle"):
        journal.latest_run_key(statuses=(RunStatus.PARKED,))
    with pytest.raises(JournalDamaged, match="durable lifecycle"):
        journal.parked_waits()


@pytest.mark.parametrize("stored_status", (RunStatus.PENDING, RunStatus.RUNNING))
def test_pending_and_running_cannot_trade_lifecycle_fences(
    stored_status: RunStatus,
    world: Any,
    journal: SqliteJournal,
) -> None:
    inputs = {"issue": {"title": stored_status.value}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId(f"run-lifecycle-{stored_status.value}")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    if stored_status is RunStatus.PENDING:
        lease = journal.claim_run(run_id, owner_id="owner-lifecycle", ttl_s=300)
        journal.transition_run(
            lease,
            expected=frozenset({RunStatus.PENDING}),
            target=RunStatus.RUNNING,
            event_kind="RunStarted",
        )
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE runs SET status = ? WHERE run_id = ?",
            (stored_status.value, str(run_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="durable lifecycle"):
        journal.latest_run_key(statuses=(RunStatus.PARKED,))


def test_latest_terminal_event_never_falls_back_past_a_damaged_latest_attempt(
    world: Any,
    journal: SqliteJournal,
) -> None:
    inputs = {"issue": {"title": "two-attempt-terminal"}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId("run-two-attempt-terminal")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    lease = journal.claim_run(run_id, owner_id="owner-terminal", ttl_s=300)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.FAILED}),
        target=RunStatus.RUNNING,
        event_kind="RunResumed",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED,
        event_kind="RunFailed",
    )
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE events SET kind = 'NodeFailed'"
            " WHERE run_id = ? AND seq = ("
            " SELECT next_event_seq FROM runs WHERE run_id = ?)",
            (str(run_id), str(run_id)),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="positive seal"):
        journal.latest_terminal_event(run_id)


def test_a_parking_event_with_invalid_units_is_damage(
    world: Any,
    journal: SqliteJournal,
) -> None:
    inputs = {"issue": {"title": "damaged"}}
    manifest = world.validate(pipeline_graph(), inputs)
    run_id = RunId("run-parked-damaged")
    world._prepare_run(manifest, run_id=run_id, inputs=inputs)
    lease = journal.claim_run(run_id, owner_id="owner-damaged", ttl_s=300)
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.PENDING}),
        target=RunStatus.RUNNING,
        event_kind="RunStarted",
    )
    journal.transition_run(
        lease,
        expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.PARKED,
        event_kind="RunParked",
        payload={"parked": [{"reason": "awaiting_advisor"}], "blocked": []},
    )
    with pytest.raises(JournalDamaged, match="invalid parked units"):
        journal.parked_waits()


def test_first_parked_snapshot_refuses_a_coerced_event_fence(
    world: Any,
    journal: SqliteJournal,
) -> None:
    run_id = _park(
        world,
        journal,
        "fractional-first-fence",
        units=(
            ParkedUnit(
                path=PATH,
                reason="awaiting_advisor",
                waiting_on=_request("fractional-first-fence"),
            ),
        ),
    )
    with sqlite3.connect(journal._db_path) as connection:
        connection.execute(
            "UPDATE events SET seq = seq + 0.5 WHERE run_id = ? AND kind = 'RunParked'",
            (str(run_id),),
        )
        connection.execute(
            "UPDATE runs SET next_event_seq = next_event_seq + 0.5 WHERE run_id = ?",
            (str(run_id),),
        )
        connection.commit()

    with pytest.raises(JournalDamaged, match="event sequence"):
        journal.parked_waits()


@pytest.mark.parametrize("fault", ("sequence", "status"))
def test_current_parked_fence_refuses_scalar_coercion(
    fault: str,
    world: Any,
    journal: SqliteJournal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = _park(
        world,
        journal,
        f"damaged-current-{fault}",
        units=(
            ParkedUnit(
                path=PATH,
                reason="awaiting_advisor",
                waiting_on=_request(f"damaged-current-{fault}"),
            ),
        ),
    )
    original = journal._run_record_from_row
    corrupted = False

    def corrupt_after_snapshot(row: Any) -> Any:
        nonlocal corrupted
        record = original(row)
        if corrupted:
            return record
        corrupted = True
        with sqlite3.connect(journal._db_path) as connection:
            if fault == "sequence":
                connection.execute(
                    "UPDATE runs SET next_event_seq = next_event_seq + 0.5 WHERE run_id = ?",
                    (str(run_id),),
                )
            else:
                connection.execute("ALTER TABLE runs RENAME TO runs_typed")
                connection.execute(
                    "CREATE TABLE runs ("
                    " run_id TEXT PRIMARY KEY, manifest_hash TEXT NOT NULL,"
                    " input_hash TEXT NOT NULL, inputs_json TEXT NOT NULL, status,"
                    " created_at TEXT NOT NULL, owner_id TEXT,"
                    " owner_epoch INTEGER NOT NULL DEFAULT 0, owner_pid INTEGER,"
                    " heartbeat_at TEXT, lease_expires_at TEXT,"
                    " next_event_seq INTEGER NOT NULL DEFAULT 0,"
                    " cancel_requested INTEGER NOT NULL DEFAULT 0)"
                )
                connection.execute(
                    "INSERT INTO runs SELECT run_id, manifest_hash, input_hash,"
                    " inputs_json, 7, created_at, owner_id, owner_epoch, owner_pid,"
                    " heartbeat_at, lease_expires_at, next_event_seq, cancel_requested"
                    " FROM runs_typed"
                )
                connection.execute("DROP TABLE runs_typed")
            connection.commit()
        return record

    monkeypatch.setattr(journal, "_run_record_from_row", corrupt_after_snapshot)

    with pytest.raises(JournalDamaged, match=r"current (event sequence|status)"):
        journal.parked_waits()


def test_parked_waits_pages_and_refuses_a_nonpositive_bound(
    world: Any,
    journal: SqliteJournal,
) -> None:
    for index in range(3):
        _park(
            world,
            journal,
            f"page-{index}",
            units=(
                ParkedUnit(
                    path=PATH,
                    reason="awaiting_advisor",
                    waiting_on=_request(f"page-{index}"),
                ),
            ),
        )
    first = journal.parked_waits(limit=2)
    assert len(first) == 2
    record = journal.run_record(first[-1].run_id)
    assert record is not None
    rest = journal.parked_waits(
        after=(record.created_at.isoformat(), str(record.run_id)),
        limit=2,
    )
    assert len(rest) == 1
    assert {wait.run_id for wait in (*first, *rest)} == {
        RunId(f"run-parked-page-{index}") for index in range(3)
    }
    with pytest.raises(ValueError, match="limit must be positive"):
        journal.parked_waits(limit=0)
