"""Portable construction checks for the proposed, unexecuted Claude stage step."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from scripts import m8_procedure_package as package

from tests.git_bash import git_bash

DOCUMENT = (Path(__file__).resolve().parents[1] / "docs/plans/handoffs" /
            "M8-N6-host-session.md")
COMMIT = "41e416f48a08a7daae6f8d30f5904f1d48affcb7"
SELECTION_SHA256 = "2035c40ea91f4d8712141a6f46ef6a7334e45325fde2a9f6db7fcbc19bc109eb"
SYNTHETIC_VALUES = {
    "EXPECTED_BOOT": "00000000-0000-4000-8000-000000000001",
    "DRIFT_STDOUT_HEX": "6f6b0a",  # Synthetic complete line "ok\n", not a host observation.
    "DRIFT_TOOL_SHA256": "d" * 64,
}


def test_stage_package_is_one_ordered_guarded_step_without_later_authority(tmp_path):
    template, = package.assemble(DOCUMENT, template=True)
    assert template.name == "claude-stage"
    assert template.alternatives == (("boot-checked", "drift-checked",
                                      "claude-stage-recorded"),)
    assert template.record is None
    with pytest.raises(package.Refused, match="unreviewed placeholder remains"):
        package.assemble(DOCUMENT)
    with pytest.raises(package.Refused, match="unreviewed placeholder remains"):
        package.build(DOCUMENT, tmp_path / "unfilled")
    assert not (tmp_path / "unfilled").exists()

    step, = package.assemble(DOCUMENT, values=SYNTHETIC_VALUES)
    text = step.text
    assert text.count(f"C={COMMIT}\n") == 1
    assert text.count(f"SELECTION_SHA256={SELECTION_SHA256}\n") == 1
    assert text.count("\n' \"$HOME\" \"$I\" \"$S\" \"$W\"\n") == 1
    assert 'and input_dir == home / "m8-claude-input"' in text
    assert 'and info.st_mode & 0o777 == 0o700' in text
    for key, value in SYNTHETIC_VALUES.items():
        assert text.count(f"readonly {key}={value}\n") == 1
        assert f"{key}=UNREVIEWED" not in text
    order = (
        text.index(f"C={COMMIT}\n"),
        text.index('test "$(/usr/bin/id -u)" -ne 0'),
        text.index('I="$HOME/m8-claude-input"'),
        text.index('S="$I/selection.json"'),
        text.index('test "$(/usr/bin/sha256sum "$S"'),
        text.index("readonly EXPECTED_BOOT="),
        text.index("boot-checked"),
        text.index("readonly DRIFT_STDOUT_HEX="),
        text.index("readonly DRIFT_TOOL_SHA256="),
        text.index('DRIFT_RECORDS="$HOME/m8-claude-drift-stage"'),
        text.index('DRIFT_CAPTURE="$DRIFT_RECORDS/prestage"'),
        text.index('tool = Path("/usr/local/bin/m8-host-drift")'),
        text.index("drift-checked"),
        text.index('/usr/bin/mkdir -m 0700 "$W"'),
        text.index('"${J[@]}" stage "$C" "$W"'),
        text.index("claude-stage-recorded"),
    )
    assert list(order) == sorted(order)
    assert text.count('"${J[@]}" stage "$C" "$W"') == 1
    assert "claude_lane" not in text
    assert '"${J[@]}" judge' not in text
    assert '"${J[@]}" verify' not in text
    assert "sudo " not in text
    assert "UNREVIEWED" not in text

    output = tmp_path / "synthetic-package"
    digest = package.build(DOCUMENT, output, values=SYNTHETIC_VALUES)
    script = (output / "claude-stage.sh").read_bytes()
    assert script == text.encode("utf-8") and b"\r" not in script
    assert json.loads((output / "claude-stage.expected.json").read_bytes()) == {
        "alternatives": [["boot-checked", "drift-checked", "claude-stage-recorded"]],
        "record": None,
    }
    manifest = (output / "MANIFEST.sha256").read_bytes()
    assert digest == hashlib.sha256(manifest).hexdigest()
    assert sorted(path.name for path in output.iterdir()) == [
        "MANIFEST.sha256", "claude-stage.expected.json", "claude-stage.sh",
    ]
    for line in manifest.decode("utf-8").splitlines():
        expected, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == expected
    parsed = subprocess.run([git_bash(), "-n", str(output / "claude-stage.sh")],
                            stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert parsed.returncode == 0, parsed.stderr.decode("utf-8", errors="replace")


def test_inline_metadata_guard_accepts_private_file_and_refuses_aliases():
    if os.name != "posix" or not hasattr(os, "geteuid"):
        pytest.skip("POSIX metadata primitive is absent")
    parent = Path.home()
    uid = os.geteuid()
    for candidate in (parent, *parent.parents):
        info = candidate.lstat()
        if not (stat.S_ISDIR(info.st_mode) and info.st_uid in (0, uid)
                and not info.st_mode & 0o022):
            pytest.skip("home ancestry does not satisfy the proposed host guard")

    step, = package.assemble(DOCUMENT, values=SYNTHETIC_VALUES)
    marker = "/usr/bin/python3 -I -S -B -c '\n"
    assert step.text.count(marker) == 1
    code = step.text.split(marker, 1)[1].split(
        "\n' \"$HOME\" \"$I\" \"$S\" \"$W\"", 1,
    )[0]
    with tempfile.TemporaryDirectory(prefix="constructicon-session-test-", dir=parent) as raw:
        home = Path(raw)
        input_dir = home / "m8-claude-input"
        input_dir.mkdir(mode=0o700)
        selection = input_dir / "selection.json"
        selection.write_bytes(b"synthetic selection, never used for a host session\n")
        selection.chmod(0o600)
        workspace = home / "m8-claude-stage"

        def status() -> int:
            result = subprocess.run(
                [sys.executable, "-I", "-S", "-B", "-c", code,
                 str(home), str(input_dir), str(selection), str(workspace)],
                stdin=subprocess.DEVNULL, capture_output=True, check=False,
            )
            return result.returncode

        assert status() == 0
        input_dir.chmod(0o755)
        assert status() != 0
        input_dir.chmod(0o700)
        selection.chmod(0o644)
        assert status() != 0
        selection.chmod(0o600)
        hardlink = home / "selection-hardlink"
        os.link(selection, hardlink)
        assert status() != 0
        hardlink.unlink()
        target = home / "selection-target"
        selection.rename(target)
        selection.symlink_to(target)
        assert status() != 0
        selection.unlink()
        target.rename(selection)
        workspace.mkdir()
        assert status() != 0


def _transport() -> str:
    document = DOCUMENT.read_bytes().decode("utf-8")
    found = package.fences(package.section(document, "Fixed private input and package transport"))
    assert len(found) == 1 and found[0][0] == "bash"
    return found[0][1]


def _bash_directory(path: Path) -> str:
    observed = subprocess.run([git_bash(), "-c", "pwd -P"], cwd=path,
                              stdin=subprocess.DEVNULL, capture_output=True, check=True)
    return observed.stdout.decode("utf-8").strip()


def _local_transport(tmp_path: Path) -> tuple[str, dict[str, str], Path]:
    directory = tmp_path / "private-package"
    directory.mkdir()
    selection = tmp_path / "reviewed-selection"
    selection.write_bytes(b"x" * 424)  # Synthetic fixture, never the reviewed private input.
    script = directory / "claude-stage.sh"
    expected = directory / "claude-stage.expected.json"
    script.write_bytes(b"synthetic stage, never run\n")
    expected.write_bytes(b"synthetic expectation\n")
    manifest = directory / "MANIFEST.sha256"
    manifest.write_bytes("".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in (script, expected)
    ).encode("utf-8"))
    source = _transport()
    assert source.count(f"SELECTION_SHA256={SELECTION_SHA256}") == 1
    source = source.replace(SELECTION_SHA256, hashlib.sha256(selection.read_bytes()).hexdigest())
    # No SSH/SFTP/SCP invocation is in the exercised prefix.
    local = source.split("OPTS=(-o", 1)[0]
    assert "ssh -T" not in local and "sftp -b" not in local and "scp " not in local
    env = os.environ.copy()
    env.update({
        "PACKAGE_DIR": _bash_directory(directory),
        "LOCAL_SELECTION": _bash_directory(tmp_path) + "/reviewed-selection",
        "SSH_TARGET": "synthetic-operator-target",
        "SSH_HOST_KEY_ALIAS": "synthetic-host-key-alias",
        "MANIFEST_SHA256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    })
    return local, env, directory


def test_transport_accepts_fresh_local_package_without_network(tmp_path):
    local, env, directory = _local_transport(tmp_path)
    accepted = subprocess.run([git_bash(), "-c", local], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert accepted.returncode == 0, accepted.stderr.decode("utf-8", errors="replace")
    assert (directory / "selection.json").read_bytes() == b"x" * 424
    assert (directory / "input.batch").read_text().splitlines() == [
        "mkdir m8-claude-input", "chmod 700 m8-claude-input",
        "put selection.json m8-claude-input/selection.json",
        "chmod 600 m8-claude-input/selection.json",
        "mkdir m8-claude-stage-package", "chmod 700 m8-claude-stage-package",
    ]
    assert not (directory / "claude-stage.stdout").exists()


def test_transport_syntax_and_dangling_local_symlink_refusal(tmp_path):
    source = _transport()
    parsed = subprocess.run([git_bash(), "-n"], input=source.encode("utf-8"),
                            capture_output=True, check=False)
    assert parsed.returncode == 0, parsed.stderr.decode("utf-8", errors="replace")
    local, env, directory = _local_transport(tmp_path)
    target = tmp_path / "outside-absent"
    alias = directory / "selection.json"
    try:
        alias.symlink_to(target)
    except (OSError, NotImplementedError):
        pytest.skip("native symlink creation is unavailable; syntax check ran")
    assert alias.is_symlink() and not target.exists()
    refused = subprocess.run([git_bash(), "-c", local], env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert refused.returncode != 0
    assert alias.is_symlink() and not target.exists()
    assert not (directory / "input.batch").exists()


def test_transport_existing_target_and_missing_package_refuse_without_network(tmp_path):
    local, env, directory = _local_transport(tmp_path)
    occupant = directory / "input.batch"
    occupant.write_bytes(b"prior owned content")
    refused = subprocess.run([git_bash(), "-c", local], env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert refused.returncode != 0
    assert occupant.read_bytes() == b"prior owned content"
    assert not (directory / "selection.json").exists()
    assert not (directory / "claude-stage.stdout").exists()

    occupant.unlink()
    moved = tmp_path / "package-no-longer-at-name"
    directory.rename(moved)
    refused = subprocess.run([git_bash(), "-c", local], env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert refused.returncode != 0
    assert not directory.exists()
    assert not (moved / "selection.json").exists()


def test_transport_noclobber_refuses_late_local_output_occupant(tmp_path):
    local, env, directory = _local_transport(tmp_path)
    marker = "/usr/bin/printf '%s\\n' \\\n"
    assert local.count(marker) == 1
    # Deterministically introduce a competing file after the fresh-path checks
    # but before the production redirect; the unmodified `set -C` must bind.
    raced = local.replace(marker, "printf sentinel > \"$PACKAGE_DIR/input.batch\"\n" + marker)
    outside = tmp_path / "outside-marker"
    outside.write_bytes(b"outside unchanged")
    refused = subprocess.run([git_bash(), "-c", raced], env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert refused.returncode != 0
    assert (directory / "input.batch").read_bytes() == b"sentinel"
    assert outside.read_bytes() == b"outside unchanged"
    assert not (directory / "claude-stage.stdout").exists()


def test_transport_selection_copy_refuses_late_occupant_but_old_install_does_not(tmp_path):
    local, env, directory = _local_transport(tmp_path)
    copy = '/usr/bin/cat "$LOCAL_SELECTION" > "$PACKAGE_DIR/selection.json"'
    assert local.count(copy) == 1
    race = 'printf sentinel > "$PACKAGE_DIR/selection.json"\n'
    raced = local.replace(copy, race + copy)
    refused = subprocess.run([git_bash(), "-c", raced], env=env,
                             stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert refused.returncode != 0
    assert (directory / "selection.json").read_bytes() == b"sentinel"
    assert not (directory / "input.batch").exists()

    # Synthetic counterexample: the former install command overwrites the
    # competing file despite the same earlier freshness checks and `set -C`.
    other = tmp_path / "old-install-counterexample"
    other.mkdir()
    old_local, old_env, old_directory = _local_transport(other)
    old = '/usr/bin/install -m 0600 "$LOCAL_SELECTION" "$PACKAGE_DIR/selection.json"'
    changed = old_local.replace(copy, race + old)
    assert changed != old_local
    overwritten = subprocess.run([git_bash(), "-c", changed], env=old_env,
                                 stdin=subprocess.DEVNULL, capture_output=True, check=False)
    assert overwritten.returncode == 0
    assert (old_directory / "selection.json").read_bytes() == b"x" * 424
