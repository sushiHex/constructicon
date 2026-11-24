"""Exact READ completion evidence; no provider assembly or native dispatch.

Run the projection as the service using the verified installed controller.
The operator verifies it against the protected original invocation artifacts
and guest completion receipt; a fresh invocation or SSH status is not evidence.

Two closure rules share one completion check (the completed native attempt,
its identities and process facts, and one released lease). M9 projects its
own checkpointed observation. The change-review advice route proves the rest
with its own replay: the installed entry, rerun without a permit, must print
exactly the original result except ``replayed``.
"""

from __future__ import annotations

import argparse
import base64
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
    from scripts.ops.m9_read_command import Site

    from constructicon.api._m9.proposer import Observation
    from constructicon.core.address import ExecutionPath, RunId
    from constructicon.core.journal import Journal

SCHEMA_VERSION = 1
ATTEMPT_LIMIT = 32768
RESULT_LIMIT = 4096
CONTROLLER = "/opt/constructicon-m8-controller"
ADVICE = "change-review-advice"
_DIGEST = r"sha256:[0-9a-f]{64}"
_HASH = r"[0-9a-f]{64}"
_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}"


class ClosureRefused(ValueError):
    pass


def _need(condition: bool, code: str = "M9_READ_CLOSURE_UNPROVED") -> None:
    if not condition:
        raise ClosureRefused(code)


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
            and _matches(_ID, self.authorization_id)
            and _matches(r"run-[0-9a-f]{32}", self.run)
            and all(_matches(_DIGEST, value) for value in (
                self.provider_revision, self.binding_digest, self.qualification_revision,
                self.source_digest, self.task_digest,
            ))
        )


@dataclass(frozen=True)
class CompletionPins:
    """What the completed native attempt must name; the guest closure's argv."""

    authorization_id: str
    run: str
    provider_revision: str
    binding_digest: str
    qualification_revision: str

    def __post_init__(self) -> None:
        _need(
            _matches(_ID, self.authorization_id) and _matches(r"run-[0-9a-f]{32}", self.run)
            and all(_matches(_DIGEST, value) for value in (
                self.provider_revision, self.binding_digest, self.qualification_revision,
            )),
            "CHANGE_REVIEW_READ_CLOSURE_UNPROVED",
        )


@dataclass(frozen=True)
class AdviceClosurePins:
    """Everything an advice READ binds beyond its candidate.

    The completion pins cross to the guest closure; the selected site and the
    exact summary bytes, pinned by digest, cross as the entry's data.
    """

    completion: CompletionPins
    instruction_digest: str
    site: Site
    summary: bytes
    summary_sha256: str

    def __post_init__(self) -> None:
        _need(
            type(self.completion) is CompletionPins
            and _matches(_DIGEST, self.instruction_digest)
            and type(self.summary) is bytes
            and hashlib.sha256(self.summary).hexdigest() == self.summary_sha256
            and getattr(getattr(self.site, "consumer", None), "id", None) == ADVICE,
            "CHANGE_REVIEW_READ_CLOSURE_UNPROVED",
        )

    @property
    def authorization_id(self) -> str:
        return self.completion.authorization_id


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value = dict(pairs)
    _need(len(value) == len(pairs))
    return value


def _bad_constant(_: str) -> NoReturn:
    raise ClosureRefused("M9_READ_CLOSURE_UNPROVED")


def _object(raw: bytes, limit: int, code: str = "M9_READ_CLOSURE_UNPROVED") -> dict[str, Any]:
    _need(type(raw) is bytes and 0 < len(raw) <= limit, code)
    try:
        value = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_bad_constant,
        )
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ClosureRefused(code) from exc
    _need(type(value) is dict, code)
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
    from constructicon.substrate.executors.codex_host import READ_GRANTS

    _need(_exact(value, set(proposer.Observation.model_fields)))
    observed = proposer.checked_observation(value)
    _need(
        str(observed.source) == pins.source_digest and str(observed.task) == pins.task_digest
        and str(observed.provider_revision) == pins.provider_revision
        and observed.requested_model == READ_GRANTS.model_selection.model
    )
    return observed


