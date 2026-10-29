"""Actual fixed files/SQLite; only host UID/mode primitives are substituted."""

from __future__ import annotations

import ast
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ops import read_attempt_evidence as reader

AUTH, RUN = "fixture-authorization", "sha256:" + "1" * 64
PRIVATE = "PRIVATE-ACCOUNT-MODEL-TEXT"


def write(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    path.chmod(0o600)


def attempt():
    return {
        "authorization_id": AUTH,
        "run_id": RUN,
        "epoch": 1,
        "acquisition_id": "acq-" + "2" * 32,
        "phase": "outcome",
        "at": "2026-10-26T00:00:00+00:00",
        "dispatch": "completed",
        "facts": {
            "status": "success",
            "callback_started": 1,
            "callback_completed": 1,
            "initial_binding_checked": True,
            "terminal_binding_checked": True,
            "relay_closed": True,
            "relay_denied": {},
            "relay_destinations": {PRIVATE: 1},
        },
    }


@pytest.fixture
def files(tmp_path, monkeypatch):
    root = tmp_path / "run"
    root.mkdir(mode=0o700)
    uid = 123
    real_permissions = reader._permissions
    ancestors = {(path.stat().st_dev, path.stat().st_ino) for path in root.parents}
    root_id = root.stat().st_dev, root.stat().st_ino

    def permissions(info):
        _owner, mode = real_permissions(info)
        identity = info.st_dev, info.st_ino
        # Temp's OS-owned ancestors and Windows' missing POSIX owner/mode
        # support are the only substituted primitives; file bytes/FDs are real.
        if identity in ancestors:
            return 0, mode & ~0o22
        if identity == root_id:
            return uid, 0o700
        return uid, 0o600 if os.name == "nt" and stat.S_ISREG(info.st_mode) else mode

    monkeypatch.setattr(reader, "_permissions", permissions)
    monkeypatch.setattr(reader, "_service_uid", lambda: uid)
    monkeypatch.setattr(reader, "_effective_uid", lambda: uid)
    write(root / "read-attempt.json", attempt())
    source = Path(__file__).parents[1] / "src/constructicon/substrate/journal/_sqlite_base.py"
    (schema,) = [
        ast.literal_eval(node.value)
        for node in ast.parse(source.read_bytes()).body
        if isinstance(node, ast.Assign)
        and any(isinstance(n, ast.Name) and n.id == "_SCHEMA" for n in node.targets)
    ]
    db = sqlite3.connect(root / "read.sqlite")
    db.executescript(schema)
    db.execute(
        "INSERT INTO runs(run_id,manifest_hash,input_hash,inputs_json,status,created_at,"
        "owner_epoch) "
        "VALUES(?,?,?,?,?,?,?)",
        (
            RUN,
            "fixture",
            "fixture",
            json.dumps({"request": {"authorization": AUTH}}),
            "failed",
            "fixture",
            1,
        ),
    )
    db.execute(
        "INSERT INTO events VALUES(?,?,?,?,?,?)",
        (
            RUN,
            0,
            "NodeFailed",
            None,
            json.dumps(
                {
                    "error_type": "ContractViolation",
                    "error": "Claude qualification did not complete its fixed READ",
                }
            ),
            "fixture",
        ),
    )
    db.commit()
    db.close()
    (root / "read.sqlite").chmod(0o600)
    return root


def collect(root):
    return reader.collect(root, AUTH, RUN, 1)


def test_real_files_and_schema_accept_without_publishing_private_values(files):
    result = collect(files)
    assert result["attempt"] == {
        "state": "valid",
        "partial": False,
        "phase": "outcome",
        "dispatch": "completed",
        "status": "success",
        "callback_started": 1,
        "callback_completed": 1,
        "initial_binding_checked": True,
        "terminal_binding_checked": True,
        "relay_closed": True,
        "callback_observation": None,
    }
    assert result["journal"] == {
        "state": "valid",
        "partial": False,
        "run_status": "failed",
        "event_count": 1,
        "events": [
            {
                "kind": "NodeFailed",
                "error_type": "ContractViolation",
                "reason": "read_contract_refused",
            }
        ],
    }
    assert (
        PRIVATE not in json.dumps(result)
        and AUTH not in json.dumps(result)
        and RUN not in json.dumps(result)
    )


def test_standalone_projector_catalog_matches_closed_driver_codes():
    from constructicon.substrate.executors.claude_read import ClaudeReadRefusalCode, refusal_detail

    emitted = {refusal_detail(code): "claude_read_" + code.value.replace("-", "_")
               for code in ClaudeReadRefusalCode}
    projected = {message: reason for message, reason in reader.REASONS.items()
                 if reason.startswith("claude_read_")}
    assert projected == emitted
    assert all(len(message.encode()) <= 96 and len(reason) <= 64
               for message, reason in emitted.items())


def test_context_vocabulary_matches_driver():
    from constructicon.substrate.executors.claude_read import (
        ClaudeReadReceivePhase,
        ClaudeReadRefusalFamily,
        ClaudeReadRefusalPredicate,
    )

    assert {v.value for v in ClaudeReadRefusalFamily} == reader.REFUSAL_FAMILIES
    assert {v.value for v in ClaudeReadReceivePhase} == reader.REFUSAL_PHASES
    assert {v.value for v in ClaudeReadRefusalPredicate} == reader.REFUSAL_PREDICATES


def test_isolated_reader_projects_every_closed_family_without_controller_imports():
    program = """\
import json, sys
namespace = {'__name__': 'standalone_reader'}
with open(sys.argv[1], encoding='utf-8') as source:
    exec(compile(source.read(), sys.argv[1], 'exec'), namespace)
result = {}
for family in sorted(namespace['REFUSAL_FAMILIES']):
    detail = ('Claude READ refused [known_refusal=system-other; family=' + family +
              '; phase=body-after-callback; predicate=unsupported-family; '
              'terminal_result_accepted=false]')
    result[family] = namespace['refusal_context'](detail)
result['private'] = namespace['refusal_context'](detail.replace(family, 'PRIVATE'))
assert not any(name.startswith('constructicon') for name in sys.modules)
print(json.dumps(result))
"""
    child = subprocess.run(
        [sys.executable, "-I", "-S", "-B", "-c", program, reader.__file__],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True,
    )
    observed = json.loads(child.stdout)
    assert observed.pop("private") is None
    assert set(observed) == reader.REFUSAL_FAMILIES
    for family, (reason, context) in observed.items():
        assert reason == "claude_read_system_other"
        assert context == {"family": family, "phase": "body-after-callback",
                           "predicate": "unsupported-family", "terminal_result_accepted": False}


@pytest.mark.parametrize("accepted", ["true", "false"])
def test_context_projects_exact_detail_independently_of_callback_counts(files, accepted):
    detail = ("Claude READ refused [known_refusal=api-retry; family=system-api-retry; "
              "phase=post-result; predicate=phase; terminal_result_accepted=" + accepted + "]")
    with sqlite3.connect(files / "read.sqlite") as db:
        db.execute("UPDATE events SET payload=?", (
            json.dumps({"error_type": "ContractViolation", "error": detail}),
        ))
    result = collect(files)
    assert result["attempt"]["callback_started"] == result["attempt"]["callback_completed"] == 1
    assert result["journal"]["events"][0] == {
        "kind": "NodeFailed", "error_type": "ContractViolation", "reason": "claude_read_api_retry",
        "refusal_context": {"family": "system-api-retry", "phase": "post-result",
                            "predicate": "phase", "terminal_result_accepted": accepted == "true"},
    }


@pytest.mark.parametrize("mutation", [
    lambda s: s + " extra", lambda s: s.replace("family=system-api-retry", "family=PRIVATE"),
    lambda s: s.replace("predicate=phase", "predicate=phase; private=PRIVATE"),
    lambda s: s.replace("terminal_result_accepted=false", "terminal_result_accepted=False"),
])
def test_context_rejects_malformed_or_private_detail(files, mutation):
    detail = mutation("Claude READ refused [known_refusal=api-retry; family=system-api-retry; "
                      "phase=drain; predicate=phase; terminal_result_accepted=false]")
    with sqlite3.connect(files / "read.sqlite") as db:
        db.execute("UPDATE events SET payload=?", (
            json.dumps({"error_type": "ContractViolation", "error": detail}),
        ))
    event = collect(files)["journal"]["events"][0]
    assert event == {"kind": "NodeFailed", "error_type": "ContractViolation", "reason": "other"}


@pytest.mark.parametrize("error_type,message", [
    ("ContractViolation", "Claude READ refused [known_refusal=private-account]"),
    ("ValueError", "Claude READ refused [known_refusal=system-init-model]"),
    ("ValueError", "Claude READ refused [known_refusal=api-retry; family=system-api-retry; "
                   "phase=drain; predicate=phase; terminal_result_accepted=true]"),
    ("ContractViolation", PRIVATE),
])
def test_closed_refusal_projection_never_accepts_unknown_detail_or_wrong_class(
    files, error_type, message,
):
    with sqlite3.connect(files / "read.sqlite") as db:
        db.execute("UPDATE events SET payload=?", (
            json.dumps({"error_type": error_type, "error": message}),
        ))
    result = collect(files)
    assert result["journal"]["state"] == "valid"
    event, = result["journal"]["events"]
    assert event["reason"] == "other"
    assert message not in json.dumps(result) and PRIVATE not in json.dumps(result)


@pytest.mark.parametrize("phase", ["acquired", "intent"])
def test_partial_attempt_never_infers_zero_or_dispatch(files, phase):
    value = attempt()
    value.pop("dispatch")
    value.pop("facts")
    value["phase"] = phase
    write(files / "read-attempt.json", value)
    result = collect(files)["attempt"]
    assert result["state"] == "valid" and result["partial"] is True and result["phase"] == phase
    assert result["dispatch"] is result["callback_started"] is result["callback_completed"] is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("authorization_id", PRIVATE),
        ("run_id", PRIVATE),
        ("epoch", True),
        ("epoch", 2),
        ("phase", []),
        ("acquisition_id", PRIVATE),
    ],
)
def test_bad_attempt_identity_or_shape_is_unknown(files, key, value):
    record = attempt()
    record[key] = value
    write(files / "read-attempt.json", record)
    result = collect(files)["attempt"]
    assert result["state"] == "invalid" and result["partial"] is True
    assert all(value is None for key, value in result.items() if key not in ("state", "partial"))


