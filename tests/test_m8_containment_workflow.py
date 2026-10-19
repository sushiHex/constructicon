"""Pin the proof inventory and routing while actionlint checks YAML semantics."""

import ast
import json
import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests import native_account
from tests.git_bash import git_bash
from tests.substrate._evidence_secrecy import (
    BRIDGE_N4,
    MAINTENANCE_N4,
    assert_clean_evidence,
)

WORKFLOW = Path(__file__).parents[1] / ".github/workflows/m8-containment.yml"
CLASSIFIER = Path(__file__).parents[1] / "scripts/ci/m8_ci_scope.py"
MAINTENANCE = Path(__file__).parent / "substrate/test_operator_store_maintenance_restart.py"
MAINTENANCE_LITERAL_EVIDENCE_NAMES = [
    node.args[0].value
    for node in ast.walk(ast.parse(MAINTENANCE.read_text(encoding="utf-8")))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    and node.func.id == "write_evidence" and node.args
    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)
]

# Every provisioned proof belongs to exactly one isolated runner. These are not
# sampled smoke tests: removing a file or mutation inventory must fail here.
PROOFS = {
    "Prove N3a protected descriptors and native-only store custody": (
        "foundation",
        "tests/substrate/test_operator_store_restart.py "
        "tests/substrate/test_operator_store_publication.py "
        "tests/substrate/test_operator_store_containment.py "
        "scripts/check_m8_n3a_mutations.py",
    ),
    "Prove N3b acquisition-scoped egress denial": (
        "foundation",
        "tests/substrate/test_native_egress_containment.py scripts/check_m8_n3b_mutations.py",
    ),
    "Prove N3c protected-root maintenance and packaged qualification": (
        "lifecycle",
        "tests/substrate/test_operator_store_maintenance_restart.py",
    ),
    "Prove N3c persistence, refresh and non-widening": (
        "foundation",
        "tests/substrate/test_operator_store_persistence.py scripts/check_m8_n3c_mutations.py",
    ),
    "Prove the N4 proxy bridge in the native zone": (
        "foundation",
        "tests/substrate/test_native_egress_bridge.py scripts/check_m8_n4_bridge_mutations.py "
        "scripts/check_m8_n5_inventory_mutations.py",
    ),
    "Prove bounded native startup without a provider route": (
        "lifecycle",
        "tests/substrate/test_native_startup.py scripts/check_m8_startup_mutations.py",
    ),
    "Prove the accepted test-only provider placement": (
        "lifecycle",
        "tests/substrate/test_provider_placement.py tests/test_native_provider.py "
        "tests/test_provider_placement.py scripts/check_m8_placement_mutations.py",
    ),
    "Prove journal-owned native fixture recovery": (
        "lifecycle",
        "tests/substrate/test_native_recovery.py tests/test_native_lifecycle.py "
        "scripts/check_m8_native_recovery_mutations.py scripts/check_m8_n5_stage1_mutations.py "
        "scripts/check_m8_n5_read_mutations.py",
    ),
    "Prove N5 Stage 1 qualification on the real store and guard": (
        "foundation",
        "tests/substrate/test_qualification_linux.py "
        "scripts/check_m8_n5_stage1_linux_mutations.py",
    ),
    "Measure combined native startup and mediation": (
        "combined",
        "tests/substrate/test_native_combined.py tests/substrate/test_combined_startup_origins.py "
        "tests/test_native_combined.py tests/substrate/test_combined_sender.py "
        "tests/substrate/test_codex_native.py tests/substrate/test_qualification_write_linux.py "
        "scripts/check_m8_combined_mutations.py scripts/check_m8_n2_mutations.py "
        "scripts/check_m8_n2_write_mutations.py scripts/check_m8_n5_write_mutations.py",
    ),
    "Probe native mediation with loopback only and no credentials": (
        "mediation",
        "tests/substrate/test_native_codex_mediation.py "
        "scripts/check_native_codex_probe_mutations.py",
    ),
    "Prove containment as the non-sudo service user": (
        "foundation",
        "tests/substrate/test_linux_containment.py tests/substrate/test_contained_workspace.py "
        "tests/substrate/test_acquisition_closure.py tests/substrate/test_recorded_executor.py "
        "tests/substrate/test_linux_duplex.py tests/substrate/test_process_io.py "
        "tests/substrate/test_lifetime.py tests/substrate/test_contained_capture.py "
        "tests/substrate/test_git_pack.py tests/substrate/test_capture_lifecycle.py "
        "tests/substrate/test_codex_write_capture.py tests/substrate/test_codex_write_restart.py "
        "tests/substrate/test_codex_write_recovery.py "
        "tests/substrate/test_git_process.py tests/substrate/test_git_executable.py "
        "tests/runtime/test_async_workspace.py tests/api/test_capture_assembly.py "
        "tests/substrate/test_contained_gates.py tests/substrate/test_gate_lifecycle.py "
        "tests/runtime/test_async_gates.py "
        # Two named parity tests from one file: the host writer and the loader.
        "tests/test_m8_host_runtime.py tests/test_m8_host_runtime.py",
    ),
    "Prove the production host assembly from the installed launch set": (
        "foundation",
        "tests/substrate/test_codex_host.py scripts/check_m8_n5_host_mutations.py",
    ),
    "Rehearse the Stage 3 READ session without a login": (
        "foundation",
        "tests/test_m8_n5_read_rehearsal.py tests/test_m8_n5_write_rehearsal.py",
    ),
    "Rehearse the q12 continuation's real-tool steps": (
        "foundation", "tests/test_m8_maintenance_q12_rehearsal.py",
    ),
    "Prove the host plans the package CI installed": (
        "foundation", "tests/test_m8_host_runtime.py",
    ),
    "Kill the native review-regression mutants": (
        "foundation",
        "scripts/check_m8_containment_mutations.py scripts/check_m8_capture_mutations.py "
        "scripts/check_m8_gate_mutations.py scripts/check_m8_duplex_mutations.py",
    ),
}


