"""The metadata CLI projects actual strict assembly facts, never a model turn."""

import sqlite3
from contextlib import closing
from dataclasses import asdict, replace
from datetime import datetime

import pytest

from constructicon.api import claude_write_qualification as entry
from constructicon.core.errors import ContractViolation
from constructicon.core.identity import digest, parse_json_value
from constructicon.core.manifest import source_graph_hash_for
from constructicon.substrate.journal.sqlite import SqliteJournal
from tests.api.test_claude_write_qualification import qualified as qualified
from tests.substrate.test_claude_provider import assembled as assembled
from tests.substrate.test_claude_provider import provider as provider


@pytest.fixture
def command(qualified, tmp_path, monkeypatch):
    a = qualified
    seen = {"read": [], "assemble": [], "opened": [], "closed": []}
    a.executor = type(a.executor)(**{**a.kwargs, "qualification": None})
    a.assembly = replace(a.assembly, executor=a.executor)

    def read(path):
        seen["read"].append(path)
        raise AssertionError("metadata checking must not read an authorization")

    async def assemble(options, authorization=None):
        assert authorization is None
        seen["assemble"].append((options, authorization))
        return a.assembly

    def opened():
        token = object()
        seen["opened"].append(token)
        a.state.locks += 1
        return token

    def closed(token):
        seen["closed"].append(token)
        a.state.locks -= 1

    monkeypatch.setattr(entry, "read_authorization", read)
    monkeypatch.setattr(entry, "assemble", assemble)
    monkeypatch.setattr(a.executor.binding_store, "open_candidate", opened)
    monkeypatch.setattr(a.executor.binding_store, "close_candidate", closed, raising=False)
    arguments = ["pins", "--journal", a.authorization.journal,
        "--fixture", str(tmp_path / "fixed-write"), "--launch-config", str(tmp_path / "launch"),
        "--launch-config-sha256", "0" * 64, "--store-root", str(tmp_path / "store"),
        "--store-key", "test-binding", "--sealed", str(tmp_path / "sealed"),
        "--qualification", str(tmp_path / "qualification"),
        "--acquisition-root", str(tmp_path / "acquisitions")]
    return a, arguments, seen


def test_main_pins_reports_actual_metadata_without_enrollment_or_dispatch(command, capsys):
    a, arguments, seen = command
    assert entry.main(arguments) == 0
    captured = capsys.readouterr()
    assert captured.err == "" and len(captured.out.encode("utf-8")) <= 8192
    actual = parse_json_value(captured.out)
    grants = entry.fixed_grants(a.executor)
    assert actual == {
        "schema": 1, "stage": "qualification-write",
        "scope": entry.fixed.WRITER_SCOPE.model_dump(mode="json"),
        "binding": entry.fixed.EXECUTOR, "capability_id": entry.CAPABILITY,
        "source_graph_hash": str(source_graph_hash_for(entry.graph(grants, a.assembly.pins))),
        "revision": a.executor.identity.revision,
        "operator_binding_digest": str(a.executor.identity.store.operator_binding_digest),
        "grants": grants.model_dump(mode="json"),
        "write": a.assembly.pins.model_dump(mode="json"),
        "qualification_digest": str(a.executor.identity.store.store_conformance_revision),
        "subscription_mode_revision": str(
            a.executor.identity.store.subscription_mode_adapter_revision),
        "model": "model", "effort": "high", "active_binding_checked": True,
        "declared_limits": {
            "native": asdict(a.executor.launcher.limits),
            "worker": asdict(a.executor.worker_launcher.limits),
            "resource": asdict(a.assembly.resources.workspace.launcher.limits),
            "callback_limit": 8, "exchange_s": 300,
        },
        "checked_at": actual["checked_at"],
    }
    assert datetime.fromisoformat(actual["checked_at"]).tzinfo is not None
    assert seen["read"] == [] and seen["assemble"][0][1] is None
    assert not hasattr(seen["assemble"][0][0], "authorization")
    assert str(seen["assemble"][0][0].journal) == a.authorization.journal
    assert a.executor.qualification is None and a.executor.unavailable_reasons
    assert len(seen["opened"]) == 1 and seen["closed"] == seen["opened"]
    assert a.state.locks == 0 and a.state.workers == a.state.exchanges == []
    assert a.assembly.resources.journal.run_state(a.authorization.run_id) is None
    assert not entry.Path(a.authorization.attempt_record).exists()
    assert all(value not in captured.out for value in (
        a.authorization.journal, a.authorization.attempt_record, "test-binding"))