@pytest.mark.parametrize(
    "key,value",
    [
        ("callback_started", True),
        ("callback_completed", 2),
        ("initial_binding_checked", 1),
        ("status", PRIVATE),
    ],
)
def test_bad_settlement_types_or_bounds_are_unknown(files, key, value):
    record = attempt()
    record["facts"][key] = value
    write(files / "read-attempt.json", record)
    result = collect(files)["attempt"]
    assert result["state"] == "invalid" and result["callback_started"] is None


def test_callback_observation_is_independent_of_settlement_counts(files):
    record = attempt()
    record["callbacks"] = {
        "schema_version": 1,
        "admitted_started": 0,
        "admitted_completed": 0,
        "worker_results": [],
    }
    write(files / "read-attempt.json", record)
    result = collect(files)["attempt"]
    assert result["callback_started"] == 1
    assert result["callback_observation"]["admitted_started"] == 0
    record["callbacks"]["admitted_started"] = True
    write(files / "read-attempt.json", record)
    assert collect(files)["attempt"]["callback_observation"] is None


def test_missing_files_are_explicit_unknown(files):
    (files / "read-attempt.json").unlink()
    (files / "read.sqlite").unlink()
    result = collect(files)
    for key in ("attempt", "journal"):
        assert result[key]["state"] == "missing" and result[key]["partial"] is True
    assert result["journal"]["event_count"] is None


