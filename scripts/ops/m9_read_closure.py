"""Exact C490 M9 READ evidence; no provider assembly or native dispatch.

Run the projection as the service using the verified installed controller.
The operator verifies it against the protected original invocation artifacts
and guest completion receipt; a fresh invocation or SSH status is not evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import stat
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn

if TYPE_CHECKING:
    from constructicon.api._m9.proposer import Observation
    from constructicon.core.journal import Journal

SCHEMA_VERSION = 1
ATTEMPT_LIMIT = 32768
RESULT_LIMIT = 4096
CONTROLLER = "/opt/constructicon-m8-controller"
_DIGEST = r"sha256:[0-9a-f]{64}"
_HASH = r"[0-9a-f]{64}"


class ClosureRefused(ValueError):
    pass


def _need(condition: bool) -> None:
    if not condition:
        raise ClosureRefused("M9_READ_CLOSURE_UNPROVED")


def _matches(pattern: str, value: object) -> bool:
    return type(value) is str and re.fullmatch(pattern, value) is not None


@dataclass(frozen=True)
class ClosurePins:
    trial: str
    authorization_id: str
    run: str
    provider_revision: str
    binding_digest: str
    qualification_revision: str
    source_digest: str
    task_digest: str

    def __post_init__(self) -> None:
        _need(
            _matches(r"[a-z0-9][a-z0-9-]{0,47}", self.trial)
            and _matches(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", self.authorization_id)
            and _matches(r"run-[0-9a-f]{32}", self.run)
            and all(_matches(_DIGEST, value) for value in (
                self.provider_revision, self.binding_digest, self.qualification_revision,
                self.source_digest, self.task_digest,
            ))
        )


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = dict(pairs)
    _need(len(value) == len(pairs))
    return value


def _bad_constant(_: str) -> NoReturn:
    raise ClosureRefused("M9_READ_CLOSURE_UNPROVED")


def _object(raw: bytes, limit: int) -> dict[str, Any]:
    _need(type(raw) is bytes and 0 < len(raw) <= limit)
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_bad_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ClosureRefused("M9_READ_CLOSURE_UNPROVED") from exc
    _need(type(value) is dict)
    return value


def _wire(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _int(value: object, expected: int) -> bool:
    return type(value) is int and value == expected


def _exact(value: Any, names: set[str]) -> bool:
    return type(value) is dict and set(value) == names


def _observation(value: Any, pins: ClosurePins) -> Observation:
    from constructicon.api._m9 import proposer

    _need(_exact(value, set(proposer.Observation.model_fields)))
    observed = proposer.checked_observation(value)
    _need(
        str(observed.source) == pins.source_digest and str(observed.task) == pins.task_digest
        and str(observed.provider_revision) == pins.provider_revision
        and observed.requested_model == "gpt-6.1-sol"
    )
    return observed


def project(
    pins: ClosurePins, journal: Journal, attempt_raw: bytes, *, next_present: bool,
) -> dict[str, Any]:
    """Require the C490 terminal checkpoint, the completed attempt and one released lease."""
    from constructicon.api._m9 import proposer
    from constructicon.api._m9.evidence import TrialIdentity
    from constructicon.api._m9.safety import selector_run
    from constructicon.core.address import RunId
    from constructicon.core.workspace import acquisition_id_for, lease_id_for

    _need(next_present is False and selector_run(TrialIdentity(pins.trial)) == pins.run)
    run = RunId(pins.run)
    attempt = _object(attempt_raw, ATTEMPT_LIMIT)
    _need(_exact(attempt, {
        "authorization_id", "run_id", "epoch", "acquisition_id", "phase", "at",
        "dispatch", "facts",
    }))
    _need(
        attempt["authorization_id"] == pins.authorization_id and attempt["run_id"] == run
        and _int(attempt["epoch"], 1) and _matches(r"acq-[0-9a-f]{32}", attempt["acquisition_id"])
        and attempt["phase"] == "outcome" and attempt["dispatch"] == "completed"
        and type(attempt["at"]) is str
    )
    _need(datetime.fromisoformat(attempt["at"]).utcoffset() == timedelta(0))
    facts = attempt["facts"]
    _need(_exact(facts, {
        "status", "refusal", "answer_bytes", "usage", "served_model", "readbacks", "relay",
        "process", "identities",
    }))
    ids, process, relay = facts["identities"], facts["process"], facts["relay"]
    _need(_exact(ids, {
        "adapter_revision", "capability_revision", "operator_binding_digest", "qualification",
    }))
    _need(_exact(process, {
        "returncode", "payload_returncode", "timed_out", "bound_exceeded", "elapsed_s",
        "stderr_bytes",
    }))
    _need(_exact(relay, {"destinations", "denied"}))
    _need(
        facts["status"] == "success" and facts["refusal"] is None
        and _matches(_DIGEST, ids["adapter_revision"])
        and ids["capability_revision"] == pins.provider_revision
        and ids["operator_binding_digest"] == pins.binding_digest
        and ids["qualification"] == pins.qualification_revision
        and _int(process["returncode"], 0) and _int(process["payload_returncode"], 0)
        and process["timed_out"] is False and process["bound_exceeded"] is False
        and type(relay["destinations"]) is dict and relay["denied"] == {}
    )
    # This producer validates terminal status, exact source/graph/input,
    # implementation, grants, manifest and the checkpoint output envelopes.
    observed = _observation(proposer.retained(journal, run).model_dump(mode="json"), pins)
    _need(_int(facts["answer_bytes"], observed.reply_bytes))
    leases = journal.capability_leases(run)
    _need(len(leases) == 1)
    lease = leases[0]
    _need(
        lease.run_id == run and lease.path == proposer.PATH and lease.binding_id == "executor"
        and lease.lifetime == "invocation" and _int(lease.acquisition_epoch, 1)
        and lease.state == "closed" and lease.disposition == "released"
        and lease.lease_id == lease_id_for(run, proposer.PATH, "executor")
        and acquisition_id_for(lease.lease_id, 1) == attempt["acquisition_id"]
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "pins": asdict(pins),
        "run_status": "succeeded",
        "attempt_phase": "outcome",
        "dispatch": "completed",
        "attempt_sha256": _sha(attempt_raw),
        "next_present": False,
        "lease_closed_released": True,
        "lease_id": lease.lease_id,
        "acquisition_id": attempt["acquisition_id"],
        "observation": observed.model_dump(mode="json"),
    }


def _read_attempt(attempt: Path) -> bytes:
    _need(attempt.is_absolute() and attempt == attempt.resolve(strict=True))
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    with os.fdopen(os.open(attempt, flags), "rb") as stream:
        info = os.fstat(stream.fileno())
        _need(
            stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
            and stat.S_IMODE(info.st_mode) == 0o600 and 0 < info.st_size <= ATTEMPT_LIMIT
        )
        raw = stream.read(ATTEMPT_LIMIT + 1)
        _need(len(raw) == info.st_size)
    return raw


def collect(pins: ClosurePins, store: Path, attempt: Path) -> dict[str, Any]:
    """Read only the selected journal and attempt; journal open may touch SQLite metadata."""
    from constructicon.api._m9.evidence import TrialIdentity
    from constructicon.api._m9.trial import _open

    _need(store.is_absolute() and store == store.resolve(strict=True) and store.is_dir())
    _need(all(not (store / name).is_symlink() for name in ("trial-id", "journal.sqlite")))
    journal = _open(store, TrialIdentity(pins.trial), initialize=False)
    raw = _read_attempt(attempt)
    return project(
        pins, journal, raw, next_present=os.path.lexists(attempt.with_name(attempt.name + ".next")),
    )


def accept_result(
    pins: ClosurePins, projection: bytes, original_stdout: bytes,
    original_stderr: bytes, original_rc: int,
) -> str:
    """Combine trusted guest projection and original protected invocation; return evidence SHA."""
    from constructicon.api._m9 import proposer
    from constructicon.core.address import RunId
    from constructicon.core.workspace import acquisition_id_for, lease_id_for

    _need(_int(original_rc, 0) and type(original_stderr) is bytes and original_stderr == b"")
    closure = _object(projection, RESULT_LIMIT)
    _need(_exact(closure, {
        "schema_version", "pins", "run_status", "attempt_phase", "dispatch", "attempt_sha256",
        "next_present", "lease_closed_released", "lease_id", "acquisition_id", "observation",
    }))
    lease_id = lease_id_for(RunId(pins.run), proposer.PATH, "executor")
    _need(
        _int(closure["schema_version"], SCHEMA_VERSION) and closure["pins"] == asdict(pins)
        and closure["run_status"] == "succeeded" and closure["attempt_phase"] == "outcome"
        and closure["dispatch"] == "completed" and _matches(_HASH, closure["attempt_sha256"])
        and closure["next_present"] is False and closure["lease_closed_released"] is True
        and closure["lease_id"] == lease_id
        and closure["acquisition_id"] == acquisition_id_for(lease_id, 1)
    )
    original = _object(original_stdout, RESULT_LIMIT)
    _need(_exact(original, {"status", "run", "observation", "replayed", "evaluation"}))
    checked = _observation(closure["observation"], pins)
    observed = _observation(original["observation"], pins)
    _need(
        original["replayed"] is False and original["run"] == pins.run
        and original["evaluation"] == "scripted-diagnostic-exam" and checked == observed
        and original["status"] == ("selected" if observed.choice == "cite-evidence"
                                   else "baseline-no-promotion")
    )
    return _sha(_wire({
        "schema_version": SCHEMA_VERSION,
        "projection_sha256": _sha(projection),
        "original_stdout_sha256": _sha(original_stdout),
        "original_stderr_sha256": _sha(original_stderr),
        "original_rc": original_rc,
    }))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("store", "attempt"):
        parser.add_argument(name, type=Path)
    for name in (
        "trial", "authorization_id", "run", "provider_revision", "binding_digest",
        "qualification_revision", "source_digest", "task_digest",
    ):
        parser.add_argument(name)
    args = vars(parser.parse_args(argv))
    store, attempt = args.pop("store"), args.pop("attempt")
    from constructicon.core.errors import ConstructiconError

    try:
        raw = _wire(collect(ClosurePins(**args), store, attempt))
        _need(len(raw) <= RESULT_LIMIT)
    except (OSError, ValueError, TypeError, KeyError, ConstructiconError, sqlite3.DatabaseError):
        print("M9_READ_CLOSURE_UNPROVED", file=sys.stderr)
        return 1
    sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, CONTROLLER)
    raise SystemExit(main())