def test_main_pins_refuses_assembled_pin_mismatch_and_closes_binding(command, capsys):
    a, arguments, seen = command
    changed = a.assembly.pins.model_copy(update={"report_definition": digest("wrong", 1, {})})
    a.assembly = replace(a.assembly, pins=changed)
    with pytest.raises(ContractViolation, match="metadata assembly"):
        entry.main(arguments)
    assert capsys.readouterr().out == ""
    assert seen["closed"] == seen["opened"] and len(seen["opened"]) == 1
    assert a.state.locks == 0 and a.state.workers == a.state.exchanges == []


def test_main_pins_rejects_authorization_input_before_assembly(command, capsys):
    _, arguments, seen = command
    with pytest.raises(SystemExit) as refused:
        entry.main([*arguments, "--authorization", "candidate.json"])
    assert refused.value.code == 2
    assert seen["read"] == seen["assemble"] == seen["opened"] == seen["closed"] == []
    assert capsys.readouterr().out == ""


def test_main_pins_current_binding_refusal_never_publishes(command, capsys, monkeypatch):
    a, arguments, seen = command

    def refused():
        raise ContractViolation("native store active selection is unavailable")

    monkeypatch.setattr(a.executor.binding_store, "open_candidate", refused)
    with pytest.raises(ContractViolation, match="active selection"):
        entry.main(arguments)
    assert capsys.readouterr().out == ""
    assert seen["closed"] == [] and a.state.locks == 0
    assert a.state.workers == a.state.exchanges == []


@pytest.mark.parametrize("failure", ["projection", "bound", "close"])
def test_main_pins_closes_on_error_and_never_emits_partial_success(
    command, capsys, monkeypatch, failure,
):
    a, arguments, seen = command
    if failure == "projection":
        def refused(*args):
            raise OSError("metadata unavailable")

        monkeypatch.setattr(entry.contained, "contained_pins", refused)
    elif failure == "bound":
        monkeypatch.setattr(entry, "PINS_BYTES", 1)
    else:
        close = a.executor.binding_store.close_candidate

        def failed_close(token):
            close(token)
            raise OSError("binding close failed")

        monkeypatch.setattr(a.executor.binding_store, "close_candidate", failed_close)
    with pytest.raises((ContractViolation, OSError)):
        entry.main(arguments)
    assert capsys.readouterr().out == ""
    assert seen["closed"] == seen["opened"] and len(seen["opened"]) == 1
    assert a.state.locks == 0 and a.state.workers == a.state.exchanges == []


def journal_contents(path):
    """Semantic schema and every table row, independent of WAL/file layout."""
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("BEGIN")
        schema = tuple(connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name",
        ))
        tables = {}
        for kind, name, _, _ in schema:
            if kind == "table":
                quoted = '"' + name.replace('"', '""') + '"'
                tables[name] = tuple(sorted(
                    connection.execute("SELECT * FROM " + quoted), key=repr,
                ))
        version = connection.execute("PRAGMA user_version").fetchone()
    return schema, tables, version


@pytest.mark.parametrize("operation", ["pins", "mint"])
def test_metadata_entries_reopen_schema_without_changing_any_domain_rows(
    command, capsys, monkeypatch, operation,
):
    a, arguments, seen = command
    path = a.authorization.journal
    # The ordinary fixture has initialized the current schema. Reopening below
    # exercises the real constructor/migration path, not an inert journal fake.
    before = journal_contents(path)
    assert {"runs", "commands", "checkpoints"} <= before[1].keys()
    assert before[1]["runs"] == before[1]["commands"] == before[1]["checkpoints"] == ()
    original = entry.assemble
    reopened = []

    async def actual_reopen(options, authorization=None):
        journal = SqliteJournal(options.journal)
        reopened.append(journal._db_path)
        return await original(options, authorization)

    monkeypatch.setattr(entry, "assemble", actual_reopen)
    if operation == "mint":
        arguments = ["mint", *arguments[1:],
            "--authorization-id", "metadata-only", "--actor", "static:test",
            "--key", "metadata-only", "--attempt-record", a.authorization.attempt_record]
    assert entry.main(arguments) == 0
    output = capsys.readouterr()
    assert output.err == "" and parse_json_value(output.out)
    assert reopened == [path]
    assert journal_contents(path) == before
    assert seen["read"] == []
    assert a.executor.qualification is None and a.executor.unavailable_reasons
    assert a.state.workers == a.state.exchanges == [] and a.state.locks == 0
    assert not entry.Path(a.authorization.attempt_record).exists()