def test_every_existing_proof_runs_once_in_its_isolated_lane():
    text = WORKFLOW.read_text(encoding="utf-8")
    steps = dict(re.findall(
        r"      - name: ([^\n]+)\n(.*?)(?=\n      - |\n  \w|\Z)", text, re.S,
    ))
    expected = []
    for name, (lane, inventory) in PROOFS.items():
        step = steps[name]
        assert f"        if: matrix.lane == '{lane}'\n" in step
        files = re.findall(r"(?:tests/[\w/]+|scripts/check_\w+)\.py", step)
        assert files == inventory.split(), name
        expected.extend(files)
        if "-m pytest" in step:
            assert step.count("--durations=10") == step.count("-m pytest")
    assert sorted(re.findall(r"(?:tests/[\w/]+|scripts/check_\w+)\.py", text)) == sorted(
        expected,
    )
    assert "lane: [foundation, lifecycle, combined, mediation]" in text
    assert "fail-fast: false" in text


def test_gate_always_checks_the_selected_proof_set_without_bypass():
    text = WORKFLOW.read_text(encoding="utf-8")
    gate = text.split("\n  containment:\n", 1)[1]
    assert "if: always()" in gate
    assert "needs: [classify, docs, proofs]" in gate
    for field in ("scope", "classification", "docs", "proofs"):
        assert f'--{field} "${field.upper()}"' in gate
    assert "needs.classify.result" in gate
    assert "needs.docs.result" in gate
    assert "needs.proofs.result" in gate
    assert "BASE_SHA: ${{ github.event.pull_request.base.sha || github.sha }}" in gate
    assert 'git cat-file -e "$BASE_SHA^{commit}"' in gate
    assert 'git show "$BASE_SHA:scripts/ci/m8_ci_scope.py"' in gate
    assert 'python3 "$RUNNER_TEMP/m8-ci-scope-gate.py" gate' in gate
    assert "fetch-depth: 0" in gate
    assert 'test "$SCOPE" = full' in gate
    assert 'test "$PROOFS" = success' in gate
    assert "python3 scripts/ci/m8_ci_scope.py gate" not in gate
    assert "scope=full" in text
    assert 'if [ "$EVENT" = pull_request ]; then' in text
    assert 'git show "$BASE_SHA:scripts/ci/m8_ci_scope.py"' in text
    assert 'python3 "$RUNNER_TEMP/m8-ci-scope.py" classify' in text
    assert "python3 scripts/ci/m8_ci_scope.py classify" not in text
    assert "fetch-depth: 0" in text
    for forbidden in ("continue-on-error", "paths-ignore:", "pull_request_target", "secrets."):
        assert forbidden not in text