@pytest.mark.parametrize("damage", ["owner", "mode", "links", "oversize", "changed", "symlink"])
def test_real_file_guard_refuses_metadata_and_stability_damage(files, monkeypatch, damage):
    path = files / "read-attempt.json"
    identity = path.stat().st_dev, path.stat().st_ino
    real_permissions = reader._permissions
    if damage in ("owner", "mode"):

        def permissions(info):
            if (info.st_dev, info.st_ino) == identity:
                return (999, 0o600) if damage == "owner" else (123, 0o644)
            return real_permissions(info)

        monkeypatch.setattr(reader, "_permissions", permissions)
    elif damage == "links":
        os.link(path, files / "linked")
    elif damage == "oversize":
        record = attempt()
        record["at"] = ""
        record["at"] = "x" * (reader.ATTEMPT_BYTES + 1 - len(json.dumps(record).encode()))
        write(path, record)
    elif damage == "changed":
        finish = reader._finish

        def changed(item, fd, before, **kwargs):
            if item == path:
                path.write_bytes(b"changed")
            return finish(item, fd, before, **kwargs)

        monkeypatch.setattr(reader, "_finish", changed)
    else:
        path.rename(files / "other")
        try:
            path.symlink_to(files / "other")
        except OSError:
            pytest.skip("Windows symlink privilege unavailable")
    assert collect(files)["attempt"]["state"] == "invalid"


