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


def _portable_gate() -> str:
    return (WORKFLOWS / "verify.yml").read_text(encoding="utf-8").split(
        "\n  verify-complete:\n", 1,
    )[1]


def test_portable_aggregate_covers_every_other_job_and_always_runs() -> None:
    workflow = (WORKFLOWS / "verify.yml").read_text(encoding="utf-8")
    jobs = set(re.findall(r"^  ([\w-]+):$", workflow.split("\njobs:\n", 1)[1], re.M))
    assert jobs == PORTABLE_JOBS | {"verify-complete"}
    gate = _portable_gate()
    assert "    if: always()\n" in gate
    needs = re.search(r"^    needs: \[([^\]]+)\]$", gate, re.M)
    assert needs is not None
    assert {item.strip() for item in needs[1].split(",")} == PORTABLE_JOBS
    for job, variable in (
        ("windows-discovery", "WINDOWS_DISCOVERY"),
        ("verify", "VERIFY"),
        ("mutations", "MUTATIONS"),
    ):
        assert f"          {variable}: ${{{{ needs.{job}.result }}}}" in gate
    assert "      fail-fast: false\n" in workflow
    # No portable job or step may quietly become optional under the aggregate.
    assert "continue-on-error" not in workflow
    assert "name:" not in gate.split("    steps:\n", 1)[0]
    assert re.findall(r"^    if: (.+)$", workflow, re.M) == ["always()"]


def _run_portable_gate(results: dict[str, str]) -> subprocess.CompletedProcess[str]:
    shell = textwrap.dedent(_portable_gate().split("        run: |\n", 1)[1])
    environment = {**os.environ, **results}
    return subprocess.run(
        [str(_bash()), "-c", shell], stdin=subprocess.DEVNULL,
        env=environment, capture_output=True, text=True, check=False, timeout=30,
    )


def test_portable_gate_positively_accepts_all_successful_jobs() -> None:
    completed = _run_portable_gate(
        dict.fromkeys(("WINDOWS_DISCOVERY", "VERIFY", "MUTATIONS"), "success"),
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == "all portable verification and mutation jobs succeeded\n"


@pytest.mark.parametrize("job", ["WINDOWS_DISCOVERY", "VERIFY", "MUTATIONS"])
@pytest.mark.parametrize("result", ["", "failure", "cancelled", "skipped", "pending", "unknown"])
def test_portable_gate_refuses_each_incomplete_job(job: str, result: str) -> None:
    results = dict.fromkeys(("WINDOWS_DISCOVERY", "VERIFY", "MUTATIONS"), "success")
    results[job] = result
    completed = _run_portable_gate(results)
    assert completed.returncode != 0
    assert completed.stdout == ""


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
