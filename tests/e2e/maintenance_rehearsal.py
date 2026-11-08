"""Run one credential-free maintenance contribution outside pytest, then report it.

Test-side and never shipped. From a checkout::

    python -m tests.e2e.maintenance_rehearsal run --state <dir> --change --key <k>
    python -m tests.e2e.maintenance_rehearsal report --state <dir> --out <fresh dir>

``run`` performs one attempt through the real ``maintenance_entry.run_maintenance``
in the world the credential-free pytest witness uses (tests/maintenance_task_world):
real Git authority, capture, journal, admission and fixed exam; a scripted native
peer in place of the vendor; a fake in-memory operator store; and a portable
process launcher in place of Linux isolation. None of that is physical
containment or vendor observation. The rehearsal base is synthetic: the
committed checkout tree with ``tests/vectors/plan_manifest.json`` stripped
(``import_fixture_tree``), because current main already holds that file and
``prepare_source`` refuses such a base; it is not a new current-main
contribution.

The first ``run`` in a state directory retains its exact authorization; a later
``run`` with the same key reopens that world in a fresh process and replays or
resumes the one durable run. ``report`` runs the shipped
``constructicon.api.maintenance_report`` in-process with only the platform-bound
capture predicates substituted on Windows (as tests/substrate/journal does).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import traceback
from pathlib import Path

import pytest

from constructicon.api import maintenance_entry as entry
from constructicon.api import maintenance_report
from constructicon.api.plan_manifest_application import GRAPH_NAME
from constructicon.core.address import ExecutionPath, ScopePath
from constructicon.core.maintenance import MaintenanceAttemptAuthorization

AUTHORIZATION_ID = "maintenance-rehearsal"
RETAINED = "rehearsal.json"
COMMAND_REPORT = "application-run.json"
DEATH_EXIT = 75
WRITER = ExecutionPath(scope=ScopePath(segments=(GRAPH_NAME, "writer")))


class RehearsalRefused(Exception):
    pass


async def open_world(state: Path, monkeypatch: pytest.MonkeyPatch):
    """The fixtures' world in their order: namespace, binding, then resources."""
    from tests.api.test_plan_manifest_application import concrete_resources
    from tests.conftest import portable_acquisition_namespace
    from tests.substrate.test_codex_adapter import portable_binding_world

    portable_acquisition_namespace.__wrapped__(monkeypatch)
    trusted = state / "trusted"
    if trusted.exists():
        shutil.rmtree(trusted)  # The fake operator store is in-memory per process.
    binding = portable_binding_world(state, monkeypatch)
    resources, launch = await concrete_resources(state, monkeypatch, committed_tree=True,
                                                 journal_name="maintenance.sqlite")
    return resources, launch, binding


def _retained(state: Path) -> dict | None:
    path = state / RETAINED
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


async def run(state: Path, *, change: bool, key: str, die_after_writer_checkpoint: bool) -> dict:
    from tests.maintenance_task_world import prepare_task_attempt

    # Capture's POSIX custody wants a private 0700 root under ancestors no
    # other principal can write (so not directly under /tmp).
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    state = state.resolve()
    retained = _retained(state)
    if retained is not None and (retained["change"] != change or retained["key"] != key):
        raise RehearsalRefused("rehearsal state retains another attempt; use a fresh --state")
    with pytest.MonkeyPatch.context() as monkeypatch:
        resources, launch, binding = await open_world(state, monkeypatch)
        attempt = await prepare_task_attempt(
            resources, launch, binding, state, monkeypatch, change=change,
            authorization=None if retained is None else
            MaintenanceAttemptAuthorization.model_validate(retained["authorization"]),
            authorization_id=AUTHORIZATION_ID, key=key,
            attempt_record=state / "maintenance-attempt.json")
        authorization = attempt.authorization
        if retained is None:
            (state / RETAINED).write_text(json.dumps({
                "change": change, "key": key,
                "authorization": authorization.model_dump(mode="json"),
            }, sort_keys=True), encoding="utf-8")
        journal = attempt.resources.journal
        if die_after_writer_checkpoint:
            # The journal's existing public fault probe: real process death once
            # the writer checkpoint transaction has committed.
            def probe(name: str) -> None:
                if name == "completion.after_commit" and journal.checkpoint(
                    authorization.run_id, WRITER,
                ) is not None:
                    sys.stdout.flush()
                    os._exit(DEATH_EXIT)

            journal.fault_probe = probe
        result = await entry.run_maintenance(resources=attempt.resources,
            executor=attempt.executor, executor_descriptor=_descriptor(attempt.executor),
            authorization=authorization)
        command = {"accepted": result is not None, "run_id": str(authorization.run_id)}
        # The entry's own `run` output shape, as a host procedure captures it.
        (state / COMMAND_REPORT).write_text(
            json.dumps(command, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        workers = [call for call in launch.calls if call[1].get("input_kind") == "task"]
        return {**command, "this_process": {
            "turn_start": attempt.scripted.native.methods.count("turn/start"),
            "task_workers": len(workers),
        }}


def _descriptor(executor):
    from tests.substrate.test_codex_adapter import descriptor_of

    return descriptor_of(executor, "executor")


def report(state: Path, out: Path) -> int:
    from constructicon.substrate.journal import maintenance_diagnostic as diagnostic
    from tests.substrate.journal.conftest import portable_capture_custody

    state = state.resolve()
    retained = _retained(state)
    if retained is None:
        raise RehearsalRefused("rehearsal state has no attempt; run one first")
    authorization = MaintenanceAttemptAuthorization.model_validate(retained["authorization"])
    with pytest.MonkeyPatch.context() as monkeypatch:
        # Exactly the journal tests' Windows seams: POSIX custody, and the
        # lstat/fstat ctime difference. Production keeps all three strict.
        portable_capture_custody.__wrapped__(monkeypatch)
        if os.name == "nt":
            identity = diagnostic._identity
            monkeypatch.setattr(diagnostic, "_identity",
                                lambda value: (*identity(value)[:-1], 0))
        return maintenance_report.main([
            "--root", str(state), "--out", str(out),
            "--command-report", str(state / COMMAND_REPORT),
            "--run-id", str(authorization.run_id), "--authorization-id", AUTHORIZATION_ID,
        ])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    attempt = commands.add_parser("run", help="perform or replay one maintenance attempt")
    attempt.add_argument("--state", type=Path, required=True)
    mode = attempt.add_mutually_exclusive_group(required=True)
    mode.add_argument("--change", dest="change", action="store_true")
    mode.add_argument("--noop", dest="change", action="store_false")
    attempt.add_argument("--key", required=True)
    attempt.add_argument("--die-after-writer-checkpoint", action="store_true",
                         help=argparse.SUPPRESS)
    packet = commands.add_parser("report", help="print the bounded packet for this state")
    packet.add_argument("--state", type=Path, required=True)
    packet.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "report":
            return report(args.state, args.out)
        observed = asyncio.run(run(args.state, change=args.change, key=args.key,
                                   die_after_writer_checkpoint=args.die_after_writer_checkpoint))
    except Exception as error:
        # Test-side harness: the cause goes to stderr for the operator; stdout
        # keeps the entry's closed refusal shape.
        traceback.print_exception(error, file=sys.stderr)
        print(json.dumps({"accepted": False, "error": "maintenance command refused or incomplete"},
                         sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(observed, sort_keys=True, separators=(",", ":")))
    return 0 if observed["accepted"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
