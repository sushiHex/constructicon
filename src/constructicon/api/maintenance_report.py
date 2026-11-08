"""One bounded result packet for one maintenance run, from a private copy only.

Composition, not a new reader: ``maintenance_evidence.capture_evidence`` makes
the fixed private byte copy (it never opens SQLite), ``maintenance_diagnostic``
validates selected historical facts read-only, ``maintenance_entry.
inspect_result`` reads the stored acceptance, and only this report's own
disposable copy of the capture is ever opened as a ``SqliteJournal`` (opening
migrates and sets WAL, so it is never pointed at the original store). The
target ref is one fixed, hook-free, non-fetching Git read; the authority is
never constructed as a ``GitAuthority`` (its constructor installs a hook).

Every label states its real strength: leases are journal-*recorded* states,
not physical quiescence; the target ref observed at the base is a current
read, not proof that cleanup ran; metering coverage is the run-result
projection's own, and unmeasured stays unmeasured, never zero cost. Missing
evidence is ``missing``. Only stores at the journal's current schema are read;
an older store (for example schema 10) is refused by name, never migrated.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Never

from constructicon.api.maintenance_entry import inspect_result
from constructicon.core.address import ExecutionPath, RunId, ScopePath
from constructicon.core.gates import MergeEvaluation
from constructicon.core.maintenance import PlanManifestRequest
from constructicon.core.run import RunStatus
from constructicon.substrate.journal._sqlite_schema import SCHEMA_VERSION
from constructicon.substrate.journal.maintenance_diagnostic import (
    GRAPH,
    MAX_JSON_BYTES,
    _connection,
    _copy_snapshot,
    _read,
    analyze_snapshot,
)
from constructicon.substrate.journal.maintenance_evidence import capture_evidence
from constructicon.substrate.journal.sqlite import SqliteJournal

MAX_PACKET_BYTES = 8192
MAX_LEASES = 16
ERROR = "maintenance report refused or incomplete"
_DIAGNOSTIC_STAGES = frozenset({"snapshot", "journal", "attempt", "command", "result", "output"})
_NODES = ("writer", "checker")
_BINDINGS = frozenset({"executor", "workspace", "gate"})
_RUN = re.compile(r"run-[0-9a-f]{32}")
_SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
_ATTESTATION = re.compile(r"att-[0-9a-f]{64}")
_SEGMENT = r"[A-Za-z0-9_-][A-Za-z0-9._-]{0,99}"
_REF = re.compile(rf"refs/heads/{_SEGMENT}(/{_SEGMENT}){{0,7}}")


class _Refusal(Exception):
    def __init__(self, stage: str, **facts: object) -> None:
        super().__init__(stage)
        self.stage, self.facts = stage, facts


def _require(condition: object) -> None:
    if not condition:
        raise _Refusal("unknown")


@contextmanager
def _stage(name: str) -> Iterator[None]:
    """Any failure inside a stage refuses at that stage; text never escapes."""
    try:
        yield
    except _Refusal as refusal:
        if refusal.stage == "unknown":
            raise _Refusal(name, **refusal.facts) from None
        raise
    except Exception:
        raise _Refusal(name) from None


def _refused(stage: str, facts: dict[str, object] | None = None) -> dict[str, object]:
    return {**(facts or {}), "schema_version": 1, "complete": False, "stage": stage,
            "error": ERROR}


def _manifest_digest(snapshot: Path) -> str:
    return hashlib.sha256(_read(snapshot / "manifest.json", MAX_JSON_BYTES)).hexdigest()


def _user_version(path: Path) -> int:
    connection = _connection(path)
    try:
        value = connection.execute("PRAGMA user_version").fetchone()[0]
    finally:
        connection.close()
    _require(type(value) is int)
    return int(value)


def _result(scratch: Path, present: set[str], run_id: RunId) -> dict[str, object]:
    if "maintenance-result.json" not in present:
        return {"observation": "missing"}
    facts = inspect_result(scratch / "maintenance-result.json")
    _require(facts["run_id"] == run_id)
    return {"observation": "historical-acceptance-observed",
            "candidate_commit": facts["candidate_commit"],
            "input_sha256": facts["input_sha256"], "render_sha256": facts["render_sha256"]}


def _metering(journal: SqliteJournal, run_id: RunId) -> tuple[dict[str, object],
                                                              dict[str, object]]:
    """The two journal reads ControlPlane.runs_result projects (schema 3), no more."""
    accounting = journal.capability_accounting_snapshot(run_id)
    _require(accounting is not None)
    assert accounting is not None
    cut = accounting.detail.through_event_seq
    metering = journal.executor_metering_snapshot(run_id, through_event_seq=cut)
    _require(metering is not None and metering.run_id == run_id and metering.event_seq == cut
             and len(metering.groups) <= 2)
    assert metering is not None
    items = accounting.detail.items
    return ({
        "projection": "run-result-v3-metering", "coverage": metering.coverage,
        "through_event_seq": cut, "attempt_count": metering.attempt_count,
        "groups": [group.model_dump(mode="json") for group in metering.groups],
        "estimate": None, "estimate_coverage": "unknown",
        "confirmed_charge": None, "confirmed_charge_coverage": "unknown",
    }, {
        "projection": "run-result-v3-capability-accounting", "through_event_seq": cut,
        "active_count": sum(item.state == "active" for item in items),
        "closed_count": sum(item.state == "closed" for item in items),
        "disposed_count": sum(item.loss == "disposed" for item in items),
        "opaque_lost_count": sum(item.loss == "opaque_lost" for item in items),
    })


def _node(path: ExecutionPath) -> str:
    segments = path.scope.segments
    if len(segments) == 2 and segments[0] == GRAPH and segments[1] in _NODES:
        return segments[1]
    return "unknown"


def _leases(journal: SqliteJournal, run_id: RunId) -> dict[str, object]:
    rows = journal.capability_leases(run_id)
    _require(len(rows) <= MAX_LEASES)
    keyed: list[tuple[tuple[str, str, int], dict[str, object]]] = []
    for row in rows:
        _require(type(row.acquisition_epoch) is int and 0 < row.acquisition_epoch < 2**31)
        node = _node(row.path)
        binding = row.binding_id if row.binding_id in _BINDINGS else "unknown"
        keyed.append(((node, binding, row.acquisition_epoch), {
            "node": node, "binding": binding, "acquisition_epoch": row.acquisition_epoch,
            "state": row.state, "disposition": row.disposition}))
    items = [item for _, item in sorted(keyed, key=lambda pair: pair[0])]
    states = {item["state"] for item in items}
    summary = ("none-recorded" if not items else
               "recorded-closed" if states == {"closed"} else "recorded-not-all-closed")
    return {"meaning": "journal-recorded-states-not-physical-quiescence",
            "summary": summary, "items": items}


def _attestation(journal: SqliteJournal, run_id: RunId) -> dict[str, object]:
    checkpoint = journal.checkpoint(run_id, ExecutionPath(scope=ScopePath(
        segments=(GRAPH, "checker"))))
    if checkpoint is None:
        return {"observation": "missing"}
    evaluation = MergeEvaluation.model_validate(checkpoint.outputs["evaluation"].payload)
    if evaluation.attestation_id is None:
        return {"observation": "none-minted", "evaluation_ok": evaluation.ok}
    _require(_ATTESTATION.fullmatch(evaluation.attestation_id))
    attestation = journal.load_attestation(evaluation.attestation_id)
    if attestation is None:
        return {"observation": "missing", "attestation_id": evaluation.attestation_id}
    return {"observation": "recorded", "attestation_id": attestation.attestation_id,
            "ok": attestation.ok, "created_by_this_run": attestation.created_by_run == run_id,
            "evaluation_ok": evaluation.ok}


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    """The reviewed fixed-read pattern (examples/change_review.py git()): no hooks,
    no ambient GIT_* environment or global/system config, no protocol, no fetch."""
    executable = shutil.which("git")
    _require(executable)
    assert executable is not None
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("GIT_")}
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_NO_REPLACE_OBJECTS": "1", "GIT_TERMINAL_PROMPT": "0",
                "GIT_ALLOW_PROTOCOL": "", "GIT_NO_LAZY_FETCH": "1",
                "GIT_OPTIONAL_LOCKS": "0"})
    return subprocess.run(
        [executable, "--no-pager", "-C", str(repository),
         "-c", f"core.hooksPath={os.devnull}", *arguments],
        env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=15, check=False,
    )


def _target(root: Path, request: PlanManifestRequest) -> dict[str, object]:
    report: dict[str, object] = {"meaning": "current-ref-read-not-proof-of-cleanup",
                                 "observation": "unknown"}
    _require(_SHA.fullmatch(request.base_commit))
    report["base_commit"] = str(request.base_commit)
    authority = root / "authority.git"
    if request.repository not in {str(authority), str(authority.resolve())}:
        report["reason"] = "request-names-another-repository"
        return report
    if _REF.fullmatch(request.target_ref) is None or ".." in request.target_ref or (
        request.target_ref.endswith(".lock")
    ):
        report["reason"] = "target-ref-outside-fixed-shape"
        return report
    if not authority.is_dir():
        report["observation"] = "missing"
        return report
    result = _git(authority, "rev-parse", "--verify", "--quiet",
                  request.target_ref + "^{commit}")
    if result.returncode == 1 and not result.stdout:
        report["observation"] = "missing"
        return report
    observed = result.stdout.strip().decode("ascii", errors="strict")
    _require(result.returncode == 0 and _SHA.fullmatch(observed))
    if observed == request.base_commit:
        report["observation"] = "observed-at-base"
    else:
        report.update(observation="observed-elsewhere", observed_commit=observed)
    return report


def _status(value: object) -> str:
    return value if isinstance(value, str) and value in {item.value for item in RunStatus} \
        else "unknown"


def _outcome(status: str, result: dict[str, object],
             nodes: dict[str, Any]) -> tuple[str, dict[str, object] | None]:
    refusal = None
    for name in _NODES:
        failures = nodes[name]["failures"]
        if failures:
            # The diagnostic maps only producer-emitted NodeFailed text to a cause.
            refusal = {"node": name, "cause": failures[0]["cause"],
                       "source": "diagnostic-producer-mapped-node-failure"}
            break
    if result["observation"] == "historical-acceptance-observed":
        return "contribution-accepted", refusal
    if status == RunStatus.FAILED:
        return "refused", refusal
    if status in {RunStatus.PENDING, RunStatus.RUNNING}:
        return "incomplete", refusal
    if status == RunStatus.SUCCEEDED:
        return "succeeded-without-stored-acceptance", refusal
    return "unknown", refusal


def _report(root: Path, out: Path, command_report: Path, run_id: str,
            authorization_id: str) -> dict[str, object]:
    with _stage("arguments"):
        _require(_RUN.fullmatch(run_id) and 0 < len(authorization_id) <= 256)
    run = RunId(run_id)
    with _stage("capture"):
        snapshot = capture_evidence(root, out, command_report=command_report)
    with tempfile.TemporaryDirectory(prefix="maintenance-report-") as temporary:
        scratch = Path(temporary).resolve()
        with _stage("snapshot"):
            # By construction: the only store this module opens lies here.
            _require(not scratch.is_relative_to(root.resolve())
                     and not root.resolve().is_relative_to(scratch))
            manifest = _manifest_digest(snapshot)
            present = _copy_snapshot(snapshot, scratch)
        with _stage("journal"):
            if "maintenance.sqlite" not in present:
                raise _Refusal("journal", journal="missing")
            version = _user_version(scratch / "maintenance.sqlite")
        if version != SCHEMA_VERSION:
            raise _Refusal("journal", journal="unsupported-schema",
                           journal_schema_version=version if 0 <= version < 2**31 else "unknown",
                           supported_journal_schema_version=SCHEMA_VERSION)
        diagnostic = analyze_snapshot(snapshot, run, authorization_id)
        if diagnostic.get("complete") is not True:
            stage = diagnostic.get("stage")
            raise _Refusal("diagnostic", diagnostic_stage=(
                stage if isinstance(stage, str) and stage in _DIAGNOSTIC_STAGES else "unknown"))
        with _stage("snapshot"):
            _require(_manifest_digest(snapshot) == manifest)
        facts = diagnostic["journal"]
        _require(isinstance(facts, dict))
        assert isinstance(facts, dict)
        if facts.get("observation") != "selected-facts-validated":
            raise _Refusal("journal", journal="run-missing")
        with _stage("result"):
            result = _result(scratch, present, run)
        with _stage("journal"):
            journal = SqliteJournal(scratch / "maintenance.sqlite")
            inputs = journal.run_inputs(run)
            _require(isinstance(inputs, dict))
            assert inputs is not None
            request = PlanManifestRequest.model_validate(inputs["request"])
        with _stage("metering"):
            metering, accounting = _metering(journal, run)
        with _stage("leases"):
            leases = _leases(journal, run)
        with _stage("attestation"):
            attestation = _attestation(journal, run)
        del journal
    with _stage("target"):
        target = _target(root, request)
    with _stage("output"):
        status = _status(facts.get("status"))
        outcome, refusal = _outcome(status, result, facts["nodes"])
        packet: dict[str, object] = {
            "schema_version": 1, "complete": True,
            "meaning": "selected-historical-run-facts-from-a-private-copy",
            "run_id": str(run), "status": status, "outcome": outcome, "refusal": refusal,
            "diagnostic": {name: diagnostic[name] for name in (
                "journal", "attempt", "pending_attempt", "command", "result")},
            "result": result, "metering": metering, "capability_accounting": accounting,
            "leases": leases, "attestation": attestation, "target": target,
        }
        _require(len(json.dumps(packet, sort_keys=True, separators=(",", ":")).encode())
                 <= MAX_PACKET_BYTES)
    return packet


def report(root: Path, out: Path, command_report: Path, run_id: str,
           authorization_id: str) -> dict[str, object]:
    """Capture, diagnose and project; every refusal is a closed, named stage."""
    try:
        return _report(root, out, command_report, run_id, authorization_id)
    except _Refusal as refusal:
        return _refused(refusal.stage, refusal.facts)
    except Exception:
        return _refused("unknown")


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        raise _Refusal("arguments")


def main(argv: list[str] | None = None) -> int:
    try:
        parser = _Parser(description=__doc__, add_help=False)
        for name in ("root", "out", "command-report", "run-id", "authorization-id"):
            parser.add_argument("--" + name, required=True)
        args = parser.parse_args(argv)
        packet = report(Path(args.root), Path(args.out), Path(args.command_report),
                        args.run_id, args.authorization_id)
    except Exception:
        packet = _refused("arguments")
    print(json.dumps(packet, sort_keys=True, separators=(",", ":")))
    return 0 if packet["complete"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
