"""The mutation harness reports each isolated child's elapsed time."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts import _mutations as mutations


def test_run_reports_elapsed_time_without_changing_nonproof_exit_status(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr(mutations.sys, "argv", ["_mutations.py"])
    monkeypatch.setattr(mutations, "source_snapshot", lambda: b"source")
    results = iter(
        (
            subprocess.CompletedProcess([], 0, 'MUTATION_BASELINE_PASSED ["test::case"]\n', ""),
            subprocess.CompletedProcess([], 1, 'MUTATION_ASSERTION_FAILURE ["test::case"]\n', ""),
            subprocess.CompletedProcess([], 1, "ordinary test failure", ""),
            subprocess.CompletedProcess([], 2, "", "harness error"),
            subprocess.TimeoutExpired([], 60),
        )
    )
    calls = []

    def run_child(*args, **kwargs):
        calls.append((args, kwargs))
        result = next(results)
        if isinstance(result, subprocess.TimeoutExpired):
            raise result
        return result

    monkeypatch.setattr(
        mutations.subprocess,
        "run",
        run_child,
    )
    times = iter((-1.0, -0.5, 0.0, 0.125, 1.0, 1.5, 2.0, 2.25, 3.0, 5.0))
    monkeypatch.setattr(mutations.time, "monotonic", lambda: next(times))

    status = mutations.run([
        (name, "module:target", "before", "after", "test")
        for name in ("killed", "failure", "error", "timeout")
    ])

    assert status == 1
    command = [mutations.sys.executable, str(Path("_mutations.py").resolve())]
    assert [args[0] for args, _ in calls] == [[*command, "0", "--baseline"]] + [
        [*command, str(index)] for index in range(4)
    ]
    assert all(
        kwargs.keys() == {"capture_output", "text", "timeout", "cwd", "env", "stdin"}
        and kwargs["stdin"] == subprocess.DEVNULL and kwargs["timeout"] == 60
        for _, kwargs in calls
    )
    output = capsys.readouterr().out
    assert "killed: KILLED (0.125s)" in output
    assert "failure: NOT PROVEN (0.500s)" in output
    assert "error: NOT PROVEN (0.250s)" in output
    assert "timeout: NOT PROVEN (harness timeout; 2.000s)" in output


def test_run_preserves_success_exit_status_when_every_mutant_is_killed(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr(mutations.sys, "argv", ["_mutations.py"])
    monkeypatch.setattr(mutations, "source_snapshot", lambda: b"source")
    monkeypatch.setattr(
        mutations.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args,
            0 if "--baseline" in args[0] else 1,
            'MUTATION_BASELINE_PASSED ["test::case"]\n' if "--baseline" in args[0]
            else 'MUTATION_ASSERTION_FAILURE ["test::case"]\n', "",
        ),
    )
    times = iter((9.0, 9.25, 10.0, 10.75))
    monkeypatch.setattr(mutations.time, "monotonic", lambda: next(times))

    assert mutations.run([("only", "module:target", "before", "after", "test")]) == 0
    assert "only: KILLED (0.750s)" in capsys.readouterr().out
