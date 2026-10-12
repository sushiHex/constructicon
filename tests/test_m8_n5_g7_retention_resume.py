"""Exercise the bounded paused-workspace resume without a host or vendor."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from tests.test_m8_n5_g6_session import _run
from tests.test_m8_n5_host_session import HANDOFFS, _fences, _section, _text
from tests.test_m8_operator_commands import PYTHON_PROGRAM, _bash

DOCUMENT = HANDOFFS / "M8-N5-g7-retention-resume.md"
CONTROLLER = "f6cd85a6ed247fdcbb44dc002b8a99fdf18f1324"
P = "d22bff86e8695a7efef04dc3f47c6d4b0847599c"
OLD = "585df33eb196cd4afd10d5c12cb1efb37fd5a6e1"
BOOT = "d8d9e311-6b35-4d6a-aaeb-cb11c86c5084"
SHA = "f0aa7b3a6e904f04c504e243114ce4b3a9ca99c48326c9c7259c1f9623399ded"
FAILURE = (
    "ValueError: /var/lib/constructicon-m8-launch holds entries the retirement "
    "does not name: ['qualification']"
)
SCRIPT = "scripts/ci/m8_host_artifacts.py"
FIXTURE_SOURCE = b"# credential-free paused-source fixture\n"
FIXTURE_SHA = hashlib.sha256(FIXTURE_SOURCE).hexdigest()


def _blocks(heading: str) -> list[str]:
    return [block.strip() for block in _fences(_section(_text(DOCUMENT), heading))]


@pytest.fixture(scope="module")
def paused_script() -> bytes:
    # CI may have only its final checkout commit. The actual historical blob
    # digest is a recorded provenance fact, not a prerequisite for these fakes.
    return FIXTURE_SOURCE


def _record(command: str) -> dict:
    return {
        "schema_version": 2, "command": command, "commit": P,
        "first_parent": True, "script_matches_commit": True,
        "blobs": {SCRIPT: {"sha256": FIXTURE_SHA}},
        **({"ready": False, "failure": FAILURE} if command == "judge-retire"
           else {"listed": True}),
    }


def _private_file(path: Path, data: bytes) -> None:
    path.write_bytes(data)
    path.chmod(0o600)


def _world(tmp_path: Path, source: bytes) -> Path:
    home = (tmp_path / "operator").resolve()
    home.mkdir(mode=0o700)
    for name in ("m8-launch", "m8-launch-" + OLD, "m8-controller"):
        path = home / name
        path.mkdir(mode=0o700)
        path.chmod(0o700)
        _private_file(path / "preserve", name.encode())
    w = home / "m8-launch"
    _private_file(w / "m8_host_artifacts.py", source)
    _private_file(w / "retire.json", json.dumps(_record("judge-retire")).encode())
    _private_file(w / "vendor.json", json.dumps(_record("vendor-inputs")).encode())
    return home


def _portable_block(*, fault: str = "none") -> str:
    block, = _blocks("Complete LR3 workspace-resume override")
    program = PYTHON_PROGRAM.search(block)
    assert program is not None
    # Substitute only the pinned source-data identity for the tiny fake. The
    # actual hashing and all identity comparisons still execute unchanged.
    body = program["body"].replace(SHA, FIXTURE_SHA)
    if os.name == "nt":
        # Substitute POSIX ownership/mode metadata only. Real paths, links,
        # bytes, JSON, hashing, existence checks and mv remain under test.
        body = "\n".join([
            "import os, stat, sys", "os.getuid = lambda: 0", "real_lstat = os.lstat",
            "def posix_lstat(path, *args, **kwargs):",
            "    info = real_lstat(path, *args, **kwargs)",
            "    fields = list(info)",
            "    fields[0] = stat.S_IFMT(info.st_mode) | "
            "(0o700 if stat.S_ISDIR(info.st_mode) else 0o600)",
            f"    fault = {json.dumps(fault)}",
            "    if str(path).endswith(\"m8-launch\"):",
            "        if fault == \"workspace-mode\": fields[0] |= 0o020",
            "        if fault == \"workspace-link\": fields[0] = stat.S_IFLNK | 0o700",
            "    else: fields[4] = 0",
            "    if str(path).endswith(\"retire.json\") and fault == \"record-link\":",
            "        fields[0] = stat.S_IFLNK | 0o600",
            "    return os.stat_result(fields)", "os.lstat = posix_lstat", body,
        ])
        if fault == "archive-link":
            body = (
                "import os\nreal_lexists = os.path.lexists\n"
                "os.path.lexists = lambda path: str(path).endswith(\"m8-launch-refused-"
                + P + "\") or real_lexists(path)\n" + body
            )
    # The executable is the platform-bound primitive, not a fake validator.
    executable = shlex.quote(sys.executable)
    return block.replace(program["body"], body).replace("/usr/bin/python3", executable)


def test_every_new_block_parses_and_actual_controller_pin_passes_the_guard():
    for block in _fences(_text(DOCUMENT)):
        checked = subprocess.run(
            [_bash(), "-n"], input=block, capture_output=True, text=True,
            timeout=30, check=False,
        )
        assert checked.returncode == 0, checked.stderr
    boot, transport = _blocks("Authorization, boot continuity and immutable transport")
    assert BOOT in boot and "/proc/sys/kernel/random/boot_id" in boot
    assert transport.splitlines()[0] == f"C={CONTROLLER}"
    accepted = _run(transport + "\necho pin-checked")
    assert accepted.returncode == 0, accepted.stderr
    assert accepted.stdout == "pin-checked\n"


@pytest.mark.parametrize("controller", ["UNPINNED", "", "a" * 39, "a" * 41, "A" * 40])
def test_unpinned_or_malformed_controller_still_refuses_before_transport(controller: str):
    _, transport = _blocks("Authorization, boot continuity and immutable transport")
    assert transport.splitlines()[0] == f"C={CONTROLLER}"
    guard = "\n".join(transport.splitlines()[1:])
    refused = _run('C="$CONTROLLER"\n' + guard + "\necho must-not-transport",
                   CONTROLLER=controller)
    assert refused.returncode == 1
    assert refused.stdout == ""


@pytest.mark.parametrize("failure", ["none", "boot", "sudo", "drift"])
def test_composed_resume_check_cannot_continue_after_a_failed_precondition(
    tmp_path: Path, failure: str,
):
    operator = _text(HANDOFFS / "M8-N4-operator-commands.md")
    setup = operator.split("## Setup", 1)[1].split("\n### ", 1)[0]
    prior, _ = _fences(_section(_text(HANDOFFS / "M8-N5-g7-session.md"),
                                "Before LR's reboot: capture checked g6 continuity"))
    common = tmp_path / "n5-g7-prior-common.sh"
    common.write_text("\n".join([*_fences(setup), prior]), encoding="utf-8", newline="\n")
    boot, _ = _blocks("Authorization, boot continuity and immutable transport")
    checks, = _fences(_section(_text(HANDOFFS / "M8-N5-host-session.md"), "H2. S0 at `C`"))
    # Only boot-id and drift's platform-owned absolute paths are substituted.
    boot = boot.replace("/usr/bin/cat /proc/sys/kernel/random/boot_id", "fake_boot")
    checks = checks.replace("/usr/local/bin/m8-host-drift", "drift")
    result = _run("\n".join([
        'fake_boot() { if test "$FAILURE" = boot; then echo changed; else echo "$BOOT"; fi; }',
        'sudo() { echo sudo; test "$FAILURE" != sudo; }',
        'drift() { echo drift; test "$FAILURE" != drift; }', boot, checks,
        'binding_check() { test "$*" = "$W/g6.sealed.json reboot-anchor -"; echo anchor; }',
        'binding_check "$W/g6.sealed.json" reboot-anchor -', "echo checked",
    ]), HOME=str(tmp_path), FAILURE=failure, BOOT=BOOT)
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert result.stdout.splitlines() == ["sudo", "drift", "anchor", "checked"]
    else:
        assert result.returncode != 0
        assert "anchor" not in result.stdout and "checked" not in result.stdout
        if failure == "boot":
            assert result.stdout == ""


@pytest.mark.parametrize("controller", ["UNPINNED", P, OLD, "a" * 39])
def test_archive_refuses_unreviewed_or_old_controller_before_move(
    tmp_path: Path, paused_script: bytes, controller: str,
):
    home = _world(tmp_path, paused_script)
    result = _run(_portable_block(), HOME=str(home), C=controller)
    assert result.returncode != 0
    assert (home / "m8-launch").is_dir()
    assert not (home / ("m8-launch-refused-" + P)).exists()


@pytest.mark.parametrize(
    "fault",
    ["none", "wrong-command", "wrong-commit", "ready", "no-first-parent",
     "no-script-proof", "generic-failure", "record-hash", "source-bytes",
     "malformed", "vendor-commit", "vendor-unlisted", "vendor-hash", "staging",
     "old-archive-missing", "controller-archived", "existing-archive", "workspace-mode"],
)
def test_archive_requires_specific_refusal_and_preserves_both_old_workspaces(
    tmp_path: Path, paused_script: bytes, fault: str,
):
    home = _world(tmp_path, paused_script)
    w = home / "m8-launch"
    old = home / ("m8-launch-" + OLD)
    controller = home / "m8-controller"
    archive = home / ("m8-launch-refused-" + P)
    old_identity = old.stat().st_ino
    controller_identity = controller.stat().st_ino
    workspace_identity = w.stat().st_ino
    record = _record("judge-retire")
    changes = {
        "wrong-command": {"command": "verify-retired"}, "wrong-commit": {"commit": OLD},
        "ready": {"ready": True}, "no-first-parent": {"first_parent": False},
        "no-script-proof": {"script_matches_commit": False},
        "generic-failure": {"failure": "ValueError: an unrelated failure"},
        "record-hash": {"blobs": {SCRIPT: {"sha256": "0" * 64}}},
    }
    record.update(changes.get(fault, {}))
    _private_file(w / "retire.json", json.dumps(record).encode())
    if fault == "source-bytes":
        _private_file(w / "m8_host_artifacts.py", b"modified source\n")
    elif fault == "malformed":
        _private_file(w / "retire.json", b"not json\n")
    elif fault.startswith("vendor-"):
        vendor = _record("vendor-inputs")
        vendor.update({
            "vendor-commit": {"commit": OLD}, "vendor-unlisted": {"listed": False},
            "vendor-hash": {"blobs": {SCRIPT: {"sha256": "0" * 64}}},
        }[fault])
        _private_file(w / "vendor.json", json.dumps(vendor).encode())
    elif fault == "staging":
        (w / "staging").mkdir()
    elif fault == "old-archive-missing":
        old.rename(home / "unexpected-old")
    elif fault == "controller-archived":
        (home / ("m8-controller-" + OLD)).mkdir()
    elif fault == "existing-archive":
        archive.mkdir()
        _private_file(archive / "preserve", b"existing")
    elif fault == "workspace-mode":
        w.chmod(0o720)
    result = _run(_portable_block(fault=fault), HOME=str(home), C=CONTROLLER)
    if fault == "none":
        assert result.returncode == 0, result.stderr
        assert result.stdout == "paused-workspace-preserved\n"
        assert not w.exists()
        assert archive.stat().st_ino == workspace_identity
        assert (archive / "m8_host_artifacts.py").read_bytes() == paused_script
    else:
        assert result.returncode != 0
        assert result.stdout == ""
        assert w.stat().st_ino == workspace_identity
        if fault == "existing-archive":
            assert (archive / "preserve").read_bytes() == b"existing"
        else:
            assert not archive.exists()
    if fault != "old-archive-missing":
        assert old.stat().st_ino == old_identity
        assert (old / "preserve").read_bytes() == old.name.encode()
    assert controller.stat().st_ino == controller_identity
    assert (controller / "preserve").read_bytes() == b"m8-controller"


@pytest.mark.parametrize("link", ["workspace", "archive", "record"])
def test_alias_or_dangling_archive_never_moves_paused_state(
    tmp_path: Path, paused_script: bytes, link: str,
):
    home = _world(tmp_path, paused_script)
    w = home / "m8-launch"
    archive = home / ("m8-launch-refused-" + P)
    if os.name == "nt":
        # Windows lacks symlink privilege here; substitute only link metadata
        # (or lexists for the dangling target), leaving the guard executable.
        block = _portable_block(fault=link + "-link")
    elif link == "workspace":
        target = home / "actual-paused"
        w.rename(target)
        w.symlink_to(target, target_is_directory=True)
    elif link == "archive":
        archive.symlink_to(home / "absent", target_is_directory=True)
    else:
        target = w / "actual-record"
        (w / "retire.json").rename(target)
        (w / "retire.json").symlink_to(target)
    if os.name != "nt":
        block = _portable_block()
    result = _run(block, HOME=str(home), C=CONTROLLER)
    assert result.returncode != 0
    assert result.stdout == ""
    assert w.exists()
    assert not archive.exists()


def test_late_failure_preserves_archive_and_does_not_authorize_r11_replay(
    tmp_path: Path, paused_script: bytes,
):
    home = _world(tmp_path, paused_script)
    result = _run(
        "set -e\n" + _portable_block() + "\nfalse\necho must-not-run-r11",
        HOME=str(home), C=CONTROLLER,
    )
    assert result.returncode != 0
    assert result.stdout == "paused-workspace-preserved\n"
    assert not (home / "m8-launch").exists()
    archive = home / ("m8-launch-refused-" + P)
    assert (archive / "m8_host_artifacts.py").read_bytes() == paused_script
    replay = _run(_portable_block(), HOME=str(home), C=CONTROLLER)
    assert replay.returncode != 0
    assert replay.stdout == ""
    assert (archive / "m8_host_artifacts.py").read_bytes() == paused_script


def test_resume_source_map_preserves_lifecycle_and_owner_gates():
    document = _text(DOCUMENT)
    for value in (CONTROLLER, P, OLD, BOOT, "8c1b14eed6f02474abcc1ac998e3bf87f8c6ade3", SHA):
        assert value in document
    assert "deployment package for separate owner review and host authorization" in document
    assert "This document authorizes no host action" in document
    assert "continuous exclusive custody" in document
    assert "no maintenance, activation, account/model acquisition" in document
    assert "R6 is not authorized" in document
    assert "No recapture, overwrite or" in document
    assert "unchanged LR3 suffix" in document
    assert "**original `O`** for controller archive" in document
    assert "no N5 common file and no added `pipefail`" in document
    assert "all H7 controls run even if refresh is measured" in document
    assert "at most\none separately authorized ER R1 attempt" in document
    assert "Pause after W4" in document and "before W5 root installation" in document
    block, = _blocks("Complete LR3 workspace-resume override")
    assert not re.search(r"\brm\b|maintain|activate|qualification.*read_bytes", block)
    assert "m8-controller-" in block and "mv -n --" in block
