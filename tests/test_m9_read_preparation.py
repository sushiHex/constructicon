"""Actual completed advice producer -> canonical writer -> compiler -> preflight.

The compiler below is a small fixture composition through the real packager and
D2 producer. It is not the private qualification compiler and proves no arbitrary
historical shell semantics. Predecessor evidence is never assembled by hand.
"""

from __future__ import annotations

import io
import json
import subprocess
from types import SimpleNamespace

import pytest
from scripts import m8_procedure_package as packager
from scripts.ops import m9_native_read as native
from scripts.ops import m9_owner_approval as owner
from scripts.ops import m9_read_preparation as preparation
from scripts.ops.claude_read_commands import sha
from scripts.ops.claude_read_session import json_bytes
from scripts.ops.m9_owner_approval import StandingApproval
from scripts.ops.m9_qualification_boundary import QualificationBoundary

from tests import test_change_review_read as chain
from tests.substrate.test_codex_adapter import portable_binding as portable_binding
from tests.substrate.test_codex_adapter import substituted_guard as substituted_guard
from tests.test_change_review_input import source_world as source_world
from tests.test_change_review_reply import produced as produced
from tests.test_m9_owner_approval import forbid_supervisor_sleep


@pytest.fixture
def prior(tmp_path, monkeypatch, portable_binding, substituted_guard, produced):
    # Only Windows ACL observation is substituted. Canonical paths, regular
    # files, private leaf modes and the remaining custody checks run for real.
    monkeypatch.setattr(owner, "_check_windows_acl", lambda path, *, leaf: None)
    packet, record, _ = produced
    platform = chain.Platform(tmp_path, monkeypatch, portable_binding)
    path, _ = chain.selection(tmp_path, summary=chain.SUMMARY)
    selected = json.loads(path.read_bytes())
    selected["controller"] = record["controller"]
    path.write_bytes(json_bytes(selected))
    digest = sha(path.read_bytes())
    host = QualificationBoundary(path, digest,
        platform.custody / ("qualification-" + digest), target=chain.TARGET,
        alias=chain.ALIAS, run=platform)
    approval_path, approval_sha = chain.issued(platform.custody, host.selected_pins())
    approval = StandingApproval.load(approval_path, approval_sha, platform.custody)
    forbid_supervisor_sleep(monkeypatch)
    try:
        result = native.run_native_read(platform.custody, host, approval, chain.LIMITS,
                                        run=platform)
    finally:
        platform.server.close()
    assert (result.reason, result.dispatch, result.cleanup, result.custody_retained,
            result.approval_suspended) == ("read-settled", "terminal", "clean", False, False)
    assert result.accepted_read_sha256 and platform.turns() == 1
    template = tmp_path / "template.json"
    values = {"previous_boot": chain.PRIOR, "previous_generation": 11,
              "prior_session": "old", "prior_label": "old",
              "opaque": {"unicode": "\N{SNOWMAN}", "sequence": [None, True, 2]}}
    template.write_bytes(json_bytes(values))

    def no_process(*args, **kwargs):
        pytest.fail("preparation or preflight attempted an external process")

    monkeypatch.setattr(subprocess, "run", no_process)
    monkeypatch.setattr(native, "run_native_read", no_process)
    return SimpleNamespace(template=template, values=values, path=path, digest=digest,
        work=platform.custody, record=result.record, packet=packet, host=host,
        approval=approval_path, approval_sha=approval_sha, result=result)


def arguments(world, out):
    return ["prepare-input", "--template", str(world.template), "--template-sha256",
            sha(world.template.read_bytes()), "--previous-selection", str(world.path),
            "--previous-selection-sha256", world.digest, "--work", str(world.work),
            "--prior-record", str(world.record), "--prior-packet", str(world.packet),
            "--out", str(out)]