def test_lane_evidence_is_disjoint_and_bound_to_the_reviewed_head():
    text = WORKFLOW.read_text(encoding="utf-8")
    artifact = "m8-containment-${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.lane }}"
    assert artifact in text
    assert "evidence/${{ github.run_id }}-${{ github.run_attempt }}-${{ matrix.lane }}" in text
    assert "EVIDENCE_COMMIT: ${{ github.event.pull_request.head.sha || github.sha }}" in text
    assert "EVIDENCE_LANE: ${{ matrix.lane }}" in text
    assert "if-no-files-found: error" in text
    assert "n3a-*.json" in text
    assert "n3b-*.json" in text
    assert "n3c-*.json" in text
    assert "n4-*.json" in text
    assert "M8_BRIDGE_REQUIRED=1" in text
    assert "m8-bridge-runtime.json" in text
    assert "M8_EGRESS_REQUIRED=1" in text
    assert "codex-*.json" in text
    assert "duplex-*.json" in text


@pytest.mark.parametrize("names", [BRIDGE_N4, MAINTENANCE_N4])
def test_each_lanes_n4_evidence_has_an_exact_clean_census(names, tmp_path):
    for name in names:
        (tmp_path / name).write_text('{"credential_free_fixture": true}')
    assert_clean_evidence(tmp_path, "n4-*.json", names, native_account.fixture_tokens())


@pytest.mark.parametrize("names", [BRIDGE_N4, MAINTENANCE_N4])
@pytest.mark.parametrize("damage", ["missing", "injected", "token", "begin", "private"])
def test_each_lanes_n4_census_or_secret_damage_is_refused(names, damage, tmp_path):
    for name in names:
        (tmp_path / name).write_text('{"credential_free_fixture": true}')
    if damage == "missing":
        (tmp_path / names[0]).unlink()
    elif damage == "injected":
        (tmp_path / "n4-injected.json").write_text("{}")
    elif damage == "token":
        (tmp_path / names[0]).write_text(native_account.fixture_tokens()[0])
    elif damage == "begin":
        (tmp_path / names[0]).write_text("-----BEGIN CERTIFICATE-----")
    else:
        (tmp_path / names[0]).write_text("PRIVATE KEY")
    with pytest.raises(AssertionError):
        assert_clean_evidence(tmp_path, "n4-*.json", names, native_account.fixture_tokens())


def test_required_maintenance_evidence_refuses_a_missing_directory(monkeypatch, tmp_path):
    from tests.substrate.test_operator_store_maintenance_restart import (
        assert_maintenance_evidence,
    )

    monkeypatch.setenv("M8_STORE_PROVISION_REQUIRED", "1")
    monkeypatch.delenv("M8_EVIDENCE_DIRECTORY", raising=False)
    with pytest.raises(AssertionError, match="required evidence directory is missing"):
        assert_maintenance_evidence()
    monkeypatch.delenv("M8_STORE_PROVISION_REQUIRED")
    assert_maintenance_evidence()
    monkeypatch.setenv("M8_STORE_PROVISION_REQUIRED", "1")
    monkeypatch.setenv("M8_EVIDENCE_DIRECTORY", str(tmp_path))
    (tmp_path / MAINTENANCE_N4[0]).write_text("{}")
    assert_maintenance_evidence()


def test_literal_maintenance_name_coverage_includes_both_isolated_startup_outcomes():
    assert {
        "n3c-isolated-startup-refusal.json", "n3c-isolated-startup-publication.json",
    } <= set(MAINTENANCE_LITERAL_EVIDENCE_NAMES)


@pytest.mark.parametrize("name", MAINTENANCE_LITERAL_EVIDENCE_NAMES)
def test_literal_maintenance_evidence_names_are_retained(name, tmp_path, monkeypatch):
    # Linux-only cases still get portable coverage for their literal names.
    # Computed names are checked when write_evidence actually emits them.
    from tests.substrate.test_native_codex_mediation import write_evidence

    monkeypatch.setenv("M8_EVIDENCE_DIRECTORY", str(tmp_path))
    write_evidence(name, {"synthetic_retention_probe": True})
    assert json.loads((tmp_path / name).read_bytes()) == {"synthetic_retention_probe": True}


