"""Local producer -> checked package -> offline operator entry, without a window."""

import json
import subprocess
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from scripts.ops import change_review_input
from scripts.ops import m9_native_read as native
from scripts.ops import m9_owner_approval as owner
from scripts.ops import m9_qualification_boundary as boundary
from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes

from tests.test_change_review_input import source_world as source_world
from tests.test_change_review_read import ALIAS, TARGET, selection

NOW = datetime(2026, 11, 18, 12, tzinfo=UTC)
RESERVE = 7200


@pytest.fixture
def prepared(source_world, tmp_path, monkeypatch, capsys):
    repository, controller, before, after = source_world
    packet = tmp_path / "packet"
    assert change_review_input.main([
        "--repository", str(repository), "--controller", controller,
        "--before", before, "--after", after, "--path", "calc.py", "--out", str(packet),
    ]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "prepared"
    package = tmp_path / "package"
    package.mkdir()
    path, _ = selection(package, summary=(packet / "summary.json").read_bytes())
    selected = json.loads(path.read_bytes())
    selected["controller"] = controller
    path.write_bytes(json_bytes(selected))
    digest = sha(path.read_bytes())
    work = tmp_path / "custody"
    work.mkdir(mode=0o700)
    host = boundary.QualificationBoundary(path, digest, work / "unused", target=TARGET,
                                           alias=ALIAS)
    record = owner.issue(host.selected_pins(), not_after=NOW + timedelta(days=1), max_runs=1)
    approval = work / "standing-approval.json"
    approval.write_bytes(record)
    # The actual input serializer is the writer involved in this boundary. Other
    # fields deliberately remain opaque; this is not a second host-values schema.
    values = {key: selected[key] for key in ("previous_boot", "previous_generation")}
    values["opaque_not_validated_here"] = {"example": "not a host assertion"}
    inputs = tmp_path / "host-values.json"
    inputs.write_bytes(json_bytes(values))
    argv = ["--selection", str(path), "--selection-sha256", digest,
            "--approval", str(approval), "--approval-sha256", sha(record),
            "--work", str(work), "--target", TARGET, "--alias", ALIAS]

    def no_process(*args, **kwargs):
        pytest.fail("offline preflight attempted a process or supervisor")

    # Git packet production above runs for real. From here, every native process
    # and supervisor is denied. Only the Windows ACL primitive is a fixture.
    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(native, "run_native_read", no_process)
    monkeypatch.setattr(owner, "_check_windows_acl", lambda path, *, leaf: None)
    monkeypatch.setattr(native, "datetime", SimpleNamespace(now=lambda zone: NOW))
    return SimpleNamespace(argv=argv, path=path, inputs=inputs, values=values, work=work,
                           approval=approval, selected=selected)


def args_for(world, *, inputs=True):
    args = [*world.argv, "--preflight", "--reserve-seconds", str(RESERVE)]
    if inputs:
        args += ["--host-values", str(world.inputs),
                 "--host-values-sha256", sha(world.inputs.read_bytes())]
    return args


def refuse(world, capsys, args, message):
    before = {path.name: path.read_bytes() for path in world.work.iterdir()}
    with pytest.raises(SystemExit) as stopped:
        native.main(args)
    assert stopped.value.code == 2
    observed = capsys.readouterr()
    assert not observed.out and message in observed.err
    assert {path.name: path.read_bytes() for path in world.work.iterdir()} == before


@pytest.mark.parametrize("inputs", [False, True])
def test_real_producers_reach_the_portable_preflight_without_claiming_a_window(
    prepared, monkeypatch, capsys, inputs,
):
    # Portable preflight precedes the Windows-only native entry guard.
    monkeypatch.setattr(native, "os", SimpleNamespace(name="posix"))
    assert native.main(args_for(prepared, inputs=inputs)) == 0
    raw = capsys.readouterr().out.encode()
    checked = json.loads(raw)
    assert raw == json_bytes(checked)
    assert checked == {
        "status": "preflight-checked", "selection_sha256": sha(prepared.path.read_bytes()),
        "approval_sha256": sha(prepared.approval.read_bytes()),
        "host_values_sha256": sha(prepared.inputs.read_bytes()) if inputs else None,
        "reserve_seconds": RESERVE, "checked_until": (NOW + timedelta(seconds=RESERVE)).isoformat(),
        "contract_coverage": "selected-literal-source-only",
        "qualification_performed": False, "private_writer_or_compiler_executed": False,
        "fresh_host_facts_verified": False,
    }
    assert {path.name for path in prepared.work.iterdir()} == {"standing-approval.json"}


def test_actual_crlf_writer_output_refuses_without_repair_or_claim(prepared, capsys):
    prepared.inputs.write_text(
        json_bytes(prepared.values).decode("utf-8"), encoding="utf-8", newline="\r\n",
    )
    assert b"\r\n" in prepared.inputs.read_bytes()
    refuse(prepared, capsys, args_for(prepared), "preflight-host-values-canonical")


@pytest.mark.parametrize("change,reason", [
    ({"previous_boot": "00000000-0000-4000-8000-000000000000"}, "previous_boot"),
    ({"previous_generation": 12}, "previous_generation"),
    ({"previous_generation": True}, "previous_generation"),
])
def test_only_known_predecessor_values_must_match_the_checked_selection(
    prepared, capsys, change, reason,
):
    prepared.inputs.write_bytes(json_bytes({**prepared.values, **change}))
    refuse(prepared, capsys, args_for(prepared), "preflight-host-values-" + reason)


def test_an_unpinned_input_refuses_before_any_window(prepared, capsys):
    args = args_for(prepared)
    args[-1] = "0" * 64
    refuse(prepared, capsys, args, "preflight-host-values-digest")


@pytest.mark.parametrize("fault", ["missing", "oversized"])
def test_unreadable_input_is_named_before_any_process_or_claim(prepared, capsys, fault):
    args = args_for(prepared)
    if fault == "missing":
        prepared.inputs.unlink()
    else:
        # Otherwise valid canonical input with matching known predecessor facts
        # and digest: the reader's byte bound must be what refuses it.
        raw = json_bytes({**prepared.values, "opaque": "x" * 65536})
        assert len(raw) > 65536
        prepared.inputs.write_bytes(raw)
        args[-1] = sha(raw)
    refuse(prepared, capsys, args, "preflight-host-values-unreadable")


def test_unreadable_json_is_a_named_refusal_without_claim(prepared, capsys):
    prepared.inputs.write_bytes(b'{"previous_boot":\n')
    refuse(prepared, capsys, args_for(prepared), "preflight-host-values-json")


@pytest.mark.parametrize("remaining", [0, RESERVE])
def test_record_must_admit_now_and_through_the_reservation(prepared, capsys, remaining):
    record = json.loads(prepared.approval.read_bytes())
    record["not_after"] = (NOW + timedelta(seconds=remaining)).isoformat()
    prepared.approval.write_bytes(json_bytes(record))
    digest_arg = prepared.argv.index("--approval-sha256") + 1
    prepared.argv[digest_arg] = sha(prepared.approval.read_bytes())
    refuse(prepared, capsys, args_for(prepared), "approval-expired")


def test_record_digest_is_checked_by_the_real_loader(prepared, capsys):
    prepared.approval.write_bytes(prepared.approval.read_bytes() + b" ")
    refuse(prepared, capsys, args_for(prepared), "approval-digest")


def test_constructor_rechecks_selected_script_bytes(prepared, capsys):
    phase = prepared.path.with_name("h4-startup.sh")
    phase.write_bytes(phase.read_bytes() + b"# unreviewed drift\n")
    refuse(prepared, capsys, args_for(prepared), "M9 window refused:")


@pytest.mark.parametrize("seconds", [0, -1, 10**100])
def test_invalid_reservation_refuses_without_a_window(prepared, capsys, seconds):
    args = args_for(prepared)
    args[args.index("--reserve-seconds") + 1] = str(seconds)
    refuse(prepared, capsys, args, "preflight-reserve-seconds")


def test_offline_options_cannot_change_the_native_entry(prepared, capsys):
    refuse(prepared, capsys, [*prepared.argv, "--reserve-seconds", str(RESERVE)],
           "local preparation options require --preflight")


def test_native_entry_keeps_its_windows_restriction(prepared, monkeypatch, capsys):
    monkeypatch.setattr(native, "os", SimpleNamespace(name="posix"))
    refuse(prepared, capsys, prepared.argv, "the selected Hyper-V host requires Windows")