@pytest.mark.parametrize("mode", [0o600, 0o644])
def test_actual_uncheckpointed_wal_is_read_and_not_checkpointed(files, monkeypatch, mode):
    writer = sqlite3.connect(files / "read.sqlite")
    try:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
        writer.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?)", (RUN, 1, "RunFailed", None, "{}", "fixture")
        )
        writer.commit()
        identities = set()
        for suffix in ("", "-wal", "-shm"):
            path = files / ("read.sqlite" + suffix)
            path.chmod(mode)
            info = path.stat()
            identities.add((info.st_dev, info.st_ino))
        permissions = reader._permissions

        def sqlite_mode(info):
            if (info.st_dev, info.st_ino) in identities:
                return 123, mode
            return permissions(info)

        monkeypatch.setattr(reader, "_permissions", sqlite_mode)
        before = (files / "read.sqlite-wal").read_bytes()
        result = collect(files)["journal"]
        assert result["state"] == "valid" and result["event_count"] == 2
        assert result["events"][-1]["kind"] == "RunFailed"
        assert (files / "read.sqlite-wal").read_bytes() == before
    finally:
        writer.close()


@pytest.mark.parametrize("change", ["timestamps", "content"])
def test_wal_timestamp_only_change_accepts_but_changed_content_refuses(files, monkeypatch, change):
    writer = sqlite3.connect(files / "read.sqlite")
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute(
        "INSERT INTO events VALUES(?,?,?,?,?,?)", (RUN, 1, "RunFailed", None, "{}", "fixture")
    )
    writer.commit()
    wal = files / "read.sqlite-wal"
    original = wal.read_bytes()
    try:
        if change == "timestamps":
            connect = sqlite3.connect

            def timestamp_changed(*args, **kwargs):
                connection = connect(*args, **kwargs)
                info = wal.stat()
                os.utime(wal, ns=(info.st_atime_ns, info.st_mtime_ns + 1000000))
                return connection

            monkeypatch.setattr(reader.sqlite3, "connect", timestamp_changed)
        else:
            finish = reader._finish

            def content_changed(item, fd, before, **kwargs):
                if item == wal:
                    with wal.open("r+b") as stream:
                        stream.seek(-1, os.SEEK_END)
                        stream.write(bytes([original[-1] ^ 1]))
                return finish(item, fd, before, **kwargs)

            monkeypatch.setattr(reader, "_finish", content_changed)
        result = collect(files)["journal"]
        assert result["state"] == ("valid" if change == "timestamps" else "invalid")
        if change == "timestamps":
            assert result["event_count"] == 2 and wal.read_bytes() == original
        else:
            assert result["event_count"] is None and wal.stat().st_size == len(original)
    finally:
        wal.write_bytes(original)
        writer.close()


@pytest.mark.parametrize(
    "target_name",
    ["root", "read-attempt.json", "read.sqlite", "read.sqlite-wal", "read.sqlite-shm"],
)
def test_symlink_resolution_loops_never_echo_private_tracebacks(
    files, monkeypatch, capsys, target_name
):
    is_root = target_name == "root"
    target = files if is_root else files / target_name
    if not is_root and not target.exists():
        target.write_bytes(b"")
        target.chmod(0o600)
    saved = target.with_name("saved-loop-target")
    target.rename(saved)
    try:
        target.symlink_to(target, target_is_directory=is_root)
    except OSError:
        saved.rename(target)
        resolve = Path.resolve

        def loop(path, *args, **kwargs):
            if path == target:
                raise RuntimeError(PRIVATE)
            return resolve(path, *args, **kwargs)

        monkeypatch.setattr(Path, "resolve", loop)
    argv = [
        "--run-root",
        str(files),
        "--authorization-id",
        AUTH,
        "--run-id",
        RUN,
        "--max-epoch",
        "1",
    ]
    assert reader.main(argv) == 1
    captured = capsys.readouterr()
    assert PRIVATE not in captured.out + captured.err
    assert str(files) not in captured.out + captured.err
    if is_root:
        assert captured.out == "" and captured.err == "read evidence collection refused\n"
    else:
        result = json.loads(captured.out)
        artifact = "attempt" if target_name == "read-attempt.json" else "journal"
        assert result[artifact]["state"] == "invalid" and result[artifact]["partial"] is True


