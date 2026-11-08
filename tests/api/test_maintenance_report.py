"""The shipped packet: closed refusals, bounded private-safe output, originals unread-for-write.

Accepting packets over a real entry run are in tests/e2e/test_maintenance_rehearsal.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from constructicon.api import maintenance_report as packet_module
from constructicon.core.run import RunStatus
from constructicon.substrate.journal import maintenance_diagnostic as diagnostic
from constructicon.substrate.journal._sqlite_schema import SCHEMA_VERSION
from tests.run_worlds import start_test_run
from tests.substrate.journal.conftest import portable_capture_custody
from tests.substrate.journal.test_maintenance_diagnostic import AUTH, RUN, WRITER, _attempt, _world

# Long and path-bearing: a host path, a credential-looking token and bulk.
HOSTILE = "/home/operator/.codex/auth.json:C:\\Users\\operator\\secret-" + "p" * 6000


@pytest.fixture
def layout(monkeypatch):
    # Exactly the journal tests' platform seams (Windows custody, ctime).
    portable_capture_custody.__wrapped__(monkeypatch)
    if os.name == "nt":
        identity = diagnostic._identity
        monkeypatch.setattr(diagnostic, "_identity", lambda value: (*identity(value)[:-1], 0))
    with tempfile.TemporaryDirectory(prefix="maintenance-report-test-", dir=Path.home()) as temp:
        parent = Path(temp).resolve()
        parent.chmod(0o700)
        yield parent / "original", parent / "captured"


def tree(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).digest()
            for path in sorted(root.rglob("*")) if path.is_file()}


def run_main(root: Path, out: Path, capsys) -> tuple[int, dict, str]:
    code = packet_module.main(["--root", str(root), "--out", str(out),
        "--command-report", str(root / "application-run.json"),
        "--run-id", RUN, "--authorization-id", AUTH])
    text = capsys.readouterr().out
    return code, json.loads(text), text


def assert_closed_refusal(packet: dict, text: str, stage: str) -> None:
    assert packet["complete"] is False and packet["stage"] == stage
    assert packet["error"] == "maintenance report refused or incomplete"
    assert len(text.encode()) <= 512
    for marker in ("operator", "auth.json", "secret", "pppp", "Users"):
        assert marker not in text


def test_missing_store_refuses_by_name(layout, capsys):
    root, out = layout
    root.mkdir(mode=0o700)
    (root / "application-run.json").write_text(json.dumps({"accepted": False, "run_id": RUN}),
                                               encoding="utf-8")
    before = tree(root)
    code, packet, text = run_main(root, out, capsys)
    assert code == 1 and packet["journal"] == "missing"
    assert_closed_refusal(packet, text, "journal")
    assert tree(root) == before and not (root / "maintenance.sqlite").exists()


def test_older_schema_store_is_refused_never_migrated_or_opened(layout, capsys, monkeypatch):
    root, out = layout
    _world(root)
    root.chmod(0o700)
    # The installed C490 controller writes schema 10; this report reads only current.
    with sqlite3.connect(root / "maintenance.sqlite") as connection:
        connection.execute("PRAGMA user_version = 10")
    connection.close()
    assert SCHEMA_VERSION == 11
    before = tree(root)

    def forbidden(*args, **kwargs):
        pytest.fail("an unsupported store reached the SqliteJournal constructor")

    monkeypatch.setattr(packet_module, "SqliteJournal", forbidden)
    code, packet, text = run_main(root, out, capsys)
    assert code == 1
    assert packet == {"schema_version": 1, "complete": False, "stage": "journal",
                      "error": "maintenance report refused or incomplete",
                      "journal": "unsupported-schema", "journal_schema_version": 10,
                      "supported_journal_schema_version": 11}
    assert_closed_refusal(packet, text, "journal")
    assert tree(root) == before
    with sqlite3.connect(f"file:{(root / 'maintenance.sqlite').as_posix()}?mode=ro",
                         uri=True) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 10
    connection.close()


def test_hostile_records_yield_bounded_private_safe_packet_and_originals_unchanged(
    layout, capsys, monkeypatch,
):
    root, out = layout
    journal = _world(root)
    root.chmod(0o700)
    lease = start_test_run(journal, RUN, owner_id="fixture")
    journal.append_event(lease, "NodeStarted", path=WRITER)
    journal.append_event(lease, "NodeFailed", path=WRITER, payload={
        "error_type": "ContractViolation", "error": HOSTILE, "private-extra": HOSTILE})
    journal.transition_run(lease, expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED, event_kind="RunFailed", payload={"error": HOSTILE})
    _attempt(root)
    (root / "application-run.json").write_text(json.dumps({"accepted": False, "run_id": RUN}),
                                               encoding="utf-8")
    before = tree(root)
    opened = []
    real = packet_module.SqliteJournal

    def observed(path, *args, **kwargs):
        opened.append(Path(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(packet_module, "SqliteJournal", observed)
    code, packet, text = run_main(root, out, capsys)
    assert code == 0 and packet["complete"] is True, packet
    assert packet["status"] == "failed" and packet["outcome"] == "refused"
    assert packet["refusal"] == {"node": "writer", "cause": "unknown",
                                 "source": "diagnostic-producer-mapped-node-failure"}
    assert packet["result"] == {"observation": "missing"}
    assert packet["attestation"] == {"observation": "missing"}
    assert packet["leases"]["summary"] == "none-recorded"
    assert packet["metering"]["coverage"] in {"legacy_unmeasured", "unmeasured",
                                              "supported_observations"}
    assert packet["metering"]["estimate"] is None
    assert packet["metering"]["confirmed_charge_coverage"] == "unknown"
    # The fixture request names a non-authority "repository": no guessed read.
    assert packet["target"]["observation"] == "unknown"
    assert packet["target"]["reason"] == "request-names-another-repository"
    assert len(text.encode()) <= packet_module.MAX_PACKET_BYTES
    for marker in ("operator", "auth.json", "secret", "pppp", "PRIVATE", str(root)):
        assert marker not in text
    assert opened and all(not path.resolve().is_relative_to(root.resolve()) for path in opened)
    assert tree(root) == before


@pytest.mark.parametrize("command", [
    {"accepted": False, "run_id": HOSTILE},
    {"accepted": True, "run_id": RUN, "detail": HOSTILE},
])
def test_hostile_command_report_refuses_closed_at_the_diagnostic(layout, capsys, command):
    root, out = layout
    journal = _world(root)
    root.chmod(0o700)
    start_test_run(journal, RUN, owner_id="fixture")
    (root / "application-run.json").write_text(json.dumps(command), encoding="utf-8")
    before = tree(root)
    code, packet, text = run_main(root, out, capsys)
    assert code == 1 and packet["diagnostic_stage"] == "command"
    assert_closed_refusal(packet, text, "diagnostic")
    assert tree(root) == before


@pytest.mark.parametrize("argv", [
    ["--root", "x"],
    ["--root", "r", "--out", "o", "--command-report", "c", "--run-id", HOSTILE,
     "--authorization-id", "a"],
])
def test_bad_arguments_refuse_without_echo(capsys, argv):
    assert packet_module.main(argv) == 1
    text = capsys.readouterr().out
    packet = json.loads(text)
    assert packet["stage"] == "arguments"
    assert_closed_refusal(packet, text, "arguments")


def test_capture_refusal_is_closed(tmp_path, capsys):
    # No platform seam: production custody refuses here (Windows, or /tmp
    # ancestry on POSIX) and the packet names only the stage.
    root = tmp_path / "original"
    root.mkdir()
    code, packet, text = run_main(root, tmp_path / "captured", capsys)
    assert code == 1
    assert_closed_refusal(packet, text, "capture")
