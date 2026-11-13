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


def failed_world(root: Path) -> None:
    """A failed run whose writer failure is producer-mapped, with its attempt and command."""
    journal = _world(root)
    root.chmod(0o700)
    lease = start_test_run(journal, RUN, owner_id="fixture")
    journal.append_event(lease, "NodeStarted", path=WRITER)
    journal.append_event(lease, "NodeFailed", path=WRITER, payload={
        "error_type": "ContractViolation",
        "error": "maintenance captured candidate equals the pinned base"})
    journal.transition_run(lease, expected=frozenset({RunStatus.RUNNING}),
        target=RunStatus.FAILED, event_kind="RunFailed", payload={"error": "failed"})
    _attempt(root)
    (root / "application-run.json").write_text(json.dumps({"accepted": False, "run_id": RUN}),
                                               encoding="utf-8")


def stored_acceptance(root: Path) -> None:
    """A shape-valid same-run sidecar; the diagnostic does not authenticate it."""
    from constructicon.core.gates import MergeEvaluation
    from constructicon.core.maintenance import PlanManifestResult
    from tests.substrate.journal.test_maintenance_diagnostic import CANDIDATE

    result = PlanManifestResult(run_id=RUN, candidate=CANDIDATE,
        evaluation=MergeEvaluation(subject=None, attestation_id=None, checks=()),
        input_sha256="a" * 64, render_sha256="b" * 64)
    (root / "maintenance-result.json").write_text(json.dumps({"schema_version": 1,
        "meaning": "historical-application-acceptance",
        "authorization_digest": "sha256:" + "c" * 64,
        "result": result.model_dump(mode="json")}), encoding="utf-8")


def test_stored_acceptance_beside_a_failed_journal_is_a_named_contradiction(layout, capsys):
    root, out = layout
    failed_world(root)
    stored_acceptance(root)
    before = tree(root)
    code, packet, _ = run_main(root, out, capsys)
    assert code == 0 and packet["complete"] is True, packet
    assert packet["status"] == "failed"
    assert packet["result"]["observation"] == "historical-acceptance-observed"
    assert packet["outcome"] == "contradictory-evidence"
    assert packet["refusal"] == {"node": "writer", "cause": "capture-unchanged",
                                 "source": "diagnostic-producer-mapped-node-failure"}
    assert tree(root) == before


def test_capture_unchanged_packet_carries_maximal_content_digests_within_the_cap(
    layout, capsys,
):
    """The #407 case: executor success, callbacks complete, capture unchanged."""
    from tests.substrate.journal.test_maintenance_diagnostic import _content

    root, out = layout
    failed_world(root)
    path = root / "maintenance-attempt.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    content = _content()
    record.update(dispatch="completed", callbacks={
        "schema_version": 1, "admitted_started": 8, "admitted_completed": 8,
        "worker_results": ["success"] * 8})
    record["facts"].update(status="success", content_digests=content,
                           answer_bytes=content["reply"]["bytes"])
    path.write_text(json.dumps(record), encoding="utf-8")
    code, packet, text = run_main(root, out, capsys)
    assert code == 0 and packet["complete"] is True, packet
    assert packet["refusal"]["cause"] == "capture-unchanged"
    assert packet["diagnostic"]["attempt"]["content_digests"] == content
    assert len(text.encode()) <= packet_module.MAX_PACKET_BYTES
    assert "PRIVATE" not in text


STORED = {"observation": "historical-acceptance-observed"}
MISSING = {"observation": "missing"}
CONFIRMED = {"observation": "recorded", "ok": True, "created_by_this_run": True}
NODES = {name: {"failures": []} for name in ("writer", "checker")}


@pytest.mark.parametrize(("status", "result", "attestation", "expected"), [
    ("succeeded", STORED, CONFIRMED, "succeeded-with-acceptance-record"),
    ("succeeded", STORED, MISSING, "contradictory-evidence"),
    ("succeeded", STORED, {**CONFIRMED, "ok": False}, "contradictory-evidence"),
    ("succeeded", STORED, {**CONFIRMED, "created_by_this_run": False}, "contradictory-evidence"),
    ("succeeded", MISSING, CONFIRMED, "succeeded-without-stored-acceptance"),
    ("failed", STORED, CONFIRMED, "contradictory-evidence"),
    ("running", STORED, MISSING, "contradictory-evidence"),
    ("failed", MISSING, MISSING, "refused"),
    ("running", MISSING, MISSING, "incomplete"),
    ("unknown", MISSING, MISSING, "unknown"),
])
def test_outcome_follows_the_validated_journal_not_the_sidecar(status, result, attestation,
                                                               expected):
    assert packet_module._outcome(status, result, NODES, attestation)[0] == expected


def test_no_observation_combination_claims_application_acceptance():
    # The report never re-derives acceptance; no input yields an authoritative verdict.
    outcomes = {packet_module._outcome(status, result, NODES, attestation)[0]
                for status in ("succeeded", "failed", "running", "pending", "cancelled", "x")
                for result in (STORED, MISSING)
                for attestation in (CONFIRMED, MISSING, {"observation": "none-minted"})}
    assert not any("accepted" in outcome for outcome in outcomes)
    assert outcomes <= {"succeeded-with-acceptance-record", "contradictory-evidence",
                        "succeeded-without-stored-acceptance", "refused", "incomplete",
                        "unknown"}


