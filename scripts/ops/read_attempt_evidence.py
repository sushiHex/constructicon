"""Fixed Claude READ metadata projection; no execution/recovery/credential imports.

Source laws: attempt_record.py:reserve/_replace; claude_provider.py:_settle;
_sqlite_base.py:_SCHEMA; walker.py NodeFailed/RunFailed writers. SQLite read
locks can touch its guarded shm; mode=ro is not a zero-filesystem-write claim.
The two retained artifacts are independent observations, not an atomic snapshot.
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
from pathlib import Path

ATTEMPT_BYTES, DB_BYTES, EVENT_BYTES, EVENT_LIMIT = 32768, 16 * 1024 * 1024, 8192, 64
OUTPUT_BYTES = 32768
EVENTS = frozenset(
    {
        "RunStarted",
        "RunSucceeded",
        "RunFailed",
        "RunCancelled",
        "NodeStarted",
        "NodeCompleted",
        "NodeFailed",
        "NodeParked",
        "LeaseAcquired",
        "LeaseTransition",
    }
)
ERRORS = frozenset(
    {
        "ContractViolation",
        "TimeoutError",
        "OSError",
        "ValueError",
        "RuntimeError",
        "ExceptionGroup",
        "BaseExceptionGroup",
        "CancelledError",
    }
)
# Exact source literals: api/claude_qualification.py:75; executors/linux.py:816.
REASONS = {
    "Claude qualification did not complete its fixed READ": "read_contract_refused",
    "the physical Linux launch probe contradicts containment": "probe_contradiction",
    "Claude READ refused [known_refusal=record]": "claude_read_record",
    "Claude READ refused [known_refusal=record-parse]": "claude_read_record_parse",
    "Claude READ refused [known_refusal=unhandled-record]": "claude_read_unhandled_record",
    "Claude READ refused [known_refusal=system-status]": "claude_read_system_status",
    "Claude READ refused [known_refusal=system-ui-panes]": "claude_read_system_ui_panes",
    "Claude READ refused [known_refusal=system-background]": "claude_read_system_background",
    "Claude READ refused [known_refusal=system-other]": "claude_read_system_other",
    "Claude READ refused [known_refusal=command-lifecycle]": "claude_read_command_lifecycle",
    "Claude READ refused [known_refusal=command-terminated]": "claude_read_command_terminated",
    "Claude READ refused [known_refusal=stream-bound]": "claude_read_stream_bound",
    "Claude READ refused [known_refusal=stream-end]": "claude_read_stream_end",
    "Claude READ refused [known_refusal=record-spacing]": "claude_read_record_spacing",
    "Claude READ refused [known_refusal=barrier-control-request]": (
        "claude_read_barrier_control_request"
    ),
    "Claude READ refused [known_refusal=barrier-result]": "claude_read_barrier_result",
    "Claude READ refused [known_refusal=barrier-user]": "claude_read_barrier_user",
    "Claude READ refused [known_refusal=barrier-unknown]": "claude_read_barrier_unknown",
    "Claude READ refused [known_refusal=ui-notification]": "claude_read_ui_notification",
    "Claude READ refused [known_refusal=mcp-envelope]": "claude_read_mcp_envelope",
    "Claude READ refused [known_refusal=mcp-handshake]": "claude_read_mcp_handshake",
    "Claude READ refused [known_refusal=mcp-call]": "claude_read_mcp_call",
    "Claude READ refused [known_refusal=mcp-arguments]": "claude_read_mcp_arguments",
    "Claude READ refused [known_refusal=system-init-order]": "claude_read_system_init_order",
    "Claude READ refused [known_refusal=system-init-session]": "claude_read_system_init_session",
    "Claude READ refused [known_refusal=system-init-uuid]": "claude_read_system_init_uuid",
    "Claude READ refused [known_refusal=system-init-model]": "claude_read_system_init_model",
    "Claude READ refused [known_refusal=system-init-tools]": "claude_read_system_init_tools",
    "Claude READ refused [known_refusal=system-init-server]": "claude_read_system_init_server",
    "Claude READ refused [known_refusal=message]": "claude_read_message",
    "Claude READ refused [known_refusal=rate-limit]": "claude_read_rate_limit",
    "Claude READ refused [known_refusal=rate-limit-rejected]": "claude_read_rate_limit_rejected",
    "Claude READ refused [known_refusal=result]": "claude_read_result",
    "Claude READ refused [known_refusal=tail]": "claude_read_tail",
    "Claude READ refused [known_refusal=api-retry]": "claude_read_api_retry",
    "Claude READ refused [known_refusal=thinking-tokens]": "claude_read_thinking_tokens",
}
# Generated from core/claude_read_observation.py: standalone -I -S -B cannot import core.
REFUSAL_FAMILIES = frozenset({
    "other-record",
    "system-agents-killed",
    "system-api-error",
    "system-api-retry",
    "system-away-summary",
    "system-background-tasks-changed",
    "system-bridge-state",
    "system-bridge-status",
    "system-cloud-session-delta",
    "system-cloud-session-status",
    "system-code-change-published",
    "system-commands-changed",
    "system-compact-boundary",
    "system-control-request-progress",
    "system-dev-intent",
    "system-elicitation-complete",
    "system-feedback-draft-queued",
    "system-file-attachments-missing",
    "system-file-snapshot",
    "system-files-persisted",
    "system-hook-progress",
    "system-hook-response",
    "system-hook-started",
    "system-informational",
    "system-init",
    "system-init-milestone",
    "system-instruction-size-warning",
    "system-invalid-subtype",
    "system-local-command",
    "system-local-command-output",
    "system-memory-recall",
    "system-memory-saved",
    "system-mirror-error",
    "system-missing-subtype",
    "system-model-consent-fallback",
    "system-model-fallback",
    "system-model-refusal-fallback",
    "system-model-refusal-no-fallback",
    "system-notification",
    "system-peer-message-hold",
    "system-per-turn-effort-changed",
    "system-permission-check-status",
    "system-permission-denied",
    "system-permission-retry",
    "system-plugin-install",
    "system-post-turn-summary",
    "system-scheduled-task-fire",
    "system-session-metadata",
    "system-session-state-changed",
    "system-session-title-changed",
    "system-status",
    "system-stop-hook-summary",
    "system-task-notification",
    "system-task-progress",
    "system-task-started",
    "system-task-summary",
    "system-task-updated",
    "system-thinking",
    "system-thinking-tokens",
    "system-tool-host-result",
    "system-turn-duration",
    "system-turn-handoff-available",
    "system-turn-preempted",
    "system-turn-starting",
    "system-ui-focus",
    "system-ui-invalidate",
    "system-ui-log",
    "system-ui-panes",
    "system-ui-scroll",
    "system-ui-status",
    "system-ui-toast",
    "system-unknown-subtype",
    "system-upgrade-relay-marker",
    "system-vcs-state-changed",
    "system-worker-shutting-down",
    "system-workflow-launch-result",
    "unparsed",
})
REFUSAL_PHASES = frozenset({
    "startup", "body-before-callback", "body-after-callback", "callback-barrier",
    "post-result", "drain",
})
REFUSAL_PREDICATES = frozenset({
    "shape", "correlation", "phase", "explicit-negative", "unsupported-family", "guard",
})
REFUSAL_PATTERN = re.compile(
    r"Claude READ refused \[known_refusal=([a-z-]+); family=([a-z-]+); "
    r"phase=([a-z-]+); predicate=([a-z-]+); terminal_result_accepted=(true|false)\]"
)


def refusal_context(value):
    """Return only exact closed context, never a partially parsed vendor value."""
    if type(value) is not str:
        return None
    match = REFUSAL_PATTERN.fullmatch(value)
    if match is None:
        return None
    code, family, phase, predicate, accepted = match.groups()
    reason = REASONS.get(f"Claude READ refused [known_refusal={code}]")
    if (reason is None or family not in REFUSAL_FAMILIES or phase not in REFUSAL_PHASES
            or predicate not in REFUSAL_PREDICATES):
        return None
    return reason, {
        "family": family, "phase": phase, "predicate": predicate,
        "terminal_result_accepted": accepted == "true",
    }
PHASES = {"acquired", "intent", "outcome"}
DISPATCH = {"completed", "not dispatched", "possibly dispatched"}
STATUS = {"success", "partial", "failure"}
RUN_STATUS = {"pending", "running", "succeeded", "failed", "cancelled"}
WORKERS = {"success", "nonzero", "timeout", "output_bound", "incomplete", "invalid_utf8"}
STABLE = (
    "st_dev",
    "st_ino",
    "st_mode",
    "st_nlink",
    "st_uid",
    "st_gid",
    "st_size",
    "st_mtime_ns",
    "st_ctime_ns",
)


def require(condition):
    if not condition:
        raise ValueError("invalid retained evidence")


def _permissions(info):
    return info.st_uid, stat.S_IMODE(info.st_mode)


def _service_uid():
    import pwd

    return pwd.getpwnam("m8-service").pw_uid


def _effective_uid():
    return os.geteuid()


def _same(before, after, *, shm=False):
    fields = STABLE[:-2] if shm else STABLE
    require(all(getattr(before, key) == getattr(after, key) for key in fields))


def _canonical(path):
    try:
        return path.resolve(strict=True) == path
    except RuntimeError:
        # Python 3.11/3.12 expose symlink loops as RuntimeError containing paths.
        raise ValueError("invalid retained evidence") from None


def _root(root, uid):
    require(root.is_absolute() and _canonical(root))
    for path in (root, *root.parents):
        info = path.lstat()
        owner, mode = _permissions(info)
        require(
            stat.S_ISDIR(info.st_mode)
            and owner in (0, uid)
            and not mode & 0o22
            and _canonical(path)
        )
    require(_permissions(root.lstat()) == (uid, 0o700))


def _open(path, uid, bound, *, sqlite_file=False):
    require(_canonical(path))
    before = path.lstat()
    owner, mode = _permissions(before)
    # SQLite inherits umask/sudo policy. Read bits do not cross the already
    # checked service-owned0700 run root; writes, exec and special bits refuse.
    private_mode = (mode & 0o600 == 0o600 and mode & ~0o644 == 0) if sqlite_file else mode == 0o600
    require(
        stat.S_ISREG(before.st_mode)
        and owner == uid
        and private_mode
        and before.st_nlink == 1
        and 0 <= before.st_size <= bound
    )
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    try:
        _same(before, os.fstat(fd))
    except BaseException:
        os.close(fd)
        raise
    return fd, before


def _wal_digest(fd, size):
    os.lseek(fd, 0, os.SEEK_SET)
    digest, total = hashlib.sha256(), 0
    while block := os.read(fd, min(65536, size + 1 - total)):
        total += len(block)
        require(total <= size)
        digest.update(block)
    require(total == size)
    return digest.digest()


def _finish(path, fd, before, *, shm=False, wal_digest=None):
    require(_canonical(path))
    metadata_only = shm or wal_digest is not None
    _same(before, os.fstat(fd), shm=metadata_only)
    _same(before, path.lstat(), shm=metadata_only)
    if wal_digest is not None:
        # SQLite can touch WAL timestamps during a read. Identity, custody,
        # size and bounded byte snapshots must still agree; shm contains locks.
        require(_wal_digest(fd, before.st_size) == wal_digest)
        _same(before, os.fstat(fd), shm=True)
        _same(before, path.lstat(), shm=True)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def _json(raw):
    return json.loads(
        raw, object_pairs_hook=_unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
    )


def _integer(value, maximum):
    return type(value) is int and 0 <= value <= maximum


def _attempt(root, uid, authorization, run, maximum):
    result = dict(
        state="invalid",
        partial=True,
        phase=None,
        dispatch=None,
        status=None,
        callback_started=None,
        callback_completed=None,
        initial_binding_checked=None,
        terminal_binding_checked=None,
        relay_closed=None,
        callback_observation=None,
    )
    path = root / "read-attempt.json"
    fd = None
    try:
        fd, before = _open(path, uid, ATTEMPT_BYTES)
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(ATTEMPT_BYTES + 1)
        require(len(raw) == before.st_size)
        _finish(path, fd, before)
        record = _json(raw)
        required = {"authorization_id", "run_id", "epoch", "acquisition_id", "phase", "at"}
        require(type(record) is dict and record.get("phase") in PHASES)
        phase = record["phase"]
        require(
            set(record)
            == required
            | ({"dispatch", "facts"} if phase == "outcome" else set())
            | ({"callbacks"} if "callbacks" in record else set())
        )
        require(
            record["authorization_id"] == authorization
            and record["run_id"] == run
            and _integer(record["epoch"], maximum)
            and record["epoch"] >= 1
            and type(record["acquisition_id"]) is str
            and re.fullmatch(r"acq-[0-9a-f]{32}", record["acquisition_id"]) is not None
        )
        projection = {}
        if "callbacks" in record:
            cb = record["callbacks"]
            require(
                type(cb) is dict
                and set(cb)
                == {"schema_version", "admitted_started", "admitted_completed", "worker_results"}
            )
            require(
                type(cb["schema_version"]) is int
                and cb["schema_version"] == 1
                and _integer(cb["admitted_started"], 8)
                and _integer(cb["admitted_completed"], cb["admitted_started"])
                and type(cb["worker_results"]) is list
                and len(cb["worker_results"]) == cb["admitted_started"]
            )
            require(
                all(
                    value is None or (type(value) is str and value in WORKERS)
                    for value in cb["worker_results"]
                )
                and all(
                    value == "success" for value in cb["worker_results"][: cb["admitted_completed"]]
                )
            )
            projection["callback_observation"] = cb
        if phase == "outcome":
            facts = record["facts"]
            require(
                type(record["dispatch"]) is str
                and record["dispatch"] in DISPATCH
                and type(facts) is dict
            )
            require(
                set(facts)
                == {
                    "status",
                    "callback_started",
                    "callback_completed",
                    "initial_binding_checked",
                    "terminal_binding_checked",
                    "relay_closed",
                    "relay_denied",
                    "relay_destinations",
                }
            )
            require(
                facts["status"] is None
                or (type(facts["status"]) is str and facts["status"] in STATUS)
            )
            require(
                _integer(facts["callback_started"], 1)
                and _integer(facts["callback_completed"], facts["callback_started"])
            )
            require(
                all(
                    type(facts[key]) is bool
                    for key in (
                        "initial_binding_checked",
                        "terminal_binding_checked",
                        "relay_closed",
                    )
                )
            )
            projection.update({key: facts[key] for key in result if key in facts})
            projection["dispatch"] = record["dispatch"]
        result.update(state="valid", partial=phase != "outcome", phase=phase, **projection)
    except FileNotFoundError:
        result["state"] = "missing" if fd is None and not path.is_symlink() else "invalid"
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        pass
    finally:
        if fd is not None:
            os.close(fd)
    return result


def _journal(root, uid, authorization, run, maximum):
    result = dict(state="invalid", partial=True, run_status=None, event_count=None, events=None)
    opened, connection, wal_digests = [], None, {}
    try:
        path = root / "read.sqlite"
        fd, before = _open(path, uid, DB_BYTES, sqlite_file=True)
        opened.append((path, fd, before, False))
        absent = []
        for suffix, bound in (("-wal", DB_BYTES), ("-shm", 1024 * 1024)):
            auxiliary = root / ("read.sqlite" + suffix)
            if auxiliary.exists() or auxiliary.is_symlink():
                aux_fd, info = _open(auxiliary, uid, bound, sqlite_file=True)
                opened.append((auxiliary, aux_fd, info, suffix == "-shm"))
                if suffix == "-wal":
                    wal_digests[aux_fd] = _wal_digest(aux_fd, info.st_size)
            else:
                absent.append((auxiliary, bound, suffix == "-shm"))
        connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=0)
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("BEGIN")
        # Fixed tables/columns from _sqlite_base._SCHEMA. No journal constructor/migration.
        require(
            connection.execute(
                "SELECT count(*) FROM sqlite_schema "
                "WHERE type='table' AND name IN ('runs','events')"
            ).fetchone()
            == (2,)
        )
        row = connection.execute(
            "SELECT status,owner_epoch,CASE WHEN length(CAST(inputs_json AS BLOB))<=4096 "
            "THEN inputs_json END FROM runs WHERE run_id=?",
            (run,),
        ).fetchone()
        require(
            row is not None
            and row[0] in RUN_STATUS
            and _integer(row[1], maximum)
            and _json(row[2]) == {"request": {"authorization": authorization}}
        )
        rows = connection.execute(
            "SELECT seq,kind,CASE WHEN kind='NodeFailed' "
            "AND length(CAST(payload AS BLOB))<=? THEN payload END "
            "FROM events WHERE run_id=? ORDER BY seq LIMIT ?",
            (EVENT_BYTES, run, EVENT_LIMIT + 1),
        ).fetchall()
        events = []
        for sequence, kind, payload in rows[:EVENT_LIMIT]:
            require(_integer(sequence, 2147483647) and type(kind) is str)
            event = dict(kind=kind if kind in EVENTS else "other", error_type=None, reason=None)
            if kind == "NodeFailed":
                failure = _json(payload)
                require(
                    type(failure) is dict
                    and type(failure.get("error")) is str
                    and type(failure.get("error_type")) is str
                )
                event.update(
                    error_type=failure["error_type"]
                    if failure["error_type"] in ERRORS
                    else "other",
                    reason=(
                        REASONS.get(failure["error"], "other")
                        if failure["error_type"] == "ContractViolation"
                        else "other"
                    ),
                )
                context = (refusal_context(failure["error"])
                           if failure["error_type"] == "ContractViolation" else None)
                if context is not None:
                    event["reason"], event["refusal_context"] = context
            events.append(event)
        # A closed WAL database may make read-only SQLite create private sidecars.
        # Guard newly present auxiliaries too; appearance alone is not invalidity.
        for item, bound, shm in absent:
            if item.exists() or item.is_symlink():
                descriptor, info = _open(item, uid, bound, sqlite_file=True)
                opened.append((item, descriptor, info, shm))
                if not shm:
                    wal_digests[descriptor] = _wal_digest(descriptor, info.st_size)
        for item, descriptor, info, shm in opened:
            _finish(item, descriptor, info, shm=shm, wal_digest=wal_digests.get(descriptor))
        result.update(
            state="valid",
            partial=len(rows) > EVENT_LIMIT,
            run_status=row[0],
            event_count=len(events),
            events=events,
        )
    except FileNotFoundError:
        result["state"] = (
            "missing" if not opened and not (root / "read.sqlite").is_symlink() else "invalid"
        )
    except (OSError, ValueError, TypeError, KeyError, RecursionError, sqlite3.Error):
        pass
    finally:
        if connection is not None:
            connection.close()
        for _, descriptor, _, _ in opened:
            os.close(descriptor)
    return result


def collect(run_root, expected_authorization_id, expected_run_id, max_epoch=1):
    """Inspect two fixed private artifacts; caller supplies previously checked pins."""
    require(type(max_epoch) is int and max_epoch == 1)
    require(
        all(
            type(value) is str and 0 < len(value) <= 256 and value.isprintable()
            for value in (expected_authorization_id, expected_run_id)
        )
    )
    root, uid = Path(run_root), _service_uid()
    require(uid > 0 and _effective_uid() == uid)
    _root(root, uid)
    directory = root.lstat()
    result = {
        "schema_version": 1,
        "attempt": _attempt(root, uid, expected_authorization_id, expected_run_id, max_epoch),
        "journal": _journal(root, uid, expected_authorization_id, expected_run_id, max_epoch),
    }
    _root(root, uid)
    after = root.lstat()
    require((directory.st_dev, directory.st_ino) == (after.st_dev, after.st_ino))
    require(len(json.dumps(result).encode("utf-8")) <= OUTPUT_BYTES)
    return result


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        del message
        self.exit(2, "read evidence arguments refused\n")


def main(argv=None):
    parser = _Parser(add_help=False, allow_abbrev=False)
    for name in ("run-root", "authorization-id", "run-id"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--max-epoch", required=True, type=int, choices=(1,))
    options = parser.parse_args(argv)
    try:
        result = collect(
            options.run_root, options.authorization_id, options.run_id, options.max_epoch
        )
    except (OSError, ValueError, TypeError, KeyError, ImportError):
        print("read evidence collection refused", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return int(any(result[key]["state"] == "invalid" for key in ("attempt", "journal")))


if __name__ == "__main__":
    raise SystemExit(main())