def completion(
    journal: Journal, attempt_raw: bytes, run: RunId, path: ExecutionPath, binding: str,
    authorization_id: str, provider_revision: str, binding_digest: str,
    qualification_revision: str, *, code: str,
) -> tuple[dict[str, Any], Any]:
    """The completed native attempt and its one released lease.

    attempt_record.py and codex.py's _attempt_facts emit this closed record.
    A checkpoint cannot substitute for the independent completed attempt.
    """
    from constructicon.core.workspace import acquisition_id_for, lease_id_for

    attempt = _object(attempt_raw, ATTEMPT_LIMIT, code)
    _need(_exact(attempt, {
        "authorization_id", "run_id", "epoch", "acquisition_id", "phase", "at",
        "dispatch", "facts",
    }), code)
    _need(
        attempt["authorization_id"] == authorization_id and attempt["run_id"] == run
        and _int(attempt["epoch"], 1) and _matches(r"acq-[0-9a-f]{32}", attempt["acquisition_id"])
        and attempt["phase"] == "outcome" and attempt["dispatch"] == "completed"
        and type(attempt["at"]) is str, code,
    )
    _need(datetime.fromisoformat(attempt["at"]).utcoffset() == timedelta(0), code)
    facts = attempt["facts"]
    _need(_exact(facts, {
        "status", "refusal", "answer_bytes", "usage", "served_model", "readbacks", "relay",
        "process", "identities",
    }), code)
    ids, process, relay = facts["identities"], facts["process"], facts["relay"]
    _need(_exact(ids, {
        "adapter_revision", "capability_revision", "operator_binding_digest", "qualification",
    }), code)
    _need(_exact(process, {
        "returncode", "payload_returncode", "timed_out", "bound_exceeded", "elapsed_s",
        "stderr_bytes",
    }), code)
    _need(_exact(relay, {"destinations", "denied"}), code)
    _need(
        facts["status"] == "success" and facts["refusal"] is None
        and _matches(_DIGEST, ids["adapter_revision"])
        and ids["capability_revision"] == provider_revision
        and ids["operator_binding_digest"] == binding_digest
        and ids["qualification"] == qualification_revision
        and _int(process["returncode"], 0) and _int(process["payload_returncode"], 0)
        and process["timed_out"] is False and process["bound_exceeded"] is False
        and type(relay["destinations"]) is dict and relay["denied"] == {}, code,
    )
    leases = journal.capability_leases(run)
    _need(len(leases) == 1, code)
    lease = leases[0]
    _need(
        lease.run_id == run and lease.path == path and lease.binding_id == binding
        and lease.lifetime == "invocation" and _int(lease.acquisition_epoch, 1)
        and lease.state == "closed" and lease.disposition == "released"
        and lease.lease_id == lease_id_for(run, path, binding)
        and acquisition_id_for(lease.lease_id, 1) == attempt["acquisition_id"], code,
    )
    return attempt, lease


def project(
    pins: ClosurePins, journal: Journal, attempt_raw: bytes, *, next_present: bool,
) -> dict[str, Any]:
    """Require the C490 terminal checkpoint, the completed attempt and one released lease."""
    from constructicon.api._m9 import proposer
    from constructicon.api._m9.evidence import TrialIdentity
    from constructicon.api._m9.safety import selector_run
    from constructicon.core.address import RunId

    _need(next_present is False and selector_run(TrialIdentity(pins.trial)) == pins.run)
    run = RunId(pins.run)
    attempt, lease = completion(
        journal, attempt_raw, run, proposer.PATH, "executor", pins.authorization_id,
        pins.provider_revision, pins.binding_digest, pins.qualification_revision,
        code="M9_READ_CLOSURE_UNPROVED",
    )
    # This producer validates terminal status, exact source/graph/input,
    # implementation, grants, manifest and the checkpoint output envelopes.
    observed = _observation(proposer.retained(journal, run).model_dump(mode="json"), pins)
    _need(_int(attempt["facts"]["answer_bytes"], observed.reply_bytes))
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