def test_packet_bound_counts_the_printed_newline_and_binds_at_the_cap(layout, capsys,
                                                                      monkeypatch):
    root, out = layout
    failed_world(root)
    code, packet, text = run_main(root, out, capsys)
    assert code == 0 and packet["complete"] is True
    printed = text.encode()
    assert printed == packet_module._encode(packet) and printed.endswith(b"\n")
    # Permitting exactly at the cap, newline included; refusing one byte below.
    monkeypatch.setattr(packet_module, "MAX_PACKET_BYTES", len(printed))
    code, again, text = run_main(root, root.parent / "captured-2", capsys)
    assert code == 0 and again == packet and len(text.encode()) == len(printed)
    monkeypatch.setattr(packet_module, "MAX_PACKET_BYTES", len(printed) - 1)
    code, refused, text = run_main(root, root.parent / "captured-3", capsys)
    assert code == 1
    assert_closed_refusal(refused, text, "output")
    assert len(text.encode()) <= len(printed) - 1


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


def test_cli_emits_exact_lf_bytes_at_the_cap_and_refuses_one_byte_over(layout, monkeypatch):
    import subprocess
    import sys

    root, _ = layout
    failed_world(root)
    # The real CLI process, its raw stdout bytes: no text-mode CRLF, one record.
    seam = (
        "import os,sys\n"
        "from constructicon.api import maintenance_report as m\n"
        "from constructicon.substrate.journal import maintenance_diagnostic as d\n"
        "from constructicon.substrate.journal import maintenance_evidence as e\n"
        "import pytest\n"
        "from tests.substrate.journal.conftest import portable_capture_custody\n"
        "mp=pytest.MonkeyPatch()\n"
        "portable_capture_custody.__wrapped__(mp)\n"
        "if os.name=='nt':\n"
        "    i=d._identity; mp.setattr(d,'_identity',lambda v:(*i(v)[:-1],0))\n"
        "cap=os.environ.get('REPORT_CAP')\n"
        "if cap: mp.setattr(m,'MAX_PACKET_BYTES',int(cap))\n"
        "raise SystemExit(m.main(sys.argv[1:]))\n"
    )
    script = root.parent / "cli_seam.py"
    script.write_text(seam, encoding="utf-8")

    checkout = Path(__file__).resolve().parents[2]
    # A script's sys.path[0] is its own directory, not the cwd: name the
    # checkout explicitly so `tests` imports without an ambient PYTHONPATH.
    path = os.pathsep.join(filter(None, (str(checkout), os.environ.get("PYTHONPATH"))))

    def cli(out: str, cap: int | None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(script), "--root", str(root), "--out", str(root.parent / out),
             "--command-report", str(root / "application-run.json"), "--run-id", RUN,
             "--authorization-id", AUTH],
            cwd=checkout, stdin=subprocess.DEVNULL, capture_output=True,
            env={**os.environ, "PYTHONPATH": path,
                 "REPORT_CAP": "" if cap is None else str(cap)},
            timeout=120, check=False)

    first = cli("c-1", None)
    assert first.returncode == 0, first.stderr
    raw = first.stdout
    assert raw.endswith(b"\n") and b"\r" not in raw and raw.count(b"\n") == 1
    assert raw == packet_module._encode(json.loads(raw))
    at_cap = cli("c-2", len(raw))
    assert at_cap.returncode == 0 and at_cap.stdout == raw
    over = cli("c-3", len(raw) - 1)
    assert over.returncode == 1 and b"\r" not in over.stdout
    refused = json.loads(over.stdout)
    assert refused["complete"] is False and refused["stage"] == "output"
    assert len(over.stdout) < len(raw)


def channel_world(root: Path) -> None:
    """A channel-task journal and run, its stored result and command report."""
    from tests.substrate.journal.test_maintenance_channel_diagnostic import (
        CHANNEL_REQUEST,
        _journal,
        _result,
    )

    _journal(root, diagnostic.CHANNEL_GRAPH, CHANNEL_REQUEST)
    root.chmod(0o700)
    _result(root, purpose="channel-stored-reply")
    (root / "application-run.json").write_text(json.dumps({"accepted": False, "run_id": RUN}),
                                               encoding="utf-8")


def test_a_channel_run_reads_as_its_own_task(layout, capsys):
    root, out = layout
    channel_world(root)
    before = tree(root)
    code, packet, _ = run_main(root, out, capsys)
    assert code == 0 and packet["complete"] is True, packet
    assert packet["purpose"] == "channel-stored-reply"
    assert packet["result"] == {"observation": "historical-acceptance-observed",
        "candidate_commit": packet["result"]["candidate_commit"],
        "base_sha256": "a" * 64, "candidate_sha256": "b" * 64}
    # A stored record beside an unfinished journal is still named a contradiction.
    assert packet["outcome"] == "contradictory-evidence"
    assert tree(root) == before


def test_a_plan_run_names_its_purpose(layout, capsys):
    root, out = layout
    failed_world(root)
    code, packet, _ = run_main(root, out, capsys)
    assert code == 0 and packet["purpose"] == "plan-manifest-maintenance"


def test_a_channel_result_beside_a_plan_journal_is_refused_as_another_task(layout, capsys):
    from tests.substrate.journal.test_maintenance_channel_diagnostic import _result

    root, out = layout
    failed_world(root)
    _result(root, purpose="channel-stored-reply")
    code, packet, text = run_main(root, out, capsys)
    assert code == 1 and packet["diagnostic_stage"] == "task"
    assert_closed_refusal(packet, text, "diagnostic")


def test_capture_refusal_is_closed(tmp_path, capsys):
    # No platform seam: production custody refuses here (Windows, or /tmp
    # ancestry on POSIX) and the packet names only the stage.
    root = tmp_path / "original"
    root.mkdir()
    code, packet, text = run_main(root, tmp_path / "captured", capsys)
    assert code == 1
    assert_closed_refusal(packet, text, "capture")
