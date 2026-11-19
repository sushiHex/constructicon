"""The documented walkthrough is the real fresh-process operator experience."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from examples.change_review import OPERATOR, assemble, checked, git
from examples.change_review_batch import MAX_RESPONSE_BYTES
from examples.change_review_batch_text import render_batch_text
from examples.change_review_walkthrough import ADVICE, CHILD_TIMEOUT_SECONDS

from constructicon.core.identity import digest

ROOT = Path(__file__).parents[2]


def child(module: str, *arguments: str, timeout: float = CHILD_TIMEOUT_SECONDS
          ) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", module, *arguments],
        cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def successful(process: subprocess.CompletedProcess[bytes]) -> str:
    assert process.returncode == 0, (process.returncode, process.stdout, process.stderr)
    assert process.stderr == b""
    return process.stdout.decode("utf-8")


def test_walkthrough_runs_real_fresh_processes_and_retains_readable_exact_facts(
    tmp_path: Path,
) -> None:
    # Run the portable entry itself, not a copy of the documentation's commands.
    # It starts six children, each with its own settlement/projection allowance.
    workspace = tmp_path / "new workspace é"
    experience = successful(child(
        "examples.change_review_walkthrough", "--workspace", str(workspace),
        timeout=6 * CHILD_TIMEOUT_SECONDS + 60,
    ))
    assert "Submitted: both files await advice." in experience
    assert ("Fresh-process partial status: second file complete; first still needs advice."
            in experience)
    partial_lines = experience.split("Fresh-process partial status:", 1)[1].split(
        "command_argv:", 1,
    )[0].splitlines()
    assert partial_lines[partial_lines.index('path: "alpha.py"') + 1] == 'status: "parked"'
    assert (partial_lines[partial_lines.index('path: "nested/beta.py"') + 1]
            == 'status: "succeeded"')
    assert "Fresh-process later reply: batch complete." in experience
    assert "Verified same-key submit replay: true; same-key reply replay: true." in experience
    assert "Usage is unmeasured; money unknown." in experience
    assert "completion is not code or merge approval" in experience
    assert "command_argv:" in experience and "--file-id" in experience
    assert "--run-id" in experience and "--key" in experience
    assert "--format" in experience and "text" in experience
    assert "root_metering:" in experience
    assert "untrusted" in experience.lower()
    for advice in ADVICE.values():
        assert advice in experience

    repository, state = workspace / "source", workspace / "state"
    assert repository.is_dir() and (state / "review.db").is_file()
    commits = git(repository, "rev-list", "--reverse", "HEAD").decode("ascii").splitlines()
    assert len(commits) == 2
    system, control = assemble(state / "review.db")
    runs = checked(control.runs_list(OPERATOR))
    assert runs.page.count == 1
    run_id = runs.items[0].run_id
    retained = checked(control.runs_result(OPERATOR, run_id)).model_dump(mode="json")
    assert retained["status"] == "succeeded"
    events_before = system._journal.events(run_id)

    # Both formats use the same CLI operation in separate processes. Exact
    # rendering equality proves text came from the existing response; the root
    # and event-cut checks reject a hidden recovery/extra mutation while reading.
    json_process = child("examples.change_review_batch", "--state", str(state),
                         "status", "--run-id", str(run_id))
    response = json.loads(successful(json_process))
    text_process = child("examples.change_review_batch", "--state", str(state),
                         "--format", "text", "status", "--run-id", str(run_id))
    text = successful(text_process)
    assert text == render_batch_text(response)
    assert len(text_process.stdout) <= MAX_RESPONSE_BYTES
    assert response["run_id"] == str(run_id)
    assert response["result"] == retained
    assert response["partial"] is False and response["limitations"] == []
    assert system._journal.events(run_id) == events_before
    assert checked(control.runs_result(OPERATOR, run_id)).model_dump(mode="json") == retained
    assert checked(control.runs_list(OPERATOR)).page.count == 1
    assert text.count("root_metering:") == 1
    metering = response["result"]["metering"]
    assert metering["coverage"] == "unmeasured"
    assert metering["groups"] == []
    assert metering["estimate"] is None and metering["estimate_coverage"] == "unknown"
    assert metering["confirmed_charge"] is None
    assert metering["confirmed_charge_coverage"] == "unknown"
    for label, field in (
        ("metering_coverage", "coverage"), ("metering_through_event_seq", "through_event_seq"),
        ("metering_attempt_count", "attempt_count"), ("estimate", "estimate"),
        ("estimate_coverage", "estimate_coverage"), ("confirmed_charge", "confirmed_charge"),
        ("confirmed_charge_coverage", "confirmed_charge_coverage"),
    ):
        line = next(line for line in text.splitlines() if line.startswith(label + ": "))
        assert json.loads(line.removeprefix(label + ": ")) == metering[field]
    assert "metering_sources: [] (no recorded source groups)" in text

    files = {file["path"]: file for file in response["files"]}
    assert list(files) == ["alpha.py", "nested/beta.py"]
    assert files["alpha.py"]["analysis"]["symbols"] == {
        "added": ["count"], "removed": [], "changed": ["total"],
    }
    assert files["nested/beta.py"]["analysis"]["symbols"] == {
        "added": ["label"], "removed": ["old_label"], "changed": [],
    }
    for kind in ("added", "removed", "changed"):
        for suffix, field in (("names", "symbols"), ("count", "counts")):
            prefix = f"{kind}_{suffix}: "
            values = [json.loads(line.removeprefix(prefix)) for line in text.splitlines()
                      if line.startswith(prefix)]
            assert values == [file["analysis"][field][kind] for file in files.values()]
    for path, file in files.items():
        assert file["status"] == "succeeded"
        assert file["analysis_provenance"] == "completed_output"
        assert file["advice"]["advice"] == ADVICE[path]
        assert file["advice"]["actor_id"] == OPERATOR.actor_id
        assert file["request"]["message_id"] != file["reply"]["message_id"]
        assert file["usage"]["coverage"] == "unknown"
        assert file["analysis"]["tests_executed"] is False
        assert file["analysis"]["comparison_available"] is True
        assert file["analysis"]["symbols_partial"] is False
        assert file["analysis"]["syntax_errors"] == {}
        for side, commit in zip(("before", "after"), commits, strict=True):
            reference = file[f"{side}_ref"]
            assert reference["repository"] == str(repository.resolve())
            assert reference["commit"] == commit and reference["paths"] == [path]
            source = git(repository, "show", f"{commit}:{path}").decode("utf-8")
            assert file["analysis"][f"{side}_hash"] == str(
                digest("example-python-source", 1, source),
            )
        assert file["file_id"] in text and path in text and ADVICE[path] in text
    assert len({file["request"]["message_id"] for file in files.values()}) == 2
    assert len({file["reply"]["message_id"] for file in files.values()}) == 2
    assert sum(event.kind == "RunSucceeded" for event in events_before) == 1
    # Existing batch tests already cover changed-payload conflicts and injected
    # process death. This experience proof reuses that command law, not new glue.


@pytest.mark.parametrize("occupied_file", [False, True], ids=["directory", "file"])
def test_walkthrough_refuses_occupied_workspace_without_overwriting(
    tmp_path: Path, occupied_file: bool,
) -> None:
    workspace = tmp_path / "operator-owned"
    if occupied_file:
        workspace.write_bytes(b"operator source")
        marker = workspace
    else:
        workspace.mkdir()
        marker = workspace / "keep.txt"
        marker.write_bytes(b"operator source")
    before = marker.read_bytes()
    refused = child("examples.change_review_walkthrough", "--workspace", str(workspace))
    assert refused.returncode == 1
    assert b"walkthrough_failed:" in refused.stderr
    assert marker.read_bytes() == before
    if not occupied_file:
        assert list(workspace.iterdir()) == [marker]