@pytest.mark.parametrize("name", ["n3c-computed-point.json", "codex-computed-case.json"])
def test_evidence_writer_accepts_names_in_the_shared_lane_upload(name, tmp_path, monkeypatch):
    from tests.substrate.test_native_codex_mediation import write_evidence

    monkeypatch.setenv("M8_EVIDENCE_DIRECTORY", str(tmp_path))
    write_evidence(name, {"synthetic_retention_probe": True})
    assert (tmp_path / name).is_file()


@pytest.mark.parametrize("name", ["unretained.json", "n3c-nested/evidence.json"])
def test_evidence_writer_refuses_names_outside_the_lane_upload(name, tmp_path, monkeypatch):
    from tests.substrate.test_native_codex_mediation import write_evidence

    monkeypatch.setenv("M8_EVIDENCE_DIRECTORY", str(tmp_path))
    with pytest.raises(AssertionError, match=r"omitted from its lane artifact|must be basenames"):
        write_evidence(name, {"synthetic_retention_probe": True})
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("change", [
    lambda text: text.replace("Preserve exact runtime and observed boundary evidence", "removed"),
    lambda text: text.replace("uses: actions/upload-artifact@", "uses: actions/other@"),
    lambda text: text.replace("        if: always()", "        if: false"),
    lambda text: text.replace("-${{ matrix.lane }}", "-unscoped"),
    lambda text: text.replace("          path: |", "          paths: |"),
    lambda text: text.replace("${{ env.M8_EVIDENCE }}/", "${{ env.OTHER }}/"),
])
def test_evidence_writer_refuses_an_unrecognized_upload_contract(change, tmp_path, monkeypatch):
    from tests.substrate.test_native_codex_mediation import write_evidence

    text = change(WORKFLOW.read_text(encoding="utf-8"))
    monkeypatch.setattr(Path, "read_text", lambda *args, **kwargs: text)
    monkeypatch.setenv("M8_EVIDENCE_DIRECTORY", str(tmp_path))
    with pytest.raises(AssertionError):
        write_evidence("n3c-synthetic.json", {"synthetic_retention_probe": True})
    assert list(tmp_path.iterdir()) == []


def test_evidence_writer_refuses_a_missing_workflow(tmp_path, monkeypatch):
    from tests.substrate.test_native_codex_mediation import write_evidence

    monkeypatch.setattr(Path, "is_file", lambda *args: False)
    monkeypatch.setenv("M8_EVIDENCE_DIRECTORY", str(tmp_path))
    with pytest.raises(AssertionError, match="evidence upload workflow is missing"):
        write_evidence("n3c-synthetic.json", {"synthetic_retention_probe": True})
    assert list(tmp_path.iterdir()) == []


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1"},
        timeout=30,
    )
    return completed.stdout.strip()


def _commit(repository: Path, message: str) -> str:
    _git(repository, "add", "-A")
    _git(repository, "commit", "-m", message)
    return _git(repository, "rev-parse", "HEAD")


def _gate_shell() -> str:
    gate = WORKFLOW.read_text(encoding="utf-8").split(
        "      - name: Require the selected proof set\n", 1,
    )[1]
    return textwrap.dedent(gate.split("        run: |\n", 1)[1])


def _repository(tmp_path: Path, *, trusted_gate: bool) -> tuple[Path, str]:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.name", "CI Test")
    _git(repository, "config", "user.email", "ci@example.invalid")
    (repository / "README.md").write_text("base\n", encoding="utf-8")
    if trusted_gate:
        target = repository / "scripts/ci/m8_ci_scope.py"
        target.parent.mkdir(parents=True)
        target.write_bytes(CLASSIFIER.read_bytes())
    base = _commit(repository, "base")

    target = repository / "scripts/ci/m8_ci_scope.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "import sys\nprint('untrusted head gate accepted')\nsys.exit(0)\n",
        encoding="utf-8",
    )
    _commit(repository, "permissive head gate")
    return repository, base


