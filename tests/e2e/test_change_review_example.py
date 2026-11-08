"""The documented local entry: durable source review without executing source."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from examples.change_review import (
    ANALYSIS,
    CHANNEL_ID,
    DEMO_ADVICE,
    OPERATOR,
    SOURCE_BYTES,
    SYMBOL_LIMIT,
    ReviewInput,
    assemble,
    checked,
    committed_source,
    compare_sources,
    git,
    read_detail,
)

from constructicon.core.address import RunId
from constructicon.core.run import RunStatus

ROOT = Path(__file__).parents[2]


def entry(state: Path, *arguments: str, crash_at: str | None = None) -> subprocess.CompletedProcess:
    command = [sys.executable, "-m", "examples.change_review"]
    if crash_at is not None:
        # Only replace the existing public fault probe; run the actual CLI.
        code = """
import os
import examples.change_review as example
original = example.ControlPlane
def injected(**kwargs):
    def probe(name):
        if name == os.environ['REVIEW_CRASH_AT']:
            os._exit(19)
    return original(**kwargs, fault_probe=probe)
example.ControlPlane = injected
raise SystemExit(example.main())
"""
        command = [sys.executable, "-c", code]
    return subprocess.run(
        [*command, "--state", str(state), *arguments],
        cwd=ROOT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "REVIEW_CRASH_AT": crash_at or ""},
        stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
        timeout=45, check=False,
    )


def output(process: subprocess.CompletedProcess) -> dict:
    assert process.returncode == 0, process.stderr
    return json.loads(process.stdout)


def source_commits(root: Path, before: bytes, after: bytes) -> tuple[Path, str, str]:
    repository = root / "source"
    repository.mkdir()
    git(repository, "init", "--quiet")
    commits = []
    for raw in (before, after):
        (repository / "calc.py").write_bytes(raw)
        git(repository, "add", "--", "calc.py")
        git(repository, "-c", "user.name=Example", "-c", "user.email=example@example.invalid",
            "commit", "--quiet", "--allow-empty", "-m", "fixture")
        commits.append(git(repository, "rev-parse", "HEAD").decode("ascii").strip())
    return repository, commits[0], commits[1]


def test_documented_demo_replays_the_same_run_and_retained_advice(tmp_path: Path) -> None:
    state = tmp_path / "state"
    first = output(entry(state, "demo", "--key", "walkthrough-1"))
    assert first["result"]["status"] == "succeeded"
    assert first["result"]["outputs"]["analysis"]["symbols"] == {
        "added": ["count"], "changed": ["total"], "removed": [],
    }
    assert first["result"]["outputs"]["advice"]["advice"] == DEMO_ADVICE
    assert first["result"]["outputs"]["advice"]["actor_id"] == OPERATOR.actor_id
    assert first["result"]["outputs"]["advice"]["message_id"] == first["reply"]["message_id"]
    assert first["result"]["outputs"]["analysis"]["tests_executed"] is False
    assert ANALYSIS.json_schema == ReviewInput.model_json_schema()
    ReviewInput.model_validate(first["result"]["outputs"]["analysis"])
    assert first["submission"]["command"]["replayed"] is False

    replay = output(entry(state, "demo", "--key", "walkthrough-1"))
    assert replay["submission"]["run_id"] == first["submission"]["run_id"]
    assert replay["submission"]["command"]["replayed"] is True
    assert replay["reply"]["command"]["replayed"] is True
    assert replay["request"]["message_id"] == first["request"]["message_id"]
    assert replay["request"]["acknowledged"] is True  # retained even after consumption
    assert replay["result"] == first["result"]

    system, control = assemble(state / "review.db")
    assert checked(control.runs_list(OPERATOR)).page.count == 1
    assert system.describe().components == ()  # exact refs need no stable promotion
    metering = replay["result"]["metering"]
    assert replay["result"]["result_schema_version"] == 3
    assert metering["coverage"] == "unmeasured"
    assert metering["attempt_count"] == 0 and metering["groups"] == []
    assert metering["estimate"] is None and metering["confirmed_charge"] is None
    assert metering["estimate_coverage"] == metering["confirmed_charge_coverage"] == "unknown"
    result = checked(control.runs_result(OPERATOR, RunId(first["result"]["run_id"])))
    assert metering["through_event_seq"] == result.capability_accounting.through_event_seq
    detail = read_detail(control, result.metering.detail)
    assert detail["attempts"] == [] and detail["next_uri"] is None
    assert detail["through_event_seq"] == metering["through_event_seq"]


def test_real_process_death_after_reply_commit_recovers_without_duplicate_work(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    marker = tmp_path / "must-not-exist"
    source = (
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('executed')\n"
        "def new():\n    return 2\n"
    )
    repository, before, after = source_commits(
        tmp_path, b"def old():\n    return 1\n", source.encode("utf-8"),
    )
    arguments = ("submit", "--repository", str(repository), "--before-commit", before,
                 "--after-commit", after, "--path", "calc.py", "--key", "change-1")
    submitted = output(entry(state, *arguments))
    run_id = submitted["result"]["run_id"]
    assert submitted["result"]["status"] == "parked"
    assert submitted["request_payload"]["analysis"]["symbols"] == {
        "added": ["new"], "removed": ["old"], "changed": [],
    }
    assert not marker.exists()
    observed = output(entry(state, "status", "--run-id", run_id))
    assert observed["result"] == submitted["result"]
    assert observed["request_payload"] == submitted["request_payload"]

    # The same command key may not silently admit different source bytes.
    changed_arguments = tuple(before if arg == after else arg for arg in arguments)
    refused = entry(state, *changed_arguments)
    assert refused.returncode == 1
    assert "control.idempotency.conflict" in refused.stderr

    reply_arguments = ("reply", "--run-id", run_id, "--advice", "Add a test for new.",
                       "--key", "advice-1")
    died = entry(state, *reply_arguments, crash_at="channels_reply.after_command_completion")
    assert died.returncode == 19
    # Positive evidence of the exact state at death, before any recovery starts.
    system, control = assemble(state / "review.db")
    assert checked(control.runs_status(OPERATOR, RunId(run_id))).status is RunStatus.PARKED
    request_id = submitted["request"]["message_id"]
    journal = system._journal
    reply = journal.channel_reply_for(channel_id=CHANNEL_ID, request_id=request_id)
    assert reply is not None
    assert reply.envelope.payload["advice"] == "Add a test for new."
    writer = journal.channel_message_writer(message_id=reply.message_id)
    assert writer is not None
    command = checked(control.commands_status(OPERATOR, writer.command_id))
    assert command.state == "committed"

    resumed = output(entry(state, *reply_arguments))
    assert resumed["result"]["status"] == "succeeded"
    assert resumed["reply"]["command"]["replayed"] is True
    assert resumed["reply"]["message_id"] == str(reply.message_id)
    assert resumed["result"]["outputs"]["analysis"] == submitted["request_payload"]["analysis"]
    assert not marker.exists()
    assert checked(control.runs_list(OPERATOR)).page.count == 1
    inputs = system.inputs_for_run(RunId(run_id))
    assert inputs["change"]["after_ref"]["commit"] == after
    assert "Path(" not in json.dumps(inputs)  # code crosses only as GitRefs
    events = checked(control.runs_events(OPERATOR, RunId(run_id), limit=100)).items
    assert sum(e.kind == "NodeCompleted" and e.path == "python-change-review/inspect"
               for e in events) == 1
    assert sum(e.kind == "NodeRestored" and e.path == "python-change-review/inspect"
               for e in events) == 1
    assert sum(e.kind == "RunSucceeded" for e in events) == 1


def test_syntax_failure_retains_diagnostic_without_inventing_symbol_comparison() -> None:
    report = compare_sources("def previous(): pass\n", "def broken(:\n").model_dump()
    assert report["comparison_available"] is False
    assert report["syntax_errors"]["after"].startswith("line 1:")
    assert report["symbols"] == {} and report["counts"] == {}
    token_error = compare_sources("", "x = \N{EURO SIGN}")
    assert token_error.syntax_errors == {"after": "line 1: SyntaxError"}


def test_symbol_bound_binds_and_utf8_bytes_are_checked() -> None:
    source = "\n".join(f"def symbol_{n:03}(): pass" for n in range(SYMBOL_LIMIT + 1))
    report = compare_sources("", source).model_dump()
    assert report["counts"]["added"] == SYMBOL_LIMIT + 1
    assert len(report["symbols"]["added"]) == SYMBOL_LIMIT
    assert report["symbols_partial"] is True
    with pytest.raises(ValueError, match="source_bytes_exceeded"):
        compare_sources("", "#" + "\N{SNOWMAN}" * (SOURCE_BYTES // 2))


@pytest.mark.parametrize("raw", [b"x" * (SOURCE_BYTES + 1), b"\xff"], ids=["oversize", "utf8"])
def test_bad_file_input_is_refused_before_creating_state(tmp_path: Path, raw: bytes) -> None:
    repository, before, after = source_commits(tmp_path, b"", raw)
    state = tmp_path / "state"
    refused = entry(state, "submit", "--repository", str(repository), "--before-commit", before,
                    "--after-commit", after, "--path", "calc.py", "--key", "bad")
    assert refused.returncode == 1
    assert json.loads(refused.stderr)["error"]
    assert not state.exists()


def test_status_does_not_create_a_missing_store(tmp_path: Path) -> None:
    state = tmp_path / "missing"
    refused = entry(state, "status", "--run-id", "run-missing")
    assert refused.returncode == 1
    assert "review_store_missing" in refused.stderr
    assert not state.exists()


def test_committed_utf8_bom_is_valid_source(tmp_path: Path) -> None:
    repository, before, after = source_commits(tmp_path, b"", b"\xef\xbb\xbfdef added(): pass\n")
    _, previous = committed_source(repository, before, "calc.py")
    _, current = committed_source(repository, after, "calc.py")
    report = compare_sources(previous, current)
    assert report.comparison_available and report.syntax_errors == {}
    assert report.symbols["added"] == ["added"]


def test_symlink_blob_is_refused_before_creating_state(tmp_path: Path) -> None:
    repository, before, regular = source_commits(tmp_path, b"", b"pass\n")
    blob = git(repository, "rev-parse", f"{regular}:calc.py").decode("ascii").strip()
    # Git index plumbing supplies the real symlink mode on Windows too; no OS
    # symlink privilege or mocked producer is needed.
    git(repository, "update-index", "--cacheinfo", f"120000,{blob},calc.py")
    git(repository, "-c", "user.name=Example", "-c", "user.email=example@example.invalid",
        "commit", "--quiet", "-m", "symlink")
    after = git(repository, "rev-parse", "HEAD").decode("ascii").strip()
    state = tmp_path / "state"
    refused = entry(state, "submit", "--repository", str(repository), "--before-commit", before,
                    "--after-commit", after, "--path", "calc.py", "--key", "symlink")
    assert refused.returncode == 1
    assert "ordinary committed file" in json.loads(refused.stderr)["error"]
    assert not state.exists()


def test_git_helper_denies_transport_even_when_repository_allows_it(tmp_path: Path) -> None:
    repository, _, after = source_commits(tmp_path, b"", b"pass\n")
    git(repository, "config", "protocol.file.allow", "always")
    args = ["fetch", "--dry-run", str(repository), after]
    # Admitting control is local-only. The same real Git transport must refuse
    # through the example helper, regardless of the repository's configuration.
    control = subprocess.run(
        ["git", "-C", str(repository), *args], stdin=subprocess.DEVNULL,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
        capture_output=True, timeout=15, check=False,
    )
    assert control.returncode == 0, control.stderr
    with pytest.raises(ValueError, match="review_git_failed: fetch"):
        git(repository, *args)
