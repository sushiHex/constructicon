"""The reviewed diagnosis bootstrap and guards, without a host or vendor process."""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
DOCUMENT = ROOT / "docs/plans/handoffs/M8-maintenance-diagnosis.md"


def _bootstrap() -> str:
    text = DOCUMENT.read_text(encoding="utf-8")
    match = re.search(r"-c '(import importlib.util, runpy, sys.*?)' \\\n", text, re.S)
    assert match is not None
    return match.group(1)


def _fence(label: str) -> str:
    text = DOCUMENT.read_text(encoding="utf-8")
    if label == "COMMON":
        pattern = r"Save this block as each package.*?```bash\n(.*?)```"
    else:
        pattern = rf"### {label}:.*?```bash\n(.*?)```"
    match = re.search(pattern, text, re.S)
    assert match is not None
    return match.group(1)


def _transport_verifier() -> str:
    text = DOCUMENT.read_text(encoding="utf-8")
    match = re.search(
        r"python -I -S -B -c '(import hashlib, re, sys\n.*?)' \\\n  \"\$STEP\"",
        text,
        re.S,
    )
    assert match is not None
    return match.group(1)


def _pinned_fence_hash(name: str) -> str:
    text = DOCUMENT.read_text(encoding="utf-8")
    match = re.search(rf"^{name}_SHA256=([0-9a-f]{{64}})$", text, re.M)
    assert match is not None
    return match.group(1)


def _run_transport_verifier(tmp_path: Path, step: str, measured_boot: str,
                            *, tamper_common: bool = False,
                            tamper_step: bool = False,
                            omit_boot: bool = False,
                            common_boot: str | None = None) -> subprocess.CompletedProcess[str]:
    common = _fence("COMMON").encode("utf-8")
    step_bytes = _fence(step.upper()).encode("utf-8")
    if tamper_common:
        common += b"# tampered\n"
    if tamper_step:
        step_bytes += b"# tampered\n"
    if omit_boot:
        common = re.sub(rb"(?m)^EXPECTED_BOOT=.*\n", b"", common)
    common_path = tmp_path / "common.sh"
    step_path = tmp_path / "step.sh"
    boot_in_file = measured_boot if common_boot is None else common_boot
    common_path.write_bytes(
        common.replace(b"EXPECTED_BOOT=UNREVIEWED", f"EXPECTED_BOOT={boot_in_file}".encode())
    )
    step_path.write_bytes(step_bytes)
    args = [sys.executable, "-I", "-S", "-B", "-c", _transport_verifier(),
            step, measured_boot, str(common_path), str(step_path),
            _pinned_fence_hash("COMMON_TEMPLATE"),
            *(_pinned_fence_hash(f"{name}_STEP") for name in ("D1", "D2", "D3"))]
    return subprocess.run(args, stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=20, check=False)


def _controller(tmp_path: Path) -> tuple[Path, Path]:
    controller = tmp_path / "controller"
    package = controller / "constructicon/substrate/journal"
    package.mkdir(parents=True)
    for parent in (controller / "constructicon", package.parent, package):
        (parent / "__init__.py").write_text("", encoding="utf-8")
    (package / "existing.py").write_text("VALUE = 'installed'\n", encoding="utf-8")
    helpers = tmp_path / "helpers"
    helpers.mkdir()
    (helpers / "existing.py").write_text("VALUE = 'shadowed'\n", encoding="utf-8")
    (helpers / "maintenance_evidence.py").write_text("VALUE = 'reviewed'\n", encoding="utf-8")
    (helpers / "maintenance_diagnostic.py").write_text(
        "from constructicon.substrate.journal import existing, maintenance_evidence\n"
        "print(existing.VALUE + ':' + maintenance_evidence.VALUE)\n", encoding="utf-8",
    )
    return controller, helpers


def _run_bootstrap(controller: Path, helpers: Path) -> subprocess.CompletedProcess[str]:
    program = _bootstrap().replace("/opt/constructicon-m8-controller", controller.as_posix())
    return subprocess.run([sys.executable, "-I", "-S", "-B", "-c", program, str(helpers)],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, check=False)


def test_isolated_bootstrap_adds_only_missing_helpers_without_shadowing(tmp_path):
    controller, helpers = _controller(tmp_path)
    result = _run_bootstrap(controller, helpers)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "installed:reviewed\n" and result.stderr == ""
    assert not list(tmp_path.rglob("__pycache__"))


