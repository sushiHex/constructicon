"""Historical diagnosis validates selected facts without activating the application."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest
from tests.run_worlds import sealed_test_manifest, start_test_run

from constructicon.core.address import ExecutionPath, GitSha, RunId, ScopePath
from constructicon.core.effect import AttestationDraft, CheckResult, MergeSubject
from constructicon.core.envelope import Envelope, GitRef, utc_now
from constructicon.core.identity import digest
from constructicon.core.journal import Checkpoint
from constructicon.core.maintenance import PlanManifestRequest
from constructicon.core.manifest import manifest_hash_for
from constructicon.core.run import RunStatus
from constructicon.core.workspace import acquisition_id_for, lease_id_for
from constructicon.substrate.journal import maintenance_diagnostic as diagnostic
from constructicon.substrate.journal.sqlite import SqliteJournal

RUN = RunId("run-" + "1" * 32)
AUTH = "fixed-maintenance-authorization"
PRIVATE = "PRIVATE-MARKER-path-credential-error-output"
WRITER = ExecutionPath(scope=ScopePath(segments=(diagnostic.GRAPH, "writer")))
CHECKER = ExecutionPath(scope=ScopePath(segments=(diagnostic.GRAPH, "checker")))
REQUEST = PlanManifestRequest(repository=PRIVATE, target_ref="refs/heads/maintenance",
    base_commit=GitSha("a" * 40), target_sha256="b" * 64,
    check_set_hash=digest("maintenance-test-checks", 1, {}))
CANDIDATE = GitRef(repository=PRIVATE, commit=GitSha("c" * 40),
                   diff_against=REQUEST.base_commit)


@pytest.fixture(autouse=True)
def windows_birthtime_boundary(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proven Windows-only difference: lstat's birthtime and fstat's ctime differ
    # even for one unchanged newly-created file. Native production stays strict.
    if os.name == "nt":
        identity = diagnostic._identity
        monkeypatch.setattr(diagnostic, "_identity", lambda value: (*identity(value)[:-1], 0))


def _world(root: Path) -> SqliteJournal:
    root.mkdir()
    journal = SqliteJournal(root / "maintenance.sqlite")
    inputs = {"request": REQUEST.model_dump(mode="json")}
    manifest = sealed_test_manifest(inputs)
    graph = manifest.source_graph.model_copy(update={"name": diagnostic.GRAPH})
    manifest = manifest.model_copy(update={"source_graph": graph,
        "source_graph_hash": digest("graph", 1, graph.model_dump(mode="json"))})
    manifest = manifest.model_copy(update={"manifest_hash": manifest_hash_for(manifest)})
    journal.create_run(RUN, manifest_json=manifest.model_dump_json(),
        manifest_hash=manifest.manifest_hash, input_hash=manifest.input_hash, inputs=inputs)
    return journal


def _snapshot(source: Path, destination: Path) -> Path:
    destination.mkdir()
    entries: dict[str, object] = {}
    for name in diagnostic.FILES:
        path = source / name
        if not path.exists():
            entries[name] = {"present": False}
            continue
        raw = path.read_bytes()
        (destination / name).write_bytes(raw)
        entries[name] = {"present": True, "bytes": len(raw),
                         "sha256": hashlib.sha256(raw).hexdigest(), "metadata": {}}
    (destination / "manifest.json").write_text(json.dumps({"schema_version": 1,
        "complete": True, "files": entries}), encoding="utf-8")
    return destination


def _attempt(root: Path, phase: str = "outcome", *, dispatch: str = "not dispatched",
             status: str | None = "failure") -> None:
    record: dict[str, object] = {"authorization_id": AUTH, "run_id": RUN, "epoch": 1,
        "purpose": "plan-manifest-maintenance", "phase": phase,
        "at": "2026-10-14T00:00:00+00:00",
        "acquisition_id": acquisition_id_for(lease_id_for(RUN, WRITER, "executor"), 1)}
    if phase == "outcome":
        record.update(dispatch=dispatch, facts={"status": status,
            "refusal": "unavailable: " + PRIVATE, "served_model": PRIVATE,
            "usage": PRIVATE, "relay": PRIVATE,
            "process": {"timed_out": False, "bound_exceeded": True, "stderr": PRIVATE}})
    (root / "maintenance-attempt.json").write_text(json.dumps(record), encoding="utf-8")


def _bytes(root: Path) -> dict[str, bytes]:
    return {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}


def test_selected_failure_facts_and_attempt_are_private_and_originals_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "original"
    journal = _world(source)
    lease = start_test_run(journal, RUN, owner_id=PRIVATE)
    journal.append_event(lease, "NodeStarted", path=WRITER)
    journal.append_event(lease, "NodeFailed", path=WRITER, payload={
        "error_type": "ContractViolation", "error": "maintenance writer did not positively succeed",
        "private-extra": PRIVATE})
    journal.transition_run(lease, expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED, event_kind="RunFailed", payload={"error": PRIVATE})
    _attempt(source)
    (source / "application-run.json").write_text(json.dumps({"accepted": False,
        "run_id": RUN}), encoding="utf-8")
    snapshot = _snapshot(source, tmp_path / "capture")
    original, captured = _bytes(source), _bytes(snapshot)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("diagnosis must not construct/migrate a SqliteJournal")

    monkeypatch.setattr(SqliteJournal, "__init__", forbidden)
    report = diagnostic.analyze_snapshot(snapshot, RUN, AUTH)
    assert report["complete"] is True
    assert report["run_id"] == RUN
    assert report["command"] == "normal-nonacceptance"
    assert report["journal"] == {"observation": "selected-facts-validated", "status": "failed",
        "command_origin": "unrecorded", "events_checked": 4, "nodes": {
            "writer": {"started": "observed", "checkpoint": "missing", "failures": [
                {"type": "ContractViolation", "cause": "writer-not-positive"}]},
            "checker": {"started": "unrecorded", "checkpoint": "missing", "failures": []}},
        "checks": []}
    assert report["attempt"] == {"observation": "identity-matched", "phase": "outcome",
        "dispatch": "not dispatched", "callbacks": "unrecorded", "executor_status": "failure",
        "failure_kind": "unavailable", "process": {"timed_out": False, "bound_exceeded": True}}
    assert PRIVATE not in json.dumps(report)
    assert len(json.dumps(report).encode()) <= diagnostic.MAX_REPORT_BYTES
    assert _bytes(source) == original
    assert _bytes(snapshot) == captured


def test_real_committed_wal_only_failure_is_observed(tmp_path: Path) -> None:
    source = tmp_path / "original"
    journal = _world(source)
    # Keep a connection open so the production writer's last close does not checkpoint WAL.
    keeper = sqlite3.connect(source / "maintenance.sqlite")
    try:
        keeper.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        lease = start_test_run(journal, RUN, owner_id="fixture")
        journal.append_event(lease, "NodeFailed", path=WRITER, payload={
            "error_type": "ContractViolation",
            "error": "maintenance capture differs from the requested candidate"})
        assert (source / "maintenance.sqlite-wal").stat().st_size > 0
        snapshot = _snapshot(source, tmp_path / "capture")
        report = diagnostic.analyze_snapshot(snapshot, RUN, AUTH)
        assert report["complete"] is True
        world = report["journal"]
        assert isinstance(world, dict)
        assert world["status"] == "running"
        assert world["nodes"]["writer"]["failures"] == [
            {"type": "ContractViolation", "cause": "capture-mismatch"}]
        # Positive sentinel: a main-DB-only view demonstrably lacks the committed fact.
        bare = tmp_path / "bare.sqlite"
        bare.write_bytes((snapshot / "maintenance.sqlite").read_bytes())
        with sqlite3.connect(bare) as connection:
            assert connection.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    finally:
        keeper.close()


def test_writer_checkpoint_and_failed_gate_attestation_are_distinct(tmp_path: Path) -> None:
    source = tmp_path / "original"
    journal = _world(source)
    lease = start_test_run(journal, RUN, owner_id="fixture")
    journal.append_event(lease, "NodeStarted", path=WRITER)
    journal.record_completion(lease, Checkpoint(run_id=RUN, path=WRITER,
        input_hash=digest("inputs", 1, {}), resolved_version=None, outputs={"candidate": Envelope(
            run_id=RUN, path=WRITER, port="candidate", created_at=utc_now(),
            payload=CANDIDATE.model_dump(mode="json"))}))
    journal.append_event(lease, "NodeStarted", path=CHECKER)
    journal.mint_attestation(lease, AttestationDraft(action="merge", subject=MergeSubject(
        repository=REQUEST.repository, target_ref=REQUEST.target_ref,
        candidate=CANDIDATE.commit, expected_base=REQUEST.base_commit,
        merge_commit=GitSha("d" * 40), tested_tree=GitSha("e" * 40)),
        checks=(CheckResult(name="plan-manifest-trusted-vectors", status="failed",
                            detail=PRIVATE, elapsed_s=0),),
        check_set_hash=REQUEST.check_set_hash, manifest_hash=journal.run_manifest_hash(RUN)))
    journal.append_event(lease, "NodeFailed", path=CHECKER, payload={
        "error_type": "ContractViolation", "error": "maintenance candidate failed its exact gate"})
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is True
    world = report["journal"]
    assert isinstance(world, dict)
    assert world["nodes"]["writer"]["checkpoint"] == "validated"
    assert world["nodes"]["checker"]["checkpoint"] == "missing"
    assert world["nodes"]["checker"]["failures"] == [
        {"type": "ContractViolation", "cause": "gate-not-positive"}]
    assert world["checks"] == [{"name": "plan-manifest-trusted-vectors", "status": "failed"}]
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize("phase,dispatch,status", [("acquired", "not dispatched", None),
    ("intent", "not dispatched", None), ("outcome", "not dispatched", "failure"),
    ("outcome", "possibly dispatched", "partial"), ("outcome", "completed", "success")])
def test_attempt_phases_are_observations_not_inferred_completion(
    tmp_path: Path, phase: str, dispatch: str, status: str | None,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _attempt(source, phase, dispatch=dispatch, status=status)
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is True
    attempt = report["attempt"]
    assert isinstance(attempt, dict)
    assert attempt["phase"] == phase
    assert attempt["dispatch"] == (dispatch if phase == "outcome" else "unknown")
    assert report["journal"] == {"observation": "missing"}


@pytest.mark.parametrize("record,expected", [
    ({"accepted": False, "error": "maintenance command refused or incomplete"}, "command-refused"),
    ({"accepted": False, "run_id": RUN}, "normal-nonacceptance"),
    ({"accepted": True, "run_id": RUN}, "accepted"),
    ({"accepted": 0, "run_id": RUN}, None),
    ({"accepted": False, "error": PRIVATE}, None),
    ({"accepted": False, "run_id": RUN, "extra": PRIVATE}, None),
])
def test_command_report_preserves_checker_ambiguity_without_raw_text(
    tmp_path: Path, record: dict[str, object], expected: str | None,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "application-run.json").write_text(json.dumps(record), encoding="utf-8")
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is (expected is not None)
    if expected is not None:
        assert report["command"] == expected
    else:
        assert report["stage"] == "command"
    assert PRIVATE not in json.dumps(report)


@pytest.mark.parametrize("fault", ["seal", "schema", "event-bound"])
def test_journal_damage_or_bound_exhaustion_refuses_instead_of_reporting_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    source = tmp_path / "source"
    journal = _world(source)
    lease = start_test_run(journal, RUN, owner_id="fixture")
    journal.append_event(lease, "NodeStarted", path=WRITER)
    if fault == "seal":
        with sqlite3.connect(source / "maintenance.sqlite") as connection:
            connection.execute("UPDATE events SET payload = ? WHERE kind = 'NodeStarted'",
                               (json.dumps({"private": PRIVATE}),))
    elif fault == "schema":
        with sqlite3.connect(source / "maintenance.sqlite") as connection:
            connection.execute("PRAGMA user_version=8")
    elif fault == "event-bound":
        monkeypatch.setattr(diagnostic, "MAX_EVENTS", 1)
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report == {"schema_version": 1, "complete": False, "stage": "journal",
                      "error": "diagnostic refused or incomplete"}


def test_sql_budget_binds_and_connection_refuses_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "fake.sqlite"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE fixture(value)")
    monkeypatch.setattr(diagnostic, "MAX_SQL_STEPS", 1000)
    connection = diagnostic._connection(path)
    try:
        with pytest.raises(sqlite3.OperationalError, match="interrupted"):
            connection.execute("WITH RECURSIVE n(x) AS (VALUES(0) UNION ALL "
                "SELECT x+1 FROM n WHERE x<10000) SELECT sum(x) FROM n").fetchone()
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("INSERT INTO fixture VALUES (1)")
    finally:
        connection.close()


@pytest.mark.parametrize("fault", [None, "partial", "failed"])
async def test_actual_application_fake_first_lifecycle_is_diagnosed(
    tmp_path: Path, fault: str | None,
) -> None:
    from tests.api.test_control_response_loss import RUN_ACTOR
    from tests.api.test_plan_manifest_application import INPUTS, register, world
    from tests.runtime.test_async_workspace import until

    from constructicon.core.control import RunSubmission

    source = tmp_path / "source"
    source.mkdir()
    journal = SqliteJournal(source / "maintenance.sqlite")
    _, control, _ = world(journal, partial=fault == "partial", fault=fault)
    await control.startup()
    try:
        graph = await register(control)
        submission = await control.runs_start(RUN_ACTOR, proposal=graph, inputs=INPUTS,
                                              idempotency_key="diagnostic-fixture")
        assert isinstance(submission, RunSubmission)
        expected = RunStatus.SUCCEEDED if fault is None else RunStatus.FAILED
        await until(lambda: journal.run_state(submission.run_id).status is expected)
    finally:
        await control.shutdown()
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"),
                                         submission.run_id, AUTH)
    assert report["complete"] is True
    recorded = report["journal"]
    assert isinstance(recorded, dict)
    assert recorded["command_origin"] == "validated"
    assert recorded["status"] == expected.value
    assert recorded["nodes"]["writer"]["checkpoint"] == (
        "missing" if fault == "partial" else "validated")
    assert recorded["nodes"]["checker"]["checkpoint"] == (
        "validated" if fault is None else "missing")
    if fault == "partial":
        assert recorded["nodes"]["writer"]["failures"] == [
            {"type": "ContractViolation", "cause": "writer-not-positive"}]
    else:
        assert recorded["checks"] == [{"name": "unknown",
                                        "status": "passed" if fault is None else "failed"}]


def test_identity_mismatch_and_pending_record_never_promoted(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _attempt(source, "intent")
    (source / "maintenance-attempt.json").rename(source / "maintenance-attempt.json.next")
    snapshot = _snapshot(source, tmp_path / "capture")
    report = diagnostic.analyze_snapshot(snapshot, RUN, AUTH)
    assert report["complete"] is True
    assert report["attempt"] == {"observation": "missing"}
    assert report["pending_attempt"] == "identity-matched-not-published"
    refused = diagnostic.analyze_snapshot(snapshot, RUN, "wrong-authorization")
    assert refused["complete"] is False and refused["stage"] == "attempt"


def test_snapshot_hash_mismatch_refuses_and_cli_errors_are_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _attempt(source)
    snapshot = _snapshot(source, tmp_path / "capture")
    (snapshot / "maintenance-attempt.json").write_text(PRIVATE, encoding="utf-8")
    report = diagnostic.analyze_snapshot(snapshot, RUN, AUTH)
    assert report["complete"] is False and report["stage"] == "snapshot"
    assert diagnostic.main(["--unexpected-private-argument", PRIVATE]) == 1
    output = capsys.readouterr()
    assert PRIVATE not in output.out + output.err
    assert json.loads(output.out)["complete"] is False


def test_historical_result_shape_is_observed_not_revalidated_as_current(tmp_path: Path) -> None:
    from constructicon.core.gates import MergeEvaluation
    from constructicon.core.maintenance import PlanManifestResult

    source = tmp_path / "source"
    source.mkdir()
    result = PlanManifestResult(run_id=RUN, candidate=CANDIDATE,
        evaluation=MergeEvaluation(subject=None, attestation_id=None, checks=()),
        input_sha256="a" * 64, render_sha256="b" * 64)
    (source / "maintenance-result.json").write_text(json.dumps({"schema_version": 1,
        "meaning": "historical-application-acceptance",
        "authorization_digest": "sha256:" + "c" * 64,
        "result": result.model_dump(mode="json")}), encoding="utf-8")
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is True
    assert report["result"] == "historical-acceptance-observed"
    assert report["journal"] == {"observation": "missing"}
    assert PRIVATE not in json.dumps(report)


def test_unknown_failure_text_never_crosses_closed_output(tmp_path: Path) -> None:
    source = tmp_path / "source"
    journal = _world(source)
    lease = start_test_run(journal, RUN, owner_id=PRIVATE)
    journal.append_event(lease, "NodeFailed", path=WRITER, payload={
        "error_type": PRIVATE, "error": PRIVATE})
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is True
    world = report["journal"]
    assert isinstance(world, dict)
    assert world["nodes"]["writer"]["failures"] == [{"type": "unknown", "cause": "unknown"}]

    allowed = {RUN, "selected-historical-facts-only", "selected-facts-validated", "running",
               "unrecorded", "missing", "unknown"}

    def walk(value: object) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            assert len(value) <= diagnostic.MAX_EVENTS
            for item in value:
                walk(item)
        elif isinstance(value, str):
            assert value in allowed
        elif type(value) is int:
            assert 0 <= value <= diagnostic.MAX_EVENTS
        else:
            assert value is None or type(value) is bool

    walk(report)
    assert len(json.dumps(report).encode()) <= diagnostic.MAX_REPORT_BYTES


def test_callback_prefix_is_bounded_and_pending_does_not_add_dispatch_proof(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _attempt(source, "intent")
    path = source / "maintenance-attempt.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["callbacks"] = {"schema_version": 1, "admitted_started": 8,
        "admitted_completed": 7, "worker_results": ["success"] * 7 + [None]}
    path.write_text(json.dumps(record), encoding="utf-8")
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is True
    attempt = report["attempt"]
    assert isinstance(attempt, dict)
    assert attempt["callbacks"] == record["callbacks"]
    assert attempt["dispatch"] == "unknown"
    record["callbacks"]["admitted_started"] = 9
    record["callbacks"]["worker_results"].append(None)
    path.write_text(json.dumps(record), encoding="utf-8")
    refused = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "second-capture"), RUN, AUTH)
    assert refused["complete"] is False and refused["stage"] == "attempt"


def test_output_bound_binds_and_orphan_sidecars_are_not_silently_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    snapshot = _snapshot(source, tmp_path / "capture")
    with monkeypatch.context() as bounded:
        bounded.setattr(diagnostic, "MAX_REPORT_BYTES", 1)
        report = diagnostic.analyze_snapshot(snapshot, RUN, AUTH)
        assert report["complete"] is False and report["stage"] == "output"
    (source / "maintenance.sqlite-wal").write_bytes(b"private orphan WAL")
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "second-capture"), RUN, AUTH)
    assert report["complete"] is False and report["stage"] == "journal"


@pytest.mark.parametrize("dispatch,status", [("completed", "success"),
                                            ("not dispatched", "success")])
def test_successful_attempt_cannot_claim_incomplete_callback_responses(
    tmp_path: Path, dispatch: str, status: str,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    _attempt(source, dispatch=dispatch, status=status)
    path = source / "maintenance-attempt.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["callbacks"] = {"schema_version": 1, "admitted_started": 1,
                           "admitted_completed": 0, "worker_results": [None]}
    path.write_text(json.dumps(record), encoding="utf-8")
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "capture"), RUN, AUTH)
    assert report["complete"] is False and report["stage"] == "attempt"
    record["callbacks"] = {"schema_version": 1, "admitted_started": 1,
                           "admitted_completed": 1, "worker_results": ["success"]}
    path.write_text(json.dumps(record), encoding="utf-8")
    report = diagnostic.analyze_snapshot(_snapshot(source, tmp_path / "second-capture"), RUN, AUTH)
    assert report["complete"] is True


def test_real_capture_analysis_and_cli_preserve_wal_fact_and_originals(
    portable_capture_custody: None, capsys: pytest.CaptureFixture[str],
) -> None:
    from constructicon.substrate.journal import maintenance_evidence as evidence

    with tempfile.TemporaryDirectory(prefix="maintenance-composition-test-",
                                     dir=Path.home()) as temporary:
        parent = Path(temporary).resolve()
        parent.chmod(0o700)
        source = parent / "app"
        journal = _world(source)
        source.chmod(0o700)
        state = parent / "state"
        state.mkdir(mode=0o700)
        command = state / "application-run.json"
        command.write_text(json.dumps({"accepted": False, "run_id": RUN}), encoding="utf-8")
        command.chmod(0o600)
        keeper = sqlite3.connect(source / "maintenance.sqlite")
        try:
            keeper.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            lease = start_test_run(journal, RUN, owner_id="fixture")
            journal.append_event(lease, "NodeFailed", path=WRITER, payload={
                "error_type": "ContractViolation",
                "error": "maintenance writer did not positively succeed"})
            for path in source.iterdir():
                path.chmod(0o600)
            assert (source / "maintenance.sqlite-wal").stat().st_size > 0

            def inventory(root: Path) -> dict[str, object]:
                return {path.name: (path.read_bytes(), evidence._metadata(path.lstat()))
                        for path in root.iterdir()}

            before_source, before_state = inventory(source), inventory(state)
            capture = evidence.capture_evidence(source, parent / "capture", command_report=command)
            before_capture = inventory(capture)
            report = diagnostic.analyze_snapshot(capture, RUN, AUTH)
            assert report["complete"] is True
            assert report["journal"]["nodes"]["writer"]["failures"] == [
                {"type": "ContractViolation", "cause": "writer-not-positive"}]
            assert diagnostic.main(["--root", str(source), "--out", str(parent / "cli-capture"),
                "--command-report", str(command), "--run-id", RUN, "--authorization-id", AUTH]) == 0
            output = capsys.readouterr()
            assert json.loads(output.out) == report
            assert output.err == "" and PRIVATE not in output.out
            assert inventory(source) == before_source
            assert inventory(state) == before_state
            assert inventory(capture) == before_capture
            assert (parent / "cli-capture" / "maintenance.sqlite-wal").is_file()
        finally:
            keeper.close()


def test_invalid_run_identity_refuses_before_claiming_capture_destination(
    portable_capture_custody: None, capsys: pytest.CaptureFixture[str],
) -> None:
    with tempfile.TemporaryDirectory(prefix="maintenance-invalid-identity-test-",
                                     dir=Path.home()) as temporary:
        parent = Path(temporary).resolve()
        parent.chmod(0o700)
        root, state = parent / "app", parent / "state"
        root.mkdir(mode=0o700)
        state.mkdir(mode=0o700)
        command = state / "application-run.json"
        command.write_text(json.dumps({"accepted": False, "run_id": RUN}), encoding="utf-8")
        command.chmod(0o600)
        destination = parent / "must-not-be-created"
        assert diagnostic.main(["--root", str(root), "--out", str(destination),
            "--command-report", str(command), "--run-id", PRIVATE,
            "--authorization-id", AUTH]) == 1
        assert not destination.exists()
    assert PRIVATE not in capsys.readouterr().out
