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
    "cosign": (CONTAINMENT, "Acquire pinned cosign binary", "cosign", "2.6.5"),
}
KINDS = {"cosign": "binary"}
COSIGN_USE = "Verify the pinned package's release signature and catalog commit"


def cache_names(name: str) -> tuple[str, str]:
    kind = KINDS.get(name, "archive")
    return f"Restore pinned {name} {kind}", f"Save pinned {name} {kind}"


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
    restore_name, save_name = cache_names(name)
    restore, save = step(workflow, restore_name), step(workflow, save_name)
    digest = re.findall(r"\b[0-9a-f]{64}\b",
                        workflow if name == "actionlint" else acquisition)[0]
    key = ("release-archive-codex-${{ env.CODEX_PIN_VERSION }}-Linux-X64-"
           "${{ env.CODEX_PIN_CODEX_SHA256 }}" if name == "codex" else
           "release-archive-actionlint-${{ env.ACTIONLINT_VERSION }}-Linux-X64-"
           "${{ env.ACTIONLINT_SHA256 }}" if name == "actionlint" else
           f"release-{KINDS.get(name, 'archive')}-{name}-{version}-Linux-X64-{digest}")
    cache_file = "${{ env.ACTIONLINT_ARCHIVE }}" if name == "actionlint" else archive
    for kind, cache_step in (("restore", restore), ("save", save)):
        assert f"uses: actions/cache/{kind}@{ACTION_PIN}" in cache_step
        assert f"path: ${{{{ runner.temp }}}}/{cache_file}\n" in cache_step
        assert f"key: {key}\n" in cache_step
        assert "restore-keys" not in cache_step
        assert "continue-on-error: true" in cache_step
    # A cache-service failure is best effort; integrity and use remain strict.
    assert "continue-on-error" not in acquisition
    assert "success() && " in save
    assert "always()" not in save and "failure()" not in save
    lane = {"pi": "lifecycle", "cosign": "foundation"}.get(name)
    guard = f"matrix.lane == '{lane}' && " if lane else ""
    assert f"if: success() && {guard}steps.{name}-cache.outputs.cache-hit != 'true'\n" in save
    if lane:
        for gated in (restore, acquisition):
            assert f"        if: matrix.lane == '{lane}'\n" in gated
    assert workflow.index(restore_name) < workflow.index(acquire_name)
    assert workflow.index(acquire_name) < workflow.index(save_name)
    assert "sha256sum --check --strict" in acquisition
    if name == "actionlint":
        for field in ("VERSION", "SHA256", "ASSET_ID"):
            assert workflow.count(f"ACTIONLINT_{field}:") == 1
        naming = shell(workflow, "Name the pinned actionlint archive")
        assert "ACTIONLINT_ARCHIVE=actionlint_%s_linux_amd64.tar.gz" in naming
        assert '"$ACTIONLINT_VERSION" >> "$GITHUB_ENV"' in naming
        assert '"$RUNNER_TEMP/$ACTIONLINT_ARCHIVE"' in acquisition
        use = shell(workflow, "Lint workflows with actionlint")
        assert 'tar -xzf "$RUNNER_TEMP/$ACTIONLINT_ARCHIVE"' in use
        assert "continue-on-error" not in step(workflow, "Lint workflows with actionlint")
    if name == "pi":
        assert f"/releases/download/v{version}/{archive}" in acquisition
        assert digest == pi_fixture.ARCHIVE_SHA
        assert workflow.index(save_name) < workflow.index(
            "Prove pinned Pi startup and its fixed local peer"
        )
    if name == "cosign":
        assert f"/sigstore/cosign/releases/download/v{version}/cosign-linux-amd64" in acquisition
        assert workflow.index(save_name) < workflow.index(COSIGN_USE)
        use = shell(workflow, COSIGN_USE)
        # Every use re-checks the pinned bytes, whether they were restored or fetched.
        check = f"printf '%s  %s\\n' {digest} \"$RUNNER_TEMP/cosign\" | sha256sum --check --strict"
        assert use.count(check) == 1
        # Nothing, not even the bundle download, runs between the check and use.
        assert f'{check}\n"$RUNNER_TEMP/cosign" verify-blob ' in use
        assert "cosign-linux-amd64" not in use


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
] + [("actionlint", "fallback-miss"), ("actionlint", "bumped-miss"),
      ("cosign", "replaced-hit"), ("cosign", "replaced-during-bundle")])