def fixture_compile(world, inputs, out):
    """Consume exact canonical writer bytes through real assembly and D2 code."""
    raw = inputs.read_bytes()
    values = json.loads(raw)
    assert raw == json_bytes(values) and b"\r" not in raw
    out.mkdir(mode=0o700)
    path, _ = chain.selection(out, summary=chain.SUMMARY,
        session={"root": "/home/m8-service/advice-next", "label": "next"},
        state="/home/m8-service/advice-next-state")
    selected = json.loads(path.read_bytes())
    selected.update(controller=json.loads(world.path.read_bytes())["controller"],
                    previous_boot=values["previous_boot"],
                    previous_generation=values["previous_generation"])
    parts = ["# Fixture compiler\n\n## Composition\n```toml\n"]
    literals = {}
    for phase in selected["phases"]:
        # D2 is emitted by chain.selection through the real _d2_script producer;
        # it is not an unreviewed literal permitted by the generic packager.
        if phase in ("d2-preserve", "d2-verify"):
            continue
        body = (out / (phase + ".sh")).read_bytes().decode()
        body = "# predecessor " + json.dumps({k: values[k] for k in preparation.FIELDS},
                                            sort_keys=True) + "\n" + body
        literals[phase] = body
    labels = sorted(set(packager.LABEL.findall("".join(literals.values()))))
    parts += ["labels = {current = " + json.dumps(labels) + "}\n"]
    for phase, body in literals.items():
        parts += ["[[steps]]\nname = " + json.dumps(phase) + "\nstdout = []\n",
                  "parts = [{literal = " + json.dumps(body) + "}]\n"]
    parts += ["```\n"]
    recipe = out / "recipe.md"
    recipe.write_bytes("".join(parts).encode())
    for step in packager.assemble(recipe, template=True):
        raw = step.text.encode()
        (out / (step.name + ".sh")).write_bytes(raw)
        selected["phases"][step.name]["script"] = sha(raw)
    path.write_bytes(json_bytes(selected))
    return path, sha(path.read_bytes())


def entry_bytes(args, monkeypatch):
    """Use the genuine Windows newline primitive on every test platform."""
    buffer = io.BytesIO()
    text = io.TextIOWrapper(buffer, encoding="utf-8", newline="\r\n")
    with monkeypatch.context() as patch:
        patch.setattr(native.sys, "stdout", text)
        assert native.main(args) == 0
    text.flush()
    raw = buffer.getvalue()
    text.detach()
    return raw


def test_actual_predecessor_writes_once_then_compiles_and_preflights(
    prior, tmp_path, monkeypatch, capsys,
):
    out = tmp_path / "next-input.json"
    before = {p: p.read_bytes() for p in prior.work.rglob("*") if p.is_file()}
    result_raw = entry_bytes(arguments(prior, out), monkeypatch)
    result = json.loads(result_raw)
    assert result_raw == json_bytes(result)
    values = json.loads(out.read_bytes())
    assert values == {**prior.values, "previous_boot": chain.BOOT, "previous_generation": 12,
                      "prior_session": chain.ROOT, "prior_label": chain.LABEL}
    assert out.read_bytes() == json_bytes(values) and b"\r" not in out.read_bytes()
    assert result == {"status": "input-prepared", "host_values_sha256": sha(out.read_bytes()),
        "previous_selection_sha256": prior.digest,
        "accepted_read_sha256": prior.result.accepted_read_sha256,
        "changed_fields": sorted(preparation.FIELDS), "compiler_executed": False,
        "fresh_host_facts_verified": False, "execution_authorized": False}
    assert {p: p.read_bytes() for p in prior.work.rglob("*") if p.is_file()} == before
    path, digest = fixture_compile(prior, out, tmp_path / "compiled")
    args = ["--selection", str(path), "--selection-sha256", digest,
        "--approval", str(prior.approval), "--approval-sha256", prior.approval_sha,
        "--work", str(prior.work), "--target", chain.TARGET, "--alias", chain.ALIAS,
        "--preflight", "--reserve-seconds", "3600", "--host-values", str(out),
        "--host-values-sha256", result["host_values_sha256"]]
    for _ in range(2):
        checked_raw = entry_bytes(args, monkeypatch)
        checked = json.loads(checked_raw)
        assert checked_raw == json_bytes(checked)
        assert checked["status"] == "preflight-checked"
        assert checked["private_writer_or_compiler_executed"] is False
    assert {p: p.read_bytes() for p in prior.work.rglob("*") if p.is_file()} == before
    with pytest.raises(SystemExit) as refused:
        native.main(arguments(prior, out))
    assert refused.value.code == 2
    assert capsys.readouterr().err == "M9 preparation refused: preparation-output-occupied\n"
    assert out.read_bytes() == json_bytes(values)