def _run_gate(
    tmp_path: Path,
    repository: Path,
    base: str,
    *,
    scope: str,
    classification: str,
    docs: str,
    proofs: str,
) -> subprocess.CompletedProcess[str]:
    summary = tmp_path / "summary.md"
    environment = {
        **os.environ,
        "TEST_PYTHON": Path(sys.executable).as_posix(),
        "BASE_SHA": base,
        "SCOPE": scope,
        "CLASSIFICATION": classification,
        "DOCS": docs,
        "PROOFS": proofs,
        "RUNNER_TEMP": tmp_path.as_posix(),
        "GITHUB_STEP_SUMMARY": summary.as_posix(),
    }
    shell = 'python3() { "$TEST_PYTHON" "$@"; }\n' + _gate_shell()
    return subprocess.run(
        [git_bash(), "-c", shell],
        cwd=repository,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


@pytest.mark.parametrize("trusted_gate", [True, False])
@pytest.mark.parametrize("proofs", ["failure", "cancelled", ""])
def test_gate_refuses_incomplete_proofs_with_or_without_a_base_gate(
    tmp_path: Path, proofs: str, trusted_gate: bool,
) -> None:
    repository, base = _repository(tmp_path, trusted_gate=trusted_gate)
    completed = _run_gate(
        tmp_path,
        repository,
        base,
        scope="full",
        classification="success",
        docs="skipped",
        proofs=proofs,
    )
    assert completed.returncode != 0
    assert "untrusted head gate accepted" not in completed.stdout


def test_gate_runs_trusted_base_code_and_accepts_complete_proofs(tmp_path: Path) -> None:
    repository, base = _repository(tmp_path, trusted_gate=True)
    completed = _run_gate(
        tmp_path,
        repository,
        base,
        scope="full",
        classification="success",
        docs="skipped",
        proofs="success",
    )
    assert completed.returncode == 0, completed.stderr
    assert "all selected physical proof lanes succeeded" in completed.stdout
    assert "untrusted head gate accepted" not in completed.stdout


def test_gate_runs_trusted_base_code_and_accepts_verified_docs(tmp_path: Path) -> None:
    repository, base = _repository(tmp_path, trusted_gate=True)
    completed = _run_gate(
        tmp_path,
        repository,
        base,
        scope="docs",
        classification="success",
        docs="success",
        proofs="skipped",
    )
    assert completed.returncode == 0, completed.stderr
    assert "verified prose-only changes" in completed.stdout
    assert "untrusted head gate accepted" not in completed.stdout


def test_introducing_pr_bootstrap_accepts_only_complete_full_proofs(tmp_path: Path) -> None:
    repository, base = _repository(tmp_path, trusted_gate=False)
    completed = _run_gate(
        tmp_path,
        repository,
        base,
        scope="full",
        classification="success",
        docs="skipped",
        proofs="success",
    )
    assert completed.returncode == 0, completed.stderr
    assert "physical proof lanes succeeded (bootstrap)" in completed.stdout


@pytest.mark.parametrize(
    ("scope", "classification", "docs", "proofs"),
    [
        ("docs", "success", "success", "skipped"),
        ("full", "failure", "skipped", "success"),
        ("full", "cancelled", "skipped", "success"),
        ("full", "success", "failure", "success"),
        ("full", "success", "success", "success"),
    ],
)
def test_introducing_pr_bootstrap_refuses_every_incomplete_state(
    tmp_path: Path,
    scope: str,
    classification: str,
    docs: str,
    proofs: str,
) -> None:
    repository, base = _repository(tmp_path, trusted_gate=False)
    completed = _run_gate(
        tmp_path,
        repository,
        base,
        scope=scope,
        classification=classification,
        docs=docs,
        proofs=proofs,
    )
    assert completed.returncode != 0


def test_gate_refuses_an_absent_base_commit_before_bootstrap(tmp_path: Path) -> None:
    repository, _base = _repository(tmp_path, trusted_gate=False)
    completed = _run_gate(
        tmp_path,
        repository,
        "f" * 40,
        scope="full",
        classification="success",
        docs="skipped",
        proofs="success",
    )
    assert completed.returncode != 0
    assert "bootstrap" not in completed.stdout