def test_actual_acquisition_shell_checks_hits_and_misses_before_use(
    tmp_path: Path, name: str, case: str,
) -> None:
    workflow, acquire_name, archive, _ = ASSETS[name]
    version = "1.7.13" if case == "bumped-miss" else "1.7.12"
    if case == "bumped-miss":
        workflow = workflow.replace('ACTIONLINT_VERSION: "1.7.12"',
                                    'ACTIONLINT_VERSION: "1.7.13"')
        archive = f"actionlint_{version}_linux_amd64.tar.gz"
    if name == "actionlint":
        matched = re.search(r'ACTIONLINT_VERSION: "([^"]+)"', workflow)
        assert matched is not None
        version = matched[1]
    payload = (b'#!/bin/sh\nprintf "use:%s\\n" "$1" >> "$USED"\n' if name == "cosign"
               else b"harmless pinned archive fixture\n")
    digest = hashlib.sha256(payload).hexdigest()
    body = shell(workflow, acquire_name)
    if name == "cosign":
        # The real use step from its pin re-check on; the vendor pin comes from env.
        use = shell(workflow, COSIGN_USE)
        if case == "replaced-hit":
            body += 'printf "swapped after acquisition\\n" > "$RUNNER_TEMP/cosign"\n'
        sourced = '. "$RUNNER_TEMP/pin.env"\n'
        body += use[use.index(sourced) + len(sourced):]
    # Only the pin bytes change. The real shell control flow and checksum tool run.
    body = re.sub(r"\b[0-9a-f]{64}\b", digest, body)
    if name == "actionlint":
        body = (shell(workflow, "Name the pinned actionlint archive")
                + 'set -a; . "$GITHUB_ENV"; set +a\n' + body)
        body += shell(workflow, "Lint workflows with actionlint")
    elif name == "pi":
        proof = shell(workflow, "Prove pinned Pi startup and its fixed local peer")
        body += proof[:proof.index("sudo install")]
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    target = runtime / archive
    if case == "bumped-miss":
        (runtime / ASSETS["actionlint"][2]).write_bytes(b"unchecked old archive")
    if case.endswith("hit"):
        target.write_bytes(payload if case in {"hit", "replaced-hit"}
                           else b"corrupt cached archive")
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
  case "$output" in
    *.sigstore)
      if [ "$SWAP_ON_BUNDLE" = 1 ]; then printf 'swapped\n' > "$RUNNER_TEMP/cosign"; fi
      : > "$output"; return 0;;
  esac
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
  printf 'use:%s\n' "$*" >> "$USED"
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
             "SWAP_ON_BUNDLE": "1" if case == "replaced-during-bundle" else "0",
             "GITHUB_ENV": (tmp_path / "github-env").as_posix(),
             "ACTIONLINT_VERSION": version, "ACTIONLINT_SHA256": digest,
             "ACTIONLINT_ASSET_ID": "fixture",
             "CODEX_PIN_CODEX_URL": "https://example.invalid/codex.tar.gz",
             "CODEX_PIN_VERSION": "0.0.0", "CODEX_PIN_CATALOG_COMMIT": "0" * 40},
    )
    accepted = case in {"hit", "miss", "fallback-miss", "bumped-miss"}
    assert (result.returncode == 0) == accepted, result.stderr
    assert used.exists() == accepted
    downloads = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    archive_downloads = [path for path in downloads if path.endswith("/" + archive)]
    assert bool(archive_downloads) == (not case.endswith("hit"))
    if case == "bumped-miss":
        assert archive in used.read_text(encoding="utf-8")
        assert ASSETS["actionlint"][2] not in used.read_text(encoding="utf-8")
    if case == "fallback-miss":
        assert len(archive_downloads) == 2
    if case in {"corrupt-hit", "corrupt-miss", "replaced-hit", "replaced-during-bundle"}:
        assert f"{archive}: FAILED" in result.stdout
    if case in {"replaced-hit", "replaced-during-bundle"}:
        # The acquisition check passed; only the re-check at use refused the bytes.
        assert f"{archive}: OK" in result.stdout
    if case in {"hit", "miss", "fallback-miss", "bumped-miss"}:
        assert f"{archive}: OK" in result.stdout
        assert target.read_bytes() == payload
        if name == "cosign":
            assert used.read_text(encoding="utf-8").startswith("use:verify-blob\n")