def _advice_path() -> ExecutionPath:
    from constructicon.api import change_review_advice as route
    from constructicon.core.address import ExecutionPath

    return ExecutionPath(scope=route.SCOPE)


def advice_completion(
    pins: CompletionPins, journal: Journal, attempt_raw: bytes, *, next_present: bool,
) -> dict[str, Any]:
    """Only what the route's replay cannot prove: the attempt and the lease."""
    from constructicon.api import change_review_advice as route
    from constructicon.core.address import RunId

    code = "CHANGE_REVIEW_READ_CLOSURE_UNPROVED"
    _need(next_present is False, code)
    attempt, lease = completion(
        journal, attempt_raw, RunId(pins.run), _advice_path(), route.EXECUTOR,
        pins.authorization_id, pins.provider_revision, pins.binding_digest,
        pins.qualification_revision, code=code,
    )
    facts = attempt["facts"]
    return {
        "schema_version": SCHEMA_VERSION,
        "consumer": ADVICE,
        "pins": asdict(pins),
        "attempt_sha256": _sha(attempt_raw),
        "answer_bytes": facts["answer_bytes"],
        "served_model": facts["served_model"],
        "next_present": False,
        "lease_closed_released": True,
        "lease_id": lease.lease_id,
        "acquisition_id": attempt["acquisition_id"],
    }


def _read_attempt(attempt: Path) -> bytes:
    """Callers' mains name the refusal; this raises only to them."""
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