@pytest.mark.parametrize("name", ["maintenance_diagnostic", "maintenance_evidence"])
def test_bootstrap_refuses_an_installed_helper_collision(tmp_path, name):
    controller, helpers = _controller(tmp_path)
    (controller / f"constructicon/substrate/journal/{name}.py").write_text(
        "raise RuntimeError('must not execute')\n", encoding="utf-8")
    result = _run_bootstrap(controller, helpers)
    assert result.returncode != 0
    assert result.stdout == ""
    assert "AssertionError" in result.stderr and "must not execute" not in result.stderr


def test_diagnosis_shell_blocks_parse_and_unprepared_pins_stop():
    bash = shutil.which("bash")
    assert bash is not None
    text = DOCUMENT.read_text(encoding="utf-8")
    blocks = re.findall(r"```bash\n(.*?)```", text, re.S)
    assert len(blocks) == 5
    for block in blocks:
        result = subprocess.run([bash, "-n", "-c", block], stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=20, check=False)
        assert result.returncode == 0, result.stderr
    for block in blocks:
        has_boot_placeholder = re.search(r"(?m)^EXPECTED_BOOT=UNREVIEWED$", block) is not None
        if not has_boot_placeholder and "EVIDENCE_SHA256=" not in block:
            continue
        # Only the closed pin guard executes; no host-bound command follows it.
        boundary = "test \"$(" if has_boot_placeholder else "P="
        guard = block.split(boundary, 1)[0]
        guard = re.sub(r'^\. .*common.sh"\n', "", guard, flags=re.M)
        guard = re.sub(r"(?m)^((?:EVIDENCE|DIAGNOSTIC)_SHA256)=.*$", r"\1=UNREVIEWED", guard)
        result = subprocess.run([bash, "-c", "set -Eeuo pipefail\n" + guard],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, check=False)
        assert result.returncode != 0 and result.stdout == "" and result.stderr == ""


def test_historical_helper_pins_and_successor_source_are_distinct():
    text = DOCUMENT.read_text(encoding="utf-8")
    successor = (ROOT / "docs/plans/handoffs/M8-maintenance-installed-diagnostics.md").read_text(
        encoding="utf-8")
    historical = {
        "EVIDENCE": "2f654a218fcb55eee65a59c1c8ae63bc8a761db3fe71143f41dff69e22a1b578",
        "DIAGNOSTIC": "f0555df16b076b7a5d65d786d9ffd5febb9878b3065e1a2fbc7565d0197a6c69",
    }
    for label, name in (("EVIDENCE", "maintenance_evidence"),
                        ("DIAGNOSTIC", "maintenance_diagnostic")):
        match = re.search(rf"^{label}_SHA256=([0-9a-f]{{64}})$", text, re.M)
        assert match is not None
        assert match.group(1) == historical[label]
        assert historical[label] in successor
        raw = (ROOT / f"src/constructicon/substrate/journal/{name}.py").read_bytes()
        assert b"\r" not in raw
        current = re.search(rf"^CURRENT_{label}_SHA256=([0-9a-f]{{64}})$", successor, re.M)
        assert current is not None
        assert hashlib.sha256(raw).hexdigest() == current.group(1)


