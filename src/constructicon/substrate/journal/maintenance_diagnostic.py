"""Bounded historical maintenance facts; no activation, recovery or original SQLite opens.

Only selected facts are validated. This is not the journal's open-time inventory,
a current authorization, or independent evidence of backend execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Never

from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.effect import MergeSubject
from constructicon.core.envelope import GitRef
from constructicon.core.identity import actor_id_is_canonical, parse_json_value
from constructicon.core.maintenance import PlanManifestRequest, PlanManifestResult
from constructicon.core.qualification_write import CallbackObservation
from constructicon.core.workspace import acquisition_id_for, lease_id_for
from constructicon.substrate.journal._sqlite_attestations import attestation_for_id
from constructicon.substrate.journal._sqlite_base import (
    _sqlite_command_id,
    _sqlite_utc_microseconds,
    read_snapshot,
)
from constructicon.substrate.journal._sqlite_execution_facts import (
    stored_checkpoint_for,
    stored_event_from_row,
)
from constructicon.substrate.journal._sqlite_runs import run_facts_for_id
from constructicon.substrate.journal.maintenance_evidence import (
    FILES,
    MAX_FILE_BYTES,
    MAX_TOTAL_BYTES,
)

GRAPH = "constructicon-plan-manifest-maintenance"
MAX_JSON_BYTES = 1024 * 1024
MAX_EVENTS = 256
MAX_ATTESTATIONS = 32
MAX_SQL_STEPS = 2_000_000
MAX_REPORT_BYTES = 8192
_FAILURES = {
    "maintenance requires an asynchronous WRITE workspace": "writer-workspace",
    "maintenance workspace differs from the pinned base": "writer-base",
    "maintenance writer did not positively succeed": "writer-not-positive",
    "maintenance capture differs from the requested candidate": "capture-mismatch",
    "maintenance captured candidate differs from capture return": "capture-return",
    "maintenance captured candidate equals the pinned base": "capture-unchanged",
    "maintenance captured candidate has another repository": "capture-repository",
    "maintenance captured candidate has path restrictions": "capture-paths",
    "maintenance captured candidate has another comparison base": "capture-base",
    "maintenance checker received another candidate or gate": "checker-input",
    "maintenance candidate failed its exact gate": "gate-not-positive",
}
_ERROR_TYPES = frozenset({"ContractViolation", "JournalDamaged", "OSError", "ValueError"})


class _Refused(Exception):
    pass


def _require(condition: bool) -> None:
    if not condition:
        raise _Refused


def _read(path: Path, limit: int) -> bytes:
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit)
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0))
    try:
        opened = os.fstat(descriptor)
        _require(_identity(before) == _identity(opened))
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            raw = source.read(limit + 1)
        _require(len(raw) <= limit and _identity(opened) == _identity(os.fstat(descriptor)))
        _require(_identity(opened) == _identity(path.lstat()))
        return raw
    finally:
        os.close(descriptor)


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid,
            value.st_nlink, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def _object(raw: bytes) -> dict[str, Any]:
    parsed = parse_json_value(raw.decode("utf-8", errors="strict"))
    if not isinstance(parsed, dict):
        raise _Refused
    return dict(parsed)


def _copy_snapshot(snapshot: Path, scratch: Path) -> set[str]:
    _require(not snapshot.is_symlink() and snapshot.is_dir())
    manifest = _object(_read(snapshot / "manifest.json", MAX_JSON_BYTES))
    _require(set(manifest) == {"schema_version", "complete", "files"})
    _require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1)
    _require(manifest["complete"] is True and isinstance(manifest["files"], dict))
    entries = manifest["files"]
    _require(set(entries) == set(FILES))
    present: set[str] = set()
    total = 0
    for name in FILES:
        entry = entries[name]
        _require(isinstance(entry, dict) and type(entry.get("present")) is bool)
        if entry["present"] is False:
            _require(set(entry) == {"present"} and not (snapshot / name).exists()
                     and not (snapshot / name).is_symlink())
            continue
        _require(set(entry) == {"present", "bytes", "sha256", "metadata"})
        _require(type(entry["bytes"]) is int and 0 <= entry["bytes"] <= MAX_FILE_BYTES)
        total += entry["bytes"]
        _require(total <= MAX_TOTAL_BYTES)
        raw = _read(snapshot / name, MAX_FILE_BYTES)
        _require(len(raw) == entry["bytes"] and hashlib.sha256(raw).hexdigest() == entry["sha256"])
        (scratch / name).write_bytes(raw)
        present.add(name)
    return present


def _attempt(path: Path, run_id: RunId, authorization_id: str) -> dict[str, object]:
    record = _object(_read(path, MAX_JSON_BYTES))
    required = {"authorization_id", "run_id", "epoch", "acquisition_id", "purpose", "phase", "at"}
    phase = record.get("phase")
    _require(phase in {"acquired", "intent", "outcome"})
    keys = required | ({"dispatch", "facts"} if phase == "outcome" else set())
    _require(set(record) in (keys, keys | {"callbacks"}))
    _require(record["authorization_id"] == authorization_id and record["run_id"] == run_id)
    _require(record["purpose"] == "plan-manifest-maintenance")
    _require(type(record["epoch"]) is int and record["epoch"] == 1)
    path_identity = ExecutionPath(scope=ScopePath(segments=(GRAPH, "writer")))
    logical = lease_id_for(run_id, path_identity, "executor")
    _require(record["acquisition_id"] == acquisition_id_for(logical, 1))
    at = datetime.fromisoformat(record["at"])
    _require(at.tzinfo is not None and at.utcoffset() is not None)
    report: dict[str, object] = {"observation": "identity-matched", "phase": phase,
                                "dispatch": "unknown", "callbacks": "unrecorded"}
    callbacks = None
    if "callbacks" in record:
        callbacks = CallbackObservation.model_validate(record["callbacks"])
        report["callbacks"] = callbacks.model_dump(mode="json")
    if phase == "outcome":
        dispatch = record["dispatch"]
        _require(dispatch in {"completed", "not dispatched", "possibly dispatched"})
        facts = record["facts"]
        _require(isinstance(facts, dict))
        status = facts.get("status")
        _require(status is None or status in {"success", "partial", "failure"})
        _require(dispatch != "completed" or status == "success")
        _require(callbacks is None or not (dispatch == "completed" or status == "success")
                 or callbacks.responses_complete)
        report.update(dispatch=dispatch, executor_status=status, failure_kind="unknown")
        refusal = facts.get("refusal")
        if isinstance(refusal, str) and status == "failure":
            for kind in ("spawn", "timeout", "exit", "unavailable"):
                if refusal.startswith(kind + ": "):
                    report["failure_kind"] = kind
        process = facts.get("process")
        if process is not None:
            _require(isinstance(process, dict))
            _require(type(process.get("timed_out")) is bool
                     and type(process.get("bound_exceeded")) is bool)
            report["process"] = {"timed_out": process["timed_out"],
                                 "bound_exceeded": process["bound_exceeded"]}
    return report


def _command(path: Path, run_id: RunId) -> str:
    record = _object(_read(path, 65536))
    if set(record) == {"accepted", "run_id"} and type(record["accepted"]) is bool:
        _require(record["run_id"] == run_id)
        return "accepted" if record["accepted"] else "normal-nonacceptance"
    if set(record) == {"accepted", "error"} and record["accepted"] is False and (
        record["error"] == "maintenance command refused or incomplete"
    ):
        return "command-refused"
    raise _Refused


def _result(path: Path, run_id: RunId) -> str:
    record = _object(_read(path, 65536))
    _require(set(record) == {"schema_version", "meaning", "authorization_digest", "result"})
    _require(type(record["schema_version"]) is int and record["schema_version"] == 1)
    _require(record["meaning"] == "historical-application-acceptance")
    _require(isinstance(record["authorization_digest"], str) and re.fullmatch(
        r"sha256:[0-9a-f]{64}", record["authorization_digest"]) is not None)
    result = PlanManifestResult.model_validate(record["result"])
    _require(result.run_id == run_id and re.fullmatch(
        r"[0-9a-f]{40}([0-9a-f]{24})?", result.candidate.commit) is not None)
    return "historical-acceptance-observed"


def _connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=1)
    connection.row_factory = sqlite3.Row
    connection.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, MAX_JSON_BYTES)
    connection.execute("PRAGMA query_only=ON")
    connection.execute("PRAGMA trusted_schema=OFF")
    steps = 0

    def budget() -> int:
        nonlocal steps
        steps += 1000
        return int(steps > MAX_SQL_STEPS)

    connection.set_progress_handler(budget, 1000)
    allowed = {sqlite3.SQLITE_READ, sqlite3.SQLITE_SELECT, sqlite3.SQLITE_FUNCTION,
               sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_RECURSIVE}

    def authorize(action: int, first: str | None, second: str | None,
                  database: str | None, trigger: str | None) -> int:
        if action in allowed or (action == sqlite3.SQLITE_PRAGMA
                                 and first == "user_version" and second is None):
            return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    connection.set_authorizer(authorize)
    connection.create_function("constructicon_utc_microseconds", 1, _sqlite_utc_microseconds,
                               deterministic=True)
    connection.create_function("constructicon_actor_id_is_canonical", 1, actor_id_is_canonical,
                               deterministic=True)
    connection.create_function("constructicon_command_id", 3, _sqlite_command_id,
                               deterministic=True)
    return connection


def _journal(path: Path, run_id: RunId) -> dict[str, object]:
    connection = _connection(path)
    try:
        with read_snapshot(connection):
            _require(connection.execute("PRAGMA user_version").fetchone()[0] == 9)
            facts = run_facts_for_id(connection, run_id)
            if facts is None:
                return {"observation": "missing"}
            world, _, _ = facts
            _require(world.manifest.source_graph.name == GRAPH)
            request = PlanManifestRequest.model_validate(world.inputs["request"])
            status = connection.execute("SELECT status FROM runs WHERE run_id = ?",
                                        (run_id,)).fetchone()[0]
            rows = connection.execute("SELECT * FROM events WHERE run_id = ? ORDER BY seq LIMIT ?",
                                      (run_id, MAX_EVENTS + 1)).fetchall()
            _require(len(rows) <= MAX_EVENTS)
            nodes: dict[str, Any] = {name: {"started": "unrecorded", "checkpoint": "missing",
                                          "failures": []} for name in ("writer", "checker")}
            for row in rows:
                event = stored_event_from_row(connection, row)
                for name in nodes:
                    expected = ExecutionPath(scope=ScopePath(segments=(GRAPH, name)))
                    if event.path != expected:
                        continue
                    if event.kind == "NodeStarted":
                        nodes[name]["started"] = "observed"
                    elif event.kind == "NodeFailed":
                        payload = event.payload
                        if not isinstance(payload, dict):
                            raise _Refused
                        error_type = payload.get("error_type")
                        error = payload.get("error")
                        nodes[name]["failures"].append({
                            "type": error_type if error_type in _ERROR_TYPES else "unknown",
                            "cause": _FAILURES.get(error, "unknown") if (
                                error_type == "ContractViolation" and isinstance(error, str)
                            ) else "unknown",
                        })
                        _require(len(nodes[name]["failures"]) <= 8)
            candidate = None
            for name in nodes:
                checkpoint = stored_checkpoint_for(connection, run_id=run_id,
                    path=ExecutionPath(scope=ScopePath(segments=(GRAPH, name))))
                if checkpoint is not None:
                    nodes[name]["checkpoint"] = "validated"
                    if name == "writer":
                        candidate = GitRef.model_validate(checkpoint.outputs["candidate"].payload)
                        _require(candidate.repository == request.repository
                                 and candidate.diff_against == request.base_commit)
            attestations = connection.execute("SELECT attestation_id FROM attestations LIMIT ?",
                                              (MAX_ATTESTATIONS + 1,)).fetchall()
            _require(len(attestations) <= MAX_ATTESTATIONS)
            checks: list[dict[str, object]] = []
            for row in attestations:
                attestation = attestation_for_id(connection, row[0])
                _require(attestation is not None)
                if attestation is None or attestation.created_by_run != run_id:
                    continue
                subject = attestation.subject
                if attestation.action != "merge" or not isinstance(subject, MergeSubject):
                    raise _Refused
                _require(candidate is not None and subject.candidate == candidate.commit
                         and subject.repository == request.repository
                         and subject.target_ref == request.target_ref
                         and subject.expected_base == request.base_commit
                         and attestation.manifest_hash == world.manifest.manifest_hash
                         and attestation.check_set_hash == request.check_set_hash)
                for check in attestation.checks:
                    _require(len(checks) < 8)
                    checks.append({"name": check.name if check.name in {
                        "plan-manifest-trusted-vectors", "snapshot-integrity"} else "unknown",
                                   "status": check.status})
            return {"observation": "selected-facts-validated", "status": status,
                    "command_origin": ("validated" if world.creation_plan is not None
                                       else "unrecorded"),
                    "events_checked": len(rows), "nodes": nodes, "checks": checks}
    finally:
        connection.close()


def analyze_snapshot(snapshot_dir: Path, run_id: RunId,
                     authorization_id: str) -> dict[str, object]:
    """Validate a completed capture on an independent disposable copy only."""
    stage = "snapshot"
    try:
        _require(re.fullmatch(r"run-[0-9a-f]{32}", run_id) is not None)
        _require(0 < len(authorization_id) <= 256)
        with tempfile.TemporaryDirectory(prefix="maintenance-analysis-") as temporary:
            scratch = Path(temporary)
            present = _copy_snapshot(snapshot_dir, scratch)
            report: dict[str, object] = {"schema_version": 1, "complete": True,
                "meaning": "selected-historical-facts-only", "run_id": str(run_id),
                "journal": {"observation": "missing"},
                "attempt": {"observation": "missing"}, "pending_attempt": "missing",
                "command": "missing", "result": "missing"}
            stage = "journal"
            _require("maintenance.sqlite" in present or not any(
                name in present for name in FILES if name.startswith("maintenance.sqlite-")))
            if "maintenance.sqlite" in present:
                report["journal"] = _journal(scratch / "maintenance.sqlite", run_id)
            stage = "attempt"
            if "maintenance-attempt.json" in present:
                report["attempt"] = _attempt(scratch / "maintenance-attempt.json", run_id,
                                             authorization_id)
            if "maintenance-attempt.json.next" in present:
                _attempt(scratch / "maintenance-attempt.json.next", run_id, authorization_id)
                report["pending_attempt"] = "identity-matched-not-published"
            stage = "command"
            if "application-run.json" in present:
                report["command"] = _command(scratch / "application-run.json", run_id)
            stage = "result"
            if "maintenance-result.json" in present:
                report["result"] = _result(scratch / "maintenance-result.json", run_id)
            stage = "output"
            _require(len(json.dumps(report).encode("utf-8")) <= MAX_REPORT_BYTES)
            return report
    except Exception:
        return {"schema_version": 1, "complete": False, "stage": stage,
                "error": "diagnostic refused or incomplete"}


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise _Refused


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__, add_help=False)
        for name in ("root", "out", "command-report", "run-id", "authorization-id"):
            parser.add_argument("--" + name, required=True)
        args = parser.parse_args(argv)
        _require(re.fullmatch(r"run-[0-9a-f]{32}", args.run_id) is not None)
        _require(0 < len(args.authorization_id) <= 256)
        from constructicon.substrate.journal.maintenance_evidence import capture_evidence
        snapshot = capture_evidence(Path(args.root), Path(args.out),
                                    command_report=Path(args.command_report))
        report = analyze_snapshot(snapshot, RunId(args.run_id), args.authorization_id)
    except Exception:
        report = {"schema_version": 1, "complete": False, "stage": "capture",
                  "error": "diagnostic refused or incomplete"}
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["complete"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