def collect_advice(pins: CompletionPins, journal: Path, attempt: Path) -> dict[str, Any]:
    """Read only the permit's journal and attempt record."""
    from constructicon.substrate.journal.sqlite import SqliteJournal

    _need(journal.is_absolute() and journal == journal.resolve(strict=True)
          and journal.is_file() and not journal.is_symlink())
    raw = _read_attempt(attempt)
    return advice_completion(
        pins, SqliteJournal(journal), raw,
        next_present=os.path.lexists(attempt.with_name(attempt.name + ".next")),
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
    return _evidence(projection, original_stdout, original_stderr, original_rc)


def _evidence(projection: bytes, stdout: bytes, stderr: bytes, rc: int) -> str:
    return _sha(_wire({
        "schema_version": SCHEMA_VERSION,
        "projection_sha256": _sha(projection),
        "original_stdout_sha256": _sha(stdout),
        "original_stderr_sha256": _sha(stderr),
        "original_rc": rc,
    }))


def _decoded(value: object, limit: int, code: str) -> bytes:
    _need(type(value) is str, code)
    try:
        raw = base64.b64decode(str(value), validate=True)
    except ValueError as exc:
        raise ClosureRefused(code) from exc
    _need(0 < len(raw) <= limit, code)
    return raw


def accept_replay(
    pins: AdviceClosurePins, projection: bytes, original_stdout: bytes,
    original_stderr: bytes, original_rc: int,
) -> str:
    """The original equals the route's own replay but for ``replayed``; return evidence SHA.

    The replay is the installed entry reading its journal through its own
    manifest, dedication and detail checks, so its equality retires any
    re-projection here. The advice is the result's whole ``advice``, never the
    preview; it is validated as a record and never parsed for authority.
    """
    from pydantic import ValidationError
    from scripts.ops.m9_read_command import ADVICE as DESCRIPTOR
    from scripts.ops.m9_read_command import COMPLETION_LIMIT

    from constructicon.api import change_review_advice as route
    from constructicon.core.address import RunId
    from constructicon.core.workspace import acquisition_id_for, lease_id_for
    from constructicon.substrate.executors.codex_host import READ_GRANTS

    code = "CHANGE_REVIEW_READ_CLOSURE_UNPROVED"
    limit = DESCRIPTOR.log_limit
    _need(type(pins) is AdviceClosurePins and _int(original_rc, 0)
          and type(original_stderr) is bytes and original_stderr == b"", code)
    record = _object(projection, DESCRIPTOR.projection_limit, code)
    _need(_exact(record, {"completion", "replay"}), code)
    replay_raw = _decoded(record["replay"], limit, code)
    closure = _object(_decoded(record["completion"], COMPLETION_LIMIT, code),
                      COMPLETION_LIMIT, code)
    lease_id = lease_id_for(RunId(pins.completion.run), _advice_path(), route.EXECUTOR)
    _need(
        _exact(closure, {
            "schema_version", "consumer", "pins", "attempt_sha256", "answer_bytes",
            "served_model", "next_present", "lease_closed_released", "lease_id",
            "acquisition_id",
        })
        and _int(closure["schema_version"], SCHEMA_VERSION) and closure["consumer"] == ADVICE
        and closure["pins"] == asdict(pins.completion)
        and _matches(_HASH, closure["attempt_sha256"])
        and closure["next_present"] is False and closure["lease_closed_released"] is True
        and closure["lease_id"] == lease_id
        and closure["acquisition_id"] == acquisition_id_for(lease_id, 1), code,
    )
    original = _object(original_stdout, limit, code)
    _need(
        _exact(original, {"run_id", "replayed", "instruction_digest", "advice", "result"})
        and original["replayed"] is False
        # Both are the entry's own printer: exact bytes, so no duplicate key,
        # CRLF or reordering hides behind an equal parse.
        and original_stdout == _wire(original)
        and replay_raw == _wire({**original, "replayed": True}), code,
    )
    result = original["result"]
    _need(
        original["run_id"] == pins.completion.run
        and original["instruction_digest"] == pins.instruction_digest
        and type(result) is dict and result.get("run_id") == pins.completion.run
        and result.get("status") == "succeeded"
        and _exact(original["advice"], set(route.ModelAdvicePayload.model_fields)), code,
    )
    try:
        advice = route.ModelAdvicePayload.model_validate(original["advice"])
    except ValidationError as exc:
        raise ClosureRefused(code) from exc
    _need(
        str(advice.instruction_digest) == pins.instruction_digest
        and advice.capability_revision == pins.completion.provider_revision
        and advice.requested_model == READ_GRANTS.model_selection.model
        and advice.reply_bytes == len(advice.advice.encode("utf-8"))
        and _int(closure["answer_bytes"], advice.reply_bytes)
        # Producer: codex.py:1907 records an unobserved served model as
        # "unknown"; the advice carries the same absence as None.
        and closure["served_model"] == (
            "unknown" if advice.served_model is None else advice.served_model
        ), code,
    )
    return _evidence(projection, original_stdout, original_stderr, original_rc)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    advice = argv[:1] == [ADVICE]
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("store", "attempt"):
        parser.add_argument(name, type=Path)
    fields = CompletionPins.__dataclass_fields__ if advice else ClosurePins.__dataclass_fields__
    for name in fields:
        parser.add_argument(name)
    args = vars(parser.parse_args(argv[1:] if advice else argv))
    store, attempt = args.pop("store"), args.pop("attempt")
    from constructicon.core.errors import ConstructiconError

    refusal = "CHANGE_REVIEW_READ_CLOSURE_UNPROVED" if advice else "M9_READ_CLOSURE_UNPROVED"
    try:
        if advice:
            raw = _wire(collect_advice(CompletionPins(**args), store, attempt))
        else:
            raw = _wire(collect(ClosurePins(**args), store, attempt))
        _need(len(raw) <= RESULT_LIMIT)
    except (OSError, ValueError, TypeError, KeyError, ConstructiconError, sqlite3.DatabaseError):
        print(refusal, file=sys.stderr)
        return 1
    sys.stdout.buffer.write(raw)
    return 0


if __name__ == "__main__":
    sys.path.insert(0, CONTROLLER)
    raise SystemExit(main())
