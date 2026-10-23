"""Exercise the merge aggregate and pin its complete workflow dependency set."""

import os
import re
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.test_m8_operator_commands import _bash

WORKFLOWS = Path(__file__).parents[1] / ".github/workflows"
PORTABLE_JOBS = {"windows-discovery", "verify", "mutations"}
SCOPE_JOBS = {"classify", "docs"}


def _portable_gate() -> str:
    return (WORKFLOWS / "verify.yml").read_text(encoding="utf-8").split(
        "\n  verify-complete:\n", 1,
    )[1]


def test_portable_aggregate_covers_every_other_job_and_always_runs() -> None:
    workflow = (WORKFLOWS / "verify.yml").read_text(encoding="utf-8")
    jobs = set(re.findall(r"^  ([\w-]+):$", workflow.split("\njobs:\n", 1)[1], re.M))
    assert jobs == PORTABLE_JOBS | SCOPE_JOBS | {"verify-complete"}
    gate = _portable_gate()
    assert "    if: always()\n" in gate
    needs = re.search(r"^    needs: \[([^\]]+)\]$", gate, re.M)
    assert needs is not None
    assert {item.strip() for item in needs[1].split(",")} == PORTABLE_JOBS | SCOPE_JOBS
    for job, variable in (
        ("classify", "CLASSIFICATION"), ("docs", "DOCS"),
        ("windows-discovery", "WINDOWS_DISCOVERY"),
        ("verify", "VERIFY"),
        ("mutations", "MUTATIONS"),
    ):
        assert f"          {variable}: ${{{{ needs.{job}.result }}}}" in gate
    assert "      fail-fast: false\n" in workflow
    assert "          SCOPE: ${{ needs.classify.outputs.scope }}" in gate
    # No selected job or step may quietly become optional under the aggregate.
    assert "continue-on-error" not in workflow
    assert "name:" not in gate.split("    steps:\n", 1)[0]
    assert re.findall(r"^    if: (.+)$", workflow, re.M) == [
        "needs.classify.outputs.scope == 'docs'",
        *("needs.classify.outputs.scope == 'full'" for _ in PORTABLE_JOBS),
        "always()",
    ]


def test_windows_job_keeps_discovery_and_exercises_minimum_python_disposal() -> None:
    workflow = (WORKFLOWS / "verify.yml").read_text(encoding="utf-8")
    windows = workflow.split("\n  windows-discovery:\n", 1)[1].split("\n  verify:\n", 1)[0]
    assert 'python-version: "3.12"' in windows
    assert "tests/test_m8_discovery_procedure.py" in windows
    assert "UV_PROJECT_ENVIRONMENT: .venv311" in windows
    assert "uv run --no-active --locked --python 3.11 python -m pytest" in windows
    for target in (
        "tests/test_gitworld.py",
        "tests/test_portable_acquisition_namespace.py",
        "tests/substrate/test_pi_provider.py::"
        "test_materialized_task_reads_exact_workspace_and_closes_both_leases",
        "tests/api/test_pi_leases.py::"
        "test_scripted_read_counterfactual_simulates_effects_and_discards_both_leases",
    ):
        assert target in windows
    assert "    if: needs.classify.outputs.scope == 'full'\n" in windows
    assert not re.search(r"^        if:", windows, re.M)
    assert "continue-on-error" not in windows


def _run_portable_gate(results: dict[str, str]) -> subprocess.CompletedProcess[str]:
    shell = textwrap.dedent(_portable_gate().split("        run: |\n", 1)[1])
    environment = {**os.environ, **results}
    return subprocess.run(
        [str(_bash()), "-c", shell], stdin=subprocess.DEVNULL,
        env=environment, capture_output=True, text=True, check=False, timeout=30,
    )


def _successful_results(scope: str) -> dict[str, str]:
    return {
        "CLASSIFICATION": "success", "SCOPE": scope,
        "DOCS": "success" if scope == "docs" else "skipped",
        **dict.fromkeys(("WINDOWS_DISCOVERY", "VERIFY", "MUTATIONS"),
                        "skipped" if scope == "docs" else "success"),
    }


@pytest.mark.parametrize("scope", ["docs", "full"])
def test_portable_gate_positively_accepts_the_complete_selected_jobs(scope: str) -> None:
    completed = _run_portable_gate(_successful_results(scope))
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "all selected portable jobs succeeded\n"
    assert completed.stderr == ""


@pytest.mark.parametrize("scope", ["docs", "full"])
@pytest.mark.parametrize("job", ["CLASSIFICATION", "DOCS", "WINDOWS_DISCOVERY",
                                 "VERIFY", "MUTATIONS"])
@pytest.mark.parametrize("result", ["", "success", "failure", "cancelled", "skipped",
                                    "pending", "unknown"])
def test_portable_gate_requires_exact_selected_and_unselected_states(
    scope: str, job: str, result: str,
) -> None:
    results = _successful_results(scope)
    expected = results[job]
    results[job] = result
    completed = _run_portable_gate(results)
    assert (completed.returncode == 0) is (result == expected)
    if result != expected:
        assert completed.stdout == ""


@pytest.mark.parametrize("scope", ["", "unknown", "DOCS"])
def test_portable_gate_never_accepts_an_unknown_classification(scope: str) -> None:
    results = _successful_results("full")
    results["SCOPE"] = scope
    completed = _run_portable_gate(results)
    assert completed.returncode != 0 and completed.stdout == ""


@pytest.mark.parametrize("variable", ["CLASSIFICATION", "SCOPE", "DOCS",
                                      "WINDOWS_DISCOVERY", "VERIFY", "MUTATIONS"])
def test_portable_gate_refuses_absent_evidence_variables(variable: str, monkeypatch) -> None:
    results = _successful_results("full")
    results.pop(variable)
    monkeypatch.delenv(variable, raising=False)
    completed = _run_portable_gate(results)
    assert completed.returncode != 0 and completed.stdout == ""


def test_required_contexts_are_unconditional_pr_checks_without_path_filters() -> None:
    for filename, context in (
        ("verify.yml", "verify-complete"),
        ("m8-runner-qualification.yml", "qualify"),
        ("m8-containment.yml", "containment"),
    ):
        workflow = (WORKFLOWS / filename).read_text(encoding="utf-8")
        assert "  pull_request:\n" in workflow
        assert "paths:" not in workflow and "paths-ignore:" not in workflow
        assert "continue-on-error" not in workflow
        assert workflow.count(f"\n  {context}:\n") == 1
    qualification = (WORKFLOWS / "m8-runner-qualification.yml").read_text(encoding="utf-8")
    assert re.findall(r"^  ([\w-]+):$", qualification.split("\njobs:\n", 1)[1], re.M) == [
        "qualify",
    ]
    assert not re.search(r"^    if:", qualification, re.M)
    assert not re.search(r"^    name:", qualification, re.M)
