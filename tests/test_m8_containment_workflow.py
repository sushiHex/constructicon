"""Pin the proof inventory and routing while actionlint checks YAML semantics."""

import re
from pathlib import Path

WORKFLOW = Path(__file__).parents[1] / ".github/workflows/m8-containment.yml"

# Every pre-split proof belongs to exactly one isolated runner. These are not
# sampled smoke tests: removing a file or mutation inventory must fail here.
PROOFS = {
    "Prove N3a protected descriptors and native-only store custody": (
        "foundation",
        "tests/substrate/test_operator_store_restart.py "
        "tests/substrate/test_operator_store_publication.py "
        "tests/substrate/test_operator_store_containment.py "
        "scripts/check_m8_n3a_mutations.py",
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
        "scripts/check_m8_native_recovery_mutations.py",
    ),
    "Measure combined native startup and mediation": (
        "combined",
        "tests/substrate/test_native_combined.py tests/substrate/test_combined_startup_origins.py "
        "tests/test_native_combined.py tests/substrate/test_combined_sender.py "
        "tests/substrate/test_codex_native.py scripts/check_m8_combined_mutations.py "
        "scripts/check_m8_n2_mutations.py",
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
        "tests/substrate/test_git_process.py tests/substrate/test_git_executable.py "
        "tests/runtime/test_async_workspace.py tests/api/test_capture_assembly.py "
        "tests/substrate/test_contained_gates.py tests/substrate/test_gate_lifecycle.py "
        "tests/runtime/test_async_gates.py",
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
    assert "codex-*.json" in text
    assert "duplex-*.json" in text
