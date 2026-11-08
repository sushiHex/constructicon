"""Execute the workflow's acquisition boundary with harmless archive bytes."""

import hashlib
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
from scripts.ci import build_m8_pi_startup_fixture as pi_fixture
from scripts.ci import m8_host_artifacts as artifacts

from tests.git_bash import git_bash

ROOT = Path(__file__).parents[1]
VERIFY = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
CONTAINMENT = (ROOT / ".github/workflows/m8-containment.yml").read_text(encoding="utf-8")
ACTION_PIN = "0057852bfaa89a56745cba8c7296529d2fc39830"
ASSETS = {
    "actionlint": (VERIFY, "Acquire pinned actionlint archive",
                   "actionlint_1.7.12_linux_amd64.tar.gz", "1.7.12"),
    "pi": (CONTAINMENT, "Acquire pinned Pi archive", "pi-linux-x64.tar.gz", "1.3.0"),
    "codex": (CONTAINMENT, "Acquire the pinned native investigation artifact (no account)",
              "codex.tar.gz", "0.160.1"),
}


def step(workflow: str, name: str) -> str:
    found = re.search(
        rf"^      - name: {re.escape(name)}\n((?:        .*\n|\n)+)", workflow, re.M,
    )
    assert found is not None, name
    return found[1]


def shell(workflow: str, name: str) -> str:
    return textwrap.dedent(step(workflow, name).split("        run: |\n", 1)[1])


@pytest.mark.parametrize("name", ASSETS)
def test_cache_key_and_save_are_bound_to_the_verified_archive(name: str) -> None:
    workflow, acquire_name, archive, version = ASSETS[name]
    acquisition = step(workflow, acquire_name)
    restore = step(workflow, f"Restore pinned {name} archive")
    save = step(workflow, f"Save pinned {name} archive")
    digest = re.findall(r"\b[0-9a-f]{64}\b", acquisition)[0]
    key = ("release-archive-codex-${{ env.CODEX_PIN_VERSION }}-Linux-X64-"
           "${{ env.CODEX_PIN_CODEX_SHA256 }}" if name == "codex" else
           f"release-archive-{name}-{version}-Linux-X64-{digest}")
    for kind, cache_step in (("restore", restore), ("save", save)):
        assert f"uses: actions/cache/{kind}@{ACTION_PIN}" in cache_step
        assert f"path: ${{{{ runner.temp }}}}/{archive}\n" in cache_step
        assert f"key: {key}\n" in cache_step
        assert "restore-keys" not in cache_step
        assert "continue-on-error" not in cache_step
    assert "always()" not in save and "failure()" not in save
    assert f"if: steps.{name}-cache.outputs.cache-hit != 'true'" in save or (
        name == "pi" and "if: matrix.lane == 'lifecycle' && "
        "steps.pi-cache.outputs.cache-hit != 'true'" in save
    )
    assert workflow.index(f"Restore pinned {name} archive") < workflow.index(acquire_name)
    assert workflow.index(acquire_name) < workflow.index(f"Save pinned {name} archive")
    assert "sha256sum --check --strict" in acquisition
    if name == "pi":
        assert digest == pi_fixture.ARCHIVE_SHA
        assert workflow.index(f"Save pinned {name} archive") < workflow.index(
            "Prove pinned Pi startup and its fixed local peer"
        )


def test_codex_template_still_captures_the_installed_pin_and_refuses_a_bypass() -> None:
    raw = CONTAINMENT.encode()
    pin = artifacts.vendor_pin(raw)
    assert artifacts.render_vendor_step(pin).encode() in raw
    assert pin["version"] == ASSETS["codex"][3]
    emitter = subprocess.run(
        [sys.executable, str(ROOT / "scripts/ci/vendor_pin_env.py")],
        stdin=subprocess.DEVNULL, capture_output=True, text=True, check=True, timeout=30,
    )
    emitted = dict(line.split("=", 1) for line in emitter.stdout.splitlines())
    assert emitted["CODEX_PIN_CODEX_SHA256"] == pin["codex_sha256"]
    assert emitted["CODEX_PIN_VERSION"] == pin["version"]
    identity = step(CONTAINMENT, "Read the pinned Codex archive cache identity")
    assert 'scripts/ci/vendor_pin_env.py >> "$GITHUB_ENV"' in identity
    assert CONTAINMENT.index("Read the pinned Codex archive cache identity") < CONTAINMENT.index(
        "Restore pinned codex archive"
    )
    bypass = raw.replace(
        b'          if [ ! -f "$RUNNER_TEMP/codex.tar.gz" ]; then\n', b"", 1,
    )
    with pytest.raises(ValueError, match="exactly one vendor acquisition step"):
        artifacts.vendor_pin(bypass)