@pytest.mark.parametrize("preexisting", [False, True])
def test_wal_digest_failure_closes_registered_descriptors(files, monkeypatch, preexisting):
    writer = None
    if preexisting:
        writer = sqlite3.connect(files / "read.sqlite")
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?)", (RUN, 1, "RunFailed", None, "{}", "fixture")
        )
        writer.commit()
    else:
        connect = sqlite3.connect

        def appeared(*args, **kwargs):
            connection = connect(*args, **kwargs)
            wal = files / "read.sqlite-wal"
            wal.write_bytes(b"")
            wal.chmod(0o600)
            return connection

        monkeypatch.setattr(reader.sqlite3, "connect", appeared)
    opened, actual_open = [], reader._open

    def tracked(*args, **kwargs):
        descriptor, info = actual_open(*args, **kwargs)
        opened.append((args[0].name, descriptor))
        return descriptor, info

    def failed_digest(*_):
        raise ValueError(PRIVATE)

    monkeypatch.setattr(reader, "_open", tracked)
    monkeypatch.setattr(reader, "_wal_digest", failed_digest)
    try:
        result = collect(files)["journal"]
        assert result["state"] == "invalid" and result["events"] is None
        assert any(name == "read.sqlite-wal" for name, _ in opened)
        for _, descriptor in opened:
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        if writer is not None:
            writer.close()


def test_fd_identity_swap_is_refused(files, monkeypatch):
    path = files / "read-attempt.json"
    real_open = os.open

    def swapped(item, flags, *args, **kwargs):
        if item == path:
            path.rename(files / "retained-original")
            write(path, attempt())
        return real_open(item, flags, *args, **kwargs)

    monkeypatch.setattr(reader.os, "open", swapped)
    assert collect(files)["attempt"]["state"] == "invalid"


