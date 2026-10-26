"""Generated Claude operator phases on a disposable, pre-provisioned Linux host.

The fixture input names actual staged installations and their measured pins. The
only transport substitution maps the fixed SSH/SCP argv to local operator-user
processes; the generated shell, capture, readback and receipt gates are real.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from scripts.ops import claude_read_commands as commands
from scripts.ops import claude_read_session as session

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "scripts/ops/claude_read_session.py"
TARGET = "runner@127.0.0.1"
ALIAS = "local-rehearsal"


def _json(path: Path, value: object) -> None:
    path.write_bytes((json.dumps(value, sort_keys=True) + "\n").encode())


def _cli(*args: str) -> dict:
    result = subprocess.run([sys.executable, "-I", "-B", str(ENTRY), *args],
                            stdin=subprocess.DEVNULL, capture_output=True, check=False,
                            timeout=120, cwd=ROOT)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert result.stderr == b""
    return json.loads(result.stdout)


@pytest.mark.skipif(sys.platform != "linux", reason="requires the disposable Linux foundation")
@pytest.mark.parametrize("abort_after_activation", [False, True], ids=["accept", "abort"])
def test_generated_phases_carry_actual_receipts_through_withdrawal(
    tmp_path, monkeypatch, abort_after_activation,
):
    fixture = os.environ.get("M8_CLAUDE_REHEARSAL_BINDINGS")
    if not fixture:
        if os.environ.get("M8_CLAUDE_REHEARSAL_REQUIRED"):
            pytest.fail("required Claude rehearsal bindings are absent")
        pytest.skip("the pre-provisioned Claude rehearsal foundation is absent")
    record = json.loads(Path(fixture).read_bytes())
    case = "abort" if abort_after_activation else "accept"
    record["namespace"] += "-" + case
    for key in ("R", "RUN", "AUTH", "ACQ"):
        record["values"][key] += "-" + case
    record["values"]["QUAL"] = record["values"]["RUN"] + "/qualify.json"
    for key in ("READ_KEY", "AUTHORIZATION_ID"):
        record["values"][key] += "-" + case
    bindings = commands.Bindings.from_dict(record)
    assert bindings.values["EXPECTED_BOOT"] == (
        Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    )
    evidence, captures = tmp_path / "evidence", tmp_path / "captures"
    evidence.mkdir()
    captures.mkdir()
    revision = commands.operator_revision()
    original_run = subprocess.run
    operator_home = Path("/home/runner")
    assert os.getuid() == operator_home.stat().st_uid

    def local_transport(argv, **kwargs):
        # Preserve the exact remote shell program and run it with its real HOME,
        # uid and cwd. SCP is a byte-preserving install into that same directory.
        if argv[0] == session.SSH:
            assert argv[-2] == TARGET
            return original_run(["/usr/bin/env", "-i",
                                 "HOME=/home/runner", "PATH=/usr/bin:/bin", "LANG=C.UTF-8",
                                 "/bin/sh", "-c", argv[-1]], **kwargs)
        assert argv[0] == session.SCP and argv[-1].startswith(TARGET + ":")
        directory = argv[-1].split(":", 1)[1]
        assert directory.endswith("/") and "/" not in directory[:-1]
        files = argv[-5:-1]
        for source in files:
            result = original_run(["/usr/bin/install", "-m", "0600", source,
                                   str(operator_home / directory / Path(source).name)], **kwargs)
            if result.returncode:
                return result
        return result

    monkeypatch.setattr(session.subprocess, "run", local_transport)
    # The CLI remains a separate real interpreter; bypass only the transport
    # adapter when invoking it from this process.
    def cli(*args: str) -> dict:
        monkeypatch.setattr(session.subprocess, "run", original_run)
        try:
            return _cli(*args)
        finally:
            monkeypatch.setattr(session.subprocess, "run", local_transport)

    def build(phase: str, output: Path) -> tuple[str, Path]:
        value_path = tmp_path / (phase + "-bindings.json")
        _json(value_path, record)
        made = cli("compile", "--phase", phase, "--bindings", str(value_path),
                   "--evidence", str(evidence), "--out", str(output),
                   "--operator-revision", revision)
        assert made["phase"] == phase
        return made["package_manifest"], output

    def execute(phase: str, manifest: str, package: Path) -> None:
        pins, actual = commands.package_checked(package, manifest, revision)
        grant = {"schema_version": 1, "phase": phase, "package_manifest": manifest,
                 "operator_revision": revision, "controller_commit": actual.controller_commit,
                 "bindings_sha256": pins["bindings_sha256"], "boot": actual.values["EXPECTED_BOOT"],
                 "target_sha256": commands.sha((TARGET + "\0" + ALIAS).encode()),
                 "checks": {name: True for name in (
                     commands.COMMON_CHECKS | commands.PHASES[phase].checks)}}
        grant_path = tmp_path / (phase + "-grant.json")
        _json(grant_path, grant)
        status = session.one_phase(package, manifest, revision, evidence, grant_path, captures,
                                   TARGET, ALIAS, commands.sha(grant_path.read_bytes()))
        assert commands.completed_zero(status), (
            phase, (evidence / (phase + ".stderr")).read_bytes())
        for part in commands.PHASES[phase].outputs:
            assert commands.completed_zero(session.readback(package, manifest, revision, evidence,
                                                             part, captures, TARGET, ALIAS))
        checked = cli("check", "--package", str(package), "--manifest", manifest,
                      "--evidence", str(evidence), "--operator-revision", revision)
        assert checked == {"phase": phase, "checked": True}

    cleanup = None
    for phase in commands.PHASES:
        if phase == "activate":
            cleanup = build("withdraw-after", evidence / "cleanup-package")
        if phase == "withdraw-after":
            assert cleanup is not None
            manifest, package = cleanup
        else:
            manifest, package = build(phase, tmp_path / ("package-" + phase))
        execute(phase, manifest, package)
        values = record["values"]
        if phase == "activate" and abort_after_activation:
            # The actual activation completed. Damage its predecessor receipt,
            # demonstrate that a later compile refuses, and use the previously
            # compiled withdrawal without minting or dispatching a READ.
            assert (evidence / "activation-may-have-completed.json").is_file()
            receipt = evidence / "qualify.stdout"
            assert receipt.read_bytes() == commands.PHASES["qualify"].stdout
            active_bindings = commands.Bindings.from_dict(record)
            assert commands.compile_phase(active_bindings, "mint", evidence)
            receipt.write_bytes(b"damaged receipt\n")
            with pytest.raises(commands.Refused):
                commands.compile_phase(active_bindings, "mint", evidence)
            assert cleanup is not None
            cleanup_manifest, cleanup_package = cleanup
            assert ("readonly GENERATION=" + values["GENERATION"] + "\n").encode() in (
                cleanup_package / "phase.sh"
            ).read_bytes()
            execute("withdraw-after", cleanup_manifest, cleanup_package)
            assert not (evidence / "authorization-candidate.json").exists()
            assert not (evidence / "read-status.json").exists()
            break
        if phase == "reload-check":
            digest_path = evidence / "reload.digest"
            actual_digest = digest_path.read_bytes()
            digest_path.write_bytes(b"sha256:" + b"0" * 64 + b"\n")
            try:
                with pytest.raises(commands.Refused):
                    commands.compile_phase(commands.Bindings.from_dict(record), "qualify", evidence)
            finally:
                digest_path.write_bytes(actual_digest)
        elif phase == "qualify-check":
            values["Q"] = (evidence / "checker.stdout").read_text().strip()
            values["QUAL_RAW_SHA256"] = commands.sha((evidence / "qualification.json").read_bytes())
        elif phase == "inventory":
            floor = json.loads((evidence / "inventory.json").read_bytes())["highest_generation"]
            values["FLOOR"], values["GENERATION"] = str(floor), str(floor + 1)
        elif phase == "publish":
            values["SEALED_SHA256"] = commands.sha(
                (evidence / "published-sealed.json").read_bytes())
        elif phase == "mint":
            values["CANDIDATE_SHA256"] = commands.sha(
                (evidence / "authorization-candidate.json").read_bytes())
        elif phase == "candidate-pins":
            approval = {"schema": 1, "owner_decision": "https://github.com/sushiHex/constructicon/issues/77#issuecomment-1",
                        "procedure_sha256": commands.DOC_SHA,
                        "source_c": record["controller_commit"],
                        "acceptance": commands.ACCEPTANCE}
            _json(evidence / "owner-approval.json", approval)
            values["OWNER_APPROVAL_SHA256"] = commands.sha(
                (evidence / "owner-approval.json").read_bytes())
    if not abort_after_activation:
        assert (evidence / "read-status.json").read_bytes() == b'{"status": "succeeded"}\n'
    assert (evidence / "withdraw-after.command.stdout").read_bytes() == b"withdrawn-checked\n"