@pytest.mark.parametrize("hostile_attributes", ["none", "configured", "default"])
def test_pinned_helpers_keep_reviewed_bytes_in_autocrlf_checkout(
    tmp_path, monkeypatch, hostile_attributes,
):
    if hostile_attributes == "configured":
        attributes = tmp_path / "hostile-attributes"
        attributes.write_text("* text eol=lf\n", encoding="utf-8")
        config = tmp_path / "hostile-gitconfig"
        config.write_text(
            f'[core]\n\tattributesFile = "{attributes.as_posix()}"\n', encoding="utf-8",
        )
        monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    elif hostile_attributes == "default":
        config_home = tmp_path / "xdg"
        attributes = config_home / "git" / "attributes"
        attributes.parent.mkdir(parents=True)
        attributes.write_text("* text eol=lf\n", encoding="utf-8")
        monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))

    empty_attributes = tmp_path / "empty-attributes"
    empty_attributes.write_bytes(b"")
    git_env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    git_env.update({
        "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_ATTR_NOSYSTEM": "1",
    })

    def git(*arguments: str, cwd: Path = tmp_path) -> bytes:
        return subprocess.run(
            ["git", "-c", f"core.attributesFile={empty_attributes}", "-C", str(cwd), *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True, check=True, timeout=20, env=git_env,
        ).stdout

    git("init", "--quiet")
    git("config", "core.autocrlf", "true")
    (tmp_path / ".gitattributes").write_bytes((ROOT / ".gitattributes").read_bytes())
    paths = [f"src/constructicon/substrate/journal/{name}.py" for name in
             ("maintenance_evidence", "maintenance_diagnostic")]
    reviewed = {}
    for path in paths:
        # Compare a real checkout with canonical Git blobs, not a normalized copy.
        reviewed[path] = git("show", f"HEAD:{path}", cwd=ROOT)
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(reviewed[path])
    control = tmp_path / "unrestricted.txt"
    control.write_bytes(b"checkout control\n")
    git("add", ".gitattributes", "unrestricted.txt", *paths)
    attributes = git("check-attr", "text", "eol", "--", *paths).decode().splitlines()
    assert attributes == [line for path in paths for line in
                          (f"{path}: text: set", f"{path}: eol: lf")]
    for path in [*paths, "unrestricted.txt"]:
        (tmp_path / path).unlink()
    git("checkout-index", "--force", "--all")
    assert control.read_bytes() == b"checkout control\r\n"
    for path in paths:
        assert (tmp_path / path).read_bytes() == reviewed[path]
        assert b"\r" not in (tmp_path / path).read_bytes()


def test_transport_pins_exact_step_and_common_fences(tmp_path):
    boot = "f19f633d-b2bc-459f-ba7c-2ceabed9ca7a"
    assert hashlib.sha256(_fence("COMMON").encode()).hexdigest() == _pinned_fence_hash(
        "COMMON_TEMPLATE"
    )
    for step in ("D1", "D2", "D3"):
        assert hashlib.sha256(_fence(step).encode()).hexdigest() == _pinned_fence_hash(
            f"{step}_STEP"
        )
        result = _run_transport_verifier(tmp_path, step.lower(), boot)
        assert result.returncode == 0 and result.stdout == "" and result.stderr == ""


def test_transport_verifier_rejects_tampering_and_wrong_or_missing_boot(tmp_path):
    boot = "f19f633d-b2bc-459f-ba7c-2ceabed9ca7a"
    other_boot = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    cases = (
        _run_transport_verifier(tmp_path, "d1", boot, tamper_common=True),
        _run_transport_verifier(tmp_path, "d1", boot, tamper_step=True),
        _run_transport_verifier(tmp_path, "d1", boot, common_boot=other_boot),
        _run_transport_verifier(tmp_path, "d1", boot, omit_boot=True),
        _run_transport_verifier(tmp_path, "d1", "UNREVIEWED"),
    )
    for result in cases:
        assert result.returncode != 0 and result.stdout == ""


def test_runbook_excludes_install_qualification_and_new_attempt():
    text = DOCUMENT.read_text(encoding="utf-8")
    commands = "\n".join(re.findall(r"```(?:bash|powershell)\n(.*?)```", text, re.S))
    for forbidden in ("activate", "qualify", "turn/start", "maintenance_entry",
                      "Save-VM", "Checkpoint-VM"):
        assert forbidden not in commands
    assert commands.count("Start-VM -Name constructicon-m8") == 1
    assert commands.count("Stop-VM -Name constructicon-m8") == 1
    assert "capture" not in _bootstrap()
    for step in ("d1", "d2", "d3"):
        assert f'. "$HOME/maintenance-diagnosis-{step}-package/common.sh"' in commands
    assert '"${FILES[@]}" > SHA256SUMS' in commands
    assert "sha256sum --check --strict SHA256SUMS && bash step.sh" in commands


@pytest.mark.parametrize("process_status", [0, 1, 2])
def test_quiescence_requires_the_exact_no_process_exit(process_status):
    text = DOCUMENT.read_text(encoding="utf-8")
    block = next(part for part in re.findall(r"```bash\n(.*?)```", text, re.S)
                 if re.search(r"(?m)^EXPECTED_BOOT=UNREVIEWED$", part))
    boot = "f19f633d-b2bc-459f-ba7c-2ceabed9ca7a"
    block = block.replace("EXPECTED_BOOT=UNREVIEWED", "EXPECTED_BOOT=" + boot)
    block = block.replace("/usr/bin/cat /proc/sys/kernel/random/boot_id", "printf " + boot)
    block = block.replace("/usr/bin/pgrep -u m8-service", f"(exit {process_status})")
    result = subprocess.run([shutil.which("bash"), "-c", "set -Eeuo pipefail\n" + block],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=20, check=False)
    if process_status == 1:
        assert result.returncode == 0 and result.stdout == "diagnosis-quiescence-checked\n"
        assert result.stderr == ""
    else:
        assert result.returncode != 0 and result.stdout == ""