@pytest.mark.parametrize("damage", ["private-mode", "appeared-unsafe", "oversize"])
def test_sqlite_file_and_auxiliary_guard_refuse(files, monkeypatch, damage):
    if damage == "private-mode":
        writer = sqlite3.connect(files / "read.sqlite")
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?)", (RUN, 1, "RunFailed", None, "{}", "fixture")
        )
        writer.commit()
        identity = (files / "read.sqlite-wal").stat()
        real_permissions = reader._permissions

        def permissions(info):
            if (info.st_dev, info.st_ino) == (identity.st_dev, identity.st_ino):
                return 123, 0o660
            return real_permissions(info)

        monkeypatch.setattr(reader, "_permissions", permissions)
        try:
            assert collect(files)["journal"]["state"] == "invalid"
        finally:
            writer.close()
    elif damage == "appeared-unsafe":
        real_connect = sqlite3.connect
        real_permissions = reader._permissions
        identities = set()

        def appeared(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            (files / "read.sqlite-wal").write_bytes(b"")
            info = (files / "read.sqlite-wal").stat()
            identities.add((info.st_dev, info.st_ino))
            return connection

        def permissions(info):
            if (info.st_dev, info.st_ino) in identities:
                return 123, 0o660
            return real_permissions(info)

        monkeypatch.setattr(reader.sqlite3, "connect", appeared)
        monkeypatch.setattr(reader, "_permissions", permissions)
        assert collect(files)["journal"]["state"] == "invalid"
    else:
        with (files / "read.sqlite").open("ab") as stream:
            stream.truncate(reader.DB_BYTES + 1)
        assert collect(files)["journal"]["state"] == "invalid"


def test_closed_wal_database_accepts_privately_created_sidecars(files):
    writer = sqlite3.connect(files / "read.sqlite")
    assert writer.execute("PRAGMA journal_mode=WAL").fetchone() == ("wal",)
    writer.execute(
        "INSERT INTO events VALUES(?,?,?,?,?,?)", (RUN, 1, "RunFailed", None, "{}", "fixture")
    )
    writer.commit()
    writer.close()
    assert not (files / "read.sqlite-wal").exists()
    assert not (files / "read.sqlite-shm").exists()
    result = collect(files)["journal"]
    assert result["state"] == "valid" and result["event_count"] == 2


def test_root_directory_identity_cannot_change_between_observations(files, monkeypatch):
    journal = reader._journal
    permissions = reader._permissions
    replacement = set()

    def replacement_permissions(info):
        if (info.st_dev, info.st_ino) in replacement:
            return 123, 0o700
        return permissions(info)

    def changed(*args):
        result = journal(*args)
        before = files.stat()
        files.rename(files.with_name("retained-root"))
        files.mkdir(mode=0o700)
        after = files.stat()
        assert (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
        replacement.add((after.st_dev, after.st_ino))
        reader._root(files, 123)  # Only the later directory-identity comparison may refuse.
        return result

    monkeypatch.setattr(reader, "_permissions", replacement_permissions)
    monkeypatch.setattr(reader, "_journal", changed)
    with pytest.raises(ValueError, match="invalid retained evidence"):
        collect(files)


def test_actual_journal_lease_kinds_are_closed_and_obsolete_names_are_other(files):
    with sqlite3.connect(files / "read.sqlite") as db:
        db.executemany(
            "INSERT INTO events VALUES(?,?,?,?,?,?)",
            [
                (RUN, 1, "LeaseAcquired", None, "{}", "fixture"),
                (RUN, 2, "LeaseTransition", None, "{}", "fixture"),
                (RUN, 3, "CapabilityAcquired", None, "{}", "fixture"),
            ],
        )
    result = collect(files)["journal"]
    assert result["state"] == "valid"
    assert [event["kind"] for event in result["events"]] == [
        "NodeFailed",
        "LeaseAcquired",
        "LeaseTransition",
        "other",
    ]


def test_oversized_or_duplicate_json_cannot_publish_partial_private_values(files):
    payload = {"error": "", "error_type": "ContractViolation"}
    payload["error"] = "x" * (reader.EVENT_BYTES + 1 - len(json.dumps(payload).encode()))
    with sqlite3.connect(files / "read.sqlite") as db:
        db.execute(
            "UPDATE events SET payload=?",
            (json.dumps(payload),),
        )
    result = collect(files)["journal"]
    assert result["state"] == "invalid" and result["events"] is None
    (files / "read-attempt.json").write_bytes(b'{"phase":"intent","phase":"acquired"}')
    assert collect(files)["attempt"]["state"] == "invalid"


def test_exact_byte_bounds_permit_and_service_identity_is_required(files, monkeypatch):
    record = attempt()
    record["at"] = ""
    record["at"] = "x" * (reader.ATTEMPT_BYTES - len(json.dumps(record).encode()))
    write(files / "read-attempt.json", record)
    payload = {"error": "", "error_type": "ContractViolation"}
    payload["error"] = "x" * (reader.EVENT_BYTES - len(json.dumps(payload).encode()))
    with sqlite3.connect(files / "read.sqlite") as db:
        db.execute("UPDATE events SET payload=?", (json.dumps(payload),))
    result = collect(files)
    assert result["attempt"]["state"] == result["journal"]["state"] == "valid"
    monkeypatch.setattr(reader, "_effective_uid", lambda: 999)
    with pytest.raises(ValueError, match="invalid retained evidence"):
        collect(files)


@pytest.mark.parametrize(
    "column,value",
    [
        ("inputs_json", json.dumps({"request": {"authorization": PRIVATE}})),
        ("owner_epoch", 2),
        ("status", PRIVATE),
    ],
)
def test_journal_identity_or_type_mismatch_is_unknown(files, column, value):
    with sqlite3.connect(files / "read.sqlite") as db:
        db.execute(f"UPDATE runs SET {column}=? WHERE run_id=?", (value, RUN))
    result = collect(files)["journal"]
    assert result["state"] == "invalid" and result["run_status"] is result["event_count"] is None


def test_event_limit_binds_and_private_strings_are_closed(files):
    record = attempt()
    record["callbacks"] = {
        "schema_version": 1,
        "admitted_started": 8,
        "admitted_completed": 8,
        "worker_results": ["success"] * 8,
    }
    write(files / "read-attempt.json", record)
    with sqlite3.connect(files / "read.sqlite") as db:
        db.executemany(
            "INSERT INTO events VALUES(?,?,?,?,?,?)",
            [
                (
                    RUN,
                    n,
                    "NodeFailed",
                    None,
                    json.dumps({"error_type": PRIVATE, "error": PRIVATE}),
                    "fixture",
                )
                for n in range(1, 66)
            ],
        )
        db.execute(
            "INSERT INTO events VALUES(?,?,?,?,?,?)", (PRIVATE, 0, PRIVATE, None, PRIVATE, PRIVATE)
        )
        db.execute(
            "UPDATE events SET payload=? WHERE seq>=2",
            (json.dumps({"error_type": "ContractViolation", "error":
                "Claude READ refused [known_refusal=api-retry; "
                "family=system-model-refusal-no-fallback; phase=body-before-callback; "
                "predicate=unsupported-family; terminal_result_accepted=false]"}),),
        )
    result = collect(files)
    assert result["journal"]["state"] == "valid" and result["journal"]["partial"] is True
    assert result["journal"]["event_count"] == reader.EVENT_LIMIT
    assert result["journal"]["events"][1] == {
        "kind": "NodeFailed",
        "error_type": "other",
        "reason": "other",
    }
    assert PRIVATE not in json.dumps(result)
    allowed_keys = {
        "schema_version",
        "attempt",
        "journal",
        "state",
        "partial",
        "phase",
        "dispatch",
        "status",
        "callback_started",
        "callback_completed",
        "initial_binding_checked",
        "terminal_binding_checked",
        "relay_closed",
        "callback_observation",
        "admitted_started",
        "admitted_completed",
        "worker_results",
        "run_status",
        "event_count",
        "events",
        "kind",
        "error_type",
        "reason",
        "refusal_context", "family", "predicate", "terminal_result_accepted",
    }
    allowed_strings = (
        reader.PHASES
        | reader.DISPATCH
        | reader.STATUS
        | reader.RUN_STATUS
        | reader.EVENTS
        | reader.ERRORS
        | reader.WORKERS
        | reader.REFUSAL_FAMILIES
        | reader.REFUSAL_PHASES
        | reader.REFUSAL_PREDICATES
        | set(reader.REASONS.values())
        | {"valid", "invalid", "missing", "other"}
    )

    def walk(value):
        if isinstance(value, dict):
            assert set(value) <= allowed_keys
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            assert len(value) <= reader.EVENT_LIMIT
            for child in value:
                walk(child)
        elif isinstance(value, str):
            assert value in allowed_strings and len(value) <= 64
        else:
            assert value is None or type(value) in (bool, int)

    walk(result)
    assert len(json.dumps(result).encode()) <= reader.OUTPUT_BYTES
    record["callbacks"]["admitted_started"] = 9
    record["callbacks"]["admitted_completed"] = 9
    record["callbacks"]["worker_results"] = ["success"] * 9
    write(files / "read-attempt.json", record)
    assert collect(files)["attempt"]["state"] == "invalid"


def test_maximum_closed_context_projection_fits_transport_bound(files):
    from scripts.ops import read_metadata_session as metadata

    code_literal = max(
        (message for message in reader.REASONS
         if message.startswith("Claude READ refused [known_refusal=")),
        key=lambda message: len(reader.REASONS[message]),
    )
    code = code_literal.removeprefix("Claude READ refused [known_refusal=").removesuffix("]")
    detail = (f"Claude READ refused [known_refusal={code}; "
              f"family={max(reader.REFUSAL_FAMILIES, key=len)}; "
              f"phase={max(reader.REFUSAL_PHASES, key=len)}; "
              f"predicate={max(reader.REFUSAL_PREDICATES, key=len)}; "
              "terminal_result_accepted=false]")
    assert len(detail.encode()) <= 256
    payload = json.dumps({"error_type": "ContractViolation", "error": detail})
    with sqlite3.connect(files / "read.sqlite") as db:
        db.execute("UPDATE events SET payload=?", (payload,))
        db.executemany("INSERT INTO events VALUES(?,?,?,?,?,?)", [
            (RUN, n, "NodeFailed", None, payload, "fixture")
            for n in range(1, reader.EVENT_LIMIT)
        ])
    result = collect(files)
    raw = json.dumps(result).encode()
    assert result["journal"]["event_count"] == reader.EVENT_LIMIT
    assert not result["journal"]["partial"]
    assert all("refusal_context" in event for event in result["journal"]["events"])
    assert 16384 < len(raw) <= reader.OUTPUT_BYTES
    assert metadata.observation_checked(raw) == result


@pytest.mark.parametrize(
    "error_type,reason", [("ContractViolation", "probe_contradiction"), ("ValueError", "other")]
)
def test_source_backed_probe_reason_requires_its_exception_type(files, error_type, reason):
    with sqlite3.connect(files / "read.sqlite") as db:
        db.execute(
            "UPDATE events SET payload=?",
            (
                json.dumps(
                    {
                        "error_type": error_type,
                        "error": "the physical Linux launch probe contradicts containment",
                    }
                ),
            ),
        )
    assert collect(files)["journal"]["events"][0]["reason"] == reason


def test_main_outputs_closed_facts_and_invalid_evidence_is_nonzero(files, capsys):
    argv = [
        "--run-root",
        str(files),
        "--authorization-id",
        AUTH,
        "--run-id",
        RUN,
        "--max-epoch",
        "1",
    ]
    assert reader.main(argv) == 0
    assert json.loads(capsys.readouterr().out)["journal"]["state"] == "valid"
    write(files / "read-attempt.json", {"private": PRIVATE})
    assert reader.main(argv) == 1
    captured = capsys.readouterr()
    assert PRIVATE not in captured.out + captured.err


def test_real_isolated_cli_argument_errors_never_echo_input():
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", reader.__file__, "--private", PRIVATE],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2 and result.stdout == b""
    assert result.stderr.decode() == "read evidence arguments refused" + os.linesep


@pytest.mark.parametrize(
    "mode,valid",
    [
        (0o600, True),
        (0o604, True),
        (0o640, True),
        (0o644, True),
        (0o660, False),
        (0o666, False),
        (0o700, False),
        (0o1600, False),
        (0o400, False),
    ],
)
def test_sqlite_only_read_bit_allowance_does_not_allow_writes_or_exec(
    files, monkeypatch, mode, valid
):
    path = files / "read.sqlite"
    path.chmod(mode)
    identity = path.stat().st_dev, path.stat().st_ino
    permissions = reader._permissions

    def file_mode(info):
        if (info.st_dev, info.st_ino) == identity:
            return 123, mode
        return permissions(info)

    monkeypatch.setattr(reader, "_permissions", file_mode)
    result = collect(files)["journal"]
    assert result["state"] == ("valid" if valid else "invalid")
    if not valid:
        assert result["run_status"] is result["event_count"] is None


@pytest.mark.parametrize("damage", ["owner", "root-mode", "attempt-mode"])
def test_sqlite_allowance_does_not_relax_owner_root_or_attempt(files, monkeypatch, damage):
    target = (
        files
        if damage == "root-mode"
        else files / ("read-attempt.json" if damage == "attempt-mode" else "read.sqlite")
    )
    identity = target.stat().st_dev, target.stat().st_ino
    permissions = reader._permissions

    def damaged(info):
        if (info.st_dev, info.st_ino) == identity:
            return (
                (999, 0o644)
                if damage == "owner"
                else (123, 0o750 if damage == "root-mode" else 0o644)
            )
        return permissions(info)

    monkeypatch.setattr(reader, "_permissions", damaged)
    if damage == "root-mode":
        with pytest.raises(ValueError, match="invalid retained evidence"):
            collect(files)
    else:
        result = collect(files)["attempt" if damage == "attempt-mode" else "journal"]
        assert result["state"] == "invalid" and result["partial"] is True


@pytest.mark.parametrize("mask,expected_mode", [(0o077, 0o600), (0o022, 0o644)])
def test_actual_current_journal_schema_and_producer_are_readable(files, mask, expected_mode):
    from constructicon.api.system import Constructicon
    from constructicon.core.address import RunId
    from constructicon.core.graph import Graph
    from constructicon.core.ports import Port
    from constructicon.substrate.journal.sqlite import SqliteJournal

    database = files / "read.sqlite"
    database.unlink()
    previous = os.umask(mask)
    try:
        journal = SqliteJournal(database)
        system = Constructicon(journal=journal)
        inputs = {"request": {"authorization": AUTH}}
        graph = Graph(
            name="fixed-metadata",
            inputs=(Port(name="request", type_id="fixture", schema_hash="v1"),),
            outputs=(),
            nodes=(),
        )
        manifest = system.validate(graph, inputs)
        journal.create_run(
            RunId(RUN),
            manifest_json=manifest.model_dump_json(),
            manifest_hash=manifest.manifest_hash,
            input_hash=manifest.input_hash,
            inputs=inputs,
        )
    finally:
        os.umask(previous)
    if os.name != "nt":
        assert stat.S_IMODE(database.stat().st_mode) == expected_mode
    # This deliberately uses no journal constructor/UDFs on the read side.
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0) as connection:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        assert connection.execute("SELECT inputs_json FROM runs WHERE run_id=?", (RUN,)).fetchone()
    result = collect(files)["journal"]
    assert result["state"] == "valid" and result["run_status"] == "pending"