@pytest.mark.parametrize(("name", "case"), [
    (name, case) for name in ASSETS
    for case in ["hit", "corrupt-hit", "miss", "corrupt-miss", "failed-miss"]
] + [("actionlint", "fallback-miss")])
def test_actual_acquisition_shell_checks_hits_and_misses_before_use(
    tmp_path: Path, name: str, case: str,
) -> None:
    workflow, acquire_name, archive, _ = ASSETS[name]
    payload = b"harmless pinned archive fixture\n"
    digest = hashlib.sha256(payload).hexdigest()
    body = shell(workflow, acquire_name)
    # Only the pin bytes change. The real shell control flow and checksum tool run.
    body = re.sub(r"\b[0-9a-f]{64}\b", digest, body)
    if name == "actionlint":
        body += shell(workflow, "Lint workflows with actionlint")
    elif name == "pi":
        proof = shell(workflow, "Prove pinned Pi startup and its fixed local peer")
        body += proof[:proof.index("sudo install")]
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    target = runtime / archive
    if case.endswith("hit"):
        target.write_bytes(payload if case == "hit" else b"corrupt cached archive")
    source = tmp_path / "payload"
    source.write_bytes(b"corrupt downloaded archive" if case == "corrupt-miss" else payload)
    script = tmp_path / "acquire.sh"
    script.write_text(
        """set -euo pipefail
curl() {
  output=''
  while [ "$#" -gt 0 ]; do
    case "$1" in -o|--output) output="$2"; shift 2;; *) shift;; esac
  done
  printf '%s\n' "$output" >> "$CALLS"
  if [ "$DOWNLOAD_FAIL" = 1 ]; then return 22; fi
  if [ "$DOWNLOAD_FAIL" = first ] && [ "$(wc -l < "$CALLS")" -eq 1 ]; then
    return 22
  fi
  cp "$PAYLOAD" "$output"
}
sudo() {
  case "$1" in tar|env) printf 'use\n' >> "$USED";; esac
}
tar() {
  printf 'use\n' >> "$USED"
  printf '#!/bin/sh\nexit 0\n' > "$RUNNER_TEMP/actionlint"
  chmod +x "$RUNNER_TEMP/actionlint"
}
shellcheck() { return 0; }
""" + body,
        encoding="utf-8", newline="\n",
    )
    calls, used = tmp_path / "calls", tmp_path / "used"
    result = subprocess.run(
        [git_bash(), str(script)], stdin=subprocess.DEVNULL, capture_output=True,
        text=True, timeout=30,
        env={**os.environ, "RUNNER_TEMP": runtime.as_posix(), "PAYLOAD": source.as_posix(),
             "CALLS": calls.as_posix(), "USED": used.as_posix(),
             "DOWNLOAD_FAIL": ("1" if case == "failed-miss" else
                               "first" if case == "fallback-miss" else "0"),
             "ACTIONLINT_VERSION": "1.7.12", "ACTIONLINT_SHA256": digest,
             "ACTIONLINT_ASSET_ID": "fixture"},
    )
    assert (result.returncode == 0) == (case in {"hit", "miss", "fallback-miss"}), result.stderr
    assert used.exists() == (case in {"hit", "miss", "fallback-miss"})
    downloads = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    archive_downloads = [path for path in downloads if path.endswith("/" + archive)]
    assert bool(archive_downloads) == (not case.endswith("hit"))
    if case == "fallback-miss":
        assert len(archive_downloads) == 2
    if case in {"corrupt-hit", "corrupt-miss"}:
        assert f"{archive}: FAILED" in result.stdout
    if case in {"hit", "miss", "fallback-miss"}:
        assert f"{archive}: OK" in result.stdout
        assert target.read_bytes() == payload