def test_predecessor_acceptance_hashes_custody_and_bounds_refuse_before_output(
    prior, tmp_path, capsys,
):
    out = tmp_path / "never-written.json"
    captures = prior.host._captures
    cleanup = captures.parent / "cleanup-no-vendor"
    faults = [
        (prior.template, lambda raw: raw.replace(b"\n", b"\r\n"), "template-canonical"),
        (prior.template, lambda raw: json_bytes({**prior.values, "opaque": "x" * 65536}),
         "template-unreadable"),
        (prior.record / "result.json", lambda raw: raw.replace(b'"cleanup": "clean"',
                                                               b'"cleanup": "unknown"'),
         "accepted-window"),
        (captures / "boot.status.json", lambda raw: raw.replace(b'"returncode": 0',
                                                               b'"returncode": false'),
         "completion"),
        (captures / "live-before-selection.stdout", lambda raw: raw.replace(
            b'"generation": 12', b'"generation": 13'), "qualification"),
        (captures / "consumer-mint.stdout", lambda raw: raw + b" ", "challenge"),
        (cleanup / "SOURCE-PINS.json", lambda raw: raw.replace(prior.digest.encode(), b"0" * 64),
         "cleanup-selection"),
        (cleanup / "phase.sh", lambda raw: raw + b"# changed\n", "cleanup-selection"),
        (captures / "withdraw-readback.stdout", lambda raw: raw.replace(
            b'"generation_floor": 12', b'"generation_floor": 11'), "withdrawal"),
        (prior.record / "withdraw.json", lambda raw: raw.replace(b'"sha256": "',
                                                                 b'"sha256": "0'), "withdrawal"),
        (captures / "park-usage.stdout", lambda raw: raw.replace(b'"Off"', b'"Running"'), "park"),
        (prior.record / "park.json", lambda raw: raw.replace(b'"sha256": "', b'"sha256": "0'),
         "park"),
    ]
    for path, change, expected in faults:
        original = path.read_bytes()
        edited = change(original)
        assert edited != original
        path.write_bytes(edited)
        try:
            with pytest.raises(SystemExit) as refused:
                native.main(arguments(prior, out))
            assert refused.value.code == 2
            observed = capsys.readouterr()
            assert not observed.out
            assert observed.err == f"M9 preparation refused: preparation-{expected}\n"
            assert not out.exists()
        finally:
            path.write_bytes(original)
    for marker in (prior.work / "active", prior.work / ("suspended-" + prior.approval_sha)):
        marker.write_bytes(b"a-different-window")
        try:
            with pytest.raises(SystemExit) as refused:
                native.main(arguments(prior, out))
            assert refused.value.code == 2 and not out.exists()
            assert "preparation-custody" in capsys.readouterr().err
        finally:
            marker.unlink()
    args = arguments(prior, out)
    args[args.index("--previous-selection-sha256") + 1] = "0" * 64
    with pytest.raises(SystemExit) as refused:
        native.main(args)
    assert refused.value.code == 2 and not out.exists()
    assert capsys.readouterr().err == "M9 preparation refused: preparation-selection\n"
